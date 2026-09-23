"""
CapiLink — Servicio de OTP (backend)
Genera el OTP, calcula el HMAC-SHA256 con salt aleatorio por orden,
y NUNCA persiste el OTP en texto plano. Ver ARCHITECTURE.md §4.
"""

import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

OTP_LENGTH = 6
OTP_TTL_HOURS = 72
OTP_MAX_ATTEMPTS = 5

# Patrones triviales que se rechazan aunque salgan del generador aleatorio
_TRIVIAL_PATTERNS = {
    "000000", "111111", "222222", "333333", "444444", "555555",
    "666666", "777777", "888888", "999999", "123456", "654321",
}


def generate_otp() -> str:
    """Genera un OTP numérico de 6 dígitos criptográficamente aleatorio,
    evitando patrones triviales."""
    while True:
        otp = "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))
        if otp not in _TRIVIAL_PATTERNS:
            return otp


def generate_order_secret() -> str:
    """32 bytes aleatorios, codificados en hex, únicos por orden.
    No es secreto en el sentido de 'nunca se comparte' — viaja al
    dispositivo del agente junto con la orden. Su función es evitar
    precómputo de tablas de hashes reutilizables entre órdenes."""
    return secrets.token_hex(32)


def compute_otp_hash(order_secret_hex: str, otp: str) -> str:
    """HMAC-SHA256(key=order_secret, message=otp) -> hex digest."""
    key = bytes.fromhex(order_secret_hex)
    return hmac.new(key, otp.encode("utf-8"), hashlib.sha256).hexdigest()


def create_order_otp() -> dict:
    """Devuelve todo lo necesario para persistir en distribution_orders
    y lo que hay que enviar al destinatario por SMS.

    IMPORTANTE: 'otp_plain' se envía por SMS y se descarta inmediatamente
    después — no se loguea, no se guarda en ninguna tabla, no se incluye
    en respuestas de API salvo la que dispara el SMS."""
    otp_plain = generate_otp()
    order_secret = generate_order_secret()
    otp_hash = compute_otp_hash(order_secret, otp_plain)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=OTP_TTL_HOURS)

    return {
        "otp_plain": otp_plain,          # -> enviar por SMS, no persistir
        "otp_hash": otp_hash,             # -> persistir en distribution_orders.otp_hash
        "otp_secret": order_secret,       # -> persistir en distribution_orders.otp_secret
                                           #    y sincronizar al dispositivo del agente asignado
        "otp_expires_at": expires_at.isoformat(),
    }


def reset_order_otp() -> dict:
    """Se usa cuando el agente agota los intentos (otp_locked_at) o el
    destinatario perdió el SMS. Requiere que el agente tenga señal para
    recibir el nuevo otp_hash/otp_secret — por diseño, un reset SIEMPRE
    requiere ida y vuelta al backend, nunca se resuelve solo localmente."""
    return create_order_otp()
