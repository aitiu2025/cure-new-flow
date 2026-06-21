"""not_needed/ folder audit.

Broward's recorder search-index has a known bug (F9) where the
``document_type`` column holds the GRANTEE NAME rather than the actual
legal document type. The search-side filter therefore silently drops
documents whose grantee string doesn't match a doc-type whitelist —
in the 0522 ANAND v2 run, two satisfactions were swept into
``not_needed/`` even though they cleared open mortgages:

* ``111293535`` — SunTrust satisfaction of mortgage ``110509370``
  (Book 48462 Page 1412)
* ``116593405`` — TD Bank satisfaction of mortgage ``111249687``
  (Book 49410 Page 211, MIN 100341850025078449)

The downstream ``document_type_classifier`` (which would catch the
mis-labelled doctype) is only run on docs that survived the search-side
filter — it never sees ``not_needed/`` files.

This module:

  1. Walks ``<case_dir>/not_needed/*_extracted.md``
  2. Re-classifies each doc by content (``classify_document_type``)
  3. Cross-references SATISFACTION/RELEASE/DISCHARGE docs against
     the known mortgages by (a) document number, (b) Book/Page,
     (c) MIN, or (d) original principal amount
  4. Returns a list of ``RecoveredDocument`` records that the linker
     can splice into its working corpus, and a full ``LedgerEntry``
     list covering every not_needed doc (Tony directive #5 —
     examine and account for every indexed document)

This is an **HTTP-only** module — no Selenium, no Playwright. It
reads pre-extracted markdown that already lives on disk.

Public API:
    audit_not_needed(case_dir, known_mortgages, *, confidence_floor=0.75)
        -> NotNeededAuditResult
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from titlepro.verification.document_type_classifier import (
    classify_document_type,
)


# ---------------------------------------------------------------------------
# Regexes (verified against ANAND v2 ``not_needed/`` content)
# ---------------------------------------------------------------------------

# Captures Broward-style book/page citations:
#   "OR BK 48462 Page 1412"
#   "Book: OR 49410 Page: 211"
#   "Book 48462, Page 1412"
#   "Bk 49468 Pg 396"
BOOK_PAGE_RE = re.compile(
    r"(?:BOOK|BK)\s*:?\s*(?:OR\s+)?(\d{4,6})[,\s]+(?:PAGE|PG)\s*:?\s*(\d{1,5})",
    re.I,
)

# MERS MIN (Mortgage Identification Number) — always 18 digits but allow 15-20
# defensively. Distinct from doc numbers (8-12 digits).
MIN_RE = re.compile(r"MIN\s*[:#]?\s*(\d{15,20})", re.I)

# Document/Instrument number references inside the body text.
DOC_NUM_RE = re.compile(
    r"(?:Document\s*#|Instr#|CFN\s*#?)\s*(\d{9,12})",
    re.I,
)

# "original principal amount of $1,519,500.00" — anchored to that phrase
# so we don't false-match stray dollar amounts.
PRINCIPAL_RE = re.compile(
    r"original\s+principal\s+amount\s+of\s+\$?([\d,]+(?:\.\d{2})?)",
    re.I,
)

# Recorder banner end marker. Broward's banner is:
#   "CFN # XXX, OR BK YYYY Page ZZ, Page A of B, Recorded MM/DD/YYYY at ..."
# followed by "Deputy Clerk XXXX" or a newline. We use this to STRIP the
# satisfaction's own banner so the first Book/Page hit isn't its own
# recording slot — we want the MORTGAGE cite in the body.
BANNER_END_RE = re.compile(
    r"Recorded\s+\d{1,2}/\d{1,2}/\d{4}.*?(?:Deputy\s+Clerk[^\n]*|\n)",
    re.I | re.S,
)

# Classifications we can act on (link to a mortgage and flip its status).
RECOVERABLE_TYPES = {"SATISFACTION", "RELEASE", "DISCHARGE", "MODIFICATION"}

# Classifications worth showing in the ledger even though we don't splice
# them (subordinations and assignments don't change a mortgage's open status).
LEDGER_TYPES = RECOVERABLE_TYPES | {"SUBORDINATION", "ASSIGNMENT"}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class MortgageMetadata:
    """Lookup tuple for cross-referencing satisfactions to mortgages."""

    doc_number: str
    book: Optional[str] = None
    page: Optional[str] = None
    min_number: Optional[str] = None
    original_principal: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "doc_number": self.doc_number,
            "book": self.book,
            "page": self.page,
            "min_number": self.min_number,
            "original_principal": self.original_principal,
        }


@dataclass
class RecoveredDocument:
    """A not_needed doc that should be spliced back into the main corpus."""

    doc_number: str
    file_path: Path
    classified_type: str            # canonical type from classify_document_type
    classification_confidence: float
    target_mortgage_doc: str        # mortgage doc# the satisfaction clears
    match_method: str               # "doc_number" | "book_page" | "min" | "principal"
    match_evidence: str             # ~80-char window around the hit
    low_confidence: bool = False    # True if confidence < confidence_floor

    def to_dict(self) -> dict:
        return {
            "doc_number": self.doc_number,
            "file_path": str(self.file_path),
            "classified_type": self.classified_type,
            "classification_confidence": self.classification_confidence,
            "target_mortgage_doc": self.target_mortgage_doc,
            "match_method": self.match_method,
            "match_evidence": self.match_evidence,
            "low_confidence": self.low_confidence,
        }


@dataclass
class LedgerEntry:
    """Accounting record for every doc found in not_needed/."""

    doc_number: str
    classified_type: str
    confidence: float
    disposition: str  # see _DISPOSITIONS below
    reason: str

    def to_dict(self) -> dict:
        return {
            "doc_number": self.doc_number,
            "classified_type": self.classified_type,
            "confidence": self.confidence,
            "disposition": self.disposition,
            "reason": self.reason,
        }


# Valid disposition values (string enum-ish; documented for the reviewer).
_DISPOSITIONS = (
    "recovered",                 # spliced into the linker corpus
    "skipped_low_conf",          # would be recovered but below confidence floor
    "skipped_subordination",     # ledger-only (Tony directive #5)
    "skipped_assignment",        # ledger-only
    "unrecoverable",             # no cross-reference hit on any method
    "phantom_blocked",           # classified MORTGAGE but anti-phantom guard fired
    "non_target",                # classified as something we don't care about (e.g. DEED)
)


@dataclass
class NotNeededAuditResult:
    recovered: List[RecoveredDocument] = field(default_factory=list)
    ledger: List[LedgerEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "recovered": [r.to_dict() for r in self.recovered],
            "ledger": [e.to_dict() for e in self.ledger],
        }


class MissingMortgageMetadata(ValueError):
    """Raised when ``known_mortgages`` is empty or all entries have no
    cross-reference fields (book/page, MIN, principal). Silent disable
    is unacceptable per the synthesis plan's modification #2 — if the
    pipeline can't supply mortgage metadata, the operator must know.
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_banner(text: str) -> str:
    """Cut off everything from the start of ``text`` through the end of
    the recorder banner. The satisfaction's own Book/Page lives in the
    banner — if we don't strip it, the first Book/Page regex hit will
    be the satisfaction's own slot (e.g. SunTrust ``111293535`` has
    its own ``OR BK 49468 Page 396`` cite BEFORE the body references
    the mortgage at Book 48462 Page 1412).
    """
    if not text:
        return ""
    m = BANNER_END_RE.search(text)
    if not m:
        return text
    return text[m.end():]


