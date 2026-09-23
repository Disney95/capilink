"""
CapiLink — Contrato de proveedor de SMS.
Cualquier proveedor (Twilio, AWS SNS, etc.) implementa esta interfaz para
que otp_service.py y los routers nunca dependan de un SDK concreto.
"""

from abc import ABC, abstractmethod


class SMSDeliveryError(Exception):
    """Se lanza cuando el proveedor no pudo enviar el SMS, tras agotar los
    reintentos de aplicación configurados. Distinta de NotImplementedError:
    esta representa un fallo real de envío (red, credenciales, número
    inválido, etc.), no un proveedor sin configurar."""

    def __init__(self, message: str, *, provider: str, retriable: bool = True):
        super().__init__(message)
        self.provider = provider
        self.retriable = retriable


class SMSProvider(ABC):
    name: str = "base"

    @abstractmethod
    def send(self, phone_number: str, message: str) -> str:
        """Envía el SMS. Devuelve un id de mensaje del proveedor (para logs/
        auditoría). Debe lanzar SMSDeliveryError si falla — nunca devolver
        silenciosamente un estado de éxito falso."""
        raise NotImplementedError
