"""Final Approval Report PDF for a scored submission (ServiceNow download API)."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


def _safe(text: Any) -> str:
    raw = str(text if text is not None else "")
    raw = (
        raw.replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2026", "...")
    )
    return "".join(ch if 32 <= ord(ch) <= 126 else "?" for ch in raw)


def _esc(text: Any) -> str:
    return _safe(text).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap(text: Any, width: int) -> list[str]:
    words = _safe(text).split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word if len(word) <= width else word[:width]
    if current:
        lines.append(current)
    return lines or [""]


def _payload_value(payload: dict, key: str) -> str:
    system = payload.get("aiSystem") or {}
    conditional = payload.get("conditionalInformation") or {}
    business = conditional.get("businessValue") or {}
    for_us = conditional.get("aiForUs") or {}
    provenance = payload.get("provenance") or {}

    mapping = {
        "name": system.get("name"),
        "owner": system.get("businessOwner") or system.get("owner"),
        "businessUnit": system.get("businessUnit"),
        "summary": system.get("summary") or system.get("description") or payload.get("description"),
        "category": payload.get("category"),
        "forTool": for_us.get("toolOrPlatform"),
        "forAccess": for_us.get("accessMethod"),
        "valueDriver": business.get("valueDriver"),
        "hoursSaved": business.get("hoursSaved"),
        "annualValue": business.get("annualValue"),
        "investmentCost": business.get("investmentCost"),
        "spendingToDate": business.get("spendingToDate"),
        "sensitive": (payload.get("screening") or {}).get("data"),
        "decision": (payload.get("screening") or {}).get("decision"),
        "action": (payload.get("screening") or {}).get("action"),
    }
    value = mapping.get(key)
    if value in (None, "") and isinstance(provenance.get(key), dict):
        value = provenance[key].get("value")
    if isinstance(value, dict):
        value = value.get("name") or value.get("email") or ""
    if isinstance(value, list):
        return ", ".join(_safe(v) for v in value if v not in (None, ""))
    return _safe(value or "")


def _money(value: str) -> str:
    text = _safe(value)
    if not text:
        return "Not stated"
    return text


class _PdfBuilder:
    def __init__(self) -> None:
        self.page_w = 595.28
        self.page_h = 841.89
        self.pages: list[list[str]] = []
        self.ops: list[str] = []

    def new_page(self) -> None:
        if self.ops:
            self.pages.append(self.ops)
        self.ops = []

    def finish_pages(self) -> None:
        if self.ops:
            self.pages.append(self.ops)
            self.ops = []

    def _rgb(self, color: tuple[float, float, float]) -> str:
        return f"{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg"

    def fill_rect(self, x: float, y: float, w: float, h: float, color: tuple[float, float, float]) -> None:
        # y is top-left in UI coords; PDF y grows upward from bottom
        self.ops.append(
            f"{self._rgb(color)}\n{x:.2f} {self.page_h - y - h:.2f} {w:.2f} {h:.2f} re f"
        )

    def hline(self, x1: float, x2: float, y: float, color: tuple[float, float, float], width: float = 0.6) -> None:
        py = self.page_h - y
        self.ops.append(
            f"{width:.2f} w\n{color[0]:.3f} {color[1]:.3f} {color[2]:.3f} RG\n"
            f"{x1:.2f} {py:.2f} m {x2:.2f} {py:.2f} l S"
        )

    def text(self, s: Any, x: float, y: float, size: float, color: tuple[float, float, float], bold: bool = False) -> None:
        font = "F2" if bold else "F1"
        py = self.page_h - y
        self.ops.append(
            f"BT /{font} {size:.1f} Tf {color[0]:.3f} {color[1]:.3f} {color[2]:.3f} rg "
            f"1 0 0 1 {x:.2f} {py:.2f} Tm ({_esc(s)}) Tj ET"
        )

    def build(self) -> bytes:
        self.finish_pages()
        offsets: dict[int, int] = {}
        out: list[str] = []

        def write_obj(n: int, body: str) -> None:
            offsets[n] = sum(len(part) for part in out)
            out.append(f"{n} 0 obj\n{body}\nendobj\n")

        font_reg, font_bold = 3, 4
        page_ids: list[int] = []
        content_ids: list[int] = []
        next_id = 5
        for _ in self.pages:
            page_ids.append(next_id)
            next_id += 1
            content_ids.append(next_id)
            next_id += 1

        write_obj(1, "<< /Type /Catalog /Pages 2 0 R >>")
        kids = " ".join(f"{pid} 0 R" for pid in page_ids)
        write_obj(2, f"<< /Type /Pages /Kids [{kids}] /Count {len(self.pages)} >>")
        write_obj(font_reg, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
        write_obj(font_bold, "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>")

        for i, page_ops in enumerate(self.pages):
            stream = "\n".join(page_ops)
            write_obj(
                page_ids[i],
                "<< /Type /Page /Parent 2 0 R "
                f"/MediaBox [0 0 {self.page_w:.2f} {self.page_h:.2f}] "
                f"/Resources << /Font << /F1 {font_reg} 0 R /F2 {font_bold} 0 R >> >> "
                f"/Contents {content_ids[i]} 0 R >>",
            )
            write_obj(content_ids[i], f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream")

        xref_pos = sum(len(part) for part in out)
        xref = [f"xref\n0 {next_id}\n0000000000 65535 f \n"]
        for i in range(1, next_id):
            xref.append(f"{offsets[i]:010d} 00000 n \n")
        pdf = (
            "%PDF-1.4\n"
            + "".join(out)
            + "".join(xref)
            + f"trailer\n<< /Size {next_id} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF"
        )
        return pdf.encode("latin-1", errors="replace")


def build_final_approval_pdf(row: Any) -> tuple[bytes, str]:
    """Return (pdf_bytes, filename) for a submission row."""
    payload = row.payload or {}
    assessment = row.assessment or {}
    result = assessment.get("result") or {}
    governance = result.get("residualRiskGovernance") or {}
    decision = row.decision or {}
    screening = payload.get("screening") or {}

    reference = row.reference_id
    name = _payload_value(payload, "name") or "Untitled use case"
    summary = (
        _payload_value(payload, "summary")
        or _safe(payload.get("description") or "")
        or "No request summary provided."
    )
    owner = _payload_value(payload, "owner") or "Not stated"
    unit = _payload_value(payload, "businessUnit") or "Not stated"
    category = _payload_value(payload, "category") or _safe(row.category) or "Not stated"
    tool = _payload_value(payload, "forTool")
    access = _payload_value(payload, "forAccess")
    platform = ", ".join(part for part in [tool, access] if part) or "Not stated"
    benefit = _payload_value(payload, "hoursSaved") or _payload_value(payload, "valueDriver") or "Not stated"
    annual = _money(_payload_value(payload, "annualValue"))
    investment = _money(_payload_value(payload, "investmentCost"))
    spent = _money(_payload_value(payload, "spendingToDate"))

    sensitive = _safe(screening.get("data") or _payload_value(payload, "sensitive") or "n/a")
    decision_s = _safe(screening.get("decision") or _payload_value(payload, "decision") or "n/a")
    action = _safe(screening.get("action") or _payload_value(payload, "action") or "n/a")

    inherent = result.get("inherentRiskScore")
    residual = result.get("residualRiskScore")
    severity = _safe(governance.get("severity") or "n/a").upper()
    tier = _safe(governance.get("tier") or "n/a").upper()
    approval = _safe(governance.get("approval") or "RAIO")
    validated = datetime.now(timezone.utc).strftime("%d %B %Y")
    decided = _safe(decision.get("outcome") or row.status or "")
    notes = _safe(decision.get("notes") or "")
    conditions = _safe(decision.get("conditions") or "")
    ritm = _safe(decision.get("serviceNowTicket") or "")
    assessed_by = _safe(assessment.get("assessedBy") or "")
    decided_by = _safe(decision.get("decidedBy") or "")

    ink = (0.11, 0.07, 0.09)
    muted = (0.45, 0.38, 0.42)
    body = (0.22, 0.16, 0.18)
    bar = (0.76, 0.07, 0.24)
    rule = (0.86, 0.80, 0.82)
    soft = (0.98, 0.96, 0.97)

    pdf = _PdfBuilder()
    L, R = 48.0, 547.0

    # Page 1
    pdf.new_page()
    pdf.fill_rect(0, 0, pdf.page_w, 56, (0.12, 0.07, 0.10))
    pdf.text("JazzWorld  |  SYRA", L, 28, 11, (1, 1, 1), True)
    pdf.text("Final Approval Report", L, 46, 9, (0.95, 0.85, 0.88), False)
    pdf.text(reference, R - 150, 28, 9, (1, 1, 1), True)
    pdf.text(validated, R - 150, 46, 8, (0.90, 0.80, 0.84), False)

    pdf.text("USE CASE", L, 84, 11, bar, True)
    pdf.hline(L, R, 94, bar, 0.9)
    pdf.text(name, L, 116, 16, ink, True)
    y = 138
    for line in _wrap(summary, 95)[:5]:
        pdf.text(line, L, y, 10, body, False)
        y += 14

    y += 10
    pdf.text("KEY FACTS", L, y, 11, bar, True)
    pdf.hline(L, R, y + 10, bar, 0.9)
    y += 34
    facts = [
        ("BUSINESS OWNER", owner),
        ("BUSINESS UNIT", unit),
        ("CATEGORY", category),
        ("PLATFORM", platform),
        ("EXPECTED BENEFIT", benefit),
        ("ESTIMATED ANNUAL VALUE", annual),
        ("INVESTMENT", investment),
        ("SPEND TO DATE", spent),
    ]
    for label, value in facts:
        pdf.text(label, L, y, 8, muted, True)
        for i, line in enumerate(_wrap(value, 70)[:2]):
            pdf.text(line, L + 160, y + i * 12, 10, ink, False)
        y += 28 if len(_wrap(value, 70)) > 1 else 22
        pdf.hline(L, R, y - 8, rule, 0.4)

    y += 8
    pdf.text(
        f"Requester screening: Data - {sensitive}. Decision - {decision_s}. Action - {action}.",
        L,
        y,
        9,
        muted,
        False,
    )

    y += 28
    pdf.text("RISK POSITION", L, y, 11, bar, True)
    pdf.hline(L, R, y + 10, bar, 0.9)
    y += 36
    cols = [
        (L, "INHERENT", str(inherent if inherent is not None else "n/a")),
        (L + 160, "RESIDUAL", str(residual if residual is not None else "n/a")),
        (L + 320, "SEVERITY / TIER", f"{severity} / {tier}"),
    ]
    for x, label, value in cols:
        pdf.hline(x, x + 120, y, bar, 2.2)
        pdf.text(label, x, y + 16, 8, muted, True)
        pdf.text(value, x, y + 40, 16, ink, True)
    y += 70
    pdf.text(f"Base approval: {approval}", L, y, 10, body, False)
    y += 18
    if decided:
        pdf.text(f"Final decision: {decided.replace('_', ' ')}", L, y, 10, body, True)
        y += 16
    if ritm:
        pdf.text(f"ServiceNow ticket: {ritm}", L, y, 10, body, False)
        y += 16
    pdf.text(f"Page 1 of 2", L, pdf.page_h - 36, 8, muted, False)
    pdf.text("Confidential - Jazz internal", R - 160, pdf.page_h - 36, 8, muted, False)

    # Page 2
    pdf.new_page()
    pdf.fill_rect(0, 0, pdf.page_w, 56, (0.12, 0.07, 0.10))
    pdf.text("JazzWorld  |  SYRA", L, 28, 11, (1, 1, 1), True)
    pdf.text("Final Approval Report", L, 46, 9, (0.95, 0.85, 0.88), False)
    pdf.text(reference, R - 150, 28, 9, (1, 1, 1), True)

    y = 88
    pdf.text("GOVERNANCE OUTCOME", L, y, 11, bar, True)
    pdf.hline(L, R, y + 10, bar, 0.9)
    y += 34
    gov_lines = [
        f"Residual risk score: {residual if residual is not None else 'n/a'} / 100",
        f"Severity: {severity}",
        f"Tier: {tier}",
        f"Approval authority: {approval}",
    ]
    if assessed_by:
        gov_lines.append(f"Assessed by: {assessed_by}")
    if decided_by:
        gov_lines.append(f"Decided by: {decided_by}")
    for line in gov_lines:
        pdf.text(line, L, y, 10, body, False)
        y += 16

    y += 16
    pdf.text("CONDITIONS OF APPROVAL", L, y, 11, bar, True)
    pdf.hline(L, R, y + 10, bar, 0.9)
    y += 34
    if conditions:
        for line in _wrap(conditions, 95)[:8]:
            pdf.text(line, L, y, 10, body, False)
            y += 14
    else:
        pdf.text("No special conditions recorded.", L, y, 10, body, False)
        y += 16

    y += 18
    pdf.text("DECISION COMMENTS", L, y, 11, bar, True)
    pdf.hline(L, R, y + 10, bar, 0.9)
    y += 34
    if notes:
        for line in _wrap(notes, 95)[:8]:
            pdf.text(line, L, y, 10, body, False)
            y += 14
    else:
        pdf.text("No decision comments recorded.", L, y, 10, body, False)
        y += 16

    y += 22
    pdf.fill_rect(L - 8, y - 8, R - L + 16, 70, soft)
    closing = (
        f"Residual risk. Indicative residual risk is {residual if residual is not None else 'n/a'} / 100 "
        f"({tier.lower()}). Reassess if the use, data, provider, integrations or autonomy change."
    )
    for i, line in enumerate(_wrap(closing, 92)[:4]):
        pdf.text(line, L, y + 8 + i * 14, 10, body, False)

    pdf.text("Page 2 of 2", L, pdf.page_h - 36, 8, muted, False)
    pdf.text("Confidential - Jazz internal", R - 160, pdf.page_h - 36, 8, muted, False)

    slug = re.sub(r"[^\w\-]+", "_", name).strip("_")[:40] or "request"
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    filename = f"SYRA_Final_Approval_Report_{slug}_{day}.pdf"
    return pdf.build(), filename
