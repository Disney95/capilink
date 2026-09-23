"""
CapiLink — Servicio de Ledger.
Todas las escrituras de saldo pasan por aquí como INSERT append-only.
Ver ARCHITECTURE.md §3.1. Nunca hacer UPDATE directo sobre available_*.
"""

import uuid as uuid_lib
from sqlalchemy import func
from sqlalchemy.orm import Session

from . import models


def insert_ledger_entry(
    db: Session,
    *,
    idempotency_key: uuid_lib.UUID,
    cash_pool_id: int,
    entry_type: str,
    currency: str,
    amount_minor: int,
    agente_id: int | None = None,
    order_id: int | None = None,
    created_by_device_id: int | None = None,
) -> models.CashLedgerEntry:
    """Inserta un movimiento. Es idempotente: si ya existe una fila con el
    mismo idempotency_key (típico al reintentar una sincronización desde
    un agente que perdió señal a mitad de subida), no duplica el efecto."""
    existing = (
        db.query(models.CashLedgerEntry)
        .filter(models.CashLedgerEntry.idempotency_key == idempotency_key)
        .first()
    )
    if existing:
        return existing

    entry = models.CashLedgerEntry(
        idempotency_key=idempotency_key,
        cash_pool_id=cash_pool_id,
        agente_id=agente_id,
        order_id=order_id,
        entry_type=entry_type,
        currency=currency,
        amount_minor=amount_minor,
        created_by_device_id=created_by_device_id,
    )
    db.add(entry)
    db.flush()  # el trigger de Postgres refresca cash_pools.available_* al hacer commit
    return entry


def get_agent_available_balance(db: Session, agente_id: int, currency: str) -> int:
    """Efectivo_Disponible = Asignado_Por_Proveedor - Σ(Órdenes_En_Ruta).
    Se calcula sumando el ledger, nunca leyendo una columna mutable."""
    total = (
        db.query(func.coalesce(func.sum(models.CashLedgerEntry.amount_minor), 0))
        .filter(
            models.CashLedgerEntry.agente_id == agente_id,
            models.CashLedgerEntry.currency == currency,
        )
        .scalar()
    )
    return int(total or 0)


def commit_order_amount(
    db: Session, order: models.DistributionOrder, cash_pool_id: int, device_id: int | None = None
) -> None:
    """Se llama al ASIGNAR una orden a un agente: el monto queda 'comprometido'
    (resta del disponible) aunque el agente todavía tenga el efectivo físico."""
    insert_ledger_entry(
        db,
        idempotency_key=uuid_lib.uuid4(),
        cash_pool_id=cash_pool_id,
        entry_type="ORDER_COMMITTED",
        currency=order.currency,
        amount_minor=-order.amount_fiat_minor,
        agente_id=order.assigned_agent_id,
        order_id=order.id,
        created_by_device_id=device_id,
    )


def settle_order_amount(
    db: Session, order: models.DistributionOrder, cash_pool_id: int, device_id: int | None = None
) -> None:
    """Se llama al confirmar la entrega (tras validar la firma). Cierra el
    ciclo: el efectivo salió físicamente de manos del agente. amount_minor=0
    porque el 'disponible' ya se había descontado en ORDER_COMMITTED; esta
    fila es para trazabilidad/auditoría, no para volver a mover el saldo."""
    insert_ledger_entry(
        db,
        idempotency_key=uuid_lib.uuid4(),
        cash_pool_id=cash_pool_id,
        entry_type="ORDER_DELIVERED_SETTLED",
        currency=order.currency,
        amount_minor=0,
        agente_id=order.assigned_agent_id,
        order_id=order.id,
        created_by_device_id=device_id,
    )


def release_order_amount(
    db: Session, order: models.DistributionOrder, cash_pool_id: int
) -> None:
    """Se llama al cancelar una orden ya comprometida: libera el monto de
    vuelta al disponible del agente."""
    insert_ledger_entry(
        db,
        idempotency_key=uuid_lib.uuid4(),
        cash_pool_id=cash_pool_id,
        entry_type="ORDER_CANCELLED_RELEASE",
        currency=order.currency,
        amount_minor=order.amount_fiat_minor,
        agente_id=order.assigned_agent_id,
        order_id=order.id,
    )
