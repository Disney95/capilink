from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db

router = APIRouter(prefix="/users", tags=["users"])


@router.post("", response_model=schemas.UserResponse, status_code=201)
def create_user(payload: schemas.CreateUserRequest, db: Session = Depends(get_db)):
    existing = db.query(models.User).filter(models.User.phone_number == payload.phone_number).first()
    if existing:
        raise HTTPException(409, "Ya existe un usuario con ese número de teléfono")

    user = models.User(
        role=payload.role,
        phone_number=payload.phone_number,
        full_name=payload.full_name,
        status="ACTIVE",  # esqueleto: sin verificación por SMS todavía, ver otp_service.send_otp_sms
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.get("/{user_id}", response_model=schemas.UserResponse)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(404, "Usuario no encontrado")
    return user


@router.get("", response_model=list[schemas.UserResponse])
def list_users(role: str | None = None, db: Session = Depends(get_db)):
    query = db.query(models.User)
    if role:
        query = query.filter(models.User.role == role)
    return query.order_by(models.User.created_at.desc()).all()
