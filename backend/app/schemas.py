import uuid
from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field


class CreateOrderRequest(BaseModel):
    emisor_id: int
    beneficiario_phone: str
    destination_address: str
    municipality: str
    amount_fiat_minor: int = Field(gt=0)
    currency: Literal["CUP", "USD"]


class OrderResponse(BaseModel):
    uuid: uuid.UUID
    status: str
    municipality: str
    amount_fiat_minor: int
    currency: str
    otp_expires_at: datetime
    otp_sms_status: str
    otp_sms_attempts: int
    otp_sms_error: Optional[str] = None

    class Config:
        from_attributes = True


class AssignOrderRequest(BaseModel):
    agent_id: int


class CancelOrderRequest(BaseModel):
    reason: Optional[str] = None


# --- Sincronización ---

class SyncOrderDownloadItem(BaseModel):
    """Lo que baja al dispositivo del agente. Nótese: incluye otp_hash y
    otp_secret (necesarios para verificar offline), pero JAMÁS el OTP en
    texto plano — ese solo lo tiene el destinatario, por SMS."""
    uuid: uuid.UUID
    beneficiario_phone: str
    destination_address: str
    municipality: str
    amount_fiat_minor: int
    currency: str
    otp_hash: str
    otp_secret: str
    otp_expires_at: datetime
    otp_attempts: int
    otp_max_attempts: int
    status: str
    assigned_at: Optional[datetime]

    class Config:
        from_attributes = True


class SyncDeliveryUploadItem(BaseModel):
    """Lo que sube el agente al confirmar una entrega. `proof_signature`
    debe venir firmada con la clave privada del dispositivo — el backend
    la valida contra devices.public_key antes de aceptar la entrega."""
    uuid: uuid.UUID
    order_uuid: uuid.UUID
    device_uuid: uuid.UUID
    delivered_at: datetime
    lat: Optional[float] = None
    lng: Optional[float] = None
    accuracy_m: Optional[float] = None
    proof_signature: str  # hex


class SyncPushRequest(BaseModel):
    deliveries: list[SyncDeliveryUploadItem] = []


class SyncPushResult(BaseModel):
    order_uuid: uuid.UUID
    accepted: bool
    reason: str  # 'OK' | 'SIGNATURE_INVALID' | 'ORDER_STATE_CONFLICT' | 'ALREADY_SYNCED'


# --- Usuarios y dispositivos ---

class CreateUserRequest(BaseModel):
    role: Literal["PROVEEDOR", "AGENTE_CAMPO", "CLIENTE"]
    phone_number: str
    full_name: Optional[str] = None


class UserResponse(BaseModel):
    id: int
    uuid: uuid.UUID
    role: str
    phone_number: str
    full_name: Optional[str]
    status: str
    created_at: datetime

    class Config:
        from_attributes = True


class RegisterDeviceRequest(BaseModel):
    user_id: int
    public_key: str  # Ed25519 pubkey, base64
    platform: Optional[Literal["ANDROID", "IOS"]] = None
    app_version: Optional[str] = None


class DeviceResponse(BaseModel):
    id: int
    uuid: uuid.UUID
    user_id: int
    public_key: str
    platform: Optional[str]
    revoked_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


# --- Tesorería ---

class CreateCashPoolRequest(BaseModel):
    proveedor_id: int


class CashPoolResponse(BaseModel):
    id: int
    uuid: uuid.UUID
    proveedor_id: int
    total_cup_minor: int
    total_usd_minor: int
    available_cup_minor: int
    available_usd_minor: int
    updated_at: datetime

    class Config:
        from_attributes = True


class DepositRequest(BaseModel):
    currency: Literal["CUP", "USD"]
    amount_minor: int = Field(gt=0)
    idempotency_key: Optional[uuid.UUID] = None


class AllocateRequest(BaseModel):
    agente_id: int
    currency: Literal["CUP", "USD"]
    amount_minor: int = Field(gt=0)
    idempotency_key: Optional[uuid.UUID] = None


class LedgerEntryResponse(BaseModel):
    id: int
    idempotency_key: uuid.UUID
    cash_pool_id: int
    agente_id: Optional[int]
    entry_type: str
    currency: str
    amount_minor: int
    created_at: datetime

    class Config:
        from_attributes = True


class AgentBalanceResponse(BaseModel):
    agente_id: int
    currency: str
    available_minor: int


# --- Colaterales ---

class LockCollateralRequest(BaseModel):
    agente_id: int
    proveedor_id: int
    amount_usdt_minor: int = Field(gt=0)  # USDT con 6 decimales -> x1,000,000
    chain: Literal["TRC20", "ERC20", "BEP20"] = "TRC20"
    tx_hash: Optional[str] = None  # tx on-chain del depósito del agente, si ya se conoce


class ForfeitCollateralRequest(BaseModel):
    settlement_tx_hash: Optional[str] = None  # tx on-chain del pago al proveedor, si ya se conoce


class CollateralResponse(BaseModel):
    id: int
    uuid: uuid.UUID
    agente_id: int
    proveedor_id: int
    amount_usdt_minor: int
    chain: str
    status: str
    tx_hash: Optional[str]
    locked_at: datetime
    released_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True
