import io
import os
import tempfile
from pathlib import Path

from django import forms
from django.conf import settings
from django.test import Client, RequestFactory, TestCase, override_settings
from PIL import Image

from diplomas.exceptions import InvalidListFileError
from diplomas.middleware import FriendlyExceptionMiddleware
from diplomas.models import EmailDelivery, GenerationBatch, GenerationRecord, ImportBatch, Participant
from diplomas.tests.helpers import MediaCase


class PageTests(TestCase):
    def test_main_pages_render(self):
        client = Client()
        for url in (
            "/",
            "/lista/",
            "/motivo/",
            "/plantilla/",
            "/configurar/",
            "/configurar/nombre/",
            "/configurar/motivo/",
            "/configurar/salida/",
            "/configurar/correo/",
            "/configurar/correo/gmail/",
            "/configurar/correo/otro/",
            "/configurar/correo/cuerpo/",
            "/lista/cargar/",
            "/motivo/cargar/",
            "/generar/",
            "/correo/continuar/",
            "/historial/",
            "/acerca/",
        ):
            response = client.get(url)
            self.assertEqual(response.status_code, 200, url)

    def test_about_names_the_author_without_contact_details(self):
        response = Client().get("/acerca/")
        body = response.content.decode()
        self.assertIn("Antonio Ralph Avezon Saavedra", body)
        self.assertIn("PMI Capítulo Santiago de Chile", body)
        self.assertNotIn("@", body)

    def test_unexpected_error_does_not_show_traceback(self):
        def explode(_request):
            raise RuntimeError("detalle interno secreto")

        response = FriendlyExceptionMiddleware(explode)(RequestFactory().get("/"))
        body = response.content.decode()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("Traceback", body)
        self.assertNotIn("detalle interno secreto", body)
        self.assertIn("inesperado", body)

    def test_domain_error_shows_the_user_message(self):
        def reject(_request):
            raise InvalidListFileError(
                "El archivo seleccionado no es un documento Excel válido o está dañado."
            )

        response = FriendlyExceptionMiddleware(reject)(RequestFactory().get("/lista/"))
        body = response.content.decode()
        self.assertEqual(response.status_code, 400)
        self.assertIn("Excel", body)
        self.assertNotIn("Traceback", body)

    def test_clear_history_removes_batches_and_keeps_the_list(self):
        listing = ImportBatch.objects.create(original_name="lista.csv", stored_name="lista.csv")
        Participant.objects.create(import_batch=listing, row_number=1, first_name="Ana", last_name="Torres")
        batch = GenerationBatch.objects.create(import_batch=listing, total=1, status="COMPLETED")
        record = GenerationRecord.objects.create(
            batch=batch,
            first_name="Ana",
            last_name="Torres",
            filename="ana.torres.pdf",
            status="GENERATED",
        )
        EmailDelivery.objects.create(
            generation_record=record,
            batch=batch,
            recipient="ana@example.com",
            attachment="ana.torres.pdf",
            status="SENT",
        )
        page = Client().get("/historial/")
        self.assertContains(page, "Borrar historial")
        cleared = Client().post("/historial/borrar/", follow=True)
        self.assertContains(cleared, "El historial se borró")
        self.assertFalse(GenerationBatch.objects.exists())
        self.assertFalse(GenerationRecord.objects.exists())
        self.assertFalse(EmailDelivery.objects.exists())
        self.assertTrue(Participant.objects.filter(first_name="Ana").exists())
        self.assertTrue(ImportBatch.objects.filter(pk=listing.pk).exists())


def _posted_fields(client, url):
    page = client.get(url)
    form = page.context["form"]
    data = {}
    for name in form.fields:
        value = form[name].value()
        if value is True:
            data[name] = "on"
        elif value is False or value is None:
            continue
        else:
            data[name] = value
    return data


class ConfigureSaveTests(TestCase):
    def test_width_percentages_save_and_only_reject_real_limits(self):
        from diplomas.forms import PercentField
        from diplomas.services.config_service import get_settings

        field = PercentField(min_value=5, max_value=100)
        self.assertEqual(field.clean("80,0"), 0.8)
        self.assertEqual(field.clean("78"), 0.78)
        with self.assertRaises(forms.ValidationError):
            field.clean("4")

        client = Client()
        hub = client.get("/configurar/")
        self.assertContains(hub, "Vista de nombre")
        self.assertContains(hub, "Vista de motivo")
        self.assertContains(hub, "Salida de certificado")
        self.assertContains(hub, "Correo")
        name_data = _posted_fields(client, "/configurar/nombre/")
        name_data["name_max_width"] = "80,0"
        saved = client.post("/configurar/nombre/", name_data)
        self.assertEqual(saved.status_code, 302, saved.content.decode()[:500] if saved.status_code != 302 else "")
        motive_data = _posted_fields(client, "/configurar/motivo/")
        motive_data["motive_max_width"] = "78,0"
        saved = client.post("/configurar/motivo/", motive_data)
        self.assertEqual(saved.status_code, 302, saved.content.decode()[:500] if saved.status_code != 302 else "")
        current = get_settings()
        self.assertEqual(current.name_max_width, 0.8)
        self.assertEqual(current.motive_max_width, 0.78)


