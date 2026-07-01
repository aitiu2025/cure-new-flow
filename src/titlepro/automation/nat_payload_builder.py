"""
NAT Payload Builder
Reads completed CURE pipeline output files and assembles the 47-field
structured JSON payload for posting back to NAT's cure-result endpoint.
"""

from __future__ import annotations
import json
import logging
import os
import re
from glob import glob
from pathlib import Path
from typing import Any, Optional

_log = logging.getLogger(__name__)


# ── Field extraction helpers ───────────────────────────────────────────────────

def _first_match(pattern: str, text: str, flags: int = re.IGNORECASE) -> str:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else ""


def _read_file_safe(path: str | Path) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def _extract_legal_from_deed_md(deed_md_path: str | Path) -> str:
    """Extract verbatim legal description from a deed's OCR-extracted markdown file.

    Normalises multi-line whitespace so that descriptions split across blank lines
    (common in Hillsborough watermark-API OCR output) are matched as one string.
    Searches between the 'to-wit:' clause and 'TO HAVE AND TO HOLD'.
    """
    text = _read_file_safe(deed_md_path)
    if not text:
        return ""

    # Collapse blank lines and stray line-breaks into a single space so multi-line
    # legal descriptions become searchable without multiline/DOTALL flags.
    normalized = re.sub(r"[ \t]*\n[ \t]*\n[ \t]*", " ", text)
    normalized = re.sub(r"\n", " ", normalized)
    normalized = re.sub(r"\s{2,}", " ", normalized)

    # Primary: between "to-wit:" (or "to wit,") and "TO HAVE AND TO HOLD"
    # Optional leading comma/space handles OCR artefacts like "to-wit: , The East..."
    m = re.search(
        r"to[- ]wit[,:]?\s*[,]?\s*(.{20,600}?)\s+TO HAVE AND TO HOLD",
        normalized, re.IGNORECASE,
    )
    if m:
        desc = m.group(1).strip().rstrip(",~").strip()
        if len(desc) > 20:
            return desc

    # Fallback: "The [directional] N feet of Lot M ... Plat Book ... Florida"
    m = re.search(
        r"(The\s+(?:East|West|North|South)\s+\d+[^|]{10,500}?"
        r"(?:Plat\s+Book|Public\s+Records|Official\s+Records)[^|]{0,300}"
        r"(?:Florida|County)(?:\s*[~])?)",
        normalized, re.IGNORECASE,
    )
    if m:
        desc = m.group(1).strip().rstrip(",~").strip()
        if 20 < len(desc) < 800:
            return desc

    return ""


def _find_tax_json(output_dir: str) -> dict:
    """Find and merge all tax_*.json files in the output folder.

    Handles two formats:
      New: flat dict with status/county/apn at root (tax_lookup_status.json)
      Old: {fetch_success, tax_information: {tax_year, annual_tax_amount, ...}}
    """
    tax: dict = {}
    for p in sorted(glob(os.path.join(output_dir, "tax_*.json"))):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                continue
            # Old project format: unwrap tax_information block if present
            ti = data.get("tax_information")
            if isinstance(ti, dict) and ti:
                # Merge top-level metadata (fetch_success, apn, county, etc.)
                for k, v in data.items():
                    if k != "tax_information" and k not in tax:
                        tax[k] = v
                # Merge tax_information fields (overwrite with real data)
                tax.update(ti)
                # If fetch_success=True and status not yet set, mark verified
                if data.get("fetch_success") and "status" not in tax:
                    tax["status"] = "verified"
            else:
                tax.update(data)
        except Exception:
            pass
    return tax


# ── RAW report section splitter ───────────────────────────────────────────────

def _split_raw_sections(raw_text: str) -> dict[str, str]:
    """Split the RAW report into named phase/section blocks."""
    sections: dict[str, str] = {}
    parts = re.split(r"(?=^##\s)", raw_text, flags=re.MULTILINE)
    for part in parts:
        header_m = re.match(r"^##\s+(.+)", part)
        if header_m:
            key = header_m.group(1).strip().upper()
            sections[key] = part
    return sections


# ── Key-value table parser (| Field | Detail | format) ───────────────────────

def _parse_kv_table(text: str, start_idx: int = 0, max_chars: int = 2500) -> dict[str, str]:
    """
    Parse a | Field | Value | two-column table starting near start_idx.
    Returns a dict of lowercased field → raw value (bold markers stripped).
    """
    chunk = text[start_idx: start_idx + max_chars]
    result: dict[str, str] = {}
    for m in re.finditer(
        r"\|\s*(?P<key>[^|\n]{2,80}?)\s*\|\s*(?P<val>[^|\n]{1,400}?)\s*\|",
        chunk,
    ):
        key = m.group("key").strip().lower()
        val = re.sub(r"\*+", "", m.group("val")).strip()
        if key and val and not re.match(r"^-+$", key) and key != "field" and key != "detail":
            result[key] = val
    return result


# ── 8-column Chain of Title table parser ──────────────────────────────────────

# Matches rows like: | Seq# | Instrument | Date | Type | Grantor | Grantee | Consideration | OR Ref |
_DEED_CHAIN_ROW_RE = re.compile(
    r"\|\s*\d+\s*\|"                              # Seq column (single digit or small number)
    r"\s*(?P<inst>(?:20|19|99)\d{6,10})\s*\|"    # CFN / instrument number
    r"\s*(?P<date>[\d/\-]+)\s*\|"                 # Recorded date
    r"\s*(?P<type>[^|\n]{2,120})\s*\|"            # Doc type
    r"\s*(?P<grantor>[^|\n]{3,300})\s*\|"         # Grantor
    r"\s*(?P<grantee>[^|\n]{3,300})\s*\|"         # Grantee
    r"\s*(?P<consideration>[^|\n]{0,120})\s*\|"   # Consideration
    r"\s*(?P<bkpg>[^|\n]{0,100})\s*\|",           # OR Book/Page reference
    re.IGNORECASE,
)

# Fallback 5-column regex for older or non-standard table formats
_DEED_BLOCK_RE = re.compile(
    r"\|\s*(?P<inst>(?:20|19|99)\d{6,10})\s*\|"
    r"\s*(?P<date>[\d/\-]+)\s*\|"
    r"\s*(?P<type>[^|\n]{2,80})\s*\|"
    r"\s*(?P<parties>[^|\n]{5,300})\s*\|"
    r"\s*(?P<status>[^|\n]{2,200})\s*\|?",
    re.IGNORECASE,
)


def _clean_bkpg(raw: str) -> str:
    """Normalise 'BK 32515 PG 469' → '32515/469'."""
    raw = raw.strip()
    m = re.search(
        r"(?:OR\s+)?(?:BK|BKS?|BOOK)\s*(\d+)[,\s/]+(?:PG|PAGE)S?\s*(\d+)",
        raw, re.IGNORECASE,
    )
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    m = re.search(r"(\d{4,6})\s*/\s*(\d{1,5})", raw)
    if m:
        return f"{m.group(1)}/{m.group(2)}"
    return raw


def _clean_consideration(raw: str) -> str:
    """Return dollar amount from a consideration string."""
    raw = re.sub(r"\*+", "", raw).strip()
    if re.search(r"no consideration|\$0\.00|for love|nominal", raw, re.IGNORECASE):
        return "$0.00"
    m = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", raw)
    return f"${m.group(1)}" if m else raw


# ── Vesting chain extraction ───────────────────────────────────────────────────

