import uuid as uuid_lib

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import models, schemas, ledger_service
from ..database import get_db

router = APIRouter(prefix="/treasury", tags=["treasury"])


@router.post("/cash-pools", response_model=schemas.CashPoolResponse, status_code=201)
def create_cash_pool(payload: schemas.CreateCashPoolRequest, db: Session = Depends(get_db)):
    proveedor = db.query(models.User).filter(
        models.User.id == payload.proveedor_id, models.User.role == "PROVEEDOR"
    ).first()
    if not proveedor:
        raise HTTPException(404, "Proveedor no encontrado")

    pool = models.CashPool(proveedor_id=payload.proveedor_id)
    db.add(pool)
    db.commit()
    db.refresh(pool)
    return pool


@router.post("/cash-pools/{pool_uuid}/deposit", response_model=schemas.LedgerEntryResponse, status_code=201)
def deposit_to_pool(pool_uuid: uuid_lib.UUID, payload: schemas.DepositRequest, db: Session = Depends(get_db)):
    """El proveedor mete efectivo físico al pool (ej. metió más dinero a la
    caja general). No mueve nada de un agente en particular."""
    pool = db.query(models.CashPool).filter(models.CashPool.uuid == pool_uuid).first()
    if not pool:
        raise HTTPException(404, "Cash pool no encontrado")

    entry = ledger_service.insert_ledger_entry(
        db,
        idempotency_key=payload.idempotency_key or uuid_lib.uuid4(),
        cash_pool_id=pool.id,
        entry_type="PROVIDER_DEPOSIT",
        currency=payload.currency,
        amount_minor=abs(payload.amount_minor),  # un depósito siempre suma
    )
    db.commit()
    db.refresh(entry)
    return entry


@router.post("/cash-pools/{pool_uuid}/allocate", response_model=schemas.LedgerEntryResponse, status_code=201)
def allocate_to_agent(pool_uuid: uuid_lib.UUID, payload: schemas.AllocateRequest, db: Session = Depends(get_db)):
    """El proveedor entrega efectivo físico en mano a un agente. Se modela
    como DOS entradas de ledger relacionadas (nunca como un UPDATE de saldo,
    ver ARCHITECTURE.md §3.1):
      1) -X con agente_id=NULL  -> sale del "disponible sin asignar" del pool
      2) +X con agente_id=agentX -> aparece como disponible para ESE agente
    Ambas comparten el mismo importe y quedan enlazadas por una clave de
    idempotencia derivada, para que reintentar la operación no la duplique."""
    pool = db.query(models.CashPool).filter(models.CashPool.uuid == pool_uuid).first()
    if not pool:
        raise HTTPException(404, "Cash pool no encontrado")

    agent = db.query(models.User).filter(
        models.User.id == payload.agente_id, models.User.role == "AGENTE_CAMPO"
    ).first()
    if not agent:
        raise HTTPException(404, "Agente no encontrado")

    pool_available = (
        pool.available_cup_minor if payload.currency == "CUP" else pool.available_usd_minor
    )
    if pool_available < payload.amount_minor:
        raise HTTPException(
            409,
            f"El pool no tiene fondos suficientes sin asignar (disponible={pool_available}, "
            f"solicitado={payload.amount_minor})",
        )

    base_key = payload.idempotency_key or uuid_lib.uuid4()
    agent_side_key = uuid_lib.uuid5(uuid_lib.NAMESPACE_OID, f"{base_key}:agent_side")

    ledger_service.insert_ledger_entry(
        db,
        idempotency_key=base_key,
        cash_pool_id=pool.id,
        entry_type="AGENT_ALLOCATION",
        currency=payload.currency,
        amount_minor=-abs(payload.amount_minor),  # sale del disponible general del pool
        agente_id=None,
    )
    agent_side_entry = ledger_service.insert_ledger_entry(
        db,
        idempotency_key=agent_side_key,
        cash_pool_id=pool.id,
        entry_type="AGENT_ALLOCATION",
        currency=payload.currency,
        amount_minor=abs(payload.amount_minor),  # aparece disponible para el agente
        agente_id=payload.agente_id,
    )

    db.commit()
    db.refresh(agent_side_entry)
    return agent_side_entry


@router.get("/agents/{agente_id}/balance", response_model=schemas.AgentBalanceResponse)
def get_agent_balance(agente_id: int, currency: str, db: Session = Depends(get_db)):
    disponible = ledger_service.get_agent_available_balance(db, agente_id, currency)
    return schemas.AgentBalanceResponse(agente_id=agente_id, currency=currency, available_minor=disponible)


@router.get("/cash-pools/{pool_uuid}", response_model=schemas.CashPoolResponse)
def get_cash_pool(pool_uuid: uuid_lib.UUID, db: Session = Depends(get_db)):
    pool = db.query(models.CashPool).filter(models.CashPool.uuid == pool_uuid).first()
    if not pool:
        raise HTTPException(404, "Cash pool no encontrado")
    return pool
