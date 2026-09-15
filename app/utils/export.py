from __future__ import annotations

import csv
from io import BytesIO, StringIO

from openpyxl import Workbook

from app.models import Contact


def contacts_to_txt(contacts: list[Contact]) -> bytes:
    lines = [c.pretty for c in contacts]
    return "\n".join(lines).encode("utf-8")


def contacts_to_csv(contacts: list[Contact]) -> bytes:
    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow(["kind", "value", "display", "status", "extra"])
    for c in contacts:
        writer.writerow([c.kind, c.value, c.display or c.pretty, c.status, c.extra])
    return buf.getvalue().encode("utf-8-sig")


def contacts_to_xlsx(contacts: list[Contact]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "contacts"
    ws.append(["kind", "value", "display", "status", "extra"])
    for c in contacts:
        ws.append([c.kind, c.value, c.display or c.pretty, c.status, c.extra])
    bio = BytesIO()
    wb.save(bio)
    return bio.getvalue()
