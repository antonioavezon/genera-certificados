import hashlib
from pathlib import Path

from django.conf import settings
from django.test import Client

from diplomas.models import GenerationStatus, Participant
from diplomas.services.generation_service import GenerationService
from diplomas.tests.helpers import MediaCase


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class GenerationTests(MediaCase):
    def test_filename_collision_blocks_the_second_file(self):
        self.use_png_template()
        self.use_motive()
        self.use_layout(collision_policy="block")
        self.use_people(
            [
                ("José", "Núñez", "jose.nunez@example.com", "warning"),
                ("Jose", "Nunez", "otro.jose@example.com", "warning"),
            ]
        )
        batch = GenerationService().run(send_email=False, regenerate=False)
        pdfs = list(Path(settings.DIPLOMAS_OUTPUT_DIR).glob("*.pdf"))
        self.assertEqual(len(pdfs), 1)
        self.assertEqual(batch.generated_count, 1)
        self.assertEqual(batch.error_count, 1)
        failed = batch.records.get(status=GenerationStatus.FAILED)
        self.assertIn("Conflicto", failed.message)
        self.assertTrue(pdfs[0].stat().st_size > 500)

    def test_existing_diploma_is_not_overwritten(self):
        self.use_png_template()
        self.use_motive("TEXTO ORIGINAL")
        self.use_layout()
        self.use_people([("Ana", "Torres", "ana.torres@example.com", "valid")])
        first = GenerationService().run(send_email=False, regenerate=False)
        path = Path(settings.DIPLOMAS_OUTPUT_DIR) / "ana.torres.pdf"
        original = _digest(path)
        self.use_motive("TEXTO CAMBIADO")
        second = GenerationService().run(send_email=False, regenerate=False)
        self.assertEqual(_digest(path), original)
        self.assertEqual(second.already_exists_count, 1)
        self.assertEqual(second.generated_count, 0)
        self.assertEqual(
            second.records.get().status,
            GenerationStatus.ALREADY_EXISTS,
        )
        self.assertIn("ya existe", second.records.get().message)
        self.assertEqual(first.generated_count, 1)

    def test_yes_creates_a_numbered_copy_without_replacing(self):
        self.use_png_template()
        self.use_motive("TEXTO ORIGINAL")
        self.use_layout()
        self.use_people([("Ana", "Torres", "ana.torres@example.com", "valid")])
        GenerationService().run(send_email=False, regenerate=False)
        path = Path(settings.DIPLOMAS_OUTPUT_DIR) / "ana.torres.pdf"
        original = _digest(path)
        self.use_motive("TEXTO REGENERADO AHORA")
        batch = GenerationService().run(send_email=False, regenerate=False, numbered_copies=True)
        copy = Path(settings.DIPLOMAS_OUTPUT_DIR) / "ana.torres_1.pdf"
        self.assertEqual(_digest(path), original)
        self.assertTrue(copy.is_file())
        self.assertEqual(batch.generated_count, 1)
        self.assertEqual(batch.records.get().filename, "ana.torres_1.pdf")
        self.assertEqual(batch.records.get().status, GenerationStatus.GENERATED)
        again = GenerationService().run(send_email=False, regenerate=False, numbered_copies=True)
        self.assertTrue((Path(settings.DIPLOMAS_OUTPUT_DIR) / "ana.torres_2.pdf").is_file())
        self.assertEqual(again.records.get().filename, "ana.torres_2.pdf")
        self.assertEqual(_digest(path), original)

    def test_generation_asks_before_creating_another_copy(self):
        self.use_png_template()
        self.use_motive()
        self.use_layout()
        self.use_people([("Ana", "Torres", "ana.torres@example.com", "valid")])
        GenerationService().run(send_email=False, regenerate=False)
        client = Client()
        asked = client.post("/generar/", {"action": "generate"})
        body = asked.content.decode()
        self.assertEqual(asked.status_code, 200)
        self.assertIn("¿Quiere volver a generar el certificado?", body)
        self.assertIn('value="no" checked', body)
        declined = client.post("/generar/", {"action": "generate", "again": "no"})
        self.assertEqual(declined.status_code, 302)
        self.assertFalse((Path(settings.DIPLOMAS_OUTPUT_DIR) / "ana.torres_1.pdf").exists())
        accepted = client.post("/generar/", {"action": "generate", "again": "yes"})
        self.assertEqual(accepted.status_code, 302)
        self.assertTrue((Path(settings.DIPLOMAS_OUTPUT_DIR) / "ana.torres_1.pdf").is_file())

    def test_one_person_certificate_does_not_touch_the_others(self):
        self.use_png_template()
        self.use_motive()
        self.use_layout()
        self.use_people(
            [
                ("Ana", "Torres", "ana.torres@example.com", "valid"),
                ("Luis", "Mendoza", "luis.mendoza@example.com", "valid"),
            ]
        )
        ana = Participant.objects.get(first_name="Ana")
        client = Client()
        created = client.post("/lista/", {"action": "certificate", "participant": ana.pk})
        self.assertEqual(created.status_code, 302)
        output = Path(settings.DIPLOMAS_OUTPUT_DIR)
        self.assertTrue((output / "ana.torres.pdf").is_file())
        self.assertFalse((output / "luis.mendoza.pdf").exists())
        asked = client.post("/lista/", {"action": "certificate", "participant": ana.pk})
        self.assertContains(asked, "¿Quiere volver a generar el certificado?")
        self.assertContains(asked, 'value="no" checked')
        copied = client.post(
            "/lista/",
            {"action": "certificate", "participant": ana.pk, "again": "yes"},
        )
        self.assertEqual(copied.status_code, 302)
        self.assertTrue((output / "ana.torres_1.pdf").is_file())
        self.assertFalse((output / "luis.mendoza.pdf").exists())

    def test_suffix_policy_is_explicit(self):
        self.use_png_template()
        self.use_motive()
        self.use_layout(collision_policy="suffix")
        self.use_people(
            [
                ("José", "Núñez", "jose.nunez@example.com", "warning"),
                ("Jose", "Nunez", "otro.jose@example.com", "warning"),
            ]
        )
        batch = GenerationService().run(send_email=False, regenerate=False)
        names = sorted(path.name for path in Path(settings.DIPLOMAS_OUTPUT_DIR).glob("*.pdf"))
        self.assertEqual(names, ["jose.nunez.pdf", "jose.nunez_2.pdf"])
        suffixed = batch.records.get(filename="jose.nunez_2.pdf")
        self.assertIn("jose.nunez_2.pdf", suffixed.message)
