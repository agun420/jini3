from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from uuid import NAMESPACE_URL, uuid5

from .broker import BrokerClient
from .canonical import canonical_sha256
from .errors import BrokerNotFound, BrokerTransportError
from .models import BrokerOrderCommand, ReconciliationReport


def reconcile_command(
    execution_id: str,
    command: BrokerOrderCommand,
    broker: BrokerClient,
    *,
    checked_at: datetime | None = None,
) -> ReconciliationReport:
    checked_at = (checked_at or datetime.now(UTC)).astimezone(UTC)
    mismatch: list[str] = []
    try:
        order = broker.get_order_by_client_order_id(command.client_order_id)
    except BrokerNotFound:
        order = None
        mismatch.append("BROKER_ORDER_NOT_FOUND")
    except BrokerTransportError:
        order = None
        mismatch.append("BROKER_LOOKUP_FAILED")
    position = broker.get_position(command.symbol)
    if order is not None:
        if order.symbol != command.symbol:
            mismatch.append("SYMBOL_MISMATCH")
        if order.side is not command.side:
            mismatch.append("SIDE_MISMATCH")
        if order.quantity != Decimal(command.quantity):
            mismatch.append("QUANTITY_MISMATCH")
        if order.client_order_id != command.client_order_id:
            mismatch.append("CLIENT_ORDER_ID_MISMATCH")
    payload = {
        "execution_id": execution_id,
        "client_order_id": command.client_order_id,
        "checked_at": checked_at,
        "matched": not mismatch,
        "mismatch_codes": tuple(mismatch),
        "broker_order": order,
        "broker_position": position,
    }
    report_hash = canonical_sha256(payload)
    report_id = uuid5(
        NAMESPACE_URL,
        f"daybreak-reconcile:{execution_id}:{command.client_order_id}:{report_hash}",
    ).hex
    return ReconciliationReport.model_validate(
        {**payload, "report_id": report_id, "report_hash": report_hash}
    )
