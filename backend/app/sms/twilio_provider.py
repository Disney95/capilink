"""
CapiLink — Proveedor de SMS real vía Twilio.
Requiere las credenciales en variables de entorno (ver app/config.py):
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN,
  y TWILIO_FROM_NUMBER o TWILIO_MESSAGING_SERVICE_SID.

Reintentos: solo ante errores transitorios (timeouts, 5xx, límites de
tasa de Twilio). Errores permanentes (número inválido, credenciales
incorrectas) fallan inmediato — reintentarlos no cambia el resultado.
"""

import logging
import time

from twilio.base.exceptions import TwilioRestException
from twilio.rest import Client

from ..config import Settings
from .base import SMSDeliveryError, SMSProvider

logger = logging.getLogger("capilink.sms.twilio")

# Códigos de error de Twilio que valen la pena reintentar. El resto
# (número inválido, cuenta suspendida, credenciales, "unsubscribed", etc.)
# son permanentes — reintentar solo gasta cuota y retrasa el fallo.
_RETRIABLE_TWILIO_CODES = {
    20429,  # Too Many Requests (rate limit de Twilio)
    20500,  # Internal Server Error de Twilio
    20503,  # Service Unavailable
}


class TwilioSMSProvider(SMSProvider):
    name = "twilio"

    def __init__(self, settings: Settings):
        if not settings.twilio_account_sid or not settings.twilio_auth_token:
            raise ValueError(
                "TWILIO_ACCOUNT_SID y TWILIO_AUTH_TOKEN son obligatorios "
                "cuando SMS_PROVIDER=twilio"
            )
        if not settings.twilio_from_number and not settings.twilio_messaging_service_sid:
            raise ValueError(
                "Configura TWILIO_FROM_NUMBER o TWILIO_MESSAGING_SERVICE_SID "
                "cuando SMS_PROVIDER=twilio"
            )

        self._client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
        self._from_number = settings.twilio_from_number
        self._messaging_service_sid = settings.twilio_messaging_service_sid
        self._max_retries = settings.sms_max_retries
        self._backoff_seconds = settings.sms_retry_backoff_seconds

    def send(self, phone_number: str, message: str) -> str:
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                kwargs = {"to": phone_number, "body": message}
                if self._messaging_service_sid:
                    kwargs["messaging_service_sid"] = self._messaging_service_sid
                else:
                    kwargs["from_"] = self._from_number

                result = self._client.messages.create(**kwargs)
                logger.info(
                    "SMS [twilio] a=%s sid=%s status=%s intento=%d",
                    phone_number, result.sid, result.status, attempt,
                )
                return result.sid

            except TwilioRestException as exc:
                last_error = exc
                retriable = exc.code in _RETRIABLE_TWILIO_CODES
                logger.warning(
                    "SMS [twilio] fallo a=%s intento=%d/%d code=%s retriable=%s: %s",
                    phone_number, attempt, self._max_retries, exc.code, retriable, exc,
                )
                if not retriable or attempt == self._max_retries:
                    raise SMSDeliveryError(
                        f"Twilio rechazó el envío (code={exc.code}): {exc.msg}",
                        provider="twilio",
                        retriable=retriable,
                    ) from exc
                time.sleep(self._backoff_seconds * attempt)

            except Exception as exc:  # errores de red/transporte, no de Twilio
                last_error = exc
                logger.warning(
                    "SMS [twilio] error de transporte a=%s intento=%d/%d: %s",
                    phone_number, attempt, self._max_retries, exc,
                )
                if attempt == self._max_retries:
                    raise SMSDeliveryError(
                        f"Error de transporte enviando SMS: {exc}",
                        provider="twilio",
                        retriable=True,
                    ) from exc
                time.sleep(self._backoff_seconds * attempt)

        # No debería llegar aquí, pero por si acaso:
        raise SMSDeliveryError(
            f"Fallo desconocido enviando SMS: {last_error}", provider="twilio",
        )