def _parse_vesting_chain(raw_text: str, sections: dict, title_text: str = "") -> list[dict]:
    """
    Extract vesting/chain-of-title instruments from the RAW report.
    Falls back to the Title_Examination_Notes.md Chain of Title wide table when
    the RAW report has no parseable chain data.
    Prefers the 8-column Phase 5 Chain of Title table format; falls back to
    the legacy 5-column pipe-table format.
    """
    chain_text = ""
    for key in sections:
        if "CHAIN OF TITLE" in key or "VESTING" in key or "PHASE 5" in key or "PHASE 6" in key:
            chain_text += sections[key]
    if not chain_text:
        chain_text = raw_text

    chain: list[dict] = []
    seen: set = set()

    # ── Primary: 8-column chain table (Phase 5 Section E format) ──
    for m in _DEED_CHAIN_ROW_RE.finditer(chain_text):
        inst = m.group("inst").strip()
        doc_type = m.group("type").strip().upper()
        if inst in seen:
            continue
        if not any(kw in doc_type for kw in ("DEED", "QCD", "CONV", "TRUST", "GRANT")):
            continue
        seen.add(inst)
        grantor = m.group("grantor").strip()
        grantee = m.group("grantee").strip()
        consideration = _clean_consideration(m.group("consideration"))
        bkpg = _clean_bkpg(m.group("bkpg"))
        chain.append({
            "VestingInstrument":          inst,
            "VestingRecordedDate":        m.group("date").strip(),
            "VestingDated":               "",
            "VestingDeedType":            doc_type,
            "VestingGrantor":             grantor,
            "VestedAsGrantee":            grantee,
            "VestingBookPage":            bkpg,
            "VestingConsiderationAmount": consideration,
            "VestingMannerOfHolding":     _extract_manner_of_holding(chain_text, inst),
            "VestingComments":            "",
        })

    # ── Fallback: 5-column table ──
    if not chain:
        for m in _DEED_BLOCK_RE.finditer(chain_text):
            inst = m.group("inst").strip()
            doc_type = m.group("type").strip().upper()
            if inst in seen:
                continue
            if not any(kw in doc_type for kw in ("DEED", "QCD", "CONV", "TRUST", "GRANT")):
                continue
            seen.add(inst)
            parties_raw = m.group("parties").strip()
            grantor, grantee = _split_parties(parties_raw)
            # In 8-col tables mis-parsed as 5-col, the grantee lands in the status group
            if not grantee:
                status_text = m.group("status").strip()
                if not any(kw in status_text.upper() for kw in ("OPEN", "RELEASED", "CLOSED", "ACTIVE")):
                    grantee = status_text
            chain.append({
                "VestingInstrument":          inst,
                "VestingRecordedDate":        m.group("date").strip(),
                "VestingDated":               "",
                "VestingDeedType":            doc_type,
                "VestingGrantor":             grantor,
                "VestedAsGrantee":            grantee,
                "VestingBookPage":            _extract_book_page(chain_text, inst),
                "VestingConsiderationAmount": _extract_consideration(chain_text, inst),
                "VestingMannerOfHolding":     _extract_manner_of_holding(chain_text, inst),
                "VestingComments":            "",
            })

    # ── Title Notes wide-table fallback ──
    if not chain and title_text:
        chain = _parse_vesting_from_title(title_text)

    return chain


def _split_parties(raw: str) -> tuple[str, str]:
    """Split 'Grantor → Grantee' or 'Grantor to Grantee' into two parts."""
    for sep in ("→", "->", " to ", " TO ", " — "):
        if sep in raw:
            parts = raw.split(sep, 1)
            return parts[0].strip(), parts[1].strip()
    return raw.strip(), ""


def _extract_book_page(text: str, inst: str) -> str:
    """Search all occurrences of inst in text for a nearby BK/PG reference."""
    for m_inst in re.finditer(re.escape(inst), text):
        ctx = text[max(0, m_inst.start() - 100): m_inst.end() + 400]
        m = re.search(
            r"(?:OR\s+)?(?:BK|BKS?|BOOK)\s*(\d+)[,\s/]+(?:PG|PAGE)S?\s*(\d+)",
            ctx, re.IGNORECASE,
        )
        if m:
            return f"{m.group(1)}/{m.group(2)}"
        m = re.search(r"Book\s+(\d+)[,\s/]+Page\s+(\d+)", ctx, re.IGNORECASE)
        if m:
            return f"{m.group(1)}/{m.group(2)}"
    return ""


def _extract_consideration(text: str, inst: str) -> str:
    """Search all occurrences of inst in text for a nearby dollar amount."""
    for m_inst in re.finditer(re.escape(inst), text):
        ctx = text[max(0, m_inst.start() - 100): m_inst.end() + 400]
        if re.search(r"no documentary|no consideration|\$0\.00|for love", ctx, re.IGNORECASE):
            return "$0.00"
        m = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", ctx)
        if m:
            return f"${m.group(1)}"
    return ""


def _extract_manner_of_holding(text: str, inst: str) -> str:
    ctx = _context_around(text, inst, chars=600)
    for phrase in (
        "husband and wife", "joint tenants", "tenants in common",
        "tenants by the entireties", "as trustees", "living trust",
        "revocable trust", "single", "unmarried",
    ):
        if phrase.lower() in ctx.lower():
            return phrase.title()
    return ""


def _context_around(text: str, keyword: str, chars: int = 300) -> str:
    idx = text.find(keyword)
    if idx < 0:
        return ""
    return text[max(0, idx - chars): idx + chars]


# ── Open mortgages extraction ─────────────────────────────────────────────────

# Key aliases used in Phase 5 Section F | Field | Detail | mortgage tables
_MTG_FIELD_ALIASES: dict[str, str] = {
    # CFN / instrument
    "cfn": "inst",
    "cfn#": "inst",
    "instrument": "inst",
    "instrument number": "inst",
    # Book/page
    "or book/page": "bkpg",
    "book/page": "bkpg",
    "or bk/pg": "bkpg",
    # Recorded date
    "recorded": "date",
    "recording date": "date",
    # Document type
    "type": "doc_type",
    "document type": "doc_type",
    # Mortgagor/borrower
    "mortgagors": "mortgagor",
    "mortgagors / borrowers": "mortgagor",
    "mortgagors/borrowers": "mortgagor",
    "borrowers": "mortgagor",
    "mortgagor": "mortgagor",
    # Mortgagee/lender
    "original mortgagee": "mortgagee",
    "mortgagee": "mortgagee",
    "lender / mortgagee": "mortgagee",
    "mortgagee / lender": "mortgagee",
    "lender": "mortgagee",
    "underlying lender": "mortgagee",
    # Amount
    "original principal": "amount",
    "note amount": "amount",
    "maximum credit line": "amount",
    "principal amount": "amount",
    "loan amount": "amount",
    # Maturity
    "maturity": "maturity",
    "maturity date": "maturity",
    # Status
    "lien status": "status",
    "status": "status",
}


def _parse_mortgage_blocks(text: str) -> list[dict]:
    """
    Find 'OPEN MORTGAGE' or 'POTENTIALLY OPEN MORTGAGE' section blocks in
    Phase 5 Section F style and parse their | Field | Detail | tables.
    Each block is bounded by the next '---' separator or next mortgage header
    so we don't spill into NOC or other sections.
    """
    results: list[dict] = []
    header_re = re.compile(
        r"(?:\*{1,2})?\s*(?:OPEN|POTENTIALLY OPEN)\s+MORTGAGE[^|\n]*",
        re.IGNORECASE,
    )
    headers = list(header_re.finditer(text))

    for i, m_hdr in enumerate(headers):
        potentially = "POTENTIALLY" in m_hdr.group(0).upper()
        start = m_hdr.start()

        # Block ends at: next mortgage header, OR first "---" line, OR 1400 chars
        next_hdr_pos = headers[i + 1].start() if i + 1 < len(headers) else start + 1400
        block_limit = min(start + 1400, len(text), next_hdr_pos)

        # Find first "---" horizontal-rule separator within the block window
        sep_m = re.search(r"\n---\s*\n", text[start:block_limit])
        end = start + sep_m.start() if sep_m else block_limit

        block_text = text[start:end]
        kv = _parse_kv_table(block_text)

        # Map aliases to canonical keys (first-win: don't overwrite)
        canonical: dict[str, str] = {}
        for raw_key, val in kv.items():
            norm = _MTG_FIELD_ALIASES.get(raw_key)
            if norm and norm not in canonical:
                canonical[norm] = val

        if "inst" not in canonical:
            continue
        results.append({
            "canonical": canonical,
            "potentially": potentially,
        })
    return results


