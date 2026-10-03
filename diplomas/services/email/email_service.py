"""Envíos idempotentes: un correo SENT no se vuelve a mandar solo."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from django.conf import settings as django_settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from diplomas.exceptions import DiplomaError, EmailConfigurationError, EmailSendError
from diplomas.models import (
    EmailAttempt,
    EmailDelivery,
    EmailStatus,
    GenerationBatch,
    GenerationRecord,
    GenerationStatus,
)
from diplomas.services.config_service import get_settings
from diplomas.services.email.base import EmailProvider, OutboundEmail, UnavailableProvider
from diplomas.services.email.outlook_provider import OutlookProvider
from diplomas.services.email.smtp_provider import SMTPProvider
from diplomas.services.file_service import contained_file
from diplomas.services.logging_service import get_logger
from diplomas.services.validation_service import email_is_valid

logger = get_logger("email")

PDF_READY = {
    GenerationStatus.GENERATED,
    GenerationStatus.REGENERATED,
    GenerationStatus.ALREADY_EXISTS,
}
_OPEN = {EmailStatus.PENDING, EmailStatus.SENDING}


@dataclass
class EmailRunResult:
    sent: int = 0
    failed: int = 0
    skipped: int = 0
    invalid: int = 0
    messages: list[str] = field(default_factory=list)
    stopped_reason: str = ""

    @property
    def summary(self) -> str:
        return (
            f"Enviados: {self.sent}. Fallidos: {self.failed}. "
            f"Omitidos: {self.skipped}. Correos inválidos: {self.invalid}."
        )


class EmailService:
    def __init__(self, provider: EmailProvider | None = None) -> None:
        self._provider = provider

    def provider_ready(self) -> tuple[bool, list[str]]:
        provider = self._resolve()
        problems = provider.validate_configuration()
        return (not problems), problems

    def send_for_batch(self, batch: GenerationBatch) -> EmailRunResult:
        records = list(
            batch.records.filter(status__in=PDF_READY).order_by("id")
        )
        return self._send_records(records, mode="all_unsent")

    def continue_pending(self) -> EmailRunResult:
        return self._send_records(list(self._pending_records()), mode="pending")

    def retry_failed(self) -> EmailRunResult:
        deliveries = EmailDelivery.objects.filter(
            status=EmailStatus.FAILED,
            sent_at__isnull=True,
        ).select_related("generation_record")
        records = [
            delivery.generation_record
            for delivery in deliveries
            if delivery.generation_record_id and delivery.generation_record is not None
        ]
        return self._send_records(records, mode="failed")

    def resend(self, delivery: EmailDelivery) -> EmailRunResult:
        result = EmailRunResult()
        outcome = self._attempt_delivery(delivery, mode="resend")
        _count(result, outcome, delivery.recipient)
        if delivery.batch_id:
            _refresh_batches_by_id([delivery.batch_id])
        return result

    def _pending_records(self):
        seen: set[tuple[str, str]] = set()
        records = GenerationRecord.objects.filter(status__in=PDF_READY).exclude(filename="").order_by("-id")
        for record in records.iterator():
            key = (record.email_key, record.filename)
            if not record.email_key or key in seen:
                continue
            seen.add(key)
            delivery = _delivery_for(record.email_key, record.filename)
            if delivery is not None and (delivery.was_sent or delivery.status not in _OPEN):
                continue
            yield record

    def _send_records(self, records: list[GenerationRecord], *, mode: str) -> EmailRunResult:
        result = EmailRunResult()
        if not records:
            result.messages.append("No hay correos pendientes para esta acción.")
            return result
        try:
            provider = self._require_provider()
        except EmailConfigurationError as exc:
            result.stopped_reason = exc.user_message
            result.messages.append(exc.user_message)
            return result
        for record in records:
            try:
                outcome = self._attempt_record(record, provider=provider, mode=mode)
            except EmailConfigurationError as exc:
                logger.exception(
                    "La configuración de correo dejó de ser válida",
                    extra={"batch": record.batch_id, "participant": record.full_name},
                )
                result.stopped_reason = exc.user_message
                result.messages.append(exc.user_message)
                break
            _count(result, outcome, record.full_name or record.email)
        _refresh_batches(records)
        return result

    def _attempt_record(self, record: GenerationRecord, *, provider: EmailProvider, mode: str) -> str:
        if not record.email.strip():
            logger.info(
                "Sin correo; no se envía.",
                extra={"batch": record.batch_id, "participant": record.full_name},
            )
            return "skipped"
        return self._deliver(
            provider=provider,
            mode=mode,
            recipient=record.email.strip(),
            filename=record.filename,
            full_name=record.full_name,
            participant=record.participant,
            generation_record=record,
            batch=record.batch,
        )

    def _attempt_delivery(self, delivery: EmailDelivery, *, mode: str) -> str:
        provider = self._require_provider()
        record = delivery.generation_record
        full_name = record.full_name if record is not None else delivery.recipient
        return self._deliver(
            provider=provider,
            mode=mode,
            recipient=delivery.recipient,
            filename=delivery.attachment,
            full_name=full_name,
            participant=delivery.participant,
            generation_record=record,
            batch=delivery.batch,
        )

    def _deliver(
        self,
        *,
        provider: EmailProvider,
        mode: str,
        recipient: str,
        filename: str,
        full_name: str,
        participant,
        generation_record,
        batch,
    ) -> str:
        recipient_key = recipient.strip().casefold()
        if not filename:
            return "skipped"
        delivery = _locked_delivery(
            recipient_key,
            filename,
            participant=participant,
            generation_record=generation_record,
            batch=batch,
        )
        if mode != "resend" and delivery.was_sent:
            logger.info(
                "Correo enviado previamente.",
                extra={"batch": getattr(batch, "pk", "-"), "participant": full_name},
            )
            return "skipped"
        if mode == "pending" and delivery.status not in _OPEN:
            return "skipped"
        if mode == "failed" and (delivery.status != EmailStatus.FAILED or delivery.sent_at is not None):
            return "skipped"
        if not email_is_valid(recipient):
            _save_invalid(delivery, full_name)
            return "invalid"

        path = _pdf_path(filename)
        if path is None or not path.is_file():
            _save_failure(
                delivery,
                f"No fue posible enviar el correo a {full_name}. "
                "No se encontró el PDF para adjuntar y el envío quedó pendiente.",
            )
            return "failed"

        app_settings = get_settings()
        message = OutboundEmail(
            to=recipient.strip(),
            subject=_personalize(app_settings.email_subject, full_name)[:255],
            body=_personalize(app_settings.email_body, full_name),
            attachment_path=path,
            attachment_name=filename,
        )
        attempts = django_settings.EMAIL_MAX_ATTEMPTS
        backoff = django_settings.EMAIL_RETRY_BACKOFF_SECONDS
        last_error = "No fue posible enviar el correo."
        for index in range(attempts):
            attempt_row = _begin_attempt(delivery, provider.name, batch)
            try:
                result = provider.send(message)
            except EmailConfigurationError:
                _finish_attempt(delivery, attempt_row, EmailStatus.FAILED, "La configuración de correo no es válida.")
                raise
            except EmailSendError as exc:
                last_error = exc.user_message
                _finish_attempt(delivery, attempt_row, EmailStatus.FAILED, exc.user_message)
                logger.warning(
                    "Intento %s fallido para %s: %s",
                    delivery.attempt_count,
                    recipient_key,
                    exc.user_message,
                    extra={"batch": getattr(batch, "pk", "-"), "participant": full_name},
                )
                if index + 1 < attempts:
                    time.sleep(backoff * (index + 1))
                    continue
                _save_failure(
                    delivery,
                    f"No fue posible enviar el correo a {full_name}. "
                    f"El diploma fue generado correctamente y el envío quedó pendiente. {last_error}",
                )
                return "failed"
            except Exception:
                logger.exception(
                    "Error inesperado al enviar",
                    extra={"batch": getattr(batch, "pk", "-"), "participant": full_name},
                )
                _finish_attempt(
                    delivery,
                    attempt_row,
                    EmailStatus.FAILED,
                    "No fue posible enviar el correo.",
                )
                _save_failure(
                    delivery,
                    f"No fue posible enviar el correo a {full_name}. "
                    "El diploma fue generado correctamente y el envío quedó pendiente.",
                )
                return "failed"
            else:
                _mark_sent(delivery, attempt_row, result.message_id, provider.name)
                logger.info(
                    "Correo enviado.",
                    extra={"batch": getattr(batch, "pk", "-"), "participant": full_name},
                )
                return "sent"
        return "failed"

    def _resolve(self) -> EmailProvider:
        if self._provider is not None:
            return self._provider
        selected = (get_settings().email_provider or "none").lower()
        if selected == "smtp":
            return SMTPProvider()
        if selected == "outlook":
            return OutlookProvider()
        return UnavailableProvider()

    def _require_provider(self) -> EmailProvider:
        provider = self._resolve()
        problems = provider.validate_configuration()
        if problems:
            raise EmailConfigurationError(problems[0])
        return provider


def build_provider(name: str) -> EmailProvider:
    if name == "smtp":
        return SMTPProvider()
    if name == "outlook":
        return OutlookProvider()
    return UnavailableProvider()


def _personalize(template: str, full_name: str) -> str:
    return (template or "").replace("{nombre}", full_name or "")


def _delivery_for(recipient_key: str, filename: str) -> EmailDelivery | None:
    return EmailDelivery.objects.filter(recipient=recipient_key, attachment=filename).first()


def _locked_delivery(recipient_key: str, filename: str, **defaults) -> EmailDelivery:
    try:
        with transaction.atomic():
            delivery, _created = EmailDelivery.objects.get_or_create(
                recipient=recipient_key,
                attachment=filename,
                defaults={
                    "participant": defaults.get("participant"),
                    "generation_record": defaults.get("generation_record"),
                    "batch": defaults.get("batch"),
                    "status": EmailStatus.PENDING,
                    "provider": "",
                },
            )
    except IntegrityError:
        delivery = EmailDelivery.objects.get(recipient=recipient_key, attachment=filename)
    changed = False
    for field_name in ("participant", "generation_record", "batch"):
        value = defaults.get(field_name)
        if value is not None and getattr(delivery, f"{field_name}_id", None) != getattr(value, "pk", None):
            setattr(delivery, field_name, value)
            changed = True
    if changed:
        delivery.save()
    return delivery


def _begin_attempt(delivery: EmailDelivery, provider_name: str, batch) -> EmailAttempt:
    with transaction.atomic():
        delivery.attempt_count += 1
        delivery.status = EmailStatus.SENDING
        delivery.provider = provider_name
        delivery.last_attempt_at = timezone.now()
        delivery.error_message = ""
        if batch is not None:
            delivery.batch = batch
        delivery.save()
        return EmailAttempt.objects.create(
            delivery=delivery,
            attempt_number=delivery.attempt_count,
            status=EmailStatus.SENDING,
        )


def _finish_attempt(delivery: EmailDelivery, attempt: EmailAttempt, status: str, error: str) -> None:
    with transaction.atomic():
        attempt.status = status
        attempt.error_message = error
        attempt.save(update_fields=["status", "error_message"])
        delivery.status = status
        delivery.error_message = error
        delivery.save(update_fields=["status", "error_message", "attempt_count", "last_attempt_at", "provider"])


def _mark_sent(delivery: EmailDelivery, attempt: EmailAttempt, message_id: str, provider_name: str) -> None:
    now = timezone.now()
    with transaction.atomic():
        attempt.status = EmailStatus.SENT
        attempt.provider_message_id = message_id
        attempt.error_message = ""
        attempt.save()
        delivery.status = EmailStatus.SENT
        delivery.sent_at = now
        delivery.error_message = ""
        delivery.provider = provider_name
        delivery.provider_message_id = message_id
        delivery.save()


def _save_failure(delivery: EmailDelivery, message: str) -> None:
    delivery.status = EmailStatus.FAILED
    delivery.error_message = message
    delivery.save(update_fields=["status", "error_message"])


def _save_invalid(delivery: EmailDelivery, full_name: str) -> None:
    delivery.status = EmailStatus.INVALID_EMAIL
    delivery.error_message = (
        f"El correo de {full_name} no tiene un formato válido. No se intentó el envío."
    )
    delivery.save(update_fields=["status", "error_message"])
    logger.info("Correo inválido; no se intenta el envío.", extra={"participant": full_name})


def _pdf_path(filename: str) -> Path | None:
    try:
        return contained_file(Path(django_settings.DIPLOMAS_OUTPUT_DIR), filename)
    except DiplomaError:
        logger.warning("Nombre de adjunto rechazado: %s", filename)
        return None


def _count(result: EmailRunResult, outcome: str, label: str) -> None:
    if outcome == "sent":
        result.sent += 1
    elif outcome == "failed":
        result.failed += 1
        if len(result.messages) < 8:
            result.messages.append(f"No se pudo enviar a {label}.")
    elif outcome == "invalid":
        result.invalid += 1
    else:
        result.skipped += 1


def _refresh_batches(records: list[GenerationRecord]) -> None:
    _refresh_batches_by_id({record.batch_id for record in records if record.batch_id})


def _refresh_batches_by_id(batch_ids) -> None:
    for batch in GenerationBatch.objects.filter(pk__in=list(batch_ids)):
        records = list(batch.records.all())
        filenames = [record.filename for record in records if record.filename]
        deliveries = {
            (item.recipient, item.attachment): item
            for item in EmailDelivery.objects.filter(attachment__in=filenames)
        }
        sent = failed = skipped = 0
        for record in records:
            delivery = deliveries.get((record.email_key, record.filename))
            if delivery is None:
                continue
            if delivery.status == EmailStatus.SENT:
                sent += 1
            elif delivery.status in {EmailStatus.FAILED, EmailStatus.INVALID_EMAIL}:
                failed += 1
            elif delivery.status == EmailStatus.SKIPPED:
                skipped += 1
        batch.sent_count = sent
        batch.email_failed_count = failed
        batch.email_skipped_count = skipped
        batch.save(update_fields=["sent_count", "email_failed_count", "email_skipped_count"])
