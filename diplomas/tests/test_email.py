from pathlib import Path

from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from diplomas.exceptions import EmailSendError
from diplomas.models import EmailDelivery, EmailStatus, GenerationBatch, GenerationRecord, GenerationStatus
from diplomas.services.email.base import EmailProvider, OutboundEmail, SendResult
from diplomas.services.email.email_service import EmailService
from diplomas.tests.helpers import MediaCase


class FakeProvider(EmailProvider):
    name = "fake"

    def __init__(self, script):
        self.script = list(script)
        self.sent: list[str] = []
        self.seen_status: list[str] = []

    def is_available(self) -> bool:
        return True

    def unavailable_reason(self) -> str:
        return ""

    def validate_configuration(self) -> list[str]:
        return []

    def send(self, message: OutboundEmail) -> SendResult:
        delivery = EmailDelivery.objects.get(recipient=message.to.casefold(), attachment=message.attachment_name)
        self.seen_status.append(delivery.status)
        self.sent.append(message.to)
        step = self.script.pop(0) if self.script else "ok"
        if isinstance(step, Exception):
            raise step
        return SendResult(message_id="mensaje-prueba")

    def create_draft(self, message: OutboundEmail) -> SendResult:
        return SendResult(message_id="borrador")


class EmailFlowTests(MediaCase):
    def setUp(self):
        super().setUp()
        self.attempts = override_settings(EMAIL_MAX_ATTEMPTS=1, EMAIL_RETRY_BACKOFF_SECONDS=0)
        self.attempts.enable()
        self.addCleanup(self.attempts.disable)
        self.batch = GenerationBatch.objects.create(total=3, status="COMPLETED")

    def add_record(self, first: str, last: str, email: str, filename: str) -> GenerationRecord:
        path = Path(settings.DIPLOMAS_OUTPUT_DIR) / filename
        path.write_bytes(b"%PDF-1.4 diploma de prueba")
        return GenerationRecord.objects.create(
            batch=self.batch,
            first_name=first,
            last_name=last,
            email=email,
            email_key=email.casefold(),
            filename=filename,
            status=GenerationStatus.GENERATED,
        )

    def test_successful_send_is_marked_only_after_confirmation(self):
        self.add_record("Ana", "Torres", "ana.torres@example.com", "ana.torres.pdf")
        provider = FakeProvider(["ok"])
        result = EmailService(provider).send_for_batch(self.batch)
        delivery = EmailDelivery.objects.get()
        self.assertEqual(result.sent, 1)
        self.assertEqual(delivery.status, EmailStatus.SENT)
        self.assertIsNotNone(delivery.sent_at)
        self.assertEqual(delivery.attempt_count, 1)
        self.assertEqual(provider.seen_status, [EmailStatus.SENDING])
        self.assertEqual(delivery.attempts.count(), 1)

    def test_failed_send_stays_failed(self):
        self.add_record("Ana", "Torres", "ana.torres@example.com", "ana.torres.pdf")
        provider = FakeProvider([EmailSendError("No hubo respuesta del servidor de correo.")])
        result = EmailService(provider).send_for_batch(self.batch)
        delivery = EmailDelivery.objects.get()
        self.assertEqual(result.failed, 1)
        self.assertEqual(delivery.status, EmailStatus.FAILED)
        self.assertIsNone(delivery.sent_at)
        self.assertIn("pendiente", delivery.error_message)

    def test_one_failure_does_not_stop_the_next(self):
        self.add_record("Ana", "Torres", "ana.torres@example.com", "ana.torres.pdf")
        self.add_record("Luis", "Mendoza", "luis.mendoza@example.com", "luis.mendoza.pdf")
        self.add_record("Camila", "Rojas", "camila.rojas@example.com", "camila.rojas.pdf")
        provider = FakeProvider(
            ["ok", EmailSendError("SMTP timeout"), "ok"]
        )
        result = EmailService(provider).send_for_batch(self.batch)
        self.assertEqual(result.sent, 2)
        self.assertEqual(result.failed, 1)
        self.assertEqual(
            provider.sent,
            [
                "ana.torres@example.com",
                "luis.mendoza@example.com",
                "camila.rojas@example.com",
            ],
        )
        luis = EmailDelivery.objects.get(recipient="luis.mendoza@example.com")
        self.assertEqual(luis.status, EmailStatus.FAILED)

    def test_resume_does_not_resend_sent_mail(self):
        self.add_record("Ana", "Torres", "ana.torres@example.com", "ana.torres.pdf")
        self.add_record("Luis", "Mendoza", "luis.mendoza@example.com", "luis.mendoza.pdf")
        provider = FakeProvider(["ok", "ok"])
        EmailService(provider).send_for_batch(self.batch)
        self.assertEqual(len(provider.sent), 2)
        again = FakeProvider(["no-deberia-usarse"])
        result = EmailService(again).send_for_batch(self.batch)
        self.assertEqual(again.sent, [])
        self.assertEqual(result.skipped, 2)
        self.assertEqual(result.sent, 0)
        self.assertEqual(EmailDelivery.objects.get(recipient="ana.torres@example.com").attempt_count, 1)

    def test_retry_failed_ignores_sent_records(self):
        self.add_record("Ana", "Torres", "ana.torres@example.com", "ana.torres.pdf")
        self.add_record("Luis", "Mendoza", "luis.mendoza@example.com", "luis.mendoza.pdf")
        EmailService(FakeProvider(["ok", EmailSendError("SMTP timeout")])).send_for_batch(self.batch)
        retry = FakeProvider(["ok"])
        result = EmailService(retry).retry_failed()
        self.assertEqual(retry.sent, ["luis.mendoza@example.com"])
        self.assertEqual(result.sent, 1)
        self.assertEqual(
            EmailDelivery.objects.get(recipient="ana.torres@example.com").status,
            EmailStatus.SENT,
        )
        self.assertEqual(
            EmailDelivery.objects.get(recipient="luis.mendoza@example.com").status,
            EmailStatus.SENT,
        )
        self.assertEqual(
            EmailDelivery.objects.get(recipient="luis.mendoza@example.com").attempt_count,
            2,
        )

    def test_continue_pending_skips_sent_and_failed(self):
        ana = self.add_record("Ana", "Torres", "ana.torres@example.com", "ana.torres.pdf")
        self.add_record("Luis", "Mendoza", "luis.mendoza@example.com", "luis.mendoza.pdf")
        camila = self.add_record("Camila", "Rojas", "camila.rojas@example.com", "camila.rojas.pdf")
        EmailDelivery.objects.create(
            generation_record=ana,
            batch=self.batch,
            recipient="ana.torres@example.com",
            attachment="ana.torres.pdf",
            status=EmailStatus.SENT,
            sent_at=timezone.now(),
            attempt_count=1,
        )
        EmailDelivery.objects.create(
            generation_record=camila,
            batch=self.batch,
            recipient="camila.rojas@example.com",
            attachment="camila.rojas.pdf",
            status=EmailStatus.FAILED,
            attempt_count=1,
            error_message="timeout",
        )
        provider = FakeProvider(["ok"])
        result = EmailService(provider).continue_pending()
        self.assertEqual(provider.sent, ["luis.mendoza@example.com"])
        self.assertEqual(result.sent, 1)
        self.assertEqual(
            EmailDelivery.objects.get(recipient="ana.torres@example.com").status,
            EmailStatus.SENT,
        )

    def test_invalid_email_does_not_stop_the_batch(self):
        self.add_record("Pedro", "López", "pedro@@correo", "pedro.lopez.pdf")
        self.add_record("Ana", "Torres", "ana.torres@example.com", "ana.torres.pdf")
        provider = FakeProvider(["ok"])
        result = EmailService(provider).send_for_batch(self.batch)
        self.assertEqual(provider.sent, ["ana.torres@example.com"])
        self.assertEqual(result.invalid, 1)
        self.assertEqual(result.sent, 1)
        self.assertEqual(
            EmailDelivery.objects.get(recipient="pedro@@correo").status,
            EmailStatus.INVALID_EMAIL,
        )

    def test_automatic_retries_are_bounded(self):
        self.add_record("Ana", "Torres", "ana.torres@example.com", "ana.torres.pdf")
        provider = FakeProvider([EmailSendError("timeout")] * 5)
        with override_settings(EMAIL_MAX_ATTEMPTS=3, EMAIL_RETRY_BACKOFF_SECONDS=0):
            EmailService(provider).send_for_batch(self.batch)
        delivery = EmailDelivery.objects.get()
        self.assertEqual(delivery.attempt_count, 3)
        self.assertEqual(delivery.attempts.count(), 3)
        self.assertEqual(delivery.status, EmailStatus.FAILED)
        self.assertEqual(len(provider.sent), 3)
