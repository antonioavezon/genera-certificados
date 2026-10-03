from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from diplomas.exceptions import CorruptFileError, InvalidMotiveError, InvalidTemplateError
from diplomas.models import ApplicationSettings
from diplomas.services.filename_service import preferred_filename
from diplomas.services.motive_service import import_txt, save_text
from diplomas.services.font_service import load_font
from diplomas.services.render_service import render_certificate
from diplomas.services.template_service import import_upload, select_page
from diplomas.services.validation_service import email_is_valid, validate_table
from diplomas.tests.helpers import FIXTURES, MediaCase
from PIL import Image


class NumberingTests(TestCase):
    def test_imported_rows_start_at_one(self):
        rows = validate_table(
            ["Nombre", "Apellido", "Correo"],
            [["Ana", "Torres", "ana.torres@example.com"], ["Luis", "Mendoza", "luis.mendoza@example.com"]],
            {"first_name": "Nombre", "last_name": "Apellido", "email": "Correo"},
            require_last_name=True,
        )
        self.assertEqual([row.row_number for row in rows], [1, 2])


class FilenameTests(TestCase):
    def test_normalizes_accents_and_spaces(self):
        filename, _warning = preferred_filename("María José", "Pérez González")
        self.assertEqual(filename, "maria-jose.perez-gonzalez.pdf")


class ValidationTests(TestCase):
    def test_empty_name(self):
        rows = validate_table(
            ["Nombre", "Apellido", "Correo"],
            [["", "Torres", "ana.torres@example.com"]],
            {"first_name": "Nombre", "last_name": "Apellido", "email": "Correo"},
            require_last_name=True,
        )
        self.assertEqual(rows[0].status, "error")
        self.assertIn("nombre está vacío", rows[0].observations)

    def test_invalid_email_does_not_drop_the_row(self):
        rows = validate_table(
            ["Nombre", "Apellido", "Correo"],
            [["Pedro", "López", "pedro@@correo"], ["Ana", "Torres", "ana.torres@example.com"]],
            {"first_name": "Nombre", "last_name": "Apellido", "email": "Correo"},
            require_last_name=True,
        )
        self.assertEqual(len(rows), 2)
        self.assertFalse(email_is_valid("pedro@@correo"))
        self.assertEqual(rows[0].status, "warning")
        self.assertIn("formato válido", rows[0].observations)
        self.assertEqual(rows[1].status, "valid")

    def test_exact_duplicate_is_kept_and_reported(self):
        from diplomas.services.list_import_service import parse_list_file

        table = parse_list_file(FIXTURES / "lista_duplicados.csv", "lista_duplicados.csv", max_rows=50)
        rows = validate_table(
            table.headers,
            table.rows,
            {"first_name": "Nombre", "last_name": "Apellido", "email": "Correo"},
            require_last_name=True,
        )
        self.assertEqual(len(rows), 7)
        self.assertEqual(rows[1].status, "error")
        self.assertIn("repetida", rows[1].observations)
        self.assertTrue(any("correos distintos" in row.observations for row in rows))
        self.assertTrue(any("nombres distintos" in row.observations for row in rows))

    def test_filename_collision_is_visible(self):
        rows = validate_table(
            ["Nombre", "Apellido", "Correo"],
            [
                ["José", "Núñez", "jose.nunez@example.com"],
                ["Jose", "Nunez", "otro.jose@example.com"],
            ],
            {"first_name": "Nombre", "last_name": "Apellido", "email": "Correo"},
            require_last_name=True,
        )
        self.assertEqual(rows[0].filename, rows[1].filename)
        self.assertIn(rows[0].filename, rows[0].observations)
        self.assertIn(rows[1].filename, rows[1].observations)