def _parse_open_mortgages(raw_text: str, sections: dict, title_text: str = "") -> list[dict]:
    """Extract OPEN/POTENTIALLY OPEN mortgages from Phase 5 Section F tables,
    with fallback to the legacy 5-column pipe-table scan, then Title Notes wide table."""
    # Build the mortgage/Phase 5 text slice
    mtg_text = ""
    for key in sections:
        if ("MORTGAGE" in key or "PHASE 5" in key or "PHASE 6" in key or "LIEN" in key):
            mtg_text += sections[key]
    if not mtg_text:
        mtg_text = raw_text

    mortgages: list[dict] = []
    seen: set = set()

    # ── Primary: parse | Field | Detail | mortgage blocks ──
    for block in _parse_mortgage_blocks(mtg_text):
        c = block["canonical"]
        inst = c.get("inst", "").strip()
        # Strip leading "CFN" prefix if present
        inst = re.sub(r"^cfn\s*", "", inst, flags=re.IGNORECASE).strip()
        if not inst or inst in seen:
            continue
        seen.add(inst)

        raw_bkpg = c.get("bkpg", "")
        bkpg = _clean_bkpg(raw_bkpg) if raw_bkpg else _extract_book_page(mtg_text, inst)

        raw_status = c.get("status", "")
        status = "POTENTIALLY OPEN" if (block["potentially"] or "POTENTIALLY" in raw_status.upper()) else "OPEN"

        mortgages.append({
            "OpenMortgageInstrument":        inst,
            "OpenMortgageRecordedDate":      c.get("date", ""),
            "OpenMortgageDated":             c.get("date", ""),
            "OpenMortgageDocumentType":      c.get("doc_type", "MORTGAGE").upper(),
            "OpenMortgageBorrowerMortgagor": c.get("mortgagor", ""),
            "OpenMortgageLenderMortgagee":   c.get("mortgagee", ""),
            "OpenMortgageAmount":            _clean_consideration(c.get("amount", "")),
            "OpenMortgageBookPage":          bkpg,
            "OpenMortgageTrustee1":          "",
            "OpenMortgageTrustee2":          "",
            "OpenMortgageComments":          "",
            "OpenMortgageStatus":            status,
            "OpenMortgageMaturityDate":      c.get("maturity", ""),
        })

    # ── Fallback: 5-column pipe-table scan (older report formats) ──
    if not mortgages:
        for m in _DEED_BLOCK_RE.finditer(raw_text):
            status = m.group("status").strip().upper()
            if not ("OPEN" in status or "POTENTIALLY" in status):
                continue
            doc_type = m.group("type").strip().upper()
            if not any(kw in doc_type for kw in ("MORTGAGE", "DOT", "DEED OF TRUST", "LIEN", "HELOC")):
                continue
            inst = m.group("inst").strip()
            if inst in seen:
                continue
            seen.add(inst)
            parties_raw = m.group("parties").strip()
            mortgagor, mortgagee = _split_parties(parties_raw)
            amount = _extract_dollar_amount(parties_raw) or _extract_dollar_amount(
                _context_around(raw_text, inst, 300)
            )
            mortgages.append({
                "OpenMortgageInstrument":        inst,
                "OpenMortgageRecordedDate":      m.group("date").strip(),
                "OpenMortgageDated":             m.group("date").strip(),
                "OpenMortgageDocumentType":      doc_type,
                "OpenMortgageBorrowerMortgagor": mortgagor,
                "OpenMortgageLenderMortgagee":   mortgagee,
                "OpenMortgageAmount":            amount,
                "OpenMortgageBookPage":          _extract_book_page(raw_text, inst),
                "OpenMortgageTrustee1":          "",
                "OpenMortgageTrustee2":          "",
                "OpenMortgageComments":          "",
                "OpenMortgageStatus":            "POTENTIALLY OPEN" if "POTENTIALLY" in status else "OPEN",
                "OpenMortgageMaturityDate":      _extract_maturity_date(raw_text, inst),
            })

    # ── Title Notes wide-table fallback ──
    if not mortgages and title_text:
        mortgages = _parse_mortgages_from_title(title_text)

    return mortgages


def _extract_dollar_amount(text: str) -> str:
    m = re.search(r"\$\s*([\d,]+(?:\.\d{2})?)", text)
    return f"${m.group(1)}" if m else ""


