"""Build the golden-set DRAFT that accuracy is scored against.

⚠ WHY THIS FILE EXISTS, AND WHY ITS OUTPUT IS A DRAFT

`ps06_sample_rate_sheets.csv` ships with `needs_review`, and the obvious move is to
score against it. Measured on the file, that is wrong: flagged rows span confidence
0.61-0.99 and unflagged rows span 0.60-0.99 -- the same range. The flag is uncorrelated
with the score because the data is synthetic, so fitting thresholds or accuracy against
it would be a number with nothing behind it.

So accuracy is scored against a set a HUMAN confirmed. This script emits the draft --
stratified, deterministic, with the expected field proposed -- and a human fills
`confirmed_by`. A row with an empty `confirmed_by` is NOT scored, and
`eval/score.py` refuses to report accuracy if fewer than 30 rows are confirmed. That
refusal is the point: it makes an unconfirmed claim impossible to make by accident.

WHAT A GOLD ROW ASSERTS
  given this source label, as THIS institution writes it in THIS format,
  the value belongs in THIS canonical field, with THIS converted value.

The conversions are known by construction, because `make_documents.py` renders the
documents from these same rows. The MAPPING is the part a human asserts, and it is the
part the problem statement is actually about.

Run:  python backend/eval/make_golden_set.py
"""

from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "data" / "samples" / "ps06_sample_rate_sheets.csv"
OUT = Path(__file__).resolve().parent / "golden_set.csv"
#: Written by make_documents.py. It is the only authority on what each institution's
#: generated document is actually called.
GROUND_TRUTH = Path(__file__).resolve().parent / "generated" / "ground_truth.json"


def generated_files() -> dict[str, str]:
    """institution -> the filename make_documents.py actually wrote.

    ⚠ THIS EXISTS BECAUSE THE GOLDEN SET SCORED 0 MATCHES AGAINST A WORKING PIPELINE.

    The first version keyed each gold row on `ps06.source_file` -- names like
    `first_national_bank_rates_page1.pdf`, which describe the ORIGINAL bank rate sheets
    the sample data was derived from. Nothing by that name is ever ingested: what the
    pipeline reads is `first_national_bank_rates.pdf`, written by make_documents.py. So
    every key missed, `matched` came back 0, and accuracy would have read 0.0 while the
    pipeline was mapping correctly -- the worst shape of bug, because the number looks
    like catastrophic failure rather than like a broken join.

    Reading the filename from ground_truth.json rather than restating it keeps the two
    generators from drifting apart silently, the same reason REPORTING_STYLE is shared.
    """
    import json

    if not GROUND_TRUTH.exists():
        raise SystemExit(
            f"{GROUND_TRUTH} is missing -- run `python backend/eval/make_documents.py` first; "
            "the golden set keys on the documents it writes."
        )
    data = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    return {d["institution"]: d["file"] for d in data["documents"]}

#: How each institution reports, and therefore what the mapper has to recognise.
#: This mirrors `make_documents.py` exactly -- one institution per format, each using
#: different words for the same quantities. Changing a label here without changing it
#: there breaks the ground truth silently, so both read this one table.
REPORTING_STYLE: dict[str, dict] = {
    "First National Bank": {
        "format": "pdf_text",
        "labels": {
            "rate_pct": "Rate",
            "apy_pct": "APY",
            "min_deposit": "Min. Deposit",
            "term_months": "Term",
            "effective_date": "Effective",
        },
        "rate_is_monthly": False,
        "note": "plain table, conventional headers -- the easy case, and the control",
    },
    "Metro Credit Union": {
        "format": "pdf_scanned",
        "labels": {
            "rate_pct": "Interest",
            "apy_pct": "Annual Yield",
            "min_deposit": "Opening Balance",
            "term_months": "Period (mo)",
            "effective_date": "In effect from",
        },
        "rate_is_monthly": False,
        "note": "scanned -- exercises OCR, and 'Opening Balance' is a synonym nobody declares up front",
    },
    "Heritage Financial": {
        "format": "html",
        "labels": {
            "rate_pct": "p.a. %",
            "apy_pct": "effective yield",
            "min_deposit": "minimum to open",
            "term_months": "term",
            "effective_date": "valid from",
        },
        "rate_is_monthly": False,
        "note": "HTML, lowercase headers, value rendered as '1.36 %' with a space",
    },
    "Pacific Savings": {
        "format": "xlsx",
        "labels": {
            "rate_pct": "Nominal (monthly)",
            "apy_pct": "Yield (annual)",
            "min_deposit": "Min Balance",
            "term_months": "Months",
            "effective_date": "From",
        },
        "rate_is_monthly": True,  # ← THE UNIT-CONVERSION CASE
        "note": "quotes a MONTHLY nominal rate; the pack's x12 rule must recover the annual figure",
    },
    "Summit Trust": {
        "format": "narrative",
        "labels": {
            "rate_pct": "pays ... annually",
            "apy_pct": "annual percentage yield of",
            "min_deposit": "balances over",
            "term_months": "for a term of",
            "effective_date": "with effect from",
        },
        "rate_is_monthly": False,
        "note": "prose disclosure -- no table at all, which is the narrative requirement",
    },
    "Valley Community Bank": {
        "format": "pdf_text_footnote",
        "labels": {
            "rate_pct": "Rate*",
            "apy_pct": "APY*",
            "min_deposit": "Minimum",
            "term_months": "Term",
            "effective_date": "Effective",
        },
        "rate_is_monthly": False,
        "note": "footnote contradicts the table -- this is the AMBIGUITY case and must be flagged, not guessed",
    },
}

