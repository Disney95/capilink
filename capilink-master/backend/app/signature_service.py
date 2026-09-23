"""
CapiLink — Verificación de firma Ed25519 de pruebas de entrega.
Ver ARCHITECTURE.md §5. Requiere PyNaCl (pynacl) — libsodium bindings.
"""

import base64
import json
from nacl.signing import VerifyKey
from nacl.exceptions import BadSignatureError


def _format_coord(value) -> str | None:
    """6 decimales fijos, igual que lat.toStringAsFixed(6) en Dart. Debe
    coincidir byte a byte con device_signature_service.dart o la
    verificación de firma fallará siempre por un detalle de formato."""
    if value is None:
        return None
    return f"{float(value):.6f}"


def build_proof_payload(order_uuid: str, otp_hash: str, lat, lng, delivered_at_iso: str, device_uuid: str) -> bytes:
    """Debe coincidir EXACTO (mismo orden de claves, mismo formato) con lo
    que firma el cliente Flutter en `device_signature_service.dart`.
    Se usa JSON canónico con claves ordenadas y lat/lng como string fijo."""
    payload = {
        "order_uuid": order_uuid,
        "otp_hash": otp_hash,
        "lat": _format_coord(lat),
        "lng": _format_coord(lng),
        "delivered_at": delivered_at_iso,
        "device_uuid": device_uuid,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def verify_delivery_signature(public_key_b64: str, payload: bytes, signature_hex: str) -> bool:
    """Devuelve True solo si la firma es válida para ese payload exacto y
    esa clave pública. Cualquier alteración del payload (lat/lng, timestamp,
    hash de OTP) invalida la firma."""
    try:
        verify_key = VerifyKey(base64.b64decode(public_key_b64))
        signature = bytes.fromhex(signature_hex)
        verify_key.verify(payload, signature)
        return True
    except (BadSignatureError, ValueError, TypeError):
        return False
