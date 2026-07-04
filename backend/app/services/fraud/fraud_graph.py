"""Minimal organised-fraud graph over claimants, surveyors, and garages.

Uses networkx. Signals are intentionally simple and inspectable:
- node degree at or above DEGREE_FLAG_THRESHOLD
- garage–surveyor co-occurrence at or above PAIR_FLAG_THRESHOLD

Graph over claimants, surveyors, and garages linked by shared claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.models import Claim
from app.models.enums import FraudSignalType
from app.services.fraud.rules_engine import FraudSignalDraft

DEGREE_FLAG_THRESHOLD = 3
PAIR_FLAG_THRESHOLD = 2


@dataclass
class GraphNode:
    id: str
    label: str
    kind: str  # claimant | surveyor | garage
    flagged: bool = False
    degree: int = 0


@dataclass
class GraphEdge:
    source: str
    target: str
    claim_reference: str


@dataclass
class ClaimNetworkView:
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    flagged_node_ids: list[str]
    clear: bool
    caption: str = "Network view of claims sharing this garage or surveyor."
    signals: list[FraudSignalDraft] = field(default_factory=list)


def _claimant_label(claim: Claim) -> str:
    if claim.claimant_name:
        return claim.claimant_name
    user = claim.creator
    if user is None:
        return f"User {claim.created_by}"
    return user.full_name or user.username


def _node_ids(claim: Claim) -> dict[str, tuple[str, str]]:
    """Return kind -> (node_id, label) for entities present on the claim."""
    nodes: dict[str, tuple[str, str]] = {}
    claimant = _claimant_label(claim)
    nodes["claimant"] = (f"claimant:{claimant}", claimant)
    if claim.surveyor_name:
        nodes["surveyor"] = (f"surveyor:{claim.surveyor_name}", claim.surveyor_name)
    if claim.garage_id and claim.garage is not None:
        nodes["garage"] = (f"garage:{claim.garage_id}", claim.garage.name)
    elif claim.garage_id:
        nodes["garage"] = (f"garage:{claim.garage_id}", f"Garage {claim.garage_id}")
    return nodes


def build_graph(db: Session) -> nx.Graph:
    claims = db.scalars(
        select(Claim).options(
            selectinload(Claim.garage),
            selectinload(Claim.creator),
        )
    ).all()
    graph = nx.Graph()
    pair_counts: dict[tuple[str, str], int] = {}

    for claim in claims:
        entities = list(_node_ids(claim).values())
        for node_id, label in entities:
            kind = node_id.split(":", 1)[0]
            if node_id not in graph:
                graph.add_node(node_id, label=label, kind=kind)
        # Connect all entity pairs on this claim (claimant–garage, claimant–surveyor, garage–surveyor).
        for i, (left_id, _) in enumerate(entities):
            for right_id, _ in entities[i + 1 :]:
                if graph.has_edge(left_id, right_id):
                    graph[left_id][right_id]["claims"].append(claim.claim_reference)
                else:
                    graph.add_edge(left_id, right_id, claims=[claim.claim_reference])
                pair = tuple(sorted((left_id, right_id)))
                pair_counts[pair] = pair_counts.get(pair, 0) + 1

    graph.graph["pair_counts"] = pair_counts
    return graph


def _flagged_nodes(graph: nx.Graph) -> set[str]:
    flagged: set[str] = set()
    for node_id, data in graph.nodes(data=True):
        degree = graph.degree(node_id)
        graph.nodes[node_id]["degree"] = degree
        if degree >= DEGREE_FLAG_THRESHOLD:
            flagged.add(node_id)

    pair_counts: dict[tuple[str, str], int] = graph.graph.get("pair_counts") or {}
    for (left, right), count in pair_counts.items():
        kinds = {graph.nodes[left]["kind"], graph.nodes[right]["kind"]}
        if kinds == {"garage", "surveyor"} and count >= PAIR_FLAG_THRESHOLD:
            flagged.add(left)
            flagged.add(right)
    return flagged


def evaluate_claim_signals(db: Session, claim: Claim) -> list[FraudSignalDraft]:
    """Explainable graph signals for fraud_scoring."""
    graph = build_graph(db)
    flagged = _flagged_nodes(graph)
    entities = _node_ids(claim)
    signals: list[FraudSignalDraft] = []

    for _kind, (node_id, label) in entities.items():
        if node_id not in graph:
            continue
        degree = graph.degree(node_id)
        if degree >= DEGREE_FLAG_THRESHOLD:
            signals.append(
                FraudSignalDraft(
                    signal_type=FraudSignalType.organised_fraud_graph,
                    risk_score=min(90, 40 + 10 * degree),
                    reason_code=f"GRAPH_HIGH_DEGREE:{label}",
                )
            )

    pair_counts: dict[tuple[str, str], int] = graph.graph.get("pair_counts") or {}
    garage = entities.get("garage")
    surveyor = entities.get("surveyor")
    if garage and surveyor:
        pair = tuple(sorted((garage[0], surveyor[0])))
        count = pair_counts.get(pair, 0)
        if count >= PAIR_FLAG_THRESHOLD:
            signals.append(
                FraudSignalDraft(
                    signal_type=FraudSignalType.organised_fraud_graph,
                    risk_score=min(95, 50 + 15 * count),
                    reason_code=(
                        f"GRAPH_GARAGE_SURVEYOR_PAIR:{garage[1]}+{surveyor[1]}x{count}"
                    ),
                )
            )

    # Deduplicate by reason_code
    by_code = {s.reason_code: s for s in signals}
    return list(by_code.values())


def claim_network_view(db: Session, claim: Claim) -> ClaimNetworkView:
    """One-hop neighborhood around this claim's garage/surveyor/claimant."""
    graph = build_graph(db)
    flagged_all = _flagged_nodes(graph)
    entities = _node_ids(claim)

    if not entities:
        # Should not happen (claimant always present), but keep a clear node.
        node = GraphNode(
            id="claim:unknown",
            label="This claim",
            kind="claimant",
            flagged=False,
            degree=0,
        )
        return ClaimNetworkView(
            nodes=[node],
            edges=[],
            flagged_node_ids=[],
            clear=True,
        )

    # Seed with this claim's entities.
    focus_ids = {node_id for node_id, _label in entities.values()}
    neighborhood = set(focus_ids)
    for node_id in list(focus_ids):
        if node_id in graph:
            neighborhood.update(graph.neighbors(node_id))

    # Notable connections: anything beyond the claim's own entities, or any flag.
    notable = (neighborhood - focus_ids) or (focus_ids & flagged_all)
    clear = not notable

    nodes: list[GraphNode] = []
    for node_id in sorted(neighborhood):
        if node_id in graph:
            data = graph.nodes[node_id]
            nodes.append(
                GraphNode(
                    id=node_id,
                    label=data.get("label", node_id),
                    kind=data.get("kind", "claimant"),
                    flagged=node_id in flagged_all,
                    degree=int(data.get("degree") or graph.degree(node_id)),
                )
            )
        else:
            # Entity on claim but not yet in graph (no edges) — still show it.
            kind, label = node_id.split(":", 1)[0], node_id.split(":", 1)[-1]
            for _k, (nid, nlabel) in entities.items():
                if nid == node_id:
                    label = nlabel
                    kind = _k
            nodes.append(
                GraphNode(
                    id=node_id,
                    label=label,
                    kind=kind,
                    flagged=False,
                    degree=0,
                )
            )

    edges: list[GraphEdge] = []
    for left, right, data in graph.edges(data=True):
        if left in neighborhood and right in neighborhood:
            refs = data.get("claims") or []
            edges.append(
                GraphEdge(
                    source=left,
                    target=right,
                    claim_reference=refs[-1] if refs else "",
                )
            )

    # Clear state: single primary node (prefer garage, then surveyor, then claimant).
    if clear:
        primary = (
            entities.get("garage")
            or entities.get("surveyor")
            or entities.get("claimant")
        )
        assert primary is not None
        node_id, label = primary
        kind = node_id.split(":", 1)[0]
        nodes = [
            GraphNode(
                id=node_id,
                label=label,
                kind=kind,
                flagged=False,
                degree=graph.degree(node_id) if node_id in graph else 0,
            )
        ]
        edges = []

    signals = evaluate_claim_signals(db, claim)
    return ClaimNetworkView(
        nodes=nodes,
        edges=edges,
        flagged_node_ids=[n.id for n in nodes if n.flagged],
        clear=clear,
        signals=signals,
    )
