"""Persistencia de listas, diseño, generaciones y envíos."""

from __future__ import annotations

from django.db import models


class ParticipantStatus(models.TextChoices):
    VALID = "valid", "Válido"
    WARNING = "warning", "Advertencia"
    ERROR = "error", "Error"


class ImportPhase(models.TextChoices):
    PENDING = "pending", "Pendiente de columnas"
    READY = "ready", "Lista lista"


class BatchStatus(models.TextChoices):
    RUNNING = "RUNNING", "En proceso"
    COMPLETED = "COMPLETED", "Completado"
    INTERRUPTED = "INTERRUPTED", "Interrumpido"
    FAILED = "FAILED", "Detenido"


class GenerationStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    GENERATED = "GENERATED", "Generado"
    SKIPPED = "SKIPPED", "Omitido"
    ALREADY_EXISTS = "ALREADY_EXISTS", "Ya existía"
    FAILED = "FAILED", "Error"
    REGENERATED = "REGENERATED", "Regenerado"


class EmailStatus(models.TextChoices):
    PENDING = "PENDING", "Pendiente"
    SENDING = "SENDING", "Enviando"
    SENT = "SENT", "Enviado"
    FAILED = "FAILED", "Fallido"
    SKIPPED = "SKIPPED", "Omitido"
    INVALID_EMAIL = "INVALID_EMAIL", "Correo inválido"


class CollisionPolicy(models.TextChoices):
    BLOCK = "block", "Bloquear el duplicado"
    SUFFIX = "suffix", "Añadir _2, _3… de forma explícita"


class OverflowPolicy(models.TextChoices):
    WARN = "warn", "Generar y advertir"
    BLOCK = "block", "Marcar como conflicto y no generar"


class ApplicationSettings(models.Model):
    """Configuración de diseño y salida. Se usa un único registro."""

    name_x = models.FloatField(default=0.5)
    name_y = models.FloatField(default=0.40)
    name_font = models.CharField(max_length=255, default="DejaVuSans.ttf")
    name_font_size = models.PositiveIntegerField(default=36)
    name_min_font_size = models.PositiveIntegerField(default=14)
    name_max_font_size = models.PositiveIntegerField(default=72)
    name_color = models.CharField(max_length=7, default="#1A1A1A")
    name_bold = models.BooleanField(default=False)
    name_italic = models.BooleanField(default=False)
    name_align = models.CharField(max_length=10, default="center")
    name_max_width = models.FloatField(default=0.80)
    name_uppercase = models.BooleanField(default=False)
    name_autofit = models.BooleanField(default=True)
    name_two_lines = models.BooleanField(default=False)
    name_overflow_policy = models.CharField(
        max_length=10,
        choices=OverflowPolicy.choices,
        default=OverflowPolicy.WARN,
    )

    motive_x = models.FloatField(default=0.5)
    motive_y = models.FloatField(default=0.55)
    motive_font = models.CharField(max_length=255, default="DejaVuSans.ttf")
    motive_font_size = models.PositiveIntegerField(default=16)
    motive_color = models.CharField(max_length=7, default="#333333")
    motive_bold = models.BooleanField(default=False)
    motive_italic = models.BooleanField(default=False)
    motive_align = models.CharField(max_length=10, default="center")
    motive_line_spacing = models.FloatField(default=1.35)
    motive_max_width = models.FloatField(default=0.78)

    dpi = models.PositiveIntegerField(default=300)
    safe_margin = models.FloatField(default=0.04)
    collision_policy = models.CharField(
        max_length=10,
        choices=CollisionPolicy.choices,
        default=CollisionPolicy.BLOCK,
    )
    require_last_name = models.BooleanField(default=True)

    email_subject = models.CharField(max_length=255, default="Su certificado")
    email_body = models.TextField(
        default=(
            "Estimado/a {nombre}:\n\n"
            "Adjuntamos su certificado correspondiente a la actividad.\n\n"
            "Muchas gracias por su participación.\n\n"
            "Saludos."
        )
    )
    email_provider = models.CharField(max_length=20, default="none")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuración"
        verbose_name_plural = "Configuración"

    def __str__(self) -> str:
        return "Configuración de diplomas"


class Motive(models.Model):
    text = models.TextField(blank=True)
    previous_text = models.TextField(blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Motivo"
        verbose_name_plural = "Motivo"

    def __str__(self) -> str:
        return "Motivo del diploma"

    @property
    def line_count(self) -> int:
        stripped = self.text.strip()
        if not stripped:
            return 0
        return len(self.text.splitlines())

    @property
    def is_ready(self) -> bool:
        return bool(self.text.strip())


class TemplateConfiguration(models.Model):
    original_name = models.CharField(max_length=255)
    stored_name = models.CharField(max_length=255)
    kind = models.CharField(max_length=10)
    page_count = models.PositiveIntegerField(default=1)
    selected_page = models.PositiveIntegerField(null=True, blank=True)
    width_px = models.PositiveIntegerField(default=0)
    height_px = models.PositiveIntegerField(default=0)
    content_hash = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Plantilla"
        verbose_name_plural = "Plantillas"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.original_name

    @property
    def needs_page_selection(self) -> bool:
        return self.kind == "pdf" and self.page_count > 1 and not self.selected_page

    @property
    def is_ready(self) -> bool:
        return self.is_active and bool(self.selected_page) and self.width_px > 0


class ImportBatch(models.Model):
    original_name = models.CharField(max_length=255)
    stored_name = models.CharField(max_length=255, blank=True)
    content_hash = models.CharField(max_length=64, blank=True)
    columns = models.JSONField(default=list, blank=True)
    mapping = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)
    phase = models.CharField(max_length=20, choices=ImportPhase.choices, default=ImportPhase.PENDING)
    total_rows = models.PositiveIntegerField(default=0)
    valid_count = models.PositiveIntegerField(default=0)
    warning_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Lista importada"
        verbose_name_plural = "Listas importadas"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return self.original_name