class ParticipantEditTests(MediaCase):
    def test_numbers_start_at_one_and_people_can_be_added_edited_and_deleted(self):
        self.use_people([("Ana", "Torres", "ana.torres@example.com", "valid")])
        client = Client()
        added = client.post(
            "/lista/",
            {
                "action": "save-participant",
                "first_name": "Luis",
                "last_name": "Mendoza",
                "email": "luis.mendoza@example.com",
            },
        )
        self.assertEqual(added.status_code, 302)
        people = list(Participant.objects.order_by("row_number").values_list("row_number", "first_name", "last_name"))
        self.assertEqual(people, [(1, "Ana", "Torres"), (2, "Luis", "Mendoza")])
        luis = Participant.objects.get(first_name="Luis")
        edited = client.post(
            "/lista/",
            {
                "action": "save-participant",
                "participant": luis.pk,
                "first_name": "Luis",
                "last_name": "Rojas",
                "email": "luis.rojas@example.com",
            },
        )
        self.assertEqual(edited.status_code, 302)
        luis.refresh_from_db()
        self.assertEqual(luis.last_name, "Rojas")
        self.assertEqual(luis.filename, "luis.rojas.pdf")
        deleted = client.post("/lista/", {"action": "delete-participant", "participant": luis.pk})
        self.assertEqual(deleted.status_code, 302)
        self.assertFalse(Participant.objects.filter(pk=luis.pk).exists())
        ana = Participant.objects.get()
        self.assertEqual(ana.row_number, 1)
        page = client.get("/lista/")
        self.assertContains(page, "Añadir participante")
        self.assertContains(page, "Cargar archivo")
        self.assertNotContains(page, "id_data_file")
        upload = client.get("/lista/cargar/")
        self.assertContains(upload, "id_data_file")
        self.assertContains(page, "Acciones")
        self.assertContains(page, "Editar")
        self.assertContains(page, "Certificado")
        self.assertContains(page, "Borrar")
        self.assertNotContains(page, "Observaciones")


class TemplateThumbnailTests(MediaCase):
    def test_home_shows_thumbnail_only_when_a_template_is_loaded(self):
        empty = Client().get("/")
        self.assertNotIn("/plantilla/miniatura/", empty.content.decode())
        missing = Client().get("/plantilla/miniatura/")
        self.assertEqual(missing.status_code, 404)

        self.use_png_template()
        home = Client().get("/")
        self.assertIn("/plantilla/miniatura/", home.content.decode())
        image = Client().get("/plantilla/miniatura/")
        self.assertEqual(image.status_code, 200)
        self.assertEqual(image["Content-Type"], "image/png")
        self.assertTrue(image.content.startswith(b"\x89PNG"))
        page = Client().get("/plantilla/").content.decode()
        thumb = page.find("/plantilla/miniatura/")
        label = page.find("Plantilla activa:")
        self.assertGreater(thumb, 0)
        self.assertGreater(label, thumb)

    def test_list_and_motive_thumbnails_match_the_template_size(self):
        self.use_png_template()
        self.use_people([("Ana", "Torres", "ana@example.com", "valid")])
        self.use_motive("POR SU PARTICIPACIÓN\nEN EL ENCUENTRO")
        client = Client()
        template = Image.open(io.BytesIO(client.get("/plantilla/miniatura/").content))
        listing = client.get("/lista/miniatura/")
        motive = client.get("/motivo/miniatura/")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(motive.status_code, 200)
        list_image = Image.open(io.BytesIO(listing.content))
        motive_image = Image.open(io.BytesIO(motive.content))
        self.assertEqual(list_image.size, template.size)
        self.assertEqual(motive_image.size, template.size)
        page = client.get("/configurar/")
        self.assertContains(page, "row-cols-2")
        for path in (
            "/configurar/nombre/miniatura/",
            "/configurar/motivo/miniatura/",
            "/configurar/salida/miniatura/",
            "/configurar/correo/miniatura/",
        ):
            self.assertContains(page, path)
            thumb = Image.open(io.BytesIO(client.get(path).content))
            self.assertEqual(thumb.size, template.size)
        home = client.get("/").content.decode()
        self.assertIn("/lista/miniatura/", home)
        self.assertIn("/motivo/miniatura/", home)
        ink = motive_image.convert("L").point(lambda pixel: 255 if pixel < 250 else 0)
        box = ink.getbbox()
        self.assertIsNotNone(box)
        center = (box[0] + box[2]) / 2
        self.assertAlmostEqual(center, motive_image.width / 2, delta=motive_image.width * 0.06)


