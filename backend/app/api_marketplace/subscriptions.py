"""Subscription and chain config for the marketplace."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api_marketplace.catalog import (
    API_CATALOG,
    CHAINABLE_APIS,
    HEAD_API,
    SUBSCRIBEABLE_APIS,
    WIP_APIS,
)
from app.api_marketplace.models import ApiChain, ApiChainStep, ApiSubscription


def list_subscriptions(db: Session, user_id: int) -> dict[str, bool]:
    rows = db.scalars(
        select(ApiSubscription).where(ApiSubscription.user_id == user_id)
    ).all()
    return {row.api_name: row.enabled for row in rows}


def is_subscribed(db: Session, user_id: int, api_name: str) -> bool:
    if api_name in WIP_APIS:
        return False
    row = db.scalar(
        select(ApiSubscription).where(
            ApiSubscription.user_id == user_id,
            ApiSubscription.api_name == api_name,
            ApiSubscription.enabled.is_(True),
        )
    )
    return row is not None


def set_subscription(
    db: Session,
    *,
    user_id: int,
    api_name: str,
    enabled: bool,
) -> ApiSubscription:
    if api_name in WIP_APIS:
        raise ValueError("This API is not yet available for subscription.")
    if api_name not in SUBSCRIBEABLE_APIS:
        raise ValueError(f"Unknown API: {api_name}")
    row = db.scalar(
        select(ApiSubscription).where(
            ApiSubscription.user_id == user_id,
            ApiSubscription.api_name == api_name,
        )
    )
    if row is None:
        row = ApiSubscription(user_id=user_id, api_name=api_name, enabled=enabled)
        db.add(row)
    else:
        row.enabled = enabled
    db.commit()
    db.refresh(row)
    return row


def catalog_with_subscriptions(db: Session, user_id: int) -> list[dict]:
    sub = list_subscriptions(db, user_id)
    out = []
    for item in API_CATALOG:
        name = item["api_name"]
        out.append(
            {
                **item,
                "subscribed": bool(sub.get(name)),
                "subscribe_disabled": bool(item.get("wip")),
            }
        )
    return out


def list_chains(db: Session, user_id: int) -> list[dict]:
    rows = db.scalars(
        select(ApiChain)
        .options(selectinload(ApiChain.steps))
        .where(ApiChain.user_id == user_id)
        .order_by(ApiChain.created_at.desc())
    ).all()
    result = []
    for chain in rows:
        steps = sorted(chain.steps, key=lambda s: s.step_order)
        result.append(
            {
                "id": str(chain.id),
                "chain_name": chain.chain_name,
                "head_api": chain.head_api,
                "steps": [{"order": s.step_order, "api_name": s.api_name} for s in steps],
                "created_at": chain.created_at.isoformat() if chain.created_at else None,
            }
        )
    return result


def create_chain(
    db: Session,
    *,
    user_id: int,
    chain_name: str,
    follow_on: list[str],
) -> ApiChain:
    name = (chain_name or "").strip()
    if not name:
        raise ValueError("Chain name is required")
    cleaned: list[str] = []
    for api in follow_on:
        api = (api or "").strip()
        if not api or api == HEAD_API:
            continue
        if api not in CHAINABLE_APIS:
            raise ValueError(f"Cannot chain API: {api}")
        if api not in cleaned:
            cleaned.append(api)

    chain = ApiChain(user_id=user_id, chain_name=name[:128], head_api=HEAD_API)
    db.add(chain)
    db.flush()
    db.add(ApiChainStep(chain_id=chain.id, step_order=1, api_name=HEAD_API))
    for idx, api in enumerate(cleaned, start=2):
        db.add(ApiChainStep(chain_id=chain.id, step_order=idx, api_name=api))
    db.commit()
    db.refresh(chain)
    return chain


def delete_chain(db: Session, *, user_id: int, chain_id: uuid.UUID) -> None:
    chain = db.get(ApiChain, chain_id)
    if not chain or chain.user_id != user_id:
        raise ValueError("Chain not found")
    db.delete(chain)
    db.commit()
