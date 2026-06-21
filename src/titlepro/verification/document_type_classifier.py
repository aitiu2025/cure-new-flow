"""Document Type Classifier.

Infers the *actual* document type of a recorder doc by scanning its
OCR/extracted-markdown content. This is required because some recorder
search-result feeds (notably Broward) put the GRANTEE NAME (e.g.,
``"TRUIST BANK"``) in the ``document_type`` column rather than the
real legal doc type (``"MORTGAGE"`` / ``"SATISFACTION OF MORTGAGE"`` /
``"WARRANTY DEED"`` / ...).

Strategy (in priority order):

  1. **Title-page scan** - the first ~500 chars of the extracted text
     almost always contain an ALL-CAPS doc-type banner (e.g.,
     ``"MORTGAGE"``, ``"SATISFACTION OF MORTGAGE"``, ``"QUIT-CLAIM
     DEED"``). Confidence: ``0.95``.

  2. **Body keyword scan** - canonical phrases anywhere in the doc
     body (``"THIS MORTGAGE"``, ``"MORTGAGEE"``, ``"DOES HEREBY
     CONVEY AND WARRANT"``, ...). Confidence: ``0.75`` - ``0.90``
     depending on signal strength (multi-token canonical phrases
     score higher than single-word markers).

  3. **Fallback** - if neither title page nor body yields a hit, try
     to infer from the ``grantee_hint`` string (the unreliable column
     from search results). Grantee names containing ``BANK`` /
     ``MORTGAGE`` / ``FINANCIAL`` are usually mortgages; otherwise
     return ``"OTHER"``. Confidence: ``<= 0.40``.

Public API:
    classify_document_type(doc_number, extracted_text, grantee_hint=None)
        -> DocumentTypeClassification
    classify_all_documents(documents, extracted_texts)
        -> Dict[doc_num, DocumentTypeClassification]
    detect_noc_termination_bundles(documents, extracted_texts=None,
                                   bundle_window_days=90,
                                   inferred_types=None)
        -> List[NocTerminationBundle]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


@dataclass
class DocumentTypeClassification:
    doc_number: str
    inferred_type: str   # canonical label (see CANONICAL_TYPES)
    confidence: float    # 0.0 - 1.0
    evidence: str        # snippet showing the match (or grantee hint)
    source: str          # "title_page" | "body_keyword" | "fallback"

    def to_dict(self) -> dict:
        return {
            "doc_number": self.doc_number,
            "inferred_type": self.inferred_type,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "source": self.source,
        }


# ---------------------------------------------------------------------------
# Canonical types & patterns
# ---------------------------------------------------------------------------

CANONICAL_TYPES = (
    "MORTGAGE",
    "SATISFACTION",
    "RELEASE",
    "MODIFICATION",
    "SUBORDINATION",
    "ASSIGNMENT",
    "DEED_WARRANTY",
    "DEED_QUITCLAIM",
    "NOC",
    "NOT",                          # Notice of Termination (FL §713.132)
    "CONTRACTOR_FINAL_AFFIDAVIT",   # Contractor's Final Affidavit
    "LIEN_WAIVER",                  # Final Waiver / Release of Lien
    "LIEN",
    "JUDGMENT",
    # NOC-termination-bundle composite labels. Not emitted by the
    # per-doc classifier; produced by ``detect_noc_termination_bundles``.
    "NOC_TERMINATED_CH713_BUNDLE_COMPLETE",
    "NOC_TERMINATED_UNRATIFIED",
    "OTHER",
)

# Title-page banner regexes. Anchored to whole-phrase matches in
# (typically) the first ~500 chars of extracted text. Order matters:
# more specific banners come first so a "SATISFACTION OF MORTGAGE"
# header isn't mis-classified as "MORTGAGE".
#
# Each entry: (canonical_type, compiled_regex)
TITLE_PAGE_PATTERNS: List[Tuple[str, "re.Pattern[str]"]] = [
    # --- Compound / qualified types (must come before plain MORTGAGE) ---
    ("SATISFACTION", re.compile(r"\bSATISFACTION OF MORTGAGE\b", re.I)),
    ("RELEASE",      re.compile(r"\bRELEASE OF MORTGAGE\b", re.I)),
    ("RELEASE",      re.compile(r"\bPARTIAL RELEASE\b", re.I)),
    ("MODIFICATION", re.compile(r"\bMODIFICATION OF MORTGAGE\b", re.I)),
    ("MODIFICATION", re.compile(r"\bMORTGAGE MODIFICATION AGREEMENT\b", re.I)),
    ("MODIFICATION", re.compile(r"\bAMENDMENT TO MORTGAGE\b", re.I)),
    ("SUBORDINATION", re.compile(r"\bSUBORDINATION OF MORTGAGE\b", re.I)),
    ("SUBORDINATION", re.compile(r"\bSUBORDINATION AGREEMENT\b", re.I)),
    ("ASSIGNMENT",   re.compile(r"\bASSIGNMENT OF MORTGAGE\b", re.I)),

    # --- Deeds (specific before generic) ---
    ("DEED_QUITCLAIM", re.compile(r"\bQUIT[- ]?CLAIM DEED\b", re.I)),
    ("DEED_WARRANTY",  re.compile(r"\b(?:GENERAL|SPECIAL)\s+WARRANTY DEED\b", re.I)),
    ("DEED_WARRANTY",  re.compile(r"\bWARRANTY DEED\b", re.I)),

    # --- NOC / NOT / Contractor's Affidavit / Lien Waiver / Lien / Judgment ---
    # Specific FL §713 termination-bundle bannering MUST come before plain
    # NOC / LIEN so a "NOTICE OF TERMINATION" doesn't get mis-classified.
    ("NOT", re.compile(r"\bNOTICE OF TERMINATION(?:\s+OF\s+NOTICE\s+OF\s+COMMENCEMENT)?\b", re.I)),
    ("NOT", re.compile(r"\bTERMINATION OF NOTICE OF COMMENCEMENT\b", re.I)),
    ("CONTRACTOR_FINAL_AFFIDAVIT", re.compile(r"\bFINAL\s+CONTRACTOR['’]?S?\s+AFFIDAVIT\b", re.I)),
    ("CONTRACTOR_FINAL_AFFIDAVIT", re.compile(r"\bCONTRACTOR['’]?S?\s+FINAL\s+AFFIDAVIT\b", re.I)),
    ("CONTRACTOR_FINAL_AFFIDAVIT", re.compile(r"\bFINAL\s+AFFIDAVIT\s+OF\s+CONTRACTOR\b", re.I)),
    ("LIEN_WAIVER", re.compile(r"\bWAIVER\s+AND\s+RELEASE\s+OF\s+LIEN\s+UPON\s+FINAL\s+PAYMENT\b", re.I)),
    ("LIEN_WAIVER", re.compile(r"\bFINAL\s+WAIVER\s+(?:AND\s+RELEASE\s+)?OF\s+LIEN\b", re.I)),
    ("LIEN_WAIVER", re.compile(r"\bFINAL\s+RELEASE\s+OF\s+LIEN\b", re.I)),
    ("LIEN_WAIVER", re.compile(r"\bWAIVER\s+OF\s+LIEN\b", re.I)),
    ("NOC",      re.compile(r"\bNOTICE OF COMMENCEMENT\b", re.I)),
    ("LIEN",     re.compile(r"\b(?:CLAIM OF LIEN|CONSTRUCTION LIEN|TAX LIEN)\b", re.I)),
    ("JUDGMENT", re.compile(r"\bFINAL JUDGMENT\b", re.I)),

    # --- Plain MORTGAGE banner (LAST - matches everything else first) ---
    ("MORTGAGE", re.compile(r"\bOPEN[- ]?END MORTGAGE\b", re.I)),
    ("MORTGAGE", re.compile(r"\bHOME EQUITY LINE OF CREDIT\b", re.I)),
    ("MORTGAGE", re.compile(r"\bMORTGAGE\b", re.I)),
]

# Body-keyword regexes (multi-word phrases score higher).
# Each entry: (canonical_type, compiled_regex, signal_weight 0..1)
BODY_PATTERNS: List[Tuple[str, "re.Pattern[str]", float]] = [
    # MORTGAGE body markers
    ("MORTGAGE",     re.compile(r"\bTHIS MORTGAGE\b", re.I), 0.90),
    ("MORTGAGE",     re.compile(r"\bTO SECURE THE PAYMENT\b", re.I), 0.85),
    ("MORTGAGE",     re.compile(r"\b(?:MORTGAGEE|MORTGAGOR)\b", re.I), 0.75),
    ("MORTGAGE",     re.compile(r"\bHOME EQUITY LINE OF CREDIT\b", re.I), 0.85),
    ("MORTGAGE",     re.compile(r"\bOPEN[- ]?END MORTGAGE\b", re.I), 0.90),

    # SATISFACTION
    ("SATISFACTION", re.compile(r"\bSATISFACTION OF MORTGAGE\b", re.I), 0.90),
    ("SATISFACTION", re.compile(r"\bSATISFIES THE MORTGAGE\b", re.I), 0.85),
    ("SATISFACTION", re.compile(r"\bFULLY PAID AND SATISFIED\b", re.I), 0.85),
    ("SATISFACTION", re.compile(r"\bDISCHARGED AND SATISFIED\b", re.I), 0.85),

    # RELEASE
    ("RELEASE",      re.compile(r"\bRELEASE OF MORTGAGE\b", re.I), 0.90),
    ("RELEASE",      re.compile(r"\bPARTIAL RELEASE\b", re.I), 0.85),
    ("RELEASE",      re.compile(r"\bRELEASE AND DISCHARGE\b", re.I), 0.85),

    # MODIFICATION
    ("MODIFICATION", re.compile(r"\bMODIFICATION OF MORTGAGE\b", re.I), 0.90),
    ("MODIFICATION", re.compile(r"\bMORTGAGE MODIFICATION AGREEMENT\b", re.I), 0.90),
    ("MODIFICATION", re.compile(r"\bAMENDMENT TO MORTGAGE\b", re.I), 0.85),
    ("MODIFICATION", re.compile(r"\bMODIFIES THE MORTGAGE\b", re.I), 0.85),

    # SUBORDINATION
    ("SUBORDINATION", re.compile(r"\bSUBORDINATION AGREEMENT\b", re.I), 0.90),
    ("SUBORDINATION", re.compile(r"\bSUBORDINATION OF MORTGAGE\b", re.I), 0.90),
    ("SUBORDINATION", re.compile(r"\bAGREES TO SUBORDINATE\b", re.I), 0.80),

    # ASSIGNMENT
    ("ASSIGNMENT",   re.compile(r"\bASSIGNMENT OF MORTGAGE\b", re.I), 0.90),
    ("ASSIGNMENT",   re.compile(r"\bASSIGNS AND TRANSFERS\b", re.I), 0.80),

    # DEED_WARRANTY
    ("DEED_WARRANTY", re.compile(r"\b(?:GENERAL|SPECIAL)\s+WARRANTY DEED\b", re.I), 0.90),
    ("DEED_WARRANTY", re.compile(r"\bWARRANTY DEED\b", re.I), 0.85),
    ("DEED_WARRANTY", re.compile(r"\bDOES HEREBY CONVEY AND WARRANT\b", re.I), 0.85),

    # DEED_QUITCLAIM
    ("DEED_QUITCLAIM", re.compile(r"\bQUIT[- ]?CLAIM DEED\b", re.I), 0.90),
    ("DEED_QUITCLAIM", re.compile(r"\bREMISE,? RELEASE AND QUIT[- ]?CLAIM\b", re.I), 0.85),

    # NOC / NOT / Contractor's Affidavit / Lien Waiver / LIEN / JUDGMENT
    ("NOC",      re.compile(r"\bNOTICE OF COMMENCEMENT\b", re.I), 0.90),
    ("NOT",      re.compile(r"\bNOTICE OF TERMINATION\b", re.I), 0.90),
    ("NOT",      re.compile(r"\bTERMINATES?\s+THE\s+NOTICE\s+OF\s+COMMENCEMENT\b", re.I), 0.85),
    ("NOT",      re.compile(r"\bF\.?S\.?\s*713\.132\b", re.I), 0.80),
    ("CONTRACTOR_FINAL_AFFIDAVIT", re.compile(r"\ball\s+subcontractors?\s+and\s+suppliers?\b", re.I), 0.80),
    ("CONTRACTOR_FINAL_AFFIDAVIT", re.compile(r"\ball\s+amounts?\s+due\b", re.I), 0.75),
    ("CONTRACTOR_FINAL_AFFIDAVIT", re.compile(r"\bpaid\s+in\s+full\b", re.I), 0.75),
    ("CONTRACTOR_FINAL_AFFIDAVIT", re.compile(r"\bpayment\s+in\s+full\b", re.I), 0.75),
    ("CONTRACTOR_FINAL_AFFIDAVIT", re.compile(r"\bcontractor['’]?s?\s+final\s+affidavit\b", re.I), 0.90),
    ("LIEN_WAIVER", re.compile(r"\babsolute\s+and\s+irrevocable\b", re.I), 0.85),
    ("LIEN_WAIVER", re.compile(r"\bany\s+and\s+all\s+liens?\b", re.I), 0.80),
    ("LIEN_WAIVER", re.compile(r"\bupon\s+final\s+payment\b", re.I), 0.80),
    ("LIEN_WAIVER", re.compile(r"\bwaiver\s+and\s+release\s+of\s+lien\b", re.I), 0.90),
    ("LIEN_WAIVER", re.compile(r"\bwaiver\s+of\s+lien\b", re.I), 0.85),
    ("LIEN",     re.compile(r"\bCLAIM OF LIEN\b", re.I), 0.90),
    ("LIEN",     re.compile(r"\bCONSTRUCTION LIEN\b", re.I), 0.85),
    ("LIEN",     re.compile(r"\bTAX LIEN\b", re.I), 0.85),
    ("JUDGMENT", re.compile(r"\bFINAL JUDGMENT\b", re.I), 0.90),
    ("JUDGMENT", re.compile(r"\bJUDGMENT\b", re.I), 0.60),
]

TITLE_PAGE_CHARS = 500


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _snippet(text: str, start: int, end: int, pad: int = 40) -> str:
    s = max(0, start - pad)
    e = min(len(text), end + pad)
    return text[s:e].replace("\n", " ").strip()


def _scan_title_page(text: str) -> Optional[Tuple[str, str]]:
    """Look at the first TITLE_PAGE_CHARS chars for a banner match.

    Returns (canonical_type, evidence_snippet) or None.
    """
    if not text:
        return None
    head = text[:TITLE_PAGE_CHARS]
    for canonical, pattern in TITLE_PAGE_PATTERNS:
        m = pattern.search(head)
        if m:
            return canonical, _snippet(head, m.start(), m.end())
    return None


def _scan_body(text: str) -> Optional[Tuple[str, float, str]]:
    """Body-keyword scan over the full text.

    Returns (canonical_type, confidence, evidence) or None.

    Strategy: count per-type signal score (sum of weights of distinct
    matching patterns, capped at 1.0). Pick the type with the highest
    score. If tied or no match, return None.
    """
    if not text:
        return None

    # type -> (cumulative_score, first_match_evidence)
    type_scores: Dict[str, Tuple[float, str]] = {}
    for canonical, pattern, weight in BODY_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        prev_score, prev_ev = type_scores.get(canonical, (0.0, ""))
        new_score = min(1.0, prev_score + weight)
        evidence = prev_ev or _snippet(text, m.start(), m.end())
        type_scores[canonical] = (new_score, evidence)

    if not type_scores:
        return None

    # Strict prioritization: types that ALSO match a "qualifying" body
    # phrase (e.g. SATISFACTION/RELEASE/MODIFICATION) should beat the
    # plain MORTGAGE signal even if MORTGAGE has higher accumulated
    # score (because mortgage-related phrases naturally appear in
    # satisfaction/release/modification docs).
    QUALIFYING = ("SATISFACTION", "RELEASE", "MODIFICATION",
                  "SUBORDINATION", "ASSIGNMENT")
    for qtype in QUALIFYING:
        if qtype in type_scores and "MORTGAGE" in type_scores:
            # If the qualifying type has any real signal, drop the
            # MORTGAGE candidate.
            if type_scores[qtype][0] >= 0.75:
                type_scores.pop("MORTGAGE", None)

    # NOT body text always references the parent NOC ("terminates the
    # NOTICE OF COMMENCEMENT recorded ..."). When NOT has any real
    # signal, it must beat NOC.
    if "NOT" in type_scores and "NOC" in type_scores:
        if type_scores["NOT"][0] >= 0.75:
            type_scores.pop("NOC", None)

    # LIEN_WAIVER body text matches the generic "lien" body markers
    # incidentally. When LIEN_WAIVER has any real signal it must beat
    # LIEN.
    if "LIEN_WAIVER" in type_scores and "LIEN" in type_scores:
        if type_scores["LIEN_WAIVER"][0] >= 0.75:
            type_scores.pop("LIEN", None)

    # CONTRACTOR_FINAL_AFFIDAVIT text frequently mentions outstanding
    # liens / lien rights. When the affidavit signal is strong, drop
    # any incidental LIEN candidate.
    if "CONTRACTOR_FINAL_AFFIDAVIT" in type_scores and "LIEN" in type_scores:
        if type_scores["CONTRACTOR_FINAL_AFFIDAVIT"][0] >= 0.75:
            type_scores.pop("LIEN", None)

    # Pick highest score; tie-break by canonical-type priority order.
    best_type = max(
        type_scores,
        key=lambda t: (type_scores[t][0], -CANONICAL_TYPES.index(t)),
    )
    score, evidence = type_scores[best_type]
    # Map cumulative score to a reported confidence in [0.75, 0.90].
    confidence = max(0.75, min(0.90, score))
    return best_type, confidence, evidence


# Grantee-hint fallback keywords. Mapping of substring -> canonical type.
# Only used when title-page and body scans both fail.
FALLBACK_GRANTEE_KEYWORDS: List[Tuple[str, str]] = [
    ("BANK",        "MORTGAGE"),
    ("MORTGAGE",    "MORTGAGE"),
    ("FINANCIAL",   "MORTGAGE"),
    ("CREDIT UNION", "MORTGAGE"),
    ("LENDING",     "MORTGAGE"),
    ("CONSTRUCTION", "NOC"),
    ("CONTRACTOR",  "NOC"),
]


def _scan_grantee_hint(grantee_hint: Optional[str]) -> Optional[Tuple[str, str]]:
    if not grantee_hint:
        return None
    hint_upper = grantee_hint.upper()
    for keyword, canonical in FALLBACK_GRANTEE_KEYWORDS:
        if keyword in hint_upper:
            return canonical, f"grantee_hint={grantee_hint!r}"
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_document_type(
    doc_number: str,
    extracted_text: str,
    grantee_hint: Optional[str] = None,
) -> DocumentTypeClassification:
    """Classify a single doc by inspecting its OCR'd text content.

    See module docstring for the full priority order. The returned
    classification always has a non-empty ``inferred_type``; in the
    worst case the type is ``"OTHER"`` with confidence ``0.0``.
    """
    # ---- 1. Title-page scan ----
    title_hit = _scan_title_page(extracted_text)
    if title_hit:
        canonical, evidence = title_hit
        return DocumentTypeClassification(
            doc_number=doc_number,
            inferred_type=canonical,
            confidence=0.95,
            evidence=evidence,
            source="title_page",
        )

    # ---- 2. Body keyword scan ----
    body_hit = _scan_body(extracted_text)
    if body_hit:
        canonical, confidence, evidence = body_hit
        return DocumentTypeClassification(
            doc_number=doc_number,
            inferred_type=canonical,
            confidence=confidence,
            evidence=evidence,
            source="body_keyword",
        )

    # ---- 3. Grantee-hint fallback ----
    hint_hit = _scan_grantee_hint(grantee_hint)
    if hint_hit:
        canonical, evidence = hint_hit
        return DocumentTypeClassification(
            doc_number=doc_number,
            inferred_type=canonical,
            confidence=0.40,
            evidence=evidence,
            source="fallback",
        )

    # ---- 4. Truly no signal ----
    return DocumentTypeClassification(
        doc_number=doc_number,
        inferred_type="OTHER",
        confidence=0.0,
        evidence="",
        source="fallback",
    )


def _doc_number(doc: dict) -> str:
    for k in ("doc_number", "document_number", "instrument_number",
              "instrument", "number"):
        v = doc.get(k)
        if v:
            return str(v).strip()
    return ""


def _grantee_hint(doc: dict) -> str:
    """Pick the best grantee-ish field to use as the fallback hint.

    Some search-result feeds put the grantee name in ``document_type``
    (Broward bug). Others use ``grantees`` / ``grantee``.
    """
    # Prefer the explicit grantees field if it isn't itself a placeholder.
    raw_grantees = (doc.get("grantees") or doc.get("grantee") or "").strip()
    raw_doctype = (doc.get("document_type") or doc.get("doc_type") or "").strip()

    # If document_type column looks like a company name (Broward bug),
    # prefer it - it's the real grantee. We treat single tokens like
    # "From"/"To" as placeholders and ignore them.
    placeholder_doctypes = {"FROM", "TO", "", "GRANTOR", "GRANTEE"}
    if raw_doctype.upper() not in placeholder_doctypes and len(raw_doctype) > 3:
        # If it contains real grantee-style words, return it.
        # (Mortgage / Satisfaction / etc are filtered by the title-page
        # path above, so by this point we know the doctype column is
        # NOT a legit doc-type.)
        return raw_doctype
    return raw_grantees


def classify_all_documents(
    documents: List[dict],
    extracted_texts: Dict[str, str],
) -> Dict[str, DocumentTypeClassification]:
    """Bulk classifier. Returns one classification per doc_number.

    Args:
        documents: list of doc records (``documents_found.json`` shape).
        extracted_texts: ``doc_num -> extracted markdown content``.
            Missing keys are tolerated (treated as empty string).

    Returns:
        Mapping ``doc_number -> DocumentTypeClassification``.
    """
    results: Dict[str, DocumentTypeClassification] = {}
    for doc in documents:
        num = _doc_number(doc)
        if not num:
            continue
        text = extracted_texts.get(num, "") or ""
        hint = _grantee_hint(doc)
        results[num] = classify_document_type(num, text, grantee_hint=hint)
    return results


# ---------------------------------------------------------------------------
# NOC-termination-bundle detector (FL §713.132)
# ---------------------------------------------------------------------------
#
# A FL Notice of Commencement (NOC, §713.13) opens a construction-lien
# window. Recording a bare Notice of Termination (NOT, §713.132) starts
# the closing process but does not by itself defeat all lien rights -
# a subcontractor with pre-existing performance can still file inside
# the §713.07 statutory window. To *definitively* close the window the
# property owner must record the triplet:
#
#   1. Notice of Termination                            (NOT)
#   2. Contractor's Final Affidavit                     (CFA)
#   3. Final Waiver/Release of Lien from contractor     (LW; sometimes
#      sub-waivers)
#
# When all three land within ~90 days of each other on the same
# project, the §713 window is definitively terminated. When only the
# NOT is recorded, the closer should still treat the project as
# potentially-lienable.
#
# Status codes:
#   BUNDLE_COMPLETE_CH713_DEFINITIVELY_TERMINATED
#       NOT + CFA + >=1 LW within the window.
#   PARTIAL_NOT_ONLY_UNRATIFIED
#       NOT only; no CFA, no LW.
#   PARTIAL_NOT_PLUS_AFFIDAVIT_NO_WAIVER
#       NOT + CFA but no LW.
#   PARTIAL_NOT_PLUS_WAIVER_NO_AFFIDAVIT
#       NOT + LW but no CFA.
#   NO_TERMINATION_FOUND
#       NOC exists but no NOT - the construction-lien window is still
#       open.


_BUNDLE_STATUS_COMPLETE = "BUNDLE_COMPLETE_CH713_DEFINITIVELY_TERMINATED"
_BUNDLE_STATUS_NOT_ONLY = "PARTIAL_NOT_ONLY_UNRATIFIED"
_BUNDLE_STATUS_NOT_PLUS_AFFIDAVIT = "PARTIAL_NOT_PLUS_AFFIDAVIT_NO_WAIVER"
_BUNDLE_STATUS_NOT_PLUS_WAIVER = "PARTIAL_NOT_PLUS_WAIVER_NO_AFFIDAVIT"
_BUNDLE_STATUS_NONE = "NO_TERMINATION_FOUND"


@dataclass
class NocTerminationBundle:
    noc_doc_number: Optional[str]
    not_doc_number: Optional[str]
    final_affidavit_doc_number: Optional[str]
    lien_waiver_doc_numbers: List[str] = field(default_factory=list)
    status: str = _BUNDLE_STATUS_NONE
    bundle_window_days: Optional[int] = None
    contractor_name: Optional[str] = None
    project_address: Optional[str] = None
    rationale: str = ""

    def to_dict(self) -> dict:
        return {
            "noc_doc_number": self.noc_doc_number,
            "not_doc_number": self.not_doc_number,
            "final_affidavit_doc_number": self.final_affidavit_doc_number,
            "lien_waiver_doc_numbers": list(self.lien_waiver_doc_numbers),
            "status": self.status,
            "bundle_window_days": self.bundle_window_days,
            "contractor_name": self.contractor_name,
            "project_address": self.project_address,
            "rationale": self.rationale,
        }


# Recording-date parser. Recorder feeds use ``MM/DD/YYYY`` consistently;
# accept a few common variants and ISO ``YYYY-MM-DD`` as a fallback.
_DATE_FORMATS = ("%m/%d/%Y", "%m-%d-%Y", "%Y-%m-%d", "%m/%d/%y")


def _parse_recording_date(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    raw = str(raw).strip()
    if not raw:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    # Last resort: try to grab MM/DD/YYYY out of a longer string.
    m = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b", raw)
    if m:
        mo, dy, yr = m.groups()
        if len(yr) == 2:
            yr = "20" + yr if int(yr) < 50 else "19" + yr
        try:
            return datetime(int(yr), int(mo), int(dy))
        except ValueError:
            return None
    return None


# Address extraction. We pull the first plausible street-line from the
# extracted text - cheap heuristic, mainly used for cluster matching.
_ADDRESS_RE = re.compile(
    r"\b(\d{1,6}\s+[A-Z][A-Z0-9 .'\-]{4,}?(?:STREET|ST|AVENUE|AVE|"
    r"ROAD|RD|DRIVE|DR|LANE|LN|BOULEVARD|BLVD|COURT|CT|PLACE|PL|"
    r"TERRACE|TER|WAY|CIRCLE|CIR|PARKWAY|PKWY|HIGHWAY|HWY)\b\.?)",
    re.I,
)


def _extract_project_address(text: str) -> Optional[str]:
    if not text:
        return None
    head = text[:2000]
    m = _ADDRESS_RE.search(head)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip().upper()
    return None


# Contractor-name extraction. NOCs typically say
# ``Contractor: ACME BUILDERS, INC.`` and CFAs / LW say
# ``the undersigned, ACME BUILDERS, INC., being duly sworn...``.
_CONTRACTOR_RE_PATTERNS = (
    re.compile(r"Contractor[:\s]+([A-Z][A-Z0-9 .,'&\-]{4,80}?(?:INC|LLC|CORP|CO|LTD|L\.?L\.?C\.?|"
               r"COMPANY|CORPORATION|INCORPORATED|BUILDERS?|CONSTRUCTION|HOMES?|GROUP))",
               re.I),
    re.compile(r"Contractor['’]?s?\s+Name[:\s]+([A-Z][A-Z0-9 .,'&\-]{4,80})", re.I),
    re.compile(r"(?:the\s+undersigned[,\s]+)([A-Z][A-Z0-9 .,'&\-]{4,80}?(?:INC|LLC|CORP|CO|LTD|"
               r"L\.?L\.?C\.?|COMPANY|CORPORATION|INCORPORATED|BUILDERS?|CONSTRUCTION|HOMES?|GROUP))",
               re.I),
)


def _normalize_contractor(name: str) -> str:
    # Strip trailing punctuation, normalize whitespace and dot-laden
    # legal-entity suffixes for fuzzy compare.
    name = re.sub(r"\s+", " ", name).strip(" ,.;:'\"")
    name = re.sub(r"\.", "", name)
    return name.upper()


def _extract_contractor_name(text: str) -> Optional[str]:
    if not text:
        return None
    head = text[:3000]
    for pat in _CONTRACTOR_RE_PATTERNS:
        m = pat.search(head)
        if m:
            return _normalize_contractor(m.group(1))
    return None


def _resolve_inferred_type(
    doc_num: str,
    doc: dict,
    extracted_texts: Optional[Dict[str, str]],
    inferred_types: Optional[Dict[str, str]],
) -> str:
    """Pick the canonical type for a doc, preferring the precomputed
    ``inferred_types`` map (matches the ``released_mortgage_linker``
    contract) and falling back to per-doc classification."""
    if inferred_types and doc_num in inferred_types:
        return (inferred_types[doc_num] or "").upper() or "OTHER"
    text = ""
    if extracted_texts:
        text = extracted_texts.get(doc_num, "") or ""
    if not text:
        text = doc.get("extracted_text") or doc.get("text") or ""
    hint = (doc.get("grantees") or doc.get("grantee")
            or doc.get("document_type") or doc.get("doc_type") or "")
    return classify_document_type(doc_num, text, grantee_hint=str(hint) or None).inferred_type


def _doc_text(doc_num: str, doc: dict,
              extracted_texts: Optional[Dict[str, str]]) -> str:
    if extracted_texts and doc_num in extracted_texts:
        return extracted_texts[doc_num] or ""
    return doc.get("extracted_text") or doc.get("text") or ""


def detect_noc_termination_bundles(
    documents: List[dict],
    extracted_texts: Optional[Dict[str, str]] = None,
    bundle_window_days: int = 90,
    inferred_types: Optional[Dict[str, str]] = None,
) -> List[NocTerminationBundle]:
    """Match each NOC in the doc set to its termination-bundle status.

    Args:
        documents: list of doc records (``documents_found.json`` shape).
            Each must carry ``doc_number`` (or one of the accepted
            aliases) and ``recording_date`` in ``MM/DD/YYYY`` form.
        extracted_texts: optional ``doc_num -> OCR/markdown text`` map.
            Used to extract project address + contractor name for
            cluster matching.
        bundle_window_days: max gap between earliest NOT and latest
            bundle doc (default 90 days, per FL §713 practice).
        inferred_types: optional ``doc_num -> canonical type`` map
            (matches the ``released_mortgage_linker`` contract). When
            provided, the per-doc classifier is skipped.

    Returns:
        One ``NocTerminationBundle`` per NOC found. If no NOC is in the
        doc set, returns ``[]``. If a NOC has no matching NOT inside
        the window, its bundle status is ``NO_TERMINATION_FOUND``.
    """
    extracted_texts = extracted_texts or {}

    # Resolve types once.
    typed: List[Tuple[str, dict, str, Optional[datetime], str, Optional[str], Optional[str]]] = []
    for doc in documents:
        num = _doc_number(doc)
        if not num:
            continue
        canonical = _resolve_inferred_type(num, doc, extracted_texts, inferred_types)
        rec_dt = _parse_recording_date(doc.get("recording_date"))
        text = _doc_text(num, doc, extracted_texts)
        addr = _extract_project_address(text)
        contractor = _extract_contractor_name(text)
        typed.append((num, doc, canonical, rec_dt, text, addr, contractor))

    nocs = [t for t in typed if t[2] == "NOC"]
    nots = [t for t in typed if t[2] == "NOT"]
    cfas = [t for t in typed if t[2] == "CONTRACTOR_FINAL_AFFIDAVIT"]
    waivers = [t for t in typed if t[2] == "LIEN_WAIVER"]

    if not nocs:
        return []

    # Order NOCs by recording date so re-NOC scenarios pick the right
    # parent for each downstream NOT.
    nocs_sorted = sorted(nocs, key=lambda t: t[3] or datetime.min)

    # Track which downstream docs have already been claimed by an
    # earlier-recorded NOC so a later NOC doesn't double-claim them.
    claimed: set = set()
    bundles: List[NocTerminationBundle] = []

    for noc_num, noc_doc, _, noc_dt, _, noc_addr, noc_contractor in nocs_sorted:
        # ---- 1. Find candidate NOTs ----
        candidate_nots = []
        for tnum, tdoc, _, tdt, _, taddr, tcontr in nots:
            if tnum in claimed:
                continue
            # If both dates known, NOT must be after the NOC. If either
            # is unknown, allow the match (rationale will note the
            # uncertainty).
            if noc_dt and tdt and tdt < noc_dt:
                continue
            # Project-address match preferred; contractor-name match is
            # fallback when addresses don't extract cleanly.
            addr_match = noc_addr and taddr and noc_addr == taddr
            contr_match = (
                noc_contractor and tcontr and
                (noc_contractor == tcontr or
                 noc_contractor in tcontr or tcontr in noc_contractor)
            )
            score = (2 if addr_match else 0) + (1 if contr_match else 0)
            candidate_nots.append((score, tdt or datetime.min, tnum, tdoc, taddr, tcontr))

        # Pick the best NOT: highest match score, then latest recording
        # date (re-NOC: latest termination wins).
        candidate_nots.sort(key=lambda x: (x[0], x[1]), reverse=True)

        if not candidate_nots:
            bundles.append(NocTerminationBundle(
                noc_doc_number=noc_num,
                not_doc_number=None,
                final_affidavit_doc_number=None,
                lien_waiver_doc_numbers=[],
                status=_BUNDLE_STATUS_NONE,
                bundle_window_days=None,
                contractor_name=noc_contractor,
                project_address=noc_addr,
                rationale=(
                    "NOC " + noc_num + " has no matched Notice of "
                    "Termination in the doc set; construction-lien "
                    "window remains open."
                ),
            ))
            continue

        # Use the best NOT.
        _, _, not_num, not_doc, not_addr, not_contractor = candidate_nots[0]
        not_dt = _parse_recording_date(not_doc.get("recording_date"))
        claimed.add(not_num)

        # The "anchor" cluster keys: prefer NOC address, fall back to
        # NOT address; same for contractor.
        cluster_addr = noc_addr or not_addr
        cluster_contractor = noc_contractor or not_contractor

        # ---- 2. Find CFA + LW inside the bundle window ----
        # The window spans from the NOT date forward by
        # bundle_window_days. We also accept docs recorded slightly
        # BEFORE the NOT (within bundle_window_days), since recording
        # order in practice can flip (the contractor sometimes files
        # the Final Affidavit before the owner files the NOT).
        def _in_window(dt: Optional[datetime]) -> bool:
            if not_dt is None or dt is None:
                # Date unknown on either side; fall back to inclusion
                # (rationale flags the imprecision).
                return True
            return abs((dt - not_dt).days) <= bundle_window_days

        def _cluster_match(addr: Optional[str], contr: Optional[str]) -> bool:
            if cluster_addr and addr and cluster_addr == addr:
                return True
            if cluster_contractor and contr and (
                cluster_contractor == contr
                or cluster_contractor in contr
                or contr in cluster_contractor
            ):
                return True
            # When neither side has an extracted anchor, fall back to
            # date-only inclusion (this happens with poor OCR).
            if not cluster_addr and not cluster_contractor and not addr and not contr:
                return True
            return False

        cfa_match = None
        for cnum, cdoc, _, cdt, _, caddr, ccontr in cfas:
            if cnum in claimed:
                continue
            if not _in_window(cdt):
                continue
            if not _cluster_match(caddr, ccontr):
                continue
            cfa_match = (cnum, cdoc, cdt, caddr, ccontr)
            break

        waiver_matches: List[Tuple[str, dict, Optional[datetime], Optional[str], Optional[str]]] = []
        for wnum, wdoc, _, wdt, _, waddr, wcontr in waivers:
            if wnum in claimed:
                continue
            if not _in_window(wdt):
                continue
            if not _cluster_match(waddr, wcontr):
                continue
            waiver_matches.append((wnum, wdoc, wdt, waddr, wcontr))

        if cfa_match:
            claimed.add(cfa_match[0])
        for wm in waiver_matches:
            claimed.add(wm[0])

        # ---- 3. Decide bundle status ----
        has_cfa = cfa_match is not None
        has_waiver = len(waiver_matches) > 0

        if has_cfa and has_waiver:
            status = _BUNDLE_STATUS_COMPLETE
        elif has_cfa:
            status = _BUNDLE_STATUS_NOT_PLUS_AFFIDAVIT
        elif has_waiver:
            status = _BUNDLE_STATUS_NOT_PLUS_WAIVER
        else:
            status = _BUNDLE_STATUS_NOT_ONLY

        # ---- 4. Compute window span ----
        dts = [not_dt]
        if cfa_match:
            dts.append(cfa_match[2])
        for wm in waiver_matches:
            dts.append(wm[2])
        dts_known = [d for d in dts if d is not None]
        if len(dts_known) >= 2:
            span = (max(dts_known) - min(dts_known)).days
        else:
            span = None

        # ---- 5. Rationale ----
        bits: List[str] = []
        bits.append(f"NOC {noc_num}")
        bits.append(f"matched NOT {not_num}")
        if cfa_match:
            bits.append(f"Final Affidavit {cfa_match[0]}")
        if waiver_matches:
            wlist = ", ".join(w[0] for w in waiver_matches)
            bits.append(f"Lien Waiver(s) [{wlist}]")
        if cluster_addr:
            bits.append(f"project address {cluster_addr}")
        elif cluster_contractor:
            bits.append(f"contractor {cluster_contractor}")
        else:
            bits.append("cluster matched by recording-date proximity only")
        if span is not None:
            bits.append(f"window span {span} day(s)")
        rationale = "; ".join(bits) + "."

        bundles.append(NocTerminationBundle(
            noc_doc_number=noc_num,
            not_doc_number=not_num,
            final_affidavit_doc_number=cfa_match[0] if cfa_match else None,
            lien_waiver_doc_numbers=[w[0] for w in waiver_matches],
            status=status,
            bundle_window_days=span,
            contractor_name=cluster_contractor,
            project_address=cluster_addr,
            rationale=rationale,
        ))

    return bundles


__all__ = [
    "DocumentTypeClassification",
    "classify_document_type",
    "classify_all_documents",
    "CANONICAL_TYPES",
    "NocTerminationBundle",
    "detect_noc_termination_bundles",
]
