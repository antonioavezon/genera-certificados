from django.contrib import admin

from diplomas.models import (
    ApplicationSettings,
    EmailAttempt,
    EmailDelivery,
    GenerationBatch,
    GenerationRecord,
    ImportBatch,
    Motive,
    Participant,
    TemplateConfiguration,
)


@admin.register(ApplicationSettings)
class ApplicationSettingsAdmin(admin.ModelAdmin):
    pass


@admin.register(Motive)
class MotiveAdmin(admin.ModelAdmin):
    pass


@admin.register(TemplateConfiguration)
class TemplateAdmin(admin.ModelAdmin):
    list_display = ("original_name", "kind", "page_count", "selected_page", "is_active", "created_at")


class ParticipantInline(admin.TabularInline):
    model = Participant
    extra = 0


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ("original_name", "phase", "total_rows", "valid_count", "error_count", "is_active")
    inlines = [ParticipantInline]


class GenerationRecordInline(admin.TabularInline):
    model = GenerationRecord
    extra = 0


@admin.register(GenerationBatch)
class GenerationBatchAdmin(admin.ModelAdmin):
    list_display = ("id", "started_at", "status", "total", "generated_count", "error_count", "sent_count")
    inlines = [GenerationRecordInline]


class EmailAttemptInline(admin.TabularInline):
    model = EmailAttempt
    extra = 0


@admin.register(EmailDelivery)
class EmailDeliveryAdmin(admin.ModelAdmin):
    list_display = ("recipient", "attachment", "status", "attempt_count", "sent_at")
    inlines = [EmailAttemptInline]
