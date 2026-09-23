"""
CapiLink — Servicio de OTP (backend).
Misma lógica descrita en ARCHITECTURE.md §4. El OTP en texto plano nunca
se persiste; solo se devuelve una vez, para enviarlo por SMS.
"""

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

OTP_LENGTH = 6
OTP_TTL_HOURS = 72

_TRIVIAL_PATTERNS = {
    "000000", "111111", "222222", "333333", "444444", "555555",
    "666666", "777777", "888888", "999999", "123456", "654321",
}


def generate_otp() -> str:
    while True:
        otp = "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))
        if otp not in _TRIVIAL_PATTERNS:
            return otp


def generate_order_secret_hex() -> str:
    return secrets.token_hex(32)


def compute_otp_hash(order_secret_hex: str, otp: str) -> str:
    key = bytes.fromhex(order_secret_hex)
    return hmac.new(key, otp.encode("utf-8"), hashlib.sha256).hexdigest()


def create_order_otp() -> dict:
    otp_plain = generate_otp()
    order_secret = generate_order_secret_hex()
    otp_hash = compute_otp_hash(order_secret, otp_plain)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=OTP_TTL_HOURS)
    return {
        "otp_plain": otp_plain,        # enviar por SMS y descartar, no persistir
        "otp_hash": otp_hash,
        "otp_secret": order_secret,
        "otp_expires_at": expires_at,
    }


def send_otp_sms(phone_number: str, otp_plain: str) -> None:
    """Punto de integración con el proveedor de SMS (Twilio/SNS/similar).
    Implementación real queda fuera de este esqueleto — aquí solo el contrato."""
    # TODO: integrar proveedor de SMS real.
    raise NotImplementedError("Conectar con proveedor de SMS (Twilio/SNS/etc.)")
