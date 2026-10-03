"""Utilidades para las pruebas de diplomas."""

from __future__ import annotations

import shutil
import tempfile
import uuid
from pathlib import Path

from django.conf import settings
from django.test import TestCase, override_settings
from PIL import Image

from diplomas.models import ImportBatch, ImportPhase, Participant, TemplateConfiguration
from diplomas.services.config_service import get_settings
from diplomas.services.motive_service import get_motive

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


class MediaCase(TestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        for name in ("generated", "uploads", "temp", "data"):
            (root / name).mkdir()
        self.override = override_settings(
            DIPLOMAS_OUTPUT_DIR=root / "generated",
            UPLOADS_DIR=root / "uploads",
            TEMP_DIR=root / "temp",
            DATA_DIR=root / "data",
        )
        self.override.enable()
        self.addCleanup(self.override.disable)

    def use_png_template(self) -> TemplateConfiguration:
        source = FIXTURES / "template.png"
        directory = Path(settings.UPLOADS_DIR) / "templates"
        directory.mkdir(parents=True, exist_ok=True)
        stored = f"{uuid.uuid4().hex}.png"
        shutil.copy(source, directory / stored)
        with Image.open(source) as image:
            width, height = image.size
        TemplateConfiguration.objects.update(is_active=False)
        return TemplateConfiguration.objects.create(
            original_name="template.png",
            stored_name=stored,
            kind="png",
            page_count=1,
            selected_page=1,
            width_px=width,
            height_px=height,
            content_hash="test",
            is_active=True,
        )

    def use_layout(self, **kwargs):
        layout = get_settings()
        layout.dpi = kwargs.pop("dpi", 72)
        layout.name_font = "DejaVuSans.ttf"
        layout.motive_font = "DejaVuSans.ttf"
        layout.name_font_size = kwargs.pop("name_font_size", 28)
        layout.name_min_font_size = kwargs.pop("name_min_font_size", 10)
        layout.name_max_font_size = kwargs.pop("name_max_font_size", 48)
        for key, value in kwargs.items():
            setattr(layout, key, value)
        layout.save()
        return layout

    def use_motive(self, text: str = "POR SU PARTICIPACIÓN EN EL CURSO"):
        motive = get_motive()
        motive.text = text
        motive.content_hash = "test"
        motive.save()
        return motive

    def use_people(self, rows: list[tuple[str, str, str, str]]) -> ImportBatch:
        batch = ImportBatch.objects.create(
            original_name="lista.csv",
            phase=ImportPhase.READY,
            is_active=True,
            mapping={"first_name": "Nombre", "last_name": "Apellido", "email": "Correo"},
            total_rows=len(rows),
        )
        for row_number, (first, last, email, status) in enumerate(rows, start=1):
            Participant.objects.create(
                import_batch=batch,
                row_number=row_number,
                first_name=first,
                last_name=last,
                email=email,
                status=status,
                filename="pendiente.pdf",
            )
        return batch