def _norm_money(raw: str) -> str:
    """Normalize a dollar amount for equality comparison.

    "1,519,500.00" -> "1519500.00"
    "$1,519,500"    -> "1519500"
    """
    s = raw.replace("$", "").replace(",", "").strip()
    if "." not in s:
        return s
    head, _, tail = s.partition(".")
    return f"{head}.{tail[:2]}"


def _evidence_window(text: str, start: int, end: int, pad: int = 40) -> str:
    s = max(0, start - pad)
    e = min(len(text), end + pad)
    return text[s:e].replace("\n", " ").strip()


def _extract_doc_number_from_filename(path: Path) -> str:
    """``111293535_extracted.md`` -> ``111293535``."""
    stem = path.stem
    if stem.endswith("_extracted"):
        stem = stem[: -len("_extracted")]
    return stem


def _classify_with_audit(
    doc_number: str,
    text: str,
) -> Tuple[str, float, str]:
    """Wrapper around classify_document_type with a phantom-open guard.

    Returns (canonical_type, confidence, evidence). For MORTGAGE inference,
    we require:

      (a) source == "title_page" AND confidence >= 0.90, AND
      (b) NO SATISFACTION/RELEASE/MODIFICATION/SUBORDINATION keyword
          present in the body. If those keywords ARE present, the
          MORTGAGE inference is suspect (probably a satisfaction whose
          banner mentions "MORTGAGE" early), so we re-run scoped to
          the body. Returns "OTHER" / 0.0 if guard fires.
    """
    result = classify_document_type(doc_number, text, grantee_hint=None)

    if result.inferred_type != "MORTGAGE":
        return result.inferred_type, result.confidence, result.evidence

    # Phantom-open guard: a satisfaction can mention "MORTGAGE" in its
    # title page (e.g. "SATISFACTION OF MORTGAGE"). The classifier
    # should pick SATISFACTION because of the compound-pattern priority,
    # but defensive-second-pass here protects against unforeseen OCR
    # quirks.
    if result.source != "title_page" or result.confidence < 0.90:
        upper = text.upper()
        anti_signals = (
            "SATISFACTION OF MORTGAGE",
            "RELEASE OF MORTGAGE",
            "MODIFICATION OF MORTGAGE",
            "SUBORDINATION OF MORTGAGE",
            "ASSIGNMENT OF MORTGAGE",
            "FULLY PAID AND SATISFIED",
        )
        if any(sig in upper for sig in anti_signals):
            return "OTHER", 0.0, "phantom_blocked: anti-signal present"
    return result.inferred_type, result.confidence, result.evidence


