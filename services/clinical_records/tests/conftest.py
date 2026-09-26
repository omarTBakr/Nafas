import io
import uuid
from dataclasses import dataclass

import pytest
from PIL import Image, ImageDraw, ImageFont

from nafas_core.db import session_scope
from nafas_identity.logic.accounts import create_doctor_account, register_patient_account
from nafas_identity.logic.directory import ensure_care_link
from nafas_identity.logic.seed import seed_specializations


@dataclass
class Clinic:
    doctor_id: uuid.UUID
    other_doctor_id: uuid.UUID
    patient_id: uuid.UUID
    other_patient_id: uuid.UUID


@pytest.fixture
async def clinic(database) -> Clinic:
    """Two doctors; a patient under the first one's care, and a second patient under no one's."""
    async with session_scope() as session:
        await seed_specializations(session)
        ids = []
        for email in ("heart@example.com", "other@example.com"):
            doctor = await create_doctor_account(
                session,
                email=email,
                password="doctor password 1",
                full_name_en="Dr",
                full_name_ar="د",
                specialization_code="cardiology",
            )
            ids.append(doctor.id)
        patients = []
        for email in ("p1@example.com", "p2@example.com"):
            account = await register_patient_account(session, email=email, password="patient password 1", full_name="م")
            patients.append(account.patient_id)
    async with session_scope(doctor_id=ids[0]) as session:
        await ensure_care_link(session, doctor_id=ids[0], patient_id=patients[0])
    return Clinic(ids[0], ids[1], patients[0], patients[1])


def text_pdf(lines: list[str]) -> bytes:
    """A one-page PDF with a real text layer, written by hand."""
    stream = "BT /F1 14 Tf 72 720 Td 18 TL " + " ".join(f"({line}) '" for line in lines) + " ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


def picture_of(lines: list[str]) -> Image.Image:
    """Black text on white, large enough for OCR: what a scanned page is."""
    font = ImageFont.load_default(size=36)
    image = Image.new("RGB", (1400, 120 + 60 * len(lines)), "white")
    draw = ImageDraw.Draw(image)
    for i, line in enumerate(lines):
        draw.text((60, 60 + 60 * i), line, fill="black", font=font)
    return image


def scanned_pdf(lines: list[str]) -> bytes:
    buffer = io.BytesIO()
    picture_of(lines).save(buffer, format="PDF")
    return buffer.getvalue()


def png(lines: list[str]) -> bytes:
    buffer = io.BytesIO()
    picture_of(lines).save(buffer, format="PNG")
    return buffer.getvalue()