def _extract_maturity_date(text: str, inst: str) -> str:
    ctx = _context_around(text, inst, 400)
    m = re.search(r"matur\w*\s*(?:date)?[:\s]+(\d{1,2}/\d{1,2}/\d{4}|\w+\s+\d{4})", ctx, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _extract_dated_from_notes(notes: str) -> str:
    """Extract agreement/note execution date from a mortgage notes string."""
    m = re.search(
        r"(?:agreement|agmt|note)\s+dated?\s+(\d{1,2}/\d{1,2}/\d{4})",
        notes, re.IGNORECASE,
    )
    if m:
        return m.group(1)
    m = re.search(r"\bdated\s+(\d{1,2}/\d{1,2}/\d{4})", notes, re.IGNORECASE)
    return m.group(1) if m else ""


def _extract_maturity_from_notes(notes: str) -> str:
    """Extract maturity/due date from a mortgage notes string."""
    m = re.search(
        r"maturit[y\w]*\s*(?:date\s+)?(?:is\s+)?(\d{1,2}/\d{1,2}/\d{4})",
        notes, re.IGNORECASE,
    )
    if m:
        return m.group(1)
    m = re.search(r"\bdue\s+(?:date\s+)?(\d{1,2}/\d{1,2}/\d{4})", notes, re.IGNORECASE)
    return m.group(1) if m else ""


# ── Title Notes wide-table mortgage parser ────────────────────────────────────

def _parse_mortgages_from_title(title_text: str) -> list[dict]:
    """
    Parse mortgage tables from Title_Examination_Notes.md wide-column format.

    Handles the '## DEEDS OF TRUST / MORTGAGES' section which contains:
      ### Open Mortgages
        | Status | Instr. # | Rec. Date | Mortgagor | Mortgagee / Lender | Original Amount | Notes |
      ### Potentially Open — No Satisfaction Found ...
        | Status | Instr. # | Rec. Date | Mortgagor | Mortgagee / Lender | Original Amount | Maturity | Notes |
    """
    if not title_text:
        return []

    mtg_m = re.search(r"##\s+DEEDS OF TRUST\s*/\s*MORTGAGES\b", title_text, re.IGNORECASE)
    if not mtg_m:
        return []

    # Slice from this section to the next ## heading
    remaining = title_text[mtg_m.start():]
    next_h2 = re.search(r"\n##\s+(?!#)", remaining[5:])
    mtg_section = remaining[: next_h2.start() + 5] if next_h2 else remaining

    mortgages: list[dict] = []
    seen: set = set()
    is_potentially = False
    current_headers: list[str] = []

    for line in mtg_section.splitlines():
        stripped = line.strip()

        # Track ### sub-section context
        if stripped.startswith("###"):
            sub_title = stripped.lstrip("#").strip().upper()
            # Skip HELOC modification chain — different table format
            if "MODIFICATION" in sub_title or "CHAIN" in sub_title:
                current_headers = []
                continue
            is_potentially = "POTENTIALLY" in sub_title
            current_headers = []
            continue

        if not stripped.startswith("|"):
            continue

        # Skip markdown separator rows (|---|---|...)
        if re.match(r"^\|[\s\-|]+\|$", stripped):
            continue

        cells = [re.sub(r"\*+", "", c).strip() for c in stripped.split("|")]
        if cells and not cells[0]:
            cells = cells[1:]
        if cells and not cells[-1]:
            cells = cells[:-1]
        if not cells:
            continue

        # Detect header row: first cell is "Status" (case-insensitive)
        if not current_headers and cells[0].lower() == "status":
            current_headers = [c.lower() for c in cells]
            continue

        if not current_headers:
            continue

        row = {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(current_headers)}

        # Extract instrument number (header aliases: "instr. #", "instr #", "cfn")
        inst = ""
        for hkey in current_headers:
            if "instr" in hkey or hkey in ("cfn", "cfn#", "instrument"):
                inst = row.get(hkey, "").strip()
                break
        if not inst or not re.match(r"^\d{5,}", inst):
            continue
        if inst in seen:
            continue
        seen.add(inst)

        rec_date = row.get("rec. date", row.get("rec.date", row.get("recorded", "")))
        mortgagor = row.get("mortgagor", row.get("borrower", ""))
        mortgagee = row.get("mortgagee / lender", row.get("lender", row.get("mortgagee", "")))
        amount_raw = row.get("original amount", row.get("amount", ""))
        maturity = row.get("maturity", row.get("maturity date", ""))
        status_cell = row.get("status", "")
        notes = row.get("notes", "")

        # For OPEN mortgages the dated/maturity live inside Notes column
        dated = _extract_dated_from_notes(notes)
        if not maturity:
            maturity = _extract_maturity_from_notes(notes)

        status = (
            "POTENTIALLY OPEN"
            if (is_potentially or "POTENTIALLY" in status_cell.upper())
            else "OPEN"
        )

        mortgages.append({
            "OpenMortgageInstrument":        inst,
            "OpenMortgageRecordedDate":      rec_date,
            "OpenMortgageDated":             dated,
            "OpenMortgageDocumentType":      "MORTGAGE",
            "OpenMortgageBorrowerMortgagor": mortgagor,
            "OpenMortgageLenderMortgagee":   mortgagee,
            "OpenMortgageAmount":            _clean_consideration(amount_raw) if amount_raw else "",
            "OpenMortgageBookPage":          "",
            "OpenMortgageTrustee1":          "",
            "OpenMortgageTrustee2":          "",
            "OpenMortgageComments":          notes[:300] if notes else "",
            "OpenMortgageStatus":            status,
            "OpenMortgageMaturityDate":      maturity,
        })

    return mortgages


# ── Title Notes wide-table vesting/chain parser ───────────────────────────────

def _parse_vesting_from_title(title_text: str) -> list[dict]:
    """
    Parse Chain of Title deed table from Title_Examination_Notes.md.

    Column format:
      | # | Recording Date | Instr. # | Type | Grantor(s) | Grantee(s) | Notes |
    """
    if not title_text:
        return []

    chain_m = re.search(r"##\s+CHAIN OF TITLE\b", title_text, re.IGNORECASE)
    if not chain_m:
        return []

    remaining = title_text[chain_m.start():]
    next_h2 = re.search(r"\n##\s+(?!#)", remaining[5:])
    chain_section = remaining[: next_h2.start() + 5] if next_h2 else remaining

    chain: list[dict] = []
    seen: set = set()
    current_headers: list[str] = []
    in_excluded = False

    for line in chain_section.splitlines():
        stripped = line.strip()

        # Track "Examined and Excluded" sub-tables — skip those rows
        if re.search(r"examined\s+and\s+excluded", stripped, re.IGNORECASE) and not stripped.startswith("|"):
            in_excluded = True
        if stripped == "---":
            in_excluded = False

        if not stripped.startswith("|"):
            continue
        if re.match(r"^\|[\s\-|]+\|$", stripped):
            continue

        cells = [re.sub(r"\*+", "", c).strip() for c in stripped.split("|")]
        if cells and not cells[0]:
            cells = cells[1:]
        if cells and not cells[-1]:
            cells = cells[:-1]
        if not cells:
            continue

        # Detect header row: look for "recording date" among cells
        if not current_headers and any("recording date" in c.lower() for c in cells):
            current_headers = [c.lower() for c in cells]
            in_excluded = False
            continue

        if not current_headers:
            continue

        row = {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(current_headers)}

        inst = row.get("instr. #", row.get("instr#", row.get("instrument", ""))).strip()
        if not inst or not re.match(r"^\d{5,}", inst):
            continue
        if inst in seen:
            continue

        doc_type = row.get("type", "").strip().upper()
        if not any(kw in doc_type for kw in ("DEED", "QCD", "CONV", "GRANT", "TRUST")):
            continue

        if in_excluded:
            continue
        notes = row.get("notes", "")
        if re.search(r"examined\s+and\s+excluded|different\s+propert", notes, re.IGNORECASE):
            continue

        seen.add(inst)

        grantor = row.get("grantor(s)", row.get("grantor", ""))
        grantee = row.get("grantee(s)", row.get("grantee", ""))
        rec_date = row.get("recording date", row.get("rec. date", ""))
        consideration = _extract_dollar_amount(notes)
        # Direct phrase search against grantee + notes (no instrument-anchor needed)
        search_text = (grantee + " " + notes).lower()
        manner = ""
        for phrase in (
            "husband and wife", "tenants by the entireties", "joint tenants",
            "tenants in common", "as trustees", "living trust",
            "revocable trust", "single", "unmarried",
        ):
            if phrase in search_text:
                manner = phrase.title()
                break

        chain.append({
            "VestingInstrument":          inst,
            "VestingRecordedDate":        rec_date,
            "VestingDated":               "",
            "VestingDeedType":            doc_type,
            "VestingGrantor":             grantor,
            "VestedAsGrantee":            grantee,
            "VestingBookPage":            "",
            "VestingConsiderationAmount": consideration,
            "VestingMannerOfHolding":     manner,
            "VestingComments":            notes[:300] if notes else "",
        })

    return chain


# ── Open judgments/liens extraction ──────────────────────────────────────────

def _parse_open_judgments(raw_text: str, sections: dict) -> list[dict]:
    """Extract OPEN/POTENTIALLY OPEN judgments, liens, lis pendens."""
    judgments: list[dict] = []
    seen: set = set()

    for m in _DEED_BLOCK_RE.finditer(raw_text):
        status = m.group("status").strip().upper()
        if not ("OPEN" in status or "POTENTIALLY" in status or "ACTIVE" in status):
            continue
        doc_type = m.group("type").strip().upper()
        if not any(kw in doc_type for kw in (
            "JUDGMENT", "LIEN", "LIS PENDENS", "TAX LIEN", "IRS", "UCC",
            "NOTICE OF COMMENCEMENT", "NOC", "ASSESSMENT",
        )):
            continue
        inst = m.group("inst").strip()
        if inst in seen:
            continue
        seen.add(inst)
        parties_raw = m.group("parties").strip()
        plaintiff, defendant = _split_parties(parties_raw)
        judgments.append({
            "OpenJudgmentsInstrument":          inst,
            "OpenJudgmentsDateRecorded":        m.group("date").strip(),
            "OpenJudgmentsDateEntered":         "",
            "OpenJudgmentsType":                doc_type,
            "OpenJudgmentsLienHolderPlaintiff": plaintiff,
            "OpenJudgmentsBorrowerDefendant":   defendant,
            "OpenJudgmentsAmount":              _extract_dollar_amount(parties_raw),
            "OpenJudgmentsBookPage":            "",
            "OpenJudgmentsComments":            "",
            "OpenJudgmentsCaseNumber":          _extract_case_number(raw_text, inst),
            "OpenJudgmentsCourtName":           _extract_court_name(raw_text, inst),
            "OpenJudgmentsStatus":              "POTENTIALLY OPEN" if "POTENTIALLY" in status else "OPEN",
        })

    return judgments


def _extract_case_number(text: str, inst: str) -> str:
    ctx = _context_around(text, inst, 400)
    m = re.search(r"case\s+(?:no\.?|#)\s*([\w\-/]+)", ctx, re.IGNORECASE)
    return m.group(1).strip() if m else ""


def _extract_court_name(text: str, inst: str) -> str:
    ctx = _context_around(text, inst, 400)
    for phrase in (
        "circuit court", "district court", "county court",
        "superior court", "court of common pleas",
    ):
        if phrase.lower() in ctx.lower():
            return phrase.title()
    return ""


# ── Tax field extraction ──────────────────────────────────────────────────────

_FL_TAX_SCHEDULE = (
    "November (4% discount), December (3% discount), "
    "January (2% discount), February (1% discount), March (full payment). "
    "Delinquent after April 1."
)

_TAX_KEY_MAP: dict[str, str] = {
    # ── TaxLookupResult.to_json_dict() keys (new pipeline format) ──────────
    "tax_year":             "TaxYear",
    "annual_total":         "TaxAmount",      # TaxLookupResult field: float
    "status":               "TaxStatus",      # "TAX_SUCCESS" / "TAX_FAILED" etc.
    "apn":                  "TaxAPNAccount",
    "property_address":     "TaxPropertyAddress",
    "source_url":           "TaxSource",
    "captured_at":          "TaxCapturedAt",
    # ── Old project format (tax_information block) ──────────────────────────
    "annual_tax_amount":    "TaxAmount",      # float like 30152.65
    "annual_tax_estimated": "TaxAmount",      # formatted string "$30,152.65"
    "annual_tax":           "TaxAmount",
    "tax_status":           "TaxStatus",      # explicit tax_status override
    "payment_status":       "TaxStatus",      # "PAID" / "DUE" / "DELINQUENT"
    # ── Flat value fields (used by some adapters / tax_pb_live.json cache) ─
    "net_taxable_value":    "TaxBuildingValue",
    "improvement_value":    "TaxBuildingValue",
    "just_value":           "TaxTotalValue",
    "land_value":           "TaxLandValue",
    "folio":                "TaxAPNAccount",
    "parcel_id":            "TaxAPNAccount",
    "parcel_number":        "TaxAPNAccount",
    "tax_address":          "TaxPropertyAddress",
    "installment_status":   "TaxInstallmentStatus",
    "source":               "TaxSource",
    "millage":              "TaxMillage",
    "city":                 "TaxCity",
    "county":               "TaxMunicipalityCounty",
}


def _county_slug_to_display(slug: str) -> str:
    """Convert 'fl_palm_beach' → 'Palm Beach', 'broward' → 'Broward', etc."""
    s = slug.lower().removeprefix("fl_").replace("_", " ").strip()
    return s.title()


def _build_tax_fields(tax_json: dict, county: str = "") -> dict:
    out: dict = {}
    for src_key, nat_key in _TAX_KEY_MAP.items():
        val = tax_json.get(src_key)
        # Skip nested dicts — handled separately below
        if val is not None and not isinstance(val, (dict, list)) and nat_key not in out:
            out[nat_key] = str(val)

    # ── Handle TaxLookupResult.assessed_value nested dict ──────────────────
    # Shape varies by county adapter:
    #   Palm Beach PBCPAO:  {"ad_valorem": int, "non_ad_valorem": int}
    #   Generic adapters:   {"land": float, "improvements": float,
    #                        "net_taxable": float, "just_value": float,
    #                        "total_market": float, ...}
    assessed_dict = tax_json.get("assessed_value")
    if isinstance(assessed_dict, dict):
        land = assessed_dict.get("land")
        impr = assessed_dict.get("improvements") or assessed_dict.get("improvement")
        net  = assessed_dict.get("net_taxable") or assessed_dict.get("taxable_value")
        just = assessed_dict.get("just_value") or assessed_dict.get("total_market")
        if land and "TaxLandValue" not in out:
            out["TaxLandValue"] = str(land)
        if impr and "TaxBuildingValue" not in out:
            out["TaxBuildingValue"] = str(impr)
        elif net and "TaxBuildingValue" not in out:
            out["TaxBuildingValue"] = str(net)
        if just and "TaxTotalValue" not in out:
            out["TaxTotalValue"] = str(just)
            out.setdefault("TaxTotalValue2", str(just))

    # ── Flat integer value fields from tax_pb_live.json cache ──────────────
    # The cache stores just_value / land_value / improvement_value as flat ints
    # (written by _try_palm_beach_tax_fallback).  Map them to display fields.
    for _src, _dst in (
        ("just_value",        "TaxTotalValue"),
        ("land_value",        "TaxLandValue"),
        ("improvement_value", "TaxBuildingValue"),
        ("net_taxable_value", "TaxBuildingValue"),
    ):
        _v = tax_json.get(_src)
        if _v and int(float(_v)) > 0 and _dst not in out:
            out[_dst] = str(_v)

    # ── Fallback aliases for older/flat schemas ─────────────────────────────
    out.setdefault("TaxYear", str(tax_json.get("year", "")))
    out.setdefault("TaxAPNAccount", tax_json.get("parcel_number", tax_json.get("apn", "")))
    out.setdefault("TaxPropertyAddress", tax_json.get("property_address", ""))
    out.setdefault("TaxInstallmentStatus", tax_json.get("installment_plan", ""))
    out.setdefault("TaxSource", tax_json.get("source_url", ""))
    out.setdefault("TaxCapturedAt", tax_json.get("captured_at", ""))
    out.setdefault("TaxAssessedYear", out.get("TaxYear", ""))

    # Old project format: fetch_success=true → treat as verified
    if tax_json.get("fetch_success") and out.get("TaxStatus", "") in ("", "skipped"):
        out["TaxStatus"] = "verified"

    # Normalize verbose status codes → display-friendly strings
    _status_display = {
        "TAX_SUCCESS":    "verified",
        "success":        "verified",
        "TAX_PARTIAL":    "partial",
        "TAX_NO_RESULTS": "no results",
        "TAX_NO_RUNNER":  "no adapter",
        "TAX_FAILED":     "failed",
    }
    raw_status = out.get("TaxStatus", "")
    if raw_status in _status_display:
        out["TaxStatus"] = _status_display[raw_status]

    # Format TaxAmount as "$X,XXX.XX" for readable display (PHP $toFloat strips $ and commas)
    raw_amt = out.get("TaxAmount", "")
    if raw_amt and str(raw_amt) not in ("", "None", "0", "0.0"):
        try:
            out["TaxAmount"] = f"${float(str(raw_amt).replace('$', '').replace(',', '')):,.2f}"
        except (ValueError, TypeError):
            pass  # leave as-is; PHP $toFloat will still extract a numeric

    # Format assessed-value fields as "$X,XXX" (whole-dollar display)
    for _k in ("TaxLandValue", "TaxBuildingValue", "TaxTotalValue", "TaxTotalValue2"):
        _v = out.get(_k, "")
        if _v and str(_v) not in ("", "None", "0", "0.0"):
            try:
                out[_k] = f"${float(str(_v).replace('$', '').replace(',', '')):,.0f}"
            except (ValueError, TypeError):
                pass

    # Clean county slug → display name
    raw_county = out.get("TaxMunicipalityCounty", "")
    if raw_county and ("_" in raw_county or raw_county == raw_county.lower()):
        out["TaxMunicipalityCounty"] = _county_slug_to_display(raw_county)
    if not out.get("TaxMunicipalityCounty") and county:
        out["TaxMunicipalityCounty"] = _county_slug_to_display(county)

    is_fl = (
        tax_json.get("state", "FL").upper() == "FL"
        or county.lower().startswith("fl_")
        or county.lower() == "fl"
    )
    if is_fl:
        out["TaxPaymentSchedule"] = _FL_TAX_SCHEDULE
        # PHP $toDate("March 31 (final)") fails strtotime — send without parenthetical
        out["TaxDueDate"] = "March 31"
        # PHP $toDate("April 1") → strtotime → "2026-04-01" → "4/1/26, 12:00 AM" in form
        out["TaxDelinquentDate"] = "April 1"
        out.setdefault("TaxType", "Ad Valorem")
    else:
        out["TaxPaymentSchedule"] = tax_json.get("payment_schedule", "")
        out["TaxDueDate"] = tax_json.get("due_date", "")
        out["TaxDelinquentDate"] = tax_json.get("delinquent_date", "")

    return out


# ── Palm Beach live tax fallback ─────────────────────────────────────────────

def _pbcpao_requests_only(pcn_clean: str) -> dict:
    """Stdlib+requests-only fallback for PBCPAO tax lookup (no curl_cffi or bs4 needed).

    Uses plain requests + regex to extract the TOTAL TAX row from the PBCPAO
    property-details page.  Called when the main PalmBeachPBCPAO adapter cannot
    be imported (curl_cffi / beautifulsoup4 not yet installed).
    """
    try:
        import requests as _req
        pcn_digits = re.sub(r"[^0-9]", "", pcn_clean)
        url = f"https://www.pbcpao.gov/Property/Details/?parcelId={pcn_digits}"
        try:
            resp = _req.get(
                url, timeout=30,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
        except Exception as _net_exc:
            _log.warning("PBCPAO GET failed for APN %r: %s: %s", pcn_clean, type(_net_exc).__name__, _net_exc)
            return {}

        _log.info("PBCPAO response: HTTP %s, %d chars for APN %r", resp.status_code, len(resp.text), pcn_clean)
        if resp.status_code != 200:
            _log.warning("PBCPAO requests-only fallback: HTTP %s for APN %s", resp.status_code, pcn_clean)
            return {}
        html = resp.text

        # ── Approach 1: broad patterns that tolerate nested HTML, extra attrs,
        # whitespace — does NOT require "Tax Year" to be the sole text in a cell.
        # "Tax Year" appears somewhere in the header row; then a year number follows
        # anywhere within ~200 chars.  "TOTAL TAX" is followed within ~300 chars
        # by the first certified-tax dollar amount.
        year_m = re.search(r"Tax Year[^0-9]{0,200}?(\d{4})", html, re.IGNORECASE | re.DOTALL)
        total_m = re.search(r"TOTAL\s+TAX[^$\d]{0,300}?\$?([\d]{1,3}(?:,[\d]{3})+|\d{4,})", html, re.IGNORECASE | re.DOTALL)

        if year_m and total_m:
            year = year_m.group(1).strip()
            total_raw = total_m.group(1).replace(",", "")
            try:
                total_float = float(total_raw)
                _log.info("PBCPAO requests-only: year=%s total=$%.2f for APN %r", year, total_float, pcn_clean)
                return {
                    "TaxYear":         year,
                    "TaxAssessedYear": year,
                    "TaxAmount":       f"${total_float:,.2f}",
                    "TaxType":         "Ad Valorem",
                    "TaxStatus":       "verified",
                    "TaxSource":       url,
                }
            except ValueError:
                pass

        _log.warning(
            "PBCPAO requests-only fallback: tax table not found in HTML for APN %r "
            "(year_match=%s, total_match=%s)",
            pcn_clean, bool(year_m), bool(total_m),
        )
        return {}
    except Exception as _exc:  # noqa: BLE001
        _log.warning("PBCPAO requests-only fallback error for APN %r: %s: %s", pcn_clean, type(_exc).__name__, _exc)
        return {}


def _try_palm_beach_tax_fallback(apn: str, output_dir: str = "") -> dict:
    """
    Attempt a live PBCPAO lookup to fill TaxYear/TaxAmount/TaxTotalValue etc.
    when the pipeline's tax phase was skipped (apn_missing at run time).

    On success, saves a cache file (tax_pb_live.json) in the output_dir so
    subsequent callback calls skip the live HTTP round-trip.

    Returns a dict of NAT payload keys on success; empty dict on any failure.
    """
    try:
        from titlepro.property_appraiser.counties.palm_beach_pbcpao import PalmBeachPBCPAO  # noqa: PLC0415

        cfg: dict = {}
        pa = PalmBeachPBCPAO(cfg)
        out: dict = {}
        raw_tax_info: dict = {}

        # ── Tax amounts & year from certified-tax endpoint ──────────────────
        tax_raw = pa.lookup_certified_tax(apn)
        if isinstance(tax_raw, dict) and tax_raw.get("status") in ("TAX_SUCCESS", "success", "ok"):
            year = str(tax_raw.get("tax_year", "")).strip()
            total = tax_raw.get("total_tax")
            if year and year != "0":
                out["TaxYear"] = year
                out["TaxAssessedYear"] = year
                raw_tax_info["tax_year"] = year
            if total is not None:
                try:
                    amt_float = float(total)
                    out["TaxAmount"] = f"${amt_float:,.2f}"
                    raw_tax_info["annual_tax_amount"] = amt_float
                except (ValueError, TypeError):
                    out["TaxAmount"] = str(total)
            if tax_raw.get("source_url"):
                out["TaxSource"] = tax_raw["source_url"]
                raw_tax_info["source"] = tax_raw["source_url"]
            out["TaxType"] = "Ad Valorem"
            out["TaxStatus"] = "verified"
            raw_tax_info["apn"] = apn
            raw_tax_info["status"] = "verified"

        # ── Assessed values from property-detail endpoint ──────────────────
        pa_result = pa.lookup_by_apn(apn)
        if hasattr(pa_result, "status") and pa_result.status in ("PA_SUCCESS", "success", "ok"):
            just_val = getattr(pa_result, "just_value", None)
            assessed_val = getattr(pa_result, "assessed_value", None)
            land_val = getattr(pa_result, "land_value", None)
            bldg_val = getattr(pa_result, "improvement_value", None)

            def _fmt(v: object) -> str:
                try:
                    return f"${int(float(v)):,}"
                except (ValueError, TypeError):
                    return str(v)

            if just_val:
                out["TaxTotalValue"] = _fmt(just_val)
                out["TaxTotalValue2"] = _fmt(just_val)
                raw_tax_info["just_value"] = just_val
            if land_val:
                out["TaxLandValue"] = _fmt(land_val)
                raw_tax_info["land_value"] = land_val
            if bldg_val:
                out["TaxBuildingValue"] = _fmt(bldg_val)
                raw_tax_info["net_taxable_value"] = bldg_val
            elif assessed_val and "TaxBuildingValue" not in out:
                out["TaxBuildingValue"] = _fmt(assessed_val)
                raw_tax_info["assessed_value"] = assessed_val
            # Always record what we tried so the cache doesn't cause re-fetching
            raw_tax_info["just_value_checked"] = True
            raw_tax_info["just_value"] = just_val or 0
            raw_tax_info["land_value"] = land_val or 0
            raw_tax_info["improvement_value"] = bldg_val or 0

        # Cache result so subsequent callback calls skip the live HTTP call
        if out and output_dir:
            try:
                cache_path = Path(output_dir) / "tax_pb_live.json"
                with open(cache_path, "w", encoding="utf-8") as _f:
                    import json as _json
                    _json.dump({"fetch_success": True, "tax_information": raw_tax_info}, _f, indent=2)
            except Exception:  # noqa: BLE001
                pass

        return out
    except ImportError as _imp_exc:
        # curl_cffi or beautifulsoup4 not installed — try the pure-requests fallback
        _log.warning(
            "PalmBeachPBCPAO import failed (%s); trying requests-only fallback for APN %r",
            _imp_exc, apn,
        )
        fallback = _pbcpao_requests_only(apn)
        if fallback and output_dir:
            try:
                raw_tax_info = {
                    "tax_year": fallback.get("TaxYear", ""),
                    "annual_tax_amount": float(
                        fallback.get("TaxAmount", "0").replace("$", "").replace(",", "")
                    ),
                    "status": "verified",
                    "apn": apn,
                }
                cache_path = Path(output_dir) / "tax_pb_live.json"
                with open(cache_path, "w", encoding="utf-8") as _f:
                    import json as _json
                    _json.dump({"fetch_success": True, "tax_information": raw_tax_info}, _f, indent=2)
            except Exception:  # noqa: BLE001
                pass
        return fallback
    except Exception as _exc:  # noqa: BLE001
        _log.warning("Palm Beach tax fallback failed for APN %r: %s: %s", apn, type(_exc).__name__, _exc)
        return {}


# ── Hillsborough live PA fallback ────────────────────────────────────────────

def _try_hillsborough_tax_fallback(apn: str, output_dir: str = "") -> dict:
    """
    Attempt a live HCPA Property Appraiser lookup to fill TaxTotalValue /
    TaxBuildingValue when the pipeline's tax phase was skipped (apn_missing).

    TaxYear / TaxAssessedYear are always set from the Florida tax calendar
    (prior calendar year) regardless of whether the PA call succeeds.

    On success, caches result to tax_z_hcpa_live.json (sorts after
    tax_lookup_status.json so it overwrites 'skipped' on subsequent calls).

    Returns a dict of NAT payload keys; always returns at least TaxYear.
    """
    import datetime as _dt
    tax_year = str(_dt.datetime.now().year - 1)

    base: dict = {
        "TaxYear":          tax_year,
        "TaxAssessedYear":  tax_year,
        "TaxType":          "Ad Valorem",
        "TaxPaymentSchedule": _FL_TAX_SCHEDULE,
        "TaxDueDate":       "March 31",
        "TaxDelinquentDate": "April 1",
    }

    try:
        from titlepro.property_appraiser.counties.hillsborough_hcpa import HillsboroughHCPA  # noqa: PLC0415

        pa = HillsboroughHCPA({})
        pa_result = pa.lookup_by_apn(apn)

        out = dict(base)

        if getattr(pa_result, "status", "") == "PA_SUCCESS":
            def _fmt(v: object) -> str:
                try:
                    return f"${int(float(str(v))):,}"
                except (ValueError, TypeError):
                    return str(v) if v else ""

            if pa_result.just_value:
                out["TaxTotalValue"] = _fmt(pa_result.just_value)
                out["TaxTotalValue2"] = _fmt(pa_result.just_value)
            if pa_result.improvement_value:
                out["TaxBuildingValue"] = _fmt(pa_result.improvement_value)
            # PA short legal description as last-resort LegalDescription source
            if pa_result.legal_description:
                out["_pa_legal_description"] = pa_result.legal_description
            out["TaxStatus"] = "partial"

            # Cache so subsequent Resend calls skip the live HTTP call.
            # Named tax_z_* so it sorts AFTER tax_lookup_status.json and wins.
            # Only store non-zero value fields to avoid _TAX_KEY_MAP mapping 0 as "0".
            if output_dir:
                try:
                    raw_info: dict = {
                        "tax_year": tax_year,
                        "status":   "partial",
                        "apn":      apn,
                        "county":   "fl_hillsborough",
                    }
                    if pa_result.just_value:
                        raw_info["just_value"] = pa_result.just_value
                    if pa_result.improvement_value:
                        raw_info["improvement_value"] = pa_result.improvement_value
                    if pa_result.land_value:
                        raw_info["land_value"] = pa_result.land_value
                    cache_path = Path(output_dir) / "tax_z_hcpa_live.json"
                    with open(cache_path, "w", encoding="utf-8") as _f:
                        json.dump(
                            {"fetch_success": True, "tax_information": raw_info},
                            _f, indent=2,
                        )
                except Exception:
                    pass
        else:
            out["TaxStatus"] = "skipped"

        # ── Grant Street Tax Collector — annual tax bill ───────────────────
        # TaxAmount (annual_total) is not available from the PA; it requires
        # the Tax Collector portal (county-taxes.net/hillsborough).  The
        # grant_street_http adapter already has Hillsborough configured.
        # Hillsborough Tax Collector's Algolia index uses the 'A'-prefixed
        # digits-only folio (e.g. "115146-0000" → "A1151460000").
        try:
            from titlepro.tax.grant_street_http import lookup_grant_street_tax  # noqa: PLC0415

            hs_folio_digits = re.sub(r"[^0-9]", "", apn)
            hs_tc_apn = f"A{hs_folio_digits}"
            gs_result = lookup_grant_street_tax(
                hs_tc_apn,
                "hillsborough",
                Path(output_dir) if output_dir else Path("."),
                safe_owner="tax_gs",
            )
            if gs_result.status in ("TAX_SUCCESS", "TAX_PARTIAL") and gs_result.annual_total:
                out["TaxAmount"] = f"${gs_result.annual_total:,.2f}"
                out["TaxStatus"] = "partial"
                # Persist annual_total into the cache so subsequent Resend
                # calls read it from tax_z_hcpa_live.json via _TAX_KEY_MAP
                # without another Grant Street HTTP round-trip.
                if output_dir:
                    try:
                        cache_path = Path(output_dir) / "tax_z_hcpa_live.json"
                        if cache_path.exists():
                            with open(cache_path, encoding="utf-8") as _cf:
                                cached = json.load(_cf)
                        else:
                            cached = {"fetch_success": True, "tax_information": {}}
                        cached.setdefault("tax_information", {})
                        cached["tax_information"]["annual_total"] = gs_result.annual_total
                        with open(cache_path, "w", encoding="utf-8") as _cf:
                            json.dump(cached, _cf, indent=2)
                    except Exception:
                        pass
        except Exception as _gs_exc:
            _log.warning("Hillsborough Grant Street tax lookup failed: %s: %s", type(_gs_exc).__name__, _gs_exc)

        return out

    except ImportError as _exc:
        _log.warning("HillsboroughHCPA import failed (%s); returning base tax fields", _exc)
        return {**base, "TaxStatus": "skipped"}
    except Exception as _exc:
        _log.warning(
            "Hillsborough PA tax fallback failed for APN %r: %s: %s",
            apn, type(_exc).__name__, _exc,
        )
        return {**base, "TaxStatus": "skipped"}


# ── APN extraction from report text ──────────────────────────────────────────

def _extract_apn_from_text(text: str) -> str:
    """Extract APN/Folio/Parcel number from report text."""
    patterns = [
        r"\*\*APN[:/\s]*\*\*\s*([\d\-]+)",
        r"APN[:/\s]+\**([\d\-]+)\**",
        # "Folio No.: 115146-0000" and "**Folio No.:** 115146-0000" formats
        r"\*{0,2}Folio\s+No\.?\*{0,2}\s*[:\s]+([0-9][0-9\-]{5,28})",
        r"(?:APN|Folio|Parcel(?:\s+(?:ID|Number|No\.?))?)[:\s]+\**([0-9\-]{8,30})\**",
        r"folio\s*(?:no\.?|number)?\s*[:\s]+\**([0-9\-]{8,30})\**",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = m.group(1).strip().rstrip(".")
            if len(val) >= 8:
                return val
    return ""


# ── Title Notes flat-field extraction ────────────────────────────────────────

def _extract_flat_fields_from_title(title_text: str, request_data: dict) -> dict:
    """Extract flat property fields from Title Examination Notes or RAW report header."""
    out: dict = {}

    # Address — look for explicit label, require leading digits
    addr = ""
    for pattern in (
        r"(?:Subject Property Address|Property Address Hint|Property Address|Subject Address)[:\s]+(\d+[^\n]+)",
        r"\*\*(?:Subject Property Address|Property Address[^*]*)\*\*[:\s]+(\d+[^\n]+)",
    ):
        addr = _first_match(pattern, title_text)
        if addr:
            break

    # Truncate address at the end of the ZIP code (strips trailing sentences)
    if addr:
        addr = re.sub(r"(\b\d{5}(?:-\d{4})?)\b[\s.,;].*$", r"\1", addr, flags=re.DOTALL).strip()
        # Also strip anything after a period-then-space followed by capital letter (sentence boundary)
        addr = re.sub(r"\.\s+[A-Z].*$", "", addr).strip()
        addr = addr.rstrip(".")

    # Fall back to request_data address if nothing usable found
    if not addr or len(addr) < 8:
        addr = request_data.get("address", "")
        city = request_data.get("city", "")
        state = "FL"
        if addr and city:
            addr = f"{addr}, {city}, {state}"

    out["OfficialPropertyAddress"] = addr.strip()

    # City — parse from address string
    city_m = re.search(r",\s*([A-Za-z][A-Za-z\s]+?)(?:,\s*FL|\s+FL\b)", addr, re.IGNORECASE)
    if city_m:
        out["City"] = city_m.group(1).strip()
    else:
        out["City"] = request_data.get("city", "")

    out["State"] = "FL"
    county_raw = request_data.get("county", "")
    out["County"] = county_raw.replace("fl_", "").replace("_", " ").title()

    return out


# ── Legal description extraction ──────────────────────────────────────────────

def _extract_legal_description(raw_text: str, title_text: str) -> str:
    """
    Extract verbatim legal description from the report.
    Priority order:
      1. RAW report ### Legal Description blockquote (verbatim deed language)
      2. Label + LOT pattern in either report
      3. LOT N, ... PLAT BOOK ... sentence pattern (verbatim FL legal)
      4. Hard-capped fallback (never returns the whole report)
    """
    # Pattern 1: blockquote in ### C. Legal Description section of RAW report
    pat_blockquote = re.compile(
        r"###[^\n]*Legal Description[^\n]*\n"
        r"(?:[^\n]*\n)*?"
        r">\s*(LOT\s+[^>]+?)(?=\n\n|\n###|\n##|\Z)",
        re.IGNORECASE | re.DOTALL,
    )

    # Pattern 2: "Legal Description:" label then LOT sentence
    pat_label = re.compile(
        r"(?:Legal Description|Exhibit A)[:\s]*\n+\s*(LOT\s+[^\n]+(?:\n(?!\n)[^\n]+)*)",
        re.IGNORECASE,
    )

    # Pattern 3: verbatim FL legal — "LOT N, NAME ... PLAT BOOK ... INCLUSIVE ... FLORIDA."
    pat_lot_verbatim = re.compile(
        r"(LOT\s+\d+[^.\n]{10,300}"
        r"(?:PLAT BOOK|OFFICIAL RECORDS|PUBLIC RECORDS)[^.]{0,300}"
        r"(?:INCLUSIVE|COUNTY,\s*FLORIDA)[^.]{0,100}\.)",
        re.IGNORECASE,
    )

    # Pattern 4: any LOT sentence with PLAT BOOK (less strict)
    pat_lot = re.compile(
        r"(LOT\s+\d+[^.\n]{10,200}(?:PLAT BOOK|OFFICIAL RECORDS|PUBLIC RECORDS)[^.]{0,200}\.)",
        re.IGNORECASE,
    )

    # Priority 1: RAW report blockquote (verbatim legal description)
    if raw_text:
        m = pat_blockquote.search(raw_text)
        if m:
            desc = m.group(1).strip()
            if len(desc) > 20:
                return re.sub(r"\n{3,}", "\n\n", desc).strip()

    # Priority 2: label + LOT in title_text, then raw_text
    for text in (title_text, raw_text):
        if not text:
            continue
        m = pat_label.search(text)
        if m:
            desc = m.group(1).strip()
            desc = re.sub(r"\|[^|\n]*\|", "", desc)
            desc = re.sub(r"\n{3,}", "\n\n", desc).strip()
            if 20 < len(desc) < 800:
                return desc

    # Priority 3: verbatim FL LOT sentence with INCLUSIVE / COUNTY, FLORIDA
    for text in (raw_text, title_text):
        if not text:
            continue
        m = pat_lot_verbatim.search(text)
        if m:
            return m.group(1).strip()

    # Priority 4: any LOT + PLAT BOOK sentence
    for text in (raw_text, title_text):
        if not text:
            continue
        m = pat_lot.search(text)
        if m:
            return m.group(1).strip()

    # Priority 5: "Phase 2 classification" / "brief description" in Title Notes
    # Matches e.g. "Subject parcel per Phase 2 classification: East 10 feet of Lot 4 ..."
    pat_phase2 = re.compile(
        r"(?:Phase 2 classification|brief description)[:\s]+([^.]{20,400})",
        re.IGNORECASE,
    )
    for text in (title_text, raw_text):
        if not text:
            continue
        m = pat_phase2.search(text)
        if m:
            desc = m.group(1).strip().rstrip(".")
            if 20 < len(desc) < 600:
                return desc

    # Fallback: generous label match, hard-capped at 800 chars
    pat_fallback = re.compile(
        r"(?:Legal Description|Exhibit A)[:\s]*\n+(.*?)(?=\n##|\n###|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    for text in (title_text, raw_text):
        if not text:
            continue
        m = pat_fallback.search(text)
        if m:
            desc = m.group(1).strip()
            if len(desc) > 800:
                lot_m = re.search(r"(LOT\s+\d+[^.]{10,500}\.)", desc, re.IGNORECASE)
                if lot_m:
                    return lot_m.group(1).strip()
                return desc[:800].strip()
            desc = re.sub(r"\|.*?\|", "", desc)
            desc = re.sub(r"\n{3,}", "\n\n", desc).strip()
            if len(desc) > 20:
                return desc

    return ""


# ── Main public function ──────────────────────────────────────────────────────

def build_nat_payload(output_dir: str, request_data: dict) -> dict:
    """
    Read pipeline output files from output_dir and build the structured
    NAT callback payload.

    Args:
        output_dir: absolute path to the NAT job folder (e.g. .../NAT_300700/)
        request_data: original NAT request dict (for fallback address/county)

    Returns:
        dict — full payload ready for JSON serialization
    """
    output_path = Path(output_dir)

    # ── Read source files ──
    raw_path = output_path / "RAW_TWO_OWNER_SEARCH_EXAM.md"
    if not raw_path.exists():
        candidates = sorted(output_path.glob("RAW_TWO_OWNER_SEARCH_EXAM*.md"))
        raw_path = candidates[0] if candidates else raw_path
    raw_text = _read_file_safe(raw_path)

    title_path = output_path / "Title_Examination_Notes.md"
    if not title_path.exists():
        candidates = sorted(output_path.glob("Title_Examination_Notes*.md"))
        title_path = candidates[0] if candidates else title_path
    title_text = _read_file_safe(title_path)

    tax_json = _find_tax_json(str(output_path))

    # ── Split RAW into sections ──
    sections = _split_raw_sections(raw_text)

    # ── Assemble payload ──
    county_slug = request_data.get("county", "") or request_data.get("county_slug", "")

    flat = _extract_flat_fields_from_title(title_text or raw_text, request_data)

    # Extract these separately so we can reference them for fallbacks below.
    vesting_chain  = _parse_vesting_chain(raw_text, sections, title_text)
    open_mortgages = _parse_open_mortgages(raw_text, sections, title_text)
    open_judgments = _parse_open_judgments(raw_text, sections)

    # ── LegalDescription: deed MD first (verbatim with Plat Book ref), then text fallback ──
    # Priority 1: read the vesting deed's OCR markdown — the "to-wit: … TO HAVE AND TO
    # HOLD" extraction gives the most complete verbatim legal including Plat Book citation.
    # Priority 2: text-based extraction from RAW/Title Notes (includes Phase 2 brief desc).
    legal_desc = ""
    if vesting_chain:
        vesting_inst = vesting_chain[0].get("VestingInstrument", "")
        if vesting_inst:
            deed_md = output_path / f"{vesting_inst}_extracted.md"
            if deed_md.exists():
                legal_desc = _extract_legal_from_deed_md(deed_md)
    if not legal_desc:
        legal_desc = _extract_legal_description(raw_text, title_text)

    payload: dict[str, Any] = {
        "OfficialPropertyAddress": flat.get("OfficialPropertyAddress", ""),
        "City":                    flat.get("City", ""),
        "State":                   flat.get("State", "FL"),
        "County":                  flat.get("County", ""),

        # NAT PHP CureCallbackController._mapCureToExamFields() reads these exact key names
        # from data{} and maps them into the files_exam_receipt DB table.
        "VestingChainOfTitleInformation": vesting_chain,
        "OpenMortgageInformation":        open_mortgages,
        "OpenJudgmentsAndEncumbrances":   open_judgments,

        "LegalDescription": legal_desc,
    }

    # ── Tax fields ──
    payload.update(_build_tax_fields(tax_json, county_slug))

    # ── APN fallback: extract from report text when tax lookup was skipped ──
    if not payload.get("TaxAPNAccount"):
        apn = _extract_apn_from_text(title_text) or _extract_apn_from_text(raw_text)
        if apn:
            payload["TaxAPNAccount"] = apn

    # ── Palm Beach live tax fallback ─────────────────────────────────────────
    # When tax was skipped (apn_missing at pipeline time) but we now know the APN,
    # try a live PBCPAO lookup to populate TaxYear, TaxAmount, TaxTotalValue, etc.
    # On success the result is cached to tax_pb_live.json so subsequent calls
    # skip the live HTTP round-trip.
    if (
        re.search(r"palm.?beach", county_slug, re.IGNORECASE)
        and payload.get("TaxStatus") in ("skipped", "", None)
        and not payload.get("TaxYear")  # only attempt when TaxYear is still missing
        and payload.get("TaxAPNAccount")
    ):
        live_tax = _try_palm_beach_tax_fallback(payload["TaxAPNAccount"], str(output_path))
        if live_tax:
            for k, v in live_tax.items():
                payload[k] = v  # overwrite skipped values with live data

    # ── Hillsborough live PA fallback ─────────────────────────────────────────
    # When tax was skipped for Hillsborough, call the HCPA property-appraiser
    # adapter to populate TaxYear, TaxTotalValue, TaxBuildingValue, and the
    # Grant Street Tax Collector for TaxAmount (annual tax bill).
    # Fires when either TaxYear or TaxAmount is missing so a second Resend
    # after the HCPA-only cache still fetches TaxAmount via Grant Street.
    if (
        re.search(r"hillsborough", county_slug, re.IGNORECASE)
        and (not payload.get("TaxYear") or not payload.get("TaxAmount"))
        and payload.get("TaxAPNAccount")
    ):
        live_tax = _try_hillsborough_tax_fallback(payload["TaxAPNAccount"], str(output_path))
        pa_legal = live_tax.pop("_pa_legal_description", "")
        for k, v in live_tax.items():
            payload[k] = v  # overwrite skipped values with live data
        # Use PA short legal as last resort if LegalDescription still empty
        if pa_legal and not payload.get("LegalDescription"):
            payload["LegalDescription"] = pa_legal

    # Ensure all tax keys are present
    for key in (
        "TaxStatus", "TaxYear", "TaxAssessedYear", "TaxAmount", "TaxBuildingValue",
        "TaxTotalValue", "TaxAssessedValue", "TaxExemptions", "TaxAPNAccount",
        "TaxPropertyAddress", "TaxInstallmentStatus", "TaxSource", "TaxCapturedAt",
        "TaxPaymentSchedule", "TaxDueDate", "TaxDelinquentDate",
        "TaxMunicipalityCounty", "TaxComments",
    ):
        payload.setdefault(key, "")

    return payload
