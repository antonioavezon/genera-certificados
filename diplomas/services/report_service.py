"""Historial filtrable y CSV de resultados."""

from __future__ import annotations

import csv
import io

from django.db import transaction
from django.utils import timezone

from diplomas.models import EmailDelivery, EmailStatus, GenerationBatch, GenerationRecord, GenerationStatus


def records_with_delivery(batch: GenerationBatch) -> list[GenerationRecord]:
    records = list(batch.records.all())
    filenames = [record.filename for record in records if record.filename]
    deliveries = {
        (item.recipient, item.attachment): item
        for item in EmailDelivery.objects.filter(attachment__in=filenames)
    }
    for record in records:
        record.delivery = deliveries.get((record.email_key, record.filename))
    return records


def filter_records(records: list[GenerationRecord], selected: str) -> list[GenerationRecord]:
    if selected == "generados":
        return [item for item in records if item.status in {GenerationStatus.GENERATED, GenerationStatus.REGENERATED}]
    if selected == "errores":
        return [
            item
            for item in records
            if item.status == GenerationStatus.FAILED or item.message.startswith("Conflicto")
        ]
    if selected == "enviados":
        return [item for item in records if _delivery_status(item) == EmailStatus.SENT]
    if selected == "fallidos":
        return [
            item
            for item in records
            if _delivery_status(item) in {EmailStatus.FAILED, EmailStatus.INVALID_EMAIL}
        ]
    if selected == "pendientes":
        return [
            item
            for item in records
            if item.status in {GenerationStatus.GENERATED, GenerationStatus.REGENERATED, GenerationStatus.ALREADY_EXISTS}
            and _delivery_status(item) in {None, EmailStatus.PENDING, EmailStatus.SENDING}
            and item.email_key
        ]
    return records


def results_csv(batch: GenerationBatch) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "nombre",
            "apellido",
            "email",
            "pdf",
            "generation_status",
            "email_status",
            "attempts",
            "timestamp",
            "error",
        ]
    )
    for record in records_with_delivery(batch):
        delivery = getattr(record, "delivery", None)
        timestamp = timezone.localtime(record.created_at).strftime("%Y-%m-%d %H:%M:%S")
        error_parts = [record.message]
        if delivery is not None and delivery.error_message:
            error_parts.append(delivery.error_message)
        writer.writerow(
            [
                record.first_name,
                record.last_name,
                record.email,
                record.filename,
                record.status,
                delivery.status if delivery is not None else "",
                delivery.attempt_count if delivery is not None else 0,
                timestamp,
                " | ".join(part for part in error_parts if part),
            ]
        )
    return buffer.getvalue().encode("utf-8-sig")


def clear_history() -> int:
    """Borra lotes, registros y envíos. No toca diplomas, lista ni plantilla."""
    with transaction.atomic():
        count = GenerationBatch.objects.count()
        EmailDelivery.objects.all().delete()
        GenerationBatch.objects.all().delete()
    return count


def _delivery_status(record: GenerationRecord) -> str | None:
    delivery = getattr(record, "delivery", None)
    if delivery is None:
        return None
    return delivery.status
