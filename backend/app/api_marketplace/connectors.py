"""Persist per-user connector URLs for marketplace integrations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api_marketplace.models import ApiConnectorSetting

SALESFORCE_API = "connect_salesforce"


def get_connector_config(db: Session, *, user_id: int, api_name: str) -> dict[str, str]:
    row = db.scalar(
        select(ApiConnectorSetting).where(
            ApiConnectorSetting.user_id == user_id,
            ApiConnectorSetting.api_name == api_name,
        )
    )
    if not row:
        return {"server_url": "", "connector_url": ""}
    return {
        "server_url": row.server_url or "",
        "connector_url": row.connector_url or "",
    }


def save_connector_config(
    db: Session,
    *,
    user_id: int,
    api_name: str,
    server_url: str,
    connector_url: str,
) -> ApiConnectorSetting:
    server = (server_url or "").strip()[:512]
    connector = (connector_url or "").strip()[:512]
    row = db.scalar(
        select(ApiConnectorSetting).where(
            ApiConnectorSetting.user_id == user_id,
            ApiConnectorSetting.api_name == api_name,
        )
    )
    if row is None:
        row = ApiConnectorSetting(
            user_id=user_id,
            api_name=api_name,
            server_url=server,
            connector_url=connector,
        )
        db.add(row)
    else:
        row.server_url = server
        row.connector_url = connector
    db.commit()
    db.refresh(row)
    return row


def dummy_salesforce_leads(*, server_url: str, connector_url: str) -> dict:
    """Stub lead payload for WIP Connect Salesforce."""
    return {
        "wip": True,
        "message": "Work in progress — stub lead data only. No live Salesforce call is made.",
        "server_url": server_url,
        "connector_url": connector_url,
        "leads": [
            {
                "id": "00Q5g00000STUB001",
                "name": "Priya Sharma",
                "company": "Metro Motors Pune",
                "status": "Open",
                "source": "Web",
            },
            {
                "id": "00Q5g00000STUB002",
                "name": "Arjun Mehta",
                "company": "City Garage Services",
                "status": "Working",
                "source": "Partner Referral",
            },
        ],
    }
