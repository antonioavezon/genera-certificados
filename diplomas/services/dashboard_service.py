"""Resumen de la pantalla de inicio."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings as django_settings

from diplomas.exceptions import StoragePermissionError
from diplomas.models import EmailDelivery, EmailStatus, GenerationBatch
from diplomas.services.config_service import configuration_problems, get_settings
from diplomas.services.email.email_service import EmailService
from diplomas.services.file_service import assert_writable
from diplomas.services.motive_service import get_motive
from diplomas.services.participant_service import get_active_batch
from diplomas.services.template_service import get_active_template


def build_dashboard() -> dict:
    layout = get_settings()
    batch = get_active_batch()
    template = get_active_template()
    motive = get_motive()
    config_problems = configuration_problems(layout)
    email_ready, email_issues = EmailService().provider_ready()
    folder_problem = ""
    try:
        assert_writable(Path(django_settings.DIPLOMAS_OUTPUT_DIR), label="la carpeta de diplomas")
    except StoragePermissionError as exc:
        folder_problem = exc.user_message
    return {
        "batch": batch,
        "template": template,
        "motive": motive,
        "layout": layout,
        "config_problems": config_problems,
        "config_ready": not config_problems,
        "email_ready": email_ready,
        "email_issues": email_issues,
        "email_counts": _email_counts(batch),
        "last_batch": GenerationBatch.objects.order_by("-started_at").first(),
        "output_dir": Path(django_settings.DIPLOMAS_OUTPUT_DIR),
        "folder_problem": folder_problem,
    }


def _email_counts(batch) -> dict[str, int]:
    counts = {"sent": 0, "pending": 0, "failed": 0}
    if batch is None:
        return counts
    people = [
        person
        for person in batch.participants.all()
        if person.email_key and person.status != "error" and person.filename
    ]
    keys = [person.email_key for person in people]
    statuses = {
        (item.recipient, item.attachment): item.status
        for item in EmailDelivery.objects.filter(recipient__in=keys)
    }
    for person in people:
        status = statuses.get((person.email_key, person.filename))
        if status == EmailStatus.SENT:
            counts["sent"] += 1
        elif status in {EmailStatus.FAILED, EmailStatus.INVALID_EMAIL}:
            counts["failed"] += 1
        else:
            counts["pending"] += 1
    return counts
