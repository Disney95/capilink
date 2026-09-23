"""
CapiLink — Configuración.
Todo lo sensible (credenciales de Twilio, etc.) viene de variables de
entorno — nunca hardcodeado. Usa pydantic-settings para validar al arrancar
la app en vez de fallar a mitad de un request.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- Selección de proveedor de SMS ---
    # "console": no envía nada real, solo loguea (desarrollo local / tests).
    # "twilio": envío real vía Twilio.
    sms_provider: Literal["console", "twilio"] = "console"

    # --- Twilio ---
    twilio_account_sid: str | None = None
    twilio_auth_token: str | None = None
    twilio_from_number: str | None = None
    # Alternativa a un número fijo: un Messaging Service de Twilio
    # (recomendado en producción — maneja pooling de números y compliance).
    twilio_messaging_service_sid: str | None = None

    # Reintentos del envío de SMS a nivel de aplicación (no confundir con
    # los reintentos de sync_queue del cliente offline — esto es servidor).
    sms_max_retries: int = 3
    sms_retry_backoff_seconds: float = 1.5


@lru_cache
def get_settings() -> Settings:
    return Settings()