class EmailSettingsTests(TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env_path = Path(self.tmp.name) / ".env"
        self.env_path.write_text("DJANGO_SECRET_KEY=keep\n", encoding="utf-8")
        self.override = override_settings(ENV_FILE=self.env_path)
        self.override.enable()
        self.saved = {
            name: getattr(settings, name)
            for name in (
                "SMTP_HOST",
                "SMTP_PORT",
                "SMTP_USE_TLS",
                "SMTP_USE_SSL",
                "SMTP_USER",
                "SMTP_PASSWORD",
                "SMTP_FROM",
            )
        }

    def tearDown(self):
        for name, value in self.saved.items():
            setattr(settings, name, value)
            if isinstance(value, bool):
                os.environ[name] = "true" if value else "false"
            else:
                os.environ[name] = "" if value is None else str(value)
        self.override.disable()
        self.tmp.cleanup()

    def test_home_replaces_the_folder_sentence_with_buttons(self):
        body = Client().get("/").content.decode()
        self.assertIn("Ver Diplomas", body)
        self.assertIn("Configurar email", body)
        self.assertNotIn("Los PDF se guardan", body)

    def test_save_writes_env_without_showing_the_password(self):
        response = Client().post(
            "/configurar/correo/gmail/",
            {
                "host": "smtp.gmail.com",
                "port": "587",
                "use_tls": "on",
                "user": "persona@gmail.com",
                "password": "clave de prueba",
                "sender": "persona@gmail.com",
                "action": "save",
            },
        )
        self.assertEqual(response.status_code, 302)
        text = self.env_path.read_text(encoding="utf-8")
        self.assertIn("DJANGO_SECRET_KEY=keep", text)
        self.assertIn("SMTP_HOST=smtp.gmail.com", text)
        self.assertIn("SMTP_PASSWORD=clavedeprueba", text)
        page = Client().get("/configurar/correo/gmail/")
        self.assertEqual(page.status_code, 200)
        body = page.content.decode()
        self.assertIn("smtp.gmail.com", body)
        self.assertIn("Contraseña de aplicación", body)
        self.assertNotIn("clave de prueba", body)
        hub = Client().get("/configurar/correo/").content.decode()
        self.assertIn("Gmail", hub)
        self.assertIn("Otro proveedor", hub)
        self.assertIn("Cuerpo del correo", hub)
        self.assertIn("/configurar/correo/gmail/miniatura/", hub)
        self.assertIn("/configurar/correo/otro/miniatura/", hub)
        self.assertIn("/configurar/correo/cuerpo/miniatura/", hub)

    def test_gmail_account_fills_the_sender_and_the_password_spaces_are_removed(self):
        response = Client().post(
            "/configurar/correo/gmail/",
            {
                "host": "smtp.gmail.com",
                "port": "587",
                "use_tls": "on",
                "user": "persona@gmail.com",
                "password": "abcd efgh ijkl mnop",
                "sender": "",
                "action": "save",
            },
        )
        self.assertEqual(response.status_code, 302)
        text = self.env_path.read_text(encoding="utf-8")
        self.assertIn("SMTP_FROM=persona@gmail.com", text)
        self.assertIn("SMTP_USER=persona@gmail.com", text)
        self.assertIn("SMTP_PASSWORD=abcdefghijklmnop", text)

    def test_gmail_without_an_account_asks_for_the_address(self):
        response = Client().post(
            "/configurar/correo/gmail/",
            {
                "host": "smtp.gmail.com",
                "port": "587",
                "use_tls": "on",
                "user": "",
                "password": "abcdefghijklmnop",
                "sender": "",
                "action": "save",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Escriba el correo de Gmail.")
        self.assertNotIn("SMTP_PASSWORD", self.env_path.read_text(encoding="utf-8"))

    def test_blank_password_keeps_the_saved_one(self):
        client = Client()
        client.post(
            "/configurar/correo/gmail/",
            {
                "host": "smtp.gmail.com",
                "port": "587",
                "use_tls": "on",
                "user": "persona@gmail.com",
                "password": "secreto-uno",
                "sender": "persona@gmail.com",
                "action": "save",
            },
        )
        client.post(
            "/configurar/correo/gmail/",
            {
                "host": "smtp.gmail.com",
                "port": "587",
                "use_tls": "on",
                "user": "persona@gmail.com",
                "password": "",
                "sender": "persona@gmail.com",
                "action": "save",
            },
        )
        self.assertIn("SMTP_PASSWORD=secreto-uno", self.env_path.read_text(encoding="utf-8"))

    def test_test_email_uses_the_gmail_account_when_the_field_is_empty(self):
        from unittest.mock import patch

        with patch("diplomas.views.email_settings.SMTPProvider.send") as send:
            response = Client().post(
                "/configurar/correo/gmail/",
                {
                    "host": "smtp.gmail.com",
                    "port": "587",
                    "use_tls": "on",
                    "user": "persona@gmail.com",
                    "password": "secreto-uno",
                    "sender": "",
                    "test_to": "",
                    "action": "test",
                },
                follow=True,
            )
        self.assertContains(response, "Se envió el correo de prueba a persona@gmail.com.")
        self.assertEqual(send.call_args.args[0].to, "persona@gmail.com")