class RenderTests(TestCase):
    def test_long_name_shrinks_and_is_not_cut(self):
        image = Image.new("RGB", (600, 400), "white")
        layout = ApplicationSettings(
            name_x=0.5,
            name_y=0.4,
            name_font="DejaVuSans.ttf",
            name_font_size=42,
            name_min_font_size=8,
            name_max_font_size=42,
            name_color="#102030",
            name_align="center",
            name_max_width=0.45,
            name_autofit=True,
            name_uppercase=False,
            motive_x=0.5,
            motive_y=0.62,
            motive_font="DejaVuSans.ttf",
            motive_font_size=12,
            motive_color="#333333",
            motive_align="center",
            motive_line_spacing=1.3,
            motive_max_width=0.8,
            dpi=72,
            safe_margin=0.02,
        )
        full_name = "María José Alejandra Fernández de la Cruz y Montenegro"
        result = render_certificate(image, full_name, "POR SU PARTICIPACIÓN", layout)
        self.assertLess(result.name_font_size, 42)
        self.assertEqual(result.rendered_name, full_name)
        self.assertTrue(result.name_fits)

    def test_name_that_cannot_fit_is_not_truncated(self):
        image = Image.new("RGB", (400, 200), "white")
        layout = ApplicationSettings(
            name_x=0.5,
            name_y=0.4,
            name_font="DejaVuSans.ttf",
            name_font_size=40,
            name_min_font_size=40,
            name_max_font_size=40,
            name_color="#102030",
            name_align="center",
            name_max_width=0.2,
            name_autofit=True,
            motive_x=0.5,
            motive_y=0.7,
            motive_font="DejaVuSans.ttf",
            motive_font_size=12,
            motive_color="#333333",
            motive_align="center",
            motive_line_spacing=1.2,
            motive_max_width=0.8,
            dpi=72,
            safe_margin=0.0,
        )
        full_name = "María José Alejandra Fernández de la Cruz y Montenegro"
        result = render_certificate(image, full_name, "MOTIVO", layout)
        self.assertFalse(result.name_fits)
        self.assertEqual(result.rendered_name, full_name)
        self.assertTrue(any("no cabe" in warning for warning in result.warnings))
        self.assertNotIn(full_name[:12] + "…", result.rendered_name)

    def test_name_and_motive_shrink_when_wider_than_the_image(self):
        image = Image.new("RGB", (500, 320), "white")
        layout = ApplicationSettings(
            name_x=0.5,
            name_y=0.35,
            name_font="DejaVuSans.ttf",
            name_font_size=72,
            name_min_font_size=72,
            name_max_font_size=72,
            name_color="#102030",
            name_align="center",
            name_max_width=1,
            name_autofit=False,
            motive_x=0.5,
            motive_y=0.6,
            motive_font="DejaVuSans.ttf",
            motive_font_size=48,
            motive_color="#333333",
            motive_align="center",
            motive_line_spacing=1.2,
            motive_max_width=1,
            dpi=72,
            safe_margin=0,
        )
        full_name = "María José Alejandra Fernández de la Cruz y Montenegro"
        motive = "POR SU PARTICIPACIÓN EN EL ENCUENTRO INTERNACIONAL DE VOLUNTARIOS"
        result = render_certificate(image, full_name, motive, layout)
        self.assertLess(result.name_font_size, 72)
        self.assertLess(result.motive_font_size, 48)
        self.assertEqual(result.rendered_name, full_name)
        name_font = load_font("DejaVuSans.ttf", result.name_font_size)
        motive_font = load_font("DejaVuSans.ttf", result.motive_font_size)
        name_width = name_font.getbbox(full_name)[2] - name_font.getbbox(full_name)[0]
        motive_width = motive_font.getbbox(motive)[2] - motive_font.getbbox(motive)[0]
        self.assertLessEqual(name_width, image.width)
        self.assertLessEqual(motive_width, image.width)


class TemplateAndMotiveTests(MediaCase):
    def test_png_and_jpg_templates(self):
        for name in ("template.png", "template.jpg"):
            upload = SimpleUploadedFile(name, (FIXTURES / name).read_bytes())
            template = import_upload(upload, dpi=72)
            self.assertTrue(template.is_active)
            self.assertEqual(template.selected_page, 1)
            self.assertGreater(template.width_px, 0)

    def test_single_page_pdf(self):
        upload = SimpleUploadedFile(
            "una.pdf",
            (FIXTURES / "template_una_pagina.pdf").read_bytes(),
            content_type="application/pdf",
        )
        template = import_upload(upload, dpi=72)
        self.assertEqual(template.page_count, 1)
        self.assertEqual(template.selected_page, 1)
        self.assertTrue(template.is_active)

    def test_multipage_pdf_requires_a_choice(self):
        upload = SimpleUploadedFile(
            "varias.pdf",
            (FIXTURES / "template_multipagina.pdf").read_bytes(),
            content_type="application/pdf",
        )
        template = import_upload(upload, dpi=72)
        self.assertGreater(template.page_count, 1)
        self.assertFalse(template.is_active)
        self.assertIsNone(template.selected_page)
        selected = select_page(template, 2, dpi=72)
        self.assertEqual(selected.selected_page, 2)
        self.assertTrue(selected.is_active)

    def test_corrupt_pdf(self):
        upload = SimpleUploadedFile("malo.pdf", (FIXTURES / "corrupto.pdf").read_bytes())
        with self.assertRaises((CorruptFileError, InvalidTemplateError)) as caught:
            import_upload(upload, dpi=72)
        self.assertIn("PDF", caught.exception.user_message)

    def test_corrupt_motive_is_friendly(self):
        upload = SimpleUploadedFile("motivo.txt", b"\xff\xfe no es utf-8 \x80")
        with self.assertRaises(InvalidMotiveError) as caught:
            import_txt(upload)
        self.assertIn("UTF-8", caught.exception.user_message)
        self.assertNotIn("Traceback", caught.exception.user_message)

    def test_motive_roundtrip(self):
        save_text((FIXTURES / "motivo.txt").read_text(encoding="utf-8"))
        from diplomas.services.motive_service import get_motive

        self.assertGreaterEqual(get_motive().line_count, 4)