def _find_match(
    text_no_banner: str,
    known_mortgages: Dict[str, MortgageMetadata],
) -> Optional[Tuple[str, str, str]]:
    """Try every match method in order of specificity.

    Returns (target_mortgage_doc, match_method, evidence) or None.
    """
    if not text_no_banner or not known_mortgages:
        return None

    # 1) Direct document-number reference (highest specificity).
    for m in DOC_NUM_RE.finditer(text_no_banner):
        candidate = m.group(1)
        if candidate in known_mortgages:
            return (
                candidate,
                "doc_number",
                _evidence_window(text_no_banner, m.start(), m.end()),
            )

    # 2) Book/Page (Broward indexing's strongest cross-ref).
    bp_hits = [
        (m.group(1), m.group(2), m.start(), m.end())
        for m in BOOK_PAGE_RE.finditer(text_no_banner)
    ]
    for book, page, s, e in bp_hits:
        for mtg in known_mortgages.values():
            if mtg.book == book and mtg.page == page:
                return (
                    mtg.doc_number,
                    "book_page",
                    _evidence_window(text_no_banner, s, e),
                )

    # 3) MERS MIN (TD Bank, modern lenders).
    for m in MIN_RE.finditer(text_no_banner):
        candidate_min = m.group(1)
        for mtg in known_mortgages.values():
            if mtg.min_number and mtg.min_number == candidate_min:
                return (
                    mtg.doc_number,
                    "min",
                    _evidence_window(text_no_banner, m.start(), m.end()),
                )

    # 4) Original principal amount (last resort — least specific).
    for m in PRINCIPAL_RE.finditer(text_no_banner):
        candidate_amt = _norm_money(m.group(1))
        for mtg in known_mortgages.values():
            if mtg.original_principal and _norm_money(mtg.original_principal) == candidate_amt:
                return (
                    mtg.doc_number,
                    "principal",
                    _evidence_window(text_no_banner, m.start(), m.end()),
                )

    return None


