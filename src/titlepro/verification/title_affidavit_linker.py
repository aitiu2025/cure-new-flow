"""Title-Affidavit Identity-Disclaimer Linker.

When a recorder search returns judgments against a common name (e.g.,
``"Robert Riley"``) that turn out NOT to be the subject (e.g., subject
is ``"Robert S. Riley"``), Florida title practice is to record a
**Title Affidavit** (a.k.a. "Affidavit of Title", "Owner's Affidavit")
at closing in which the subject sworn-statement disclaims being the
named judgment debtor. The Title Affidavit cites the OR Book/Page of
the disclaimed judgment(s).

Real example from ``OnE_Report_RILEY_ROBERT_S_(Pasco).pdf``:

* Title Affidavit Instr# ``2012188920``, recorded 2012-11-05 same day
  as the vesting WD.
* Disclaims a "Robert Riley" judgment at ``OR 8626/1641`` and
  ``OR 3850/...`` (different OR pages, same Robert Riley).
* The OnE renders §4 as "None of record" -- BUT cites the affidavit
  narrative as the disclaimer audit trail.

This module surfaces those pairings as a JSON sidecar so the LLM can
render the narrative without re-doing the OCR cross-reference work.

Public API:
    link_title_affidavits_to_judgments(documents, extracted_texts=None,
                                       inferred_types=None)
        -> list[TitleAffidavitPairing]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TitleAffidavitPairing:
    """One Title Affidavit and the judgments (if any) it disclaims.

    Fields:
        affidavit_doc_number:           CFN / instrument number of the
            affidavit itself.
        affidavit_recording_date:       ISO date string (or None).
        disclaimed_or_book_page_refs:   Verbatim OR Book/Page citations
            extracted from the affidavit body (e.g. ``"OR 8626/1641"``,
            ``"Book 3850 Page 12"``). Audit-trail strings.
        matched_judgment_doc_numbers:   Judgments in the same ``documents``
            list whose Book/Page metadata matches one of the citations.
            Empty list = affidavit's citations don't resolve against the
            current document set (still useful audit trail).
        affiant_name:                   Name of the affiant if parseable
            from the title-page text, else None.
        rationale:                      Human-readable summary suitable
            for inclusion in the report narrative.
    """

    affidavit_doc_number: str
    affidavit_recording_date: Optional[str]
    disclaimed_or_book_page_refs: List[str] = field(default_factory=list)
    matched_judgment_doc_numbers: List[str] = field(default_factory=list)
    affiant_name: Optional[str] = None
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "affidavit_doc_number": self.affidavit_doc_number,
            "affidavit_recording_date": self.affidavit_recording_date,
            "disclaimed_or_book_page_refs": list(self.disclaimed_or_book_page_refs),
            "matched_judgment_doc_numbers": list(self.matched_judgment_doc_numbers),
            "affiant_name": self.affiant_name,
            "rationale": self.rationale,
        }


# ---------------------------------------------------------------------------
# Doc-type classification (Title Affidavit detection)
# ---------------------------------------------------------------------------

# Title-page banners. These are the canonical document-title strings that
# appear in the top ~500 chars of the OCR'd extract.
_TITLE_PAGE_BANNERS = (
    re.compile(r"\bTITLE\s+AFFIDAVIT\b", re.I),
    re.compile(r"\bAFFIDAVIT\s+OF\s+TITLE\b", re.I),
    re.compile(r"\bOWNER[''']?S?\s+AFFIDAVIT\b", re.I),
    re.compile(r"\bAFFIDAVIT\s+AS\s+TO\s+IDENTITY\b", re.I),
    re.compile(r"\bIDENTITY\s+AFFIDAVIT\b", re.I),
    re.compile(r"\bSAME[- ]NAME\s+AFFIDAVIT\b", re.I),
    re.compile(r"\bNOT[- ]THE[- ]SAME\s+AFFIDAVIT\b", re.I),
)

# Body-keyword fallbacks. When the title page is missing (poor OCR),
# these phrases in the body strongly indicate an identity-disclaimer
# affidavit. Each must be a multi-word phrase to avoid generic
# "affidavit" false positives (the search-result feed already calls
# generic affidavits "AFFIDAVIT").
_BODY_KEYWORDS = (
    re.compile(
        r"the\s+undersigned[,\s]+being\s+(?:first\s+)?duly\s+sworn",
        re.I,
    ),
    re.compile(r"affirms?\s+and\s+disclaims?", re.I),
    re.compile(r"identity\s+disclaimer", re.I),
    re.compile(r"is\s+not\s+the\s+same\s+person", re.I),
    re.compile(r"not\s+one\s+and\s+the\s+same", re.I),
    re.compile(r"affiant\s+is\s+not\s+the\s+person\s+named", re.I),
)

# How many leading characters count as the "title page".
_TITLE_PAGE_CHARS = 500


def _doc_type(doc: dict) -> str:
    return (doc.get("document_type") or doc.get("doc_type") or "").upper()


def _doc_number(doc: dict) -> str:
    for k in (
        "doc_number",
        "document_number",
        "instrument_number",
        "instrument",
        "number",
    ):
        v = doc.get(k)
        if v:
            return str(v).strip()
    return ""


def _doc_record_book_page(doc: dict) -> Optional[tuple]:
    """Pull (book, page) tuple from a doc record's metadata fields.

    Handles several shapes:
      * ``{"book": "8626", "page": "1641"}``
      * ``{"or_book": "8626", "or_page": "1641"}``
      * ``{"or_book_page": "OR 8626/1641"}`` (string form)
      * ``{"book_page": "8626/1641"}``
    """
    if not isinstance(doc, dict):
        return None
    # Direct numeric fields
    book = doc.get("book") or doc.get("or_book")
    page = doc.get("page") or doc.get("or_page")
    if book and page:
        return (str(book).strip(), str(page).strip())
    # Combined "OR 8626/1641" or "8626/1641" forms
    for k in ("or_book_page", "book_page", "or_bp"):
        v = doc.get(k)
        if not v:
            continue
        s = str(v).strip()
        # Strip "OR " prefix if present
        s = re.sub(r"^OR\s+", "", s, flags=re.I)
        m = re.match(r"(\d+)\s*[/\\-]\s*(\d+)", s)
        if m:
            return (m.group(1), m.group(2))
    return None


def is_title_affidavit(
    doc: dict,
    extracted_text: Optional[str] = None,
    inferred_type: Optional[str] = None,
) -> bool:
    """Return True if `doc` is a Title / Owner / Identity affidavit.

    Detection order (highest signal first):
      1. ``inferred_type == "TITLE_AFFIDAVIT"`` from the central classifier.
      2. Title-page banner match (first ~500 chars of extracted text).
      3. Body-keyword fallback (full extracted text) -- but ONLY if the
         doc's `document_type` mentions ``AFFIDAVIT`` so we don't
         mis-classify random docs that happen to use boilerplate sworn
         language.
    """
    # 1. Inferred-type wins outright.
    if inferred_type and inferred_type.upper() == "TITLE_AFFIDAVIT":
        return True

    text = extracted_text or doc.get("extracted_text") or doc.get("text") or ""

    # 2. Title-page banner -- strong signal.
    if text:
        head = text[:_TITLE_PAGE_CHARS]
        for pat in _TITLE_PAGE_BANNERS:
            if pat.search(head):
                return True

    # 3. Body-keyword fallback -- only fire if the search-feed
    # `document_type` mentions AFFIDAVIT (avoids generic false-positives).
    doctype = _doc_type(doc)
    if "AFFIDAVIT" in doctype and text:
        for pat in _BODY_KEYWORDS:
            if pat.search(text):
                return True

    return False


# ---------------------------------------------------------------------------
# OR Book/Page citation extraction
# ---------------------------------------------------------------------------

# Handles all common citation forms found in FL title affidavits:
#   "OR 8626/1641"   "OR Book 8626 Page 1641"   "Book 8626 Page 1641"
#   "O.R. 8626, page 1641"   "Official Records Book 8626, Page 1641"
#   "OR BK 8626 Pg 1641"   "Bk 8626 / Pg 1641"
#
# Capture groups: (book, page)
_OR_BOOK_PAGE_PATTERNS = (
    # Compact "OR 8626/1641" -- requires OR/O.R. prefix to avoid noise.
    re.compile(
        r"\bO\.?\s*R\.?\s+(\d{3,6})\s*[/\\-]\s*(\d{1,5})\b",
        re.I,
    ),
    # "OR Book 8626 Page 1641" or "Book 8626 Page 1641" or "Book 8626, Page 1641"
    re.compile(
        r"(?:(?:OFFICIAL\s+RECORDS?|O\.?\s*R\.?)\s+)?"
        r"(?:BOOK|BK)\s*:?\s*(\d{3,6})\s*[,\s]+(?:PAGE|PG)\s*:?\s*(\d{1,5})",
        re.I,
    ),
)


def extract_or_citations(text: str) -> List[tuple]:
    """Extract OR Book/Page citations from `text`.

    Returns a list of (verbatim_match, book, page) tuples, deduplicated
    by (book, page). Verbatim_match is the literal substring matched so
    the report can echo it back to the user.
    """
    if not text:
        return []
    seen: set = set()
    out: List[tuple] = []
    for pat in _OR_BOOK_PAGE_PATTERNS:
        for m in pat.finditer(text):
            book = m.group(1)
            page = m.group(2)
            key = (book, page)
            if key in seen:
                continue
            seen.add(key)
            verbatim = m.group(0).strip()
            out.append((verbatim, book, page))
    return out


# ---------------------------------------------------------------------------
# Judgment-doc detection (used for cross-reference)
# ---------------------------------------------------------------------------

# These canonical types are considered "judgment-shaped" docs the
# affidavit might disclaim. Plain LIEN is included because Florida
# practice often lumps judgment-liens under "lien" in search feeds.
_JUDGMENT_LIKE_TYPES = {"JUDGMENT", "LIEN", "FINAL JUDGMENT", "LIS PENDENS"}


def _is_judgment_like(doc: dict, inferred_type: Optional[str] = None) -> bool:
    if inferred_type and inferred_type.upper() in _JUDGMENT_LIKE_TYPES:
        return True
    t = _doc_type(doc)
    if not t:
        return False
    for marker in _JUDGMENT_LIKE_TYPES:
        if marker in t:
            return True
    return False


# ---------------------------------------------------------------------------
# Recording-date / affiant-name parsing
# ---------------------------------------------------------------------------

# "Recorded 11/05/2012" / "Recorded: 11/05/2012" -- prefer this form
# (matches the FL recorder banner).
_RECORD_DATE_RE = re.compile(
    r"Recorded\s*:?\s*(\d{1,2})/(\d{1,2})/(\d{4})",
    re.I,
)

# Affiant capture: "I, ROBERT S. RILEY, being duly sworn..." style.
_AFFIANT_RE = re.compile(
    r"\bI[,\s]+([A-Z][A-Z .'\-]{2,80}?)[,\s]+"
    r"(?:being|do\s+hereby|having\s+been|am)",
    re.M,
)


def _parse_recording_date(text: str) -> Optional[str]:
    if not text:
        return None
    m = _RECORD_DATE_RE.search(text)
    if not m:
        return None
    mm, dd, yyyy = m.group(1), m.group(2), m.group(3)
    try:
        return f"{int(yyyy):04d}-{int(mm):02d}-{int(dd):02d}"
    except ValueError:
        return None


def _parse_affiant_name(text: str) -> Optional[str]:
    if not text:
        return None
    # Only scan the first 2000 chars -- affiant intro is always near the top.
    head = text[:2000]
    m = _AFFIANT_RE.search(head)
    if not m:
        return None
    name = m.group(1).strip(" ,.\t\n")
    # Reject obvious false positives (single token, all-uppercase nonsense).
    if len(name.split()) < 2:
        return None
    return name


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def link_title_affidavits_to_judgments(
    documents: List[dict],
    extracted_texts: Optional[Dict[str, str]] = None,
    inferred_types: Optional[Dict[str, str]] = None,
) -> List[TitleAffidavitPairing]:
    """Identify Title Affidavits in `documents` and pair them to judgments.

    Args:
      documents: list of doc records (``documents_found.json`` shape).
        Each must have a doc-number-ish field. Book/Page metadata
        ((``book`` + ``page``) or ``or_book_page`` string) is what gets
        matched against the affidavit citations.
      extracted_texts: OPTIONAL ``doc_num -> extracted markdown content``.
        Missing entries are tolerated (treated as empty string). The
        affidavit body needs to be readable for OR Book/Page extraction;
        if no text is available the pairing is still returned with an
        empty ``disclaimed_or_book_page_refs`` list.
      inferred_types: OPTIONAL ``doc_num -> canonical inferred type`` from
        ``document_type_classifier.classify_all_documents``. When the
        upstream classifier does NOT recognize ``"TITLE_AFFIDAVIT"`` (it
        currently does not -- see module docstring), the detection
        falls back to title-page banner + body-keyword scan. House style
        (see ``released_mortgage_linker`` / ``not_needed_audit``):
        passing ``inferred_types`` skips per-doc re-classification.

    Returns:
      One ``TitleAffidavitPairing`` per detected affidavit. Affidavits
      with no OR Book/Page citations or no matching judgments still
      appear in the list -- they are useful audit-trail records.
    """
    extracted_texts = extracted_texts or {}
    inferred_types = inferred_types or {}

    # ---- Build judgment-doc Book/Page index for cross-reference ----
    # Map (book, page) -> list of judgment doc-numbers. Multiple docs
    # may share a slot if the recorder ever re-issues; tolerate that.
    judgment_index: Dict[tuple, List[str]] = {}
    for d in documents:
        num = _doc_number(d)
        if not num:
            continue
        inf = inferred_types.get(num)
        if not _is_judgment_like(d, inferred_type=inf):
            continue
        bp = _doc_record_book_page(d)
        if not bp:
            continue
        judgment_index.setdefault(bp, []).append(num)

    # ---- Detect and link affidavits ----
    pairings: List[TitleAffidavitPairing] = []
    for d in documents:
        num = _doc_number(d)
        if not num:
            continue
        text = extracted_texts.get(num, "") or d.get("extracted_text") or d.get("text") or ""
        inf = inferred_types.get(num)
        if not is_title_affidavit(d, extracted_text=text, inferred_type=inf):
            continue

        # Extract OR Book/Page citations from the affidavit body.
        citations = extract_or_citations(text)
        disclaimed_refs = [verbatim for (verbatim, _b, _p) in citations]

        # Cross-reference each citation against the judgment index.
        matched: List[str] = []
        for _verbatim, book, page in citations:
            for j_num in judgment_index.get((book, page), []):
                if j_num not in matched:
                    matched.append(j_num)

        # Build the audit-trail rationale.
        if matched:
            rationale = (
                f"Title Affidavit Instr# {num} disclaims judgment(s) cited at "
                f"{', '.join(disclaimed_refs)} -- matched to recorded "
                f"judgment doc(s) {', '.join(matched)} in the current "
                f"document set."
            )
        elif disclaimed_refs:
            rationale = (
                f"Title Affidavit Instr# {num} cites OR Book/Page references "
                f"({', '.join(disclaimed_refs)}) but none resolve against "
                f"judgment documents in the current set. Useful audit trail."
            )
        else:
            rationale = (
                f"Title Affidavit Instr# {num} detected but no OR Book/Page "
                f"citations were extractable from its body. Manual review "
                f"recommended."
            )

        pairings.append(
            TitleAffidavitPairing(
                affidavit_doc_number=num,
                affidavit_recording_date=_parse_recording_date(text),
                disclaimed_or_book_page_refs=disclaimed_refs,
                matched_judgment_doc_numbers=matched,
                affiant_name=_parse_affiant_name(text),
                rationale=rationale,
            )
        )

    return pairings


__all__ = [
    "TitleAffidavitPairing",
    "link_title_affidavits_to_judgments",
    "is_title_affidavit",
    "extract_or_citations",
]
