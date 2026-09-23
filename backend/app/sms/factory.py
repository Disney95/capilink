"""
CapiLink — Fábrica de proveedor de SMS.
El resto de la app nunca importa Twilio directamente, solo pide
get_sms_provider() — así cambiar de proveedor (o mockearlo en tests) es
un solo punto de cambio.
"""

from functools import lru_cache

from ..config import Settings, get_settings
from .base import SMSProvider
from .console_provider import ConsoleSMSProvider


@lru_cache
def get_sms_provider() -> SMSProvider:
    settings = get_settings()

    if settings.sms_provider == "twilio":
        from .twilio_provider import TwilioSMSProvider  # import perezoso:
        # así el paquete `twilio` no es obligatorio si nunca se usa ese modo.
        return TwilioSMSProvider(settings)

    return ConsoleSMSProvider()
