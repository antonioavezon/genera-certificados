"""Contrato de los proveedores de correo."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OutboundEmail:
    to: str
    subject: str
    body: str
    attachment_path: Path | None
    attachment_name: str


@dataclass(frozen=True)
class SendResult:
    message_id: str = ""


class EmailProvider(ABC):
    name = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """True solo cuando este equipo puede usar el proveedor ahora."""

    @abstractmethod
    def unavailable_reason(self) -> str:
        """Texto para la interfaz cuando is_available() es falso."""

    @abstractmethod
    def validate_configuration(self) -> list[str]:
        """Lista vacía si la configuración alcanza para enviar."""

    @abstractmethod
    def send(self, message: OutboundEmail) -> SendResult:
        """Envía y confirma. No debe marcar nada como enviado: eso lo hace el servicio."""

    @abstractmethod
    def create_draft(self, message: OutboundEmail) -> SendResult:
        """Crea un borrador cuando el proveedor lo permite."""


class UnavailableProvider(EmailProvider):
    name = "none"

    def is_available(self) -> bool:
        return False

    def unavailable_reason(self) -> str:
        return "No hay un proveedor de correo configurado."

    def validate_configuration(self) -> list[str]:
        return [self.unavailable_reason()]

    def send(self, message: OutboundEmail) -> SendResult:
        from diplomas.exceptions import EmailConfigurationError

        raise EmailConfigurationError(self.unavailable_reason())

    def create_draft(self, message: OutboundEmail) -> SendResult:
        from diplomas.exceptions import EmailConfigurationError

        raise EmailConfigurationError(self.unavailable_reason())