class Participant(models.Model):
    import_batch = models.ForeignKey(
        ImportBatch,
        related_name="participants",
        on_delete=models.CASCADE,
    )
    row_number = models.PositiveIntegerField()
    first_name = models.CharField(max_length=200, blank=True)
    last_name = models.CharField(max_length=200, blank=True)
    email = models.CharField(max_length=320, blank=True)
    status = models.CharField(max_length=20, choices=ParticipantStatus.choices, default=ParticipantStatus.VALID)
    observations = models.TextField(blank=True)
    filename = models.CharField(max_length=180, blank=True)
    duplicate_kind = models.CharField(max_length=80, blank=True)

    class Meta:
        verbose_name = "Participante"
        verbose_name_plural = "Participantes"
        ordering = ["row_number", "id"]
        indexes = [
            models.Index(fields=["import_batch", "status"]),
            models.Index(fields=["filename"]),
        ]

    def __str__(self) -> str:
        return self.full_name or f"Fila {self.row_number}"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    @property
    def email_key(self) -> str:
        return self.email.strip().casefold()


class GenerationBatch(models.Model):
    import_batch = models.ForeignKey(
        ImportBatch,
        related_name="generation_batches",
        null=True,
        on_delete=models.PROTECT,
    )
    template = models.ForeignKey(
        TemplateConfiguration,
        related_name="generation_batches",
        null=True,
        on_delete=models.PROTECT,
    )
    list_hash = models.CharField(max_length=64, blank=True)
    template_hash = models.CharField(max_length=64, blank=True)
    motive_hash = models.CharField(max_length=64, blank=True)
    motive_text = models.TextField(blank=True)
    config_hash = models.CharField(max_length=64, blank=True)
    config_snapshot = models.JSONField(default=dict, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    total = models.PositiveIntegerField(default=0)
    generated_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    already_exists_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)
    sent_count = models.PositiveIntegerField(default=0)
    email_failed_count = models.PositiveIntegerField(default=0)
    email_skipped_count = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, choices=BatchStatus.choices, default=BatchStatus.RUNNING)
    regenerate = models.BooleanField(default=False)
    send_email = models.BooleanField(default=False)
    message = models.TextField(blank=True)

    class Meta:
        verbose_name = "Lote de generación"
        verbose_name_plural = "Lotes de generación"
        ordering = ["-started_at"]

    def __str__(self) -> str:
        return f"Lote #{self.pk}"


class GenerationRecord(models.Model):
    batch = models.ForeignKey(GenerationBatch, related_name="records", on_delete=models.CASCADE)
    participant = models.ForeignKey(
        Participant,
        related_name="generation_records",
        null=True,
        on_delete=models.SET_NULL,
    )
    first_name = models.CharField(max_length=200, blank=True)
    last_name = models.CharField(max_length=200, blank=True)
    email = models.CharField(max_length=320, blank=True)
    email_key = models.CharField(max_length=320, blank=True)
    filename = models.CharField(max_length=180, blank=True)
    status = models.CharField(
        max_length=20,
        choices=GenerationStatus.choices,
        default=GenerationStatus.PENDING,
    )
    message = models.TextField(blank=True)
    config_hash = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Diploma generado"
        verbose_name_plural = "Diplomas generados"
        ordering = ["id"]
        indexes = [
            models.Index(fields=["batch", "status"]),
            models.Index(fields=["email_key", "filename"]),
        ]

    def __str__(self) -> str:
        return self.filename or self.full_name or f"Registro {self.pk}"

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class EmailDelivery(models.Model):
    participant = models.ForeignKey(
        Participant,
        related_name="email_deliveries",
        null=True,
        on_delete=models.SET_NULL,
    )
    generation_record = models.ForeignKey(
        GenerationRecord,
        related_name="email_deliveries",
        null=True,
        on_delete=models.SET_NULL,
    )
    batch = models.ForeignKey(
        GenerationBatch,
        related_name="email_deliveries",
        null=True,
        on_delete=models.SET_NULL,
    )
    recipient = models.CharField(max_length=320)
    subject = models.CharField(max_length=255, blank=True)
    attachment = models.CharField(max_length=180)
    provider = models.CharField(max_length=20, blank=True)
    status = models.CharField(max_length=20, choices=EmailStatus.choices, default=EmailStatus.PENDING)
    attempt_count = models.PositiveIntegerField(default=0)
    last_attempt_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "Envío de correo"
        verbose_name_plural = "Envíos de correo"
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "attachment"],
                name="unique_delivery_recipient_attachment",
            )
        ]
        indexes = [
            models.Index(fields=["status"]),
        ]

    def __str__(self) -> str:
        return f"{self.recipient} · {self.attachment}"

    @property
    def was_sent(self) -> bool:
        return self.status == EmailStatus.SENT or self.sent_at is not None


class EmailAttempt(models.Model):
    delivery = models.ForeignKey(EmailDelivery, related_name="attempts", on_delete=models.CASCADE)
    attempt_number = models.PositiveIntegerField()
    status = models.CharField(max_length=20, choices=EmailStatus.choices)
    error_message = models.TextField(blank=True)
    provider_message_id = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Intento de envío"
        verbose_name_plural = "Intentos de envío"
        ordering = ["attempt_number", "id"]

    def __str__(self) -> str:
        return f"Intento {self.attempt_number} · {self.status}"
