"""
CapiLink — Proveedor de SMS "console".
No envía nada real: loguea el mensaje. Útil para desarrollo local y para
correr la suite de tests sin credenciales de Twilio ni gastar SMS reales.
Nunca debe usarse en producción — es responsabilidad del operador fijar
SMS_PROVIDER=twilio fuera de local/test.
"""

import logging
import uuid

logger = logging.getLogger("capilink.sms.console")


class ConsoleSMSProvider:
    name = "console"

    def send(self, phone_number: str, message: str) -> str:
        fake_message_id = f"console-{uuid.uuid4().hex[:12]}"
        logger.info(
            "SMS [console] a=%s id=%s texto=%r",
            phone_number, fake_message_id, message,
        )
        return fake_message_id
