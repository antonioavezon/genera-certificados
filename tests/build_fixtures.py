"""Genera los archivos binarios de tests/fixtures. Los CSV de texto ya están en el repo."""

from pathlib import Path

import openpyxl
from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent / "fixtures"
ROOT.mkdir(parents=True, exist_ok=True)


def main() -> None:
    image = Image.new("RGB", (1200, 800), "#f7f1e8")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 1160, 760), outline="#0b3a5b", width=8)
    draw.rectangle((70, 180, 1130, 190), fill="#c4a35a")
    image.save(ROOT / "template.png", format="PNG")
    image.save(ROOT / "template.jpg", format="JPEG", quality=90)

    one = canvas.Canvas(str(ROOT / "template_una_pagina.pdf"), pagesize=(600, 400))
    one.setFillColorRGB(0.04, 0.23, 0.36)
    one.rect(20, 20, 560, 360, stroke=1, fill=0)
    one.drawString(40, 200, "Plantilla de una pagina")
    one.save()

    multi = canvas.Canvas(str(ROOT / "template_multipagina.pdf"), pagesize=(600, 400))
    multi.drawString(40, 200, "Pagina 1")
    multi.showPage()
    multi.drawString(40, 200, "Pagina 2")
    multi.save()

    (ROOT / "corrupto.pdf").write_bytes(b"%PDF-1.4\nesto no es un pdf valido")
    (ROOT / "corrupto.xlsx").write_bytes(b"PK\x03\x04esto no es un excel")
    (ROOT / "corrupto.csv").write_bytes(b"Nombre,Apellido\nAna,\xffTorres\n")

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Participantes"
    sheet.append(["Nombre", "Apellido", "Correo"])
    sheet.append(["Ana", "Torres", "ana.torres@example.com"])
    sheet.append(["Luis", "Mendoza", "luis.mendoza@example.com"])
    sheet.append(["Camila", "Rojas", "camila.rojas@example.com"])
    extra = workbook.create_sheet("Notas")
    extra.append(["Esta hoja no se usa"])
    workbook.save(ROOT / "lista_valida.xlsx")
    csv_path = ROOT / "lista_valida.csv"
    raw = csv_path.read_bytes()
    if not raw.startswith(b"\xef\xbb\xbf"):
        csv_path.write_bytes(b"\xef\xbb\xbf" + raw)
    print(f"Fixtures listas en {ROOT}")


if __name__ == "__main__":
    main()
