from datetime import datetime, timezone

import uuid as uuid_lib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/collaterals", tags=["collaterals"])


@router.post("", response_model=schemas.CollateralResponse, status_code=201)
def lock_collateral(payload: schemas.LockCollateralRequest, db: Session = Depends(get_db)):
    """El agente deposita colateral en USDT antes de poder recibir efectivo
    físico de un proveedor (garantía frente a robo/pérdida/impago). Se crea
    en estado LOCKED — no se descuenta de ningún saldo fiat, es un depósito
    aparte en cadena, aquí solo se registra su estado."""
    agente = db.query(models.User).filter(
        models.User.id == payload.agente_id, models.User.role == "AGENTE_CAMPO"
    ).first()
    if not agente:
        raise HTTPException(404, "Agente no encontrado")

    proveedor = db.query(models.User).filter(
        models.User.id == payload.proveedor_id, models.User.role == "PROVEEDOR"
    ).first()
    if not proveedor:
        raise HTTPException(404, "Proveedor no encontrado")

    collateral = models.Collateral(
        agente_id=payload.agente_id,
        proveedor_id=payload.proveedor_id,
        amount_usdt_minor=payload.amount_usdt_minor,
        chain=payload.chain,
        tx_hash=payload.tx_hash,
        status="LOCKED",
    )
    db.add(collateral)
    db.commit()
    db.refresh(collateral)
    return collateral


@router.post("/{collateral_uuid}/release", response_model=schemas.CollateralResponse)
def release_collateral(collateral_uuid: uuid_lib.UUID, db: Session = Depends(get_db)):
    """El proveedor libera el colateral del agente (ej. fin de la relación
    comercial sin incidentes, o el agente saldó todo lo que debía). Solo
    válido desde LOCKED — es una transición terminal en un solo sentido,
    igual que FORFEITED."""
    collateral = db.query(models.Collateral).filter(models.Collateral.uuid == collateral_uuid).first()
    if not collateral:
        raise HTTPException(404, "Colateral no encontrado")
    if collateral.status != "LOCKED":
        raise HTTPException(409, f"El colateral no está LOCKED (actual: {collateral.status})")

    collateral.status = "RELEASED"
    collateral.released_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(collateral)
    return collateral


@router.post("/{collateral_uuid}/forfeit", response_model=schemas.CollateralResponse)
def forfeit_collateral(
    collateral_uuid: uuid_lib.UUID, payload: schemas.ForfeitCollateralRequest, db: Session = Depends(get_db)
):
    """El proveedor ejecuta el colateral (ej. el agente desapareció con
    efectivo entregado y sin liquidar). Solo válido desde LOCKED. Si se
    conoce ya el tx_hash del pago on-chain al proveedor, sobrescribe el
    tx_hash original del depósito — el campo pasa a representar el
    movimiento que cierra el colateral, no el que lo abrió."""
    collateral = db.query(models.Collateral).filter(models.Collateral.uuid == collateral_uuid).first()
    if not collateral:
        raise HTTPException(404, "Colateral no encontrado")
    if collateral.status != "LOCKED":
        raise HTTPException(409, f"El colateral no está LOCKED (actual: {collateral.status})")

    collateral.status = "FORFEITED"
    collateral.released_at = datetime.now(timezone.utc)
    if payload.settlement_tx_hash:
        collateral.tx_hash = payload.settlement_tx_hash
    db.commit()
    db.refresh(collateral)
    return collateral


@router.get("/{collateral_uuid}", response_model=schemas.CollateralResponse)
def get_collateral(collateral_uuid: uuid_lib.UUID, db: Session = Depends(get_db)):
    collateral = db.query(models.Collateral).filter(models.Collateral.uuid == collateral_uuid).first()
    if not collateral:
        raise HTTPException(404, "Colateral no encontrado")
    return collateral


@router.get("", response_model=list[schemas.CollateralResponse])
def list_collaterals(agente_id: int | None = None, status: str | None = None, db: Session = Depends(get_db)):
    query = db.query(models.Collateral)
    if agente_id is not None:
        query = query.filter(models.Collateral.agente_id == agente_id)
    if status is not None:
        query = query.filter(models.Collateral.status == status)
    return query.order_by(models.Collateral.created_at.desc()).all()
