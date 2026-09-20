from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, ledger_service, signature_service
from ..database import get_db

router = APIRouter(prefix="/sync", tags=["sync"])


@router.get("/pull/{agent_id}", response_model=list[schemas.SyncOrderDownloadItem])
def pull_orders(agent_id: int, db: Session = Depends(get_db)):
    """El agente llama esto cuando recupera señal. Devuelve todas las
    órdenes asignadas a él que aún no están en un estado terminal.
    Incluye otp_hash + otp_secret (nunca el OTP en texto plano) para que
    el dispositivo pueda verificar entregas 100% offline después."""
    orders = (
        db.query(models.DistributionOrder)
        .filter(
            models.DistributionOrder.assigned_agent_id == agent_id,
            models.DistributionOrder.status.in_(["ASSIGNED", "IN_TRANSIT"]),
        )
        .all()
    )
    return orders


@router.post("/push", response_model=list[schemas.SyncPushResult])
def push_deliveries(payload: schemas.SyncPushRequest, db: Session = Depends(get_db)):
    """El agente sube su outbox local (sync_queue) cuando recupera señal.
    Cada entrega se valida por firma antes de aceptarse — ver ARCHITECTURE.md §5.
    Es idempotente: reenviar la misma entrega (mismo uuid) no duplica efectos."""
    results: list[schemas.SyncPushResult] = []

    for item in payload.deliveries:
        order = db.query(models.DistributionOrder).filter(models.DistributionOrder.uuid == item.order_uuid).first()
        if not order:
            results.append(schemas.SyncPushResult(order_uuid=item.order_uuid, accepted=False, reason="ORDER_STATE_CONFLICT"))
            continue

        existing_delivery = db.query(models.Delivery).filter(models.Delivery.order_id == order.id).first()
        if existing_delivery and existing_delivery.synced_at is not None:
            results.append(schemas.SyncPushResult(order_uuid=item.order_uuid, accepted=True, reason="ALREADY_SYNCED"))
            continue

        device = db.query(models.Device).filter(models.Device.uuid == item.device_uuid, models.Device.revoked_at.is_(None)).first()
        if not device:
            results.append(schemas.SyncPushResult(order_uuid=item.order_uuid, accepted=False, reason="SIGNATURE_INVALID"))
            continue

        payload_bytes = signature_service.build_proof_payload(
            order_uuid=str(item.order_uuid),
            otp_hash=order.otp_hash,
            lat=item.lat,
            lng=item.lng,
            delivered_at_iso=item.delivered_at.isoformat(),
            device_uuid=str(item.device_uuid),
        )
        signature_ok = signature_service.verify_delivery_signature(
            device.public_key, payload_bytes, item.proof_signature
        )
        if not signature_ok:
            db.add(models.SyncConflict(
                entity_type="deliveries",
                entity_uuid=item.uuid,
                conflict_reason="Firma Ed25519 inválida para el dispositivo declarado",
                incoming_payload=item.model_dump(mode="json"),
                current_state_snapshot={"order_status": order.status},
            ))
            db.commit()
            results.append(schemas.SyncPushResult(order_uuid=item.order_uuid, accepted=False, reason="SIGNATURE_INVALID"))
            continue

        # Máquina de estados estricta: no se sobrescribe silenciosamente un
        # estado terminal distinto ya presente en el backend (ver ARCHITECTURE.md §6.2).
        if order.status in ("CANCELLED", "SETTLED", "FAILED"):
            db.add(models.SyncConflict(
                entity_type="distribution_orders",
                entity_uuid=item.order_uuid,
                conflict_reason=f"El agente reporta DELIVERED pero el backend ya tiene status={order.status}",
                incoming_payload=item.model_dump(mode="json"),
                current_state_snapshot={"order_status": order.status},
            ))
            db.commit()
            results.append(schemas.SyncPushResult(order_uuid=item.order_uuid, accepted=False, reason="ORDER_STATE_CONFLICT"))
            continue

        delivery = models.Delivery(
            uuid=item.uuid,
            order_id=order.id,
            agente_id=order.assigned_agent_id,
            device_id=device.id,
            assigned_at=order.assigned_at,
            delivered_at=item.delivered_at,
            synced_at=datetime.now(timezone.utc),
            lat=item.lat,
            lng=item.lng,
            accuracy_m=item.accuracy_m,
            proof_signature=item.proof_signature,
            signature_verified=True,
        )
        db.add(delivery)

        order.status = "DELIVERED"

        pool = (
            db.query(models.CashPool)
            .filter(models.CashPool.proveedor_id.isnot(None))
            .first()
        )
        if pool:
            ledger_service.settle_order_amount(db, order, cash_pool_id=pool.id, device_id=device.id)

        db.commit()
        results.append(schemas.SyncPushResult(order_uuid=item.order_uuid, accepted=True, reason="OK"))

    return results
