"""Render the synthetic leases in ``lease_content.py`` to PDFs + ground truth.

    python scripts/generate_leases.py [--out data/synthetic]

Writes one PDF per document plus ``ground_truth.json``, which the segmenter
tests and the eval suite both read. Because the PDFs are generated from the same
specs the ground truth is derived from, eval expectations are exact rather than
hand-labelled.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lease_content import (  # noqa: E402
    ALL_LEASES,
    MESSY_LOFT,
    MESSY_LOFT_TEXT,
    DocumentSpec,
    LeaseSpec,
)

DEFAULT_OUT = Path(__file__).resolve().parents[1] / "data" / "synthetic"

_BASE = getSampleStyleSheet()

TITLE_STYLE = ParagraphStyle(
    "LeaseTitle",
    parent=_BASE["Title"],
    fontName="Times-Bold",
    fontSize=13,
    spaceAfter=18,
)
PREAMBLE_STYLE = ParagraphStyle(
    "Preamble",
    parent=_BASE["BodyText"],
    fontName="Times-Roman",
    fontSize=10.5,
    leading=15,
    alignment=TA_LEFT,
    spaceAfter=14,
)
HEADING_STYLE = ParagraphStyle(
    "ClauseHeading",
    parent=_BASE["BodyText"],
    fontName="Times-Bold",
    fontSize=10.5,
    leading=15,
    spaceBefore=10,
    spaceAfter=4,
)
BODY_STYLE = ParagraphStyle(
    "ClauseBody",
    parent=_BASE["BodyText"],
    fontName="Times-Roman",
    fontSize=10.5,
    leading=15,
    alignment=TA_LEFT,
    spaceAfter=8,
)


def _marker_label(number: str, heading: str) -> str:
    """How the clause number is printed — the string the segmenter parses back."""
    if number.isupper() and number.strip("IVXLCDM") == "":
        return f"ARTICLE {number}."
    if "(" in number:  # 14(a), 14(b)
        return f"{number}"
    return f"{number}."


def render_document(spec: DocumentSpec, path: Path) -> None:
    doc = SimpleDocTemplate(
        str(path),
        pagesize=LETTER,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
        title=spec.title or spec.doc_id,
    )
    flow: list = []
    if spec.title:
        flow.append(Paragraph(spec.title, TITLE_STYLE))
    if spec.preamble:
        flow.append(Paragraph(spec.preamble, PREAMBLE_STYLE))

    for clause in spec.clauses:
        label = _marker_label(clause.number, clause.heading)
        if clause.heading:
            flow.append(Paragraph(f"{label} {clause.heading}", HEADING_STYLE))
            if clause.body:
                flow.append(Paragraph(clause.body, BODY_STYLE))
        else:
            # No heading: the marker leads the body text on the same line.
            flow.append(Paragraph(f"{label} {clause.body}", BODY_STYLE))

    flow.append(Spacer(1, 24))
    flow.append(
        Paragraph(
            f"Executed on {spec.signed_date}. LANDLORD ______________  "
            "TENANT ______________",
            BODY_STYLE,
        )
    )
    doc.build(flow)


def render_prose_document(text: str, path: Path, title: str) -> None:
    """The messy lease: plain paragraphs, no clause markers at all."""
    doc = SimpleDocTemplate(
        str(path),
        pagesize=LETTER,
        leftMargin=1 * inch,
        rightMargin=1 * inch,
        topMargin=1 * inch,
        bottomMargin=1 * inch,
        title=title,
    )
    flow = [Paragraph(block.replace("\n", " "), PREAMBLE_STYLE) for block in text.split("\n\n")]
    doc.build(flow)


def _lease_ground_truth(lease: LeaseSpec, files: dict[str, str]) -> dict:
    return {
        "lease_id": lease.lease_id,
        "strategy": lease.strategy,
        "documents": [
            {
                "doc_id": d.doc_id,
                "file": files[d.doc_id],
                "kind": d.kind,
                "signed_date": d.signed_date,
                "clauses": [asdict(c) for c in d.clauses],
            }
            for d in lease.documents
        ],
        "answerable": lease.answerable,
        "not_covered": lease.not_covered,
        "overrides": lease.overrides,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    ground_truth = []
    for lease in ALL_LEASES:
        files: dict[str, str] = {}
        for spec in lease.documents:
            filename = f"{spec.doc_id}.pdf"
            path = out / filename
            if lease is MESSY_LOFT:
                render_prose_document(MESSY_LOFT_TEXT, path, spec.doc_id)
            else:
                render_document(spec, path)
            files[spec.doc_id] = filename
            print(f"wrote {path.relative_to(out.parent.parent)}")
        ground_truth.append(_lease_ground_truth(lease, files))

    gt_path = out / "ground_truth.json"
    gt_path.write_text(json.dumps(ground_truth, indent=2) + "\n")
    print(f"wrote {gt_path.relative_to(out.parent.parent)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