#: Source column -> the canonical field it belongs in. PROPOSED, not decided: a human
#: confirms each row. The pack declares these names; they are not invented here.
PROPOSED_FIELD: dict[str, str] = {
    "rate_pct": "interest_rate_annual_pct",
    "apy_pct": "annual_percentage_yield_pct",
    "min_deposit": "minimum_deposit_usd",
    "term_months": "term_months",
    "effective_date": "effective_date",
}

UNIT: dict[str, str] = {
    "rate_pct": "percent_per_annum",
    "apy_pct": "percent_per_annum",
    "min_deposit": "USD",
    "term_months": "months",
    "effective_date": "date",
}

#: Five gold rows per institution, 30 in total. Each institution gets the two rate
#: fields (the ones terminology actually differs on), the deposit, and two others, so
#: every institution's own vocabulary is exercised rather than one institution's five times.
FIELDS_PER_INSTITUTION = ["rate_pct", "apy_pct", "min_deposit", "term_months", "effective_date"]


def build() -> list[dict]:
    rows = list(csv.DictReader(SOURCE.open(encoding="utf-8")))
    by_institution: dict[str, list[dict]] = {}
    for r in rows:
        by_institution.setdefault(r["institution_name"], []).append(r)

    gold: list[dict] = []
    files = generated_files()
    n = 0
    for institution in sorted(by_institution):
        style = REPORTING_STYLE.get(institution)
        if style is None:
            raise SystemExit(f"no reporting style declared for {institution!r} -- add it above")
        # Deterministic pick: the first record of each distinct product type, so the
        # five gold rows for an institution are not five near-identical savings rows.
        seen: set[str] = set()
        picked: list[dict] = []
        for r in by_institution[institution]:
            if r["product_type"] not in seen:
                seen.add(r["product_type"])
                picked.append(r)
            if len(picked) == len(FIELDS_PER_INSTITUTION):
                break
        while len(picked) < len(FIELDS_PER_INSTITUTION):
            picked.append(by_institution[institution][len(picked)])

        for field, record in zip(FIELDS_PER_INSTITUTION, picked):
            n += 1
            raw = record[field]
            expected = raw
            as_printed = raw
            if field == "rate_pct" and style["rate_is_monthly"]:
                # The document prints the monthly figure; the gold value is the annual one.
                as_printed = f"{float(raw) / 12:.4f}"
            gold.append(
                {
                    "gold_id": f"G{n:03d}",
                    "institution_name": institution,
                    # The document the pipeline actually ingests. ps06's own
                    # source_file is kept beside it as provenance, but it is NOT
                    # the join key -- see generated_files().
                    "document_file": files[institution],
                    "ps06_source_file": record["source_file"],
                    "document_format": style["format"],
                    "product_type": record["product_type"],
                    "source_label": style["labels"][field],
                    "value_as_printed": as_printed,
                    "expected_field": PROPOSED_FIELD[field],
                    "expected_value": expected,
                    "expected_unit": UNIT[field],
                    "conversion_expected": "x12 monthly->annual"
                    if (field == "rate_pct" and style["rate_is_monthly"])
                    else "none",
                    "difficulty": style["note"],
                    "confirmed_by": "",  # ← a human fills this. Empty rows are not scored.
                }
            )
    return gold


def main() -> None:
    gold = build()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(gold[0]))
        writer.writeheader()
        writer.writerows(gold)
    confirmed = sum(1 for r in gold if r["confirmed_by"])
    print(f"wrote {OUT} -- {len(gold)} rows, {confirmed} confirmed")
    print("Fill `confirmed_by` on every row you have checked. Unconfirmed rows are not scored.")


if __name__ == "__main__":
    main()