def _extract_one_mortgage_metadata(
    doc_number: str,
    text: str,
) -> MortgageMetadata:
    """Pull Book/Page/MIN/Principal out of a single mortgage's extracted
    markdown. Banner-skip is applied so the mortgage's OWN recording
    slot becomes the Book/Page anchor (which is exactly what later
    satisfactions cite).
    """
    md = MortgageMetadata(doc_number=doc_number)
    if not text:
        return md

    # Book/Page: the recorder banner is the canonical recording slot.
    # We want the BANNER hit here (NOT skip), because that's what
    # later satisfactions reference.
    bp = BOOK_PAGE_RE.search(text)
    if bp:
        md.book = bp.group(1)
        md.page = bp.group(2)

    # MIN: search the full text (often in the body, not banner).
    mm = MIN_RE.search(text)
    if mm:
        md.min_number = mm.group(1)

    # Principal: search the full text.
    pm = PRINCIPAL_RE.search(text)
    if pm:
        md.original_principal = _norm_money(pm.group(1))

    return md


def _extract_mortgage_metadata(
    docs: List[dict],
    extracted_texts: Dict[str, str],
) -> Dict[str, MortgageMetadata]:
    """Build {doc# -> MortgageMetadata} from already-known mortgages.

    Caller is responsible for passing in only docs that are mortgages
    (or candidates) — this helper is content-driven, so non-mortgages
    that happen to have Book/Page in their text won't hurt, but they
    also won't help.
    """
    out: Dict[str, MortgageMetadata] = {}
    for d in docs:
        # Doc-number key resolution mirrors released_mortgage_linker.
        num = (
            d.get("doc_number")
            or d.get("document_number")
            or d.get("instrument_number")
            or d.get("instrument")
            or d.get("number")
            or ""
        )
        num = str(num).strip()
        if not num:
            continue
        text = extracted_texts.get(num, "") or ""
        out[num] = _extract_one_mortgage_metadata(num, text)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def audit_not_needed(
    case_dir: Path,
    known_mortgages: Dict[str, MortgageMetadata],
    *,
    confidence_floor: float = 0.75,
) -> NotNeededAuditResult:
    """Audit ``case_dir/not_needed/*_extracted.md`` and return splice-list.

    Args:
        case_dir: top-level case folder (contains a ``not_needed/``
            sub-folder).
        known_mortgages: mapping of mortgage doc# -> MortgageMetadata.
            Built from already-known mortgages in the main corpus via
            ``_extract_mortgage_metadata``. Must not be empty.
        confidence_floor: minimum classification confidence to recover
            (default 0.75 = matches the ``body_keyword`` floor in
            ``document_type_classifier``).

    Returns:
        NotNeededAuditResult with two lists:
          * ``recovered``: docs to splice into ``classify_mortgages``
          * ``ledger``: full accounting of every doc in not_needed/
            (Tony directive #5 — examine every document)

    Raises:
        MissingMortgageMetadata: when ``known_mortgages`` is empty or
            none of the entries has a cross-reference field. Silent
            disable is unacceptable.
    """
    case_dir = Path(case_dir)
    not_needed_dir = case_dir / "not_needed"

    # ---- Validate known_mortgages -----------------------------------------
    if not known_mortgages:
        raise MissingMortgageMetadata(
            "audit_not_needed requires known_mortgages; received empty mapping."
        )
    has_any_xref_field = any(
        (mtg.book and mtg.page) or mtg.min_number or mtg.original_principal
        for mtg in known_mortgages.values()
    )
    if not has_any_xref_field:
        raise MissingMortgageMetadata(
            "audit_not_needed: none of the known_mortgages has a usable "
            "cross-reference field (book/page, MIN, or original_principal). "
            "Cannot link satisfactions back to mortgages."
        )

    result = NotNeededAuditResult()

    if not not_needed_dir.exists() or not not_needed_dir.is_dir():
        # Nothing to do, but this isn't an error condition — case folder
        # may simply have had no docs swept aside.
        return result

    # ---- Walk every _extracted.md in not_needed/ --------------------------
    for md_path in sorted(not_needed_dir.glob("*_extracted.md")):
        doc_number = _extract_doc_number_from_filename(md_path)
        try:
            text = md_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            result.ledger.append(LedgerEntry(
                doc_number=doc_number,
                classified_type="OTHER",
                confidence=0.0,
                disposition="unrecoverable",
                reason=f"Failed to read file: {e}",
            ))
            continue

        canonical_type, confidence, _evidence = _classify_with_audit(
            doc_number, text
        )

        # ---- Non-target / phantom-blocked ---------------------------------
        if canonical_type == "OTHER" or confidence == 0.0:
            result.ledger.append(LedgerEntry(
                doc_number=doc_number,
                classified_type=canonical_type,
                confidence=confidence,
                disposition="phantom_blocked" if "phantom" in _evidence else "non_target",
                reason=_evidence or "Could not classify content.",
            ))
            continue

        if canonical_type not in LEDGER_TYPES:
            result.ledger.append(LedgerEntry(
                doc_number=doc_number,
                classified_type=canonical_type,
                confidence=confidence,
                disposition="non_target",
                reason=f"Type {canonical_type} not in {sorted(LEDGER_TYPES)}.",
            ))
            continue

        # ---- Ledger-only types (SUBORDINATION, ASSIGNMENT) ----------------
        if canonical_type == "SUBORDINATION":
            result.ledger.append(LedgerEntry(
                doc_number=doc_number,
                classified_type=canonical_type,
                confidence=confidence,
                disposition="skipped_subordination",
                reason="Subordinations are tracked but don't flip mortgage status.",
            ))
            continue
        if canonical_type == "ASSIGNMENT":
            result.ledger.append(LedgerEntry(
                doc_number=doc_number,
                classified_type=canonical_type,
                confidence=confidence,
                disposition="skipped_assignment",
                reason="Assignments are tracked but don't flip mortgage status.",
            ))
            continue

        # ---- Recoverable types (SATISFACTION/RELEASE/DISCHARGE/MODIFICATION)
        text_no_banner = _strip_banner(text)
        match = _find_match(text_no_banner, known_mortgages)
        if match is None:
            result.ledger.append(LedgerEntry(
                doc_number=doc_number,
                classified_type=canonical_type,
                confidence=confidence,
                disposition="unrecoverable",
                reason=(
                    "No cross-reference hit on doc_number/book_page/min/"
                    "principal against known mortgages."
                ),
            ))
            continue

        target_doc, method, evidence = match
        low_conf = confidence < confidence_floor

        result.recovered.append(RecoveredDocument(
            doc_number=doc_number,
            file_path=md_path,
            classified_type=canonical_type,
            classification_confidence=confidence,
            target_mortgage_doc=target_doc,
            match_method=method,
            match_evidence=evidence,
            low_confidence=low_conf,
        ))
        result.ledger.append(LedgerEntry(
            doc_number=doc_number,
            classified_type=canonical_type,
            confidence=confidence,
            disposition="skipped_low_conf" if low_conf else "recovered",
            reason=(
                f"Matched to mortgage {target_doc} via {method}. "
                f"Evidence: {evidence}"
            ),
        ))

    return result


__all__ = [
    "MortgageMetadata",
    "RecoveredDocument",
    "LedgerEntry",
    "NotNeededAuditResult",
    "MissingMortgageMetadata",
    "RECOVERABLE_TYPES",
    "LEDGER_TYPES",
    "BOOK_PAGE_RE",
    "MIN_RE",
    "DOC_NUM_RE",
    "PRINCIPAL_RE",
    "BANNER_END_RE",
    "audit_not_needed",
    "_extract_mortgage_metadata",
    "_extract_one_mortgage_metadata",
    "_strip_banner",
    "_classify_with_audit",
]
