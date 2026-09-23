import uuid as uuid_lib
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, otp_service, ledger_service
from ..config import get_settings
from ..database import get_db
from ..sms import SMSDeliveryError

router = APIRouter(prefix="/orders", tags=["orders"])


def _attempt_send_otp_sms(order: models.DistributionOrder, otp_plain: str, db: Session) -> None:
    """Envía el SMS y deja el resultado grabado en la orden. Nunca lanza —
    un fallo de SMS es visible en otp_sms_status, pero no debe tumbar la
    request que la llamó (creación de orden o reenvío manual)."""
    order.otp_sms_attempts += 1
    try:
        message_id = otp_service.send_otp_sms(order.beneficiario_phone, otp_plain)
        order.otp_sms_status = "SENT"
        order.otp_sms_provider = get_settings().sms_provider
        order.otp_sms_message_id = message_id
        order.otp_sms_error = None
        order.otp_sms_sent_at = datetime.now(timezone.utc)
    except SMSDeliveryError as exc:
        order.otp_sms_status = "FAILED"
        order.otp_sms_provider = exc.provider
        order.otp_sms_error = str(exc)
    db.commit()
    db.refresh(order)


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

    # Envío de SMS: no revierte la creación de la orden si falla — el
    # resultado queda en otp_sms_status/otp_sms_error para reintentar via
    # POST /orders/{uuid}/resend-otp sin tener que recrear la orden.
    _attempt_send_otp_sms(order, otp_data["otp_plain"], db)

    return order


@router.post("/{order_uuid}/resend-otp", response_model=schemas.OrderResponse)
def resend_otp(order_uuid: uuid_lib.UUID, db: Session = Depends(get_db)):
    """Reintento manual de envío del SMS con el OTP — para cuando el envío
    original falló (otp_sms_status='FAILED') o el destinatario dice no
    haberlo recibido. Genera un OTP nuevo (invalida el anterior) porque el
    texto plano original ya no existe en el servidor — nunca se persiste."""
    order = db.query(models.DistributionOrder).filter(models.DistributionOrder.uuid == order_uuid).first()
    if not order:
        raise HTTPException(404, "Orden no encontrada")
    if order.status not in ("PENDING", "ASSIGNED"):
        raise HTTPException(409, f"No se puede reenviar el OTP con la orden en estado {order.status}")

    otp_data = otp_service.create_order_otp()
    order.otp_hash = otp_data["otp_hash"]
    order.otp_secret = otp_data["otp_secret"]
    order.otp_expires_at = otp_data["otp_expires_at"]
    order.otp_attempts = 0
    order.otp_locked_at = None
    db.commit()
    db.refresh(order)

    _attempt_send_otp_sms(order, otp_data["otp_plain"], db)
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


@router.post("/{order_uuid}/cancel", response_model=schemas.OrderResponse)
def cancel_order(order_uuid: uuid_lib.UUID, payload: schemas.CancelOrderRequest, db: Session = Depends(get_db)):
    """Cancela una orden que aún no fue entregada. Si ya estaba ASSIGNED,
    el monto comprometido (ORDER_COMMITTED) se libera de vuelta al
    disponible del agente vía ledger_service.release_order_amount — nunca
    se toca available_* directamente (ver ARCHITECTURE.md §3.1)."""
    order = db.query(models.DistributionOrder).filter(models.DistributionOrder.uuid == order_uuid).first()
    if not order:
        raise HTTPException(404, "Orden no encontrada")
    if order.status not in ("PENDING", "ASSIGNED"):
        raise HTTPException(409, f"No se puede cancelar una orden en estado {order.status}")

    if order.status == "ASSIGNED":
        # El pool a liberar es el mismo que se comprometió al asignar —
        # se recupera del propio ledger en vez de volver a adivinarlo por
        # "el pool más reciente", que sería incorrecto si hay varios.
        committed_entry = (
            db.query(models.CashLedgerEntry)
            .filter(
                models.CashLedgerEntry.order_id == order.id,
                models.CashLedgerEntry.entry_type == "ORDER_COMMITTED",
            )
            .first()
        )
        if not committed_entry:
            raise HTTPException(
                409,
                "La orden está ASSIGNED pero no tiene un movimiento ORDER_COMMITTED en el "
                "ledger — estado inconsistente, revisar manualmente antes de cancelar",
            )
        ledger_service.release_order_amount(db, order, cash_pool_id=committed_entry.cash_pool_id)

    order.status = "CANCELLED"
    db.commit()
    db.refresh(order)
    return order


@router.get("/{order_uuid}", response_model=schemas.OrderResponse)
def get_order(order_uuid: uuid_lib.UUID, db: Session = Depends(get_db)):
    order = db.query(models.DistributionOrder).filter(models.DistributionOrder.uuid == order_uuid).first()
    if not order:
        raise HTTPException(404, "Orden no encontrada")
    return order
