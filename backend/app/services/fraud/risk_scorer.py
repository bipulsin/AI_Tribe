"""Aggregate fraud risk score from rule-engine signals."""

from __future__ import annotations

from dataclasses import dataclass

from app.services.fraud.rules_engine import FraudSignalDraft


@dataclass
class RiskScoreResult:
    risk_score: int
    signals: list[FraudSignalDraft]
    detail: str


def score_signals(signals: list[FraudSignalDraft]) -> RiskScoreResult:
    if not signals:
        return RiskScoreResult(
            risk_score=0,
            signals=[],
            detail="No elevated fraud signals.",
        )

    # Conservative aggregate: max signal dominates, with a small boost for volume.
    peak = max(signal.risk_score for signal in signals)
    boost = min(15, 5 * (len(signals) - 1))
    total = min(100, peak + boost)
    codes = ", ".join(signal.reason_code for signal in signals)
    detail = f"Fraud risk {total}/100 ({codes})."
    return RiskScoreResult(risk_score=total, signals=signals, detail=detail)
