import uuid as uuid_lib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, otp_service, ledger_service
from ..database import get_db

router = APIRouter(prefix="/orders", tags=["orders"])


@router.post("", response_model=schemas.OrderResponse, status_code=201)
def create_order(payload: schemas.CreateOrderRequest, db: Session = Depends(get_db)):
    otp_data = otp_service.create_order_otp()

    order = models.DistributionOrder(
        emisor_id=payload.emisor_id,
        beneficiario_phone=payload.beneficiario_phone,
        destination_address=payload.destination_address,
        municipality=payload.municipality,
        amount_fiat_minor=payload.amount_fiat_minor,
        currency=payload.currency,
        otp_hash=otp_data["otp_hash"],
        otp_secret=otp_data["otp_secret"],
        otp_expires_at=otp_data["otp_expires_at"],
        status="PENDING",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    # Envío de SMS: se hace fuera de la transacción de DB. Si falla, no debe
    # revertir la creación de la orden — se reintenta el envío por separado.
    try:
        otp_service.send_otp_sms(order.beneficiario_phone, otp_data["otp_plain"])
    except NotImplementedError:
        pass  # esqueleto: conectar proveedor de SMS real en producción

    return order


@router.post("/{order_uuid}/assign", response_model=schemas.OrderResponse)
def assign_order(order_uuid: uuid_lib.UUID, payload: schemas.AssignOrderRequest, db: Session = Depends(get_db)):
    order = db.query(models.DistributionOrder).filter(models.DistributionOrder.uuid == order_uuid).first()
    if not order:
        raise HTTPException(404, "Orden no encontrada")
    if order.status != "PENDING":
        raise HTTPException(409, f"La orden no está en estado PENDING (actual: {order.status})")

    agent = db.query(models.User).filter(models.User.id == payload.agent_id, models.User.role == "AGENTE_CAMPO").first()
    if not agent:
        raise HTTPException(404, "Agente no encontrado")

    # Se necesita el cash_pool del proveedor que fondea a este agente.
    # En un sistema real, la relación agente<->proveedor<->pool se resuelve
    # por una tabla de asignación de agentes; aquí se asume la más reciente.
    pool = (
        db.query(models.CashPool)
        .join(models.User, models.User.id == models.CashPool.proveedor_id)
        .order_by(models.CashPool.updated_at.desc())
        .first()
    )
    if not pool:
        raise HTTPException(409, "No hay un cash_pool disponible para asignar la orden")

    disponible = ledger_service.get_agent_available_balance(db, agent.id, order.currency)
    if disponible < order.amount_fiat_minor:
        raise HTTPException(
            409,
            f"El agente no tiene efectivo disponible suficiente "
            f"(disponible={disponible}, requerido={order.amount_fiat_minor})",
        )

    order.assigned_agent_id = agent.id
    order.assigned_at = datetime.now(timezone.utc)
    order.status = "ASSIGNED"

    ledger_service.commit_order_amount(db, order, cash_pool_id=pool.id)

    db.commit()
    db.refresh(order)
    return order


@router.get("/{order_uuid}", response_model=schemas.OrderResponse)
def get_order(order_uuid: uuid_lib.UUID, db: Session = Depends(get_db)):
    order = db.query(models.DistributionOrder).filter(models.DistributionOrder.uuid == order_uuid).first()
    if not order:
        raise HTTPException(404, "Orden no encontrada")
    return order
