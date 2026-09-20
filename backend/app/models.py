import uuid as uuid_lib
from sqlalchemy import (
    Column, BigInteger, Integer, String, Text, Boolean, DateTime,
    ForeignKey, CheckConstraint, JSON, Double, func
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from .database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(BigInteger, primary_key=True)
    uuid = Column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid_lib.uuid4)
    role = Column(String, nullable=False)  # PROVEEDOR | AGENTE_CAMPO | CLIENTE
    phone_number = Column(String, unique=True, nullable=False)
    full_name = Column(String)
    status = Column(String, nullable=False, default="PENDING_VERIFICATION")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    devices = relationship("Device", back_populates="user")


class Device(Base):
    __tablename__ = "devices"

    id = Column(BigInteger, primary_key=True)
    uuid = Column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid_lib.uuid4)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    public_key = Column(Text, nullable=False)  # Ed25519 pubkey, base64
    platform = Column(String)
    app_version = Column(String)
    last_sync_at = Column(DateTime(timezone=True))
    revoked_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="devices")


class CashPool(Base):
    __tablename__ = "cash_pools"

    id = Column(BigInteger, primary_key=True)
    uuid = Column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid_lib.uuid4)
    proveedor_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    total_cup_minor = Column(BigInteger, nullable=False, default=0)
    total_usd_minor = Column(BigInteger, nullable=False, default=0)
    available_cup_minor = Column(BigInteger, nullable=False, default=0)  # caché, ver ledger
    available_usd_minor = Column(BigInteger, nullable=False, default=0)  # caché, ver ledger
    version = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class CashLedgerEntry(Base):
    """Append-only. Nunca se hace UPDATE ni DELETE sobre esta tabla desde la
    aplicación — solo INSERT. Ver ARCHITECTURE.md §3.1."""
    __tablename__ = "cash_ledger_entries"

    id = Column(BigInteger, primary_key=True)
    idempotency_key = Column(UUID(as_uuid=True), unique=True, nullable=False)
    cash_pool_id = Column(BigInteger, ForeignKey("cash_pools.id"), nullable=False)
    agente_id = Column(BigInteger, ForeignKey("users.id"))
    order_id = Column(BigInteger, ForeignKey("distribution_orders.id"))
    entry_type = Column(String, nullable=False)
    currency = Column(String, nullable=False)  # CUP | USD
    amount_minor = Column(BigInteger, nullable=False)  # con signo
    created_by_device_id = Column(BigInteger, ForeignKey("devices.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    metadata_json = Column("metadata", JSONB)


class Collateral(Base):
    __tablename__ = "collaterals"

    id = Column(BigInteger, primary_key=True)
    uuid = Column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid_lib.uuid4)
    agente_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    proveedor_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    amount_usdt_minor = Column(BigInteger, nullable=False)
    chain = Column(String, nullable=False, default="TRC20")
    status = Column(String, nullable=False, default="LOCKED")
    tx_hash = Column(String)
    locked_at = Column(DateTime(timezone=True), server_default=func.now())
    released_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class DistributionOrder(Base):
    __tablename__ = "distribution_orders"

    id = Column(BigInteger, primary_key=True)
    uuid = Column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid_lib.uuid4)
    emisor_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    beneficiario_phone = Column(String, nullable=False)
    destination_address = Column(Text, nullable=False)
    municipality = Column(String, nullable=False)
    amount_fiat_minor = Column(BigInteger, nullable=False)
    currency = Column(String, nullable=False)  # CUP | USD

    otp_hash = Column(Text, nullable=False)
    otp_secret = Column(Text, nullable=False)
    otp_expires_at = Column(DateTime(timezone=True), nullable=False)
    otp_attempts = Column(Integer, nullable=False, default=0)
    otp_max_attempts = Column(Integer, nullable=False, default=5)
    otp_locked_at = Column(DateTime(timezone=True))

    status = Column(String, nullable=False, default="PENDING")
    assigned_agent_id = Column(BigInteger, ForeignKey("users.id"))
    assigned_at = Column(DateTime(timezone=True))

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())


class Delivery(Base):
    __tablename__ = "deliveries"

    id = Column(BigInteger, primary_key=True)
    uuid = Column(UUID(as_uuid=True), unique=True, nullable=False, default=uuid_lib.uuid4)
    order_id = Column(BigInteger, ForeignKey("distribution_orders.id"), unique=True, nullable=False)
    agente_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    device_id = Column(BigInteger, ForeignKey("devices.id"), nullable=False)

    assigned_at = Column(DateTime(timezone=True), nullable=False)
    delivered_at = Column(DateTime(timezone=True), nullable=False)
    synced_at = Column(DateTime(timezone=True))

    lat = Column(Double)
    lng = Column(Double)
    accuracy_m = Column(Double)

    proof_signature = Column(Text, nullable=False)
    signature_verified = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SyncConflict(Base):
    __tablename__ = "sync_conflicts"

    id = Column(BigInteger, primary_key=True)
    entity_type = Column(String, nullable=False)
    entity_uuid = Column(UUID(as_uuid=True), nullable=False)
    conflict_reason = Column(Text, nullable=False)
    incoming_payload = Column(JSONB, nullable=False)
    current_state_snapshot = Column(JSONB, nullable=False)
    resolved = Column(Boolean, nullable=False, default=False)
    resolved_by = Column(BigInteger, ForeignKey("users.id"))
    resolved_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(BigInteger, primary_key=True)
    actor_user_id = Column(BigInteger, ForeignKey("users.id"))
    actor_device_id = Column(BigInteger, ForeignKey("devices.id"))
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=False)
    entity_uuid = Column(UUID(as_uuid=True), nullable=False)
    metadata_json = Column("metadata", JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
