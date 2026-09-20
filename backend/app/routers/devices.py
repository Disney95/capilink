from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/devices", tags=["devices"])


@router.post("", response_model=schemas.DeviceResponse, status_code=201)
def register_device(payload: schemas.RegisterDeviceRequest, db: Session = Depends(get_db)):
    """Se llama la primera vez que el dispositivo del agente sincroniza con
    señal. Registra su clave pública Ed25519 — sin esto, el backend no puede
    verificar ninguna firma de entrega que ese dispositivo produzca offline
    (ver ARCHITECTURE.md §5)."""
    user = db.query(models.User).filter(models.User.id == payload.user_id).first()
    if not user:
        raise HTTPException(404, "Usuario no encontrado")

    device = models.Device(
        user_id=payload.user_id,
        public_key=payload.public_key,
        platform=payload.platform,
        app_version=payload.app_version,
    )
    db.add(device)
    db.commit()
    db.refresh(device)
    return device


@router.post("/{device_uuid}/revoke", response_model=schemas.DeviceResponse)
def revoke_device(device_uuid: str, db: Session = Depends(get_db)):
    """Para cuando se pierde/roba el teléfono del agente — cualquier firma
    posterior de este dispositivo debe dejar de aceptarse en /sync/push."""
    from datetime import datetime, timezone

    device = db.query(models.Device).filter(models.Device.uuid == device_uuid).first()
    if not device:
        raise HTTPException(404, "Dispositivo no encontrado")

    device.revoked_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(device)
    return device


@router.get("/user/{user_id}", response_model=list[schemas.DeviceResponse])
def list_user_devices(user_id: int, db: Session = Depends(get_db)):
    return (
        db.query(models.Device)
        .filter(models.Device.user_id == user_id, models.Device.revoked_at.is_(None))
        .all()
    )
