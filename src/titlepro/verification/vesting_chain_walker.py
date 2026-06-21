"""Vesting Chain Walker.

Detects same-day or near-same-day refi-cycle interim deeds that are
mistakenly selected as Prior Vesting and recommends a walk target
pointing at the most-recent arm's-length acquisition.

Motivated by the RILEY case (Pasco County, Peter Bodonyi shop, OnE
Report v1.2 dated 2026-06-02):

  * Current Vesting: QCD Instr# 2021099994, recorded 2021-05-13,
    Riley husband/wife -> Riley Trust (estate-planning conveyance).
  * WRONG Prior Vesting (Jun 2 draft): QCD Instr# 2021099992,
    recorded 2021-05-13 - the SAME day - Riley Trust -> Riley
    husband/wife. This is a refi-cycle interim where the trust
    temporarily un-vested for the lender, then re-vested same day.
  * CORRECT Prior Vesting (Jun 3 revision): WD Instr# 2012188921,
    recorded 2012-11-05, Stiefel Properties LLC -> Riley husband/wife
    - the actual arm's-length acquisition 9 years earlier.

The wrong Prior Vesting carried the same parties on both sides of the
row, which adds zero examiner value. The correct Prior Vesting must
be the most-recent arm's-length acquisition between unrelated parties.

The walker:

  1. Identifies the Current Vesting deed (caller-supplied or inferred
     as the most-recent deed-type doc).
  2. Picks the next-most-recent deed as the candidate Prior Vesting.
  3. If the candidate is inside the refi window AND has party overlap
     with the Current, flags it as ``SAME_DAY_REFI_INTERIM_DETECTED``
     and walks past further interim deeds until it lands on the first
     deed that is BOTH older than the refi window AND has no party
     overlap. That deed is the recommended walk target.

Public API:
    walk_vesting_chain(documents, extracted_texts=None,
                       current_vesting_doc_number=None,
                       subject_owner_names=None,
                       refi_window_days=30)
        -> VestingChainFinding
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Literal, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Canonical deed-type labels (mirrors document_type_classifier output)
# ---------------------------------------------------------------------------

DEED_TYPES: Set[str] = {
    "DEED_WARRANTY",
    "DEED_QUITCLAIM",
    "DEED_SPECIAL_WARRANTY",
    "DEED_PERSONAL_REPRESENTATIVE",
    "CERTIFICATE_OF_TITLE",
    "TAX_DEED",
}

# Tenure-start instruments the walker must not walk past. Personal
# Representative / probate deeds represent inheritance vesting; certificates
# of title and tax deeds represent court/involuntary starts.
PR_DEED_TYPES: Set[str] = {
    "DEED_PERSONAL_REPRESENTATIVE",
}
TENURE_STOP_TYPES: Set[str] = {
    "DEED_PERSONAL_REPRESENTATIVE",
    "CERTIFICATE_OF_TITLE",
    "TAX_DEED",
}

# Keywords used to fall back to deed-type inference when the caller did
# not supply a canonical type. Matched against ``document_type``-style
# strings, NOT against full OCR bodies.
_DEED_TYPE_TOKEN_RE = re.compile(
    r"\b(WARRANTY\s+DEED|QUIT\s*CLAIM\s+DEED|QUITCLAIM\s+DEED|"
    r"SPECIAL\s+WARRANTY\s+DEED|PERSONAL\s+REPRESENTATIVE'?S?\s+DEED|"
    r"PR'?S?\s+DEED|PROBATE\s+DEED|CERTIFICATE\s+OF\s+TITLE|"
    r"TAX\s+DEED)\b",
    re.I,
)

_PR_DEED_TOKEN_RE = re.compile(
    r"\b(PERSONAL\s+REPRESENTATIVE'?S?\s+DEED|PR'?S?\s+DEED|PROBATE\s+DEED)\b",
    re.I,
)

_TENURE_STOP_TOKEN_RE = re.compile(
    r"\b(PERSONAL\s+REPRESENTATIVE'?S?\s+DEED|PR'?S?\s+DEED|PROBATE\s+DEED|"
    r"CERTIFICATE\s+OF\s+TITLE|TAX\s+DEED)\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------


VestingChainStatus = Literal[
    "PASS",
    "SAME_DAY_REFI_INTERIM_DETECTED",
    "AMBIGUOUS",
]


@dataclass
class VestingChainFinding:
    status: VestingChainStatus
    current_vesting_doc_number: Optional[str]
    candidate_prior_vesting_doc_number: Optional[str]
    candidate_age_days_from_current: Optional[int]
    candidate_party_overlap_reason: Optional[str]
    recommended_walk_target_doc_number: Optional[str]
    recommended_walk_target_reason: Optional[str]
    walked_past_doc_numbers: List[str] = field(default_factory=list)
    ordered_chain: List[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "current_vesting_doc_number": self.current_vesting_doc_number,
            "candidate_prior_vesting_doc_number": self.candidate_prior_vesting_doc_number,
            "candidate_age_days_from_current": self.candidate_age_days_from_current,
            "candidate_party_overlap_reason": self.candidate_party_overlap_reason,
            "recommended_walk_target_doc_number": self.recommended_walk_target_doc_number,
            "recommended_walk_target_reason": self.recommended_walk_target_reason,
            "walked_past_doc_numbers": list(self.walked_past_doc_numbers),
            "ordered_chain": [dict(row) for row in self.ordered_chain],
        }


# ---------------------------------------------------------------------------
# Doc-key + deed-type helpers
# ---------------------------------------------------------------------------


def _doc_number(doc: dict) -> str:
    for k in (
        "doc_number", "document_number", "instrument_number",
        "instrument", "number",
    ):
        v = doc.get(k)
        if v:
            return str(v).strip()
    return ""


def _doc_type_string(doc: dict) -> str:
    return (
        doc.get("inferred_type")
        or doc.get("document_type")
        or doc.get("doc_type")
        or ""
    ).strip()


def _is_deed(doc: dict) -> bool:
    t = _doc_type_string(doc).upper()
    if not t:
        return False
    # Canonical inferred-type wins.
    if t in DEED_TYPES:
        return True
    # Free-text doctype string fallback.
    return bool(_DEED_TYPE_TOKEN_RE.search(t))


def _is_pr_deed(doc: dict) -> bool:
    t = _doc_type_string(doc).upper()
    if t in PR_DEED_TYPES:
        return True
    return bool(_PR_DEED_TOKEN_RE.search(t))


def _is_tenure_stop_deed(doc: dict) -> bool:
    t = _doc_type_string(doc).upper()
    if t in TENURE_STOP_TYPES:
        return True
    return bool(_TENURE_STOP_TOKEN_RE.search(t))


def _chain_row(
    entry: Tuple[str, dict, Optional[datetime]],
    *,
    tenure: str,
    kind: str,
) -> dict:
    num, doc, dt = entry
    grantors, grantees = _extract_parties_from_metadata(doc)
    return {
        "document_number": num,
        "recording_date": dt.date().isoformat() if dt else None,
        "document_type": _doc_type_string(doc) or None,
        "grantor": doc.get("grantor") or doc.get("grantors") or doc.get("from"),
        "grantee": doc.get("grantee") or doc.get("grantees") or doc.get("to"),
        "tenure": tenure,
        "kind": kind,
        "grantor_tokens": sorted(grantors),
        "grantee_tokens": sorted(grantees),
    }


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

# Common recording-date keys seen across recorder feeds.
_DATE_KEYS = (
    "recording_date",
    "recorded_date",
    "date_recorded",
    "rec_date",
    "recording_dt",
    "filing_date",
    "date",
)

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%m/%d/%Y",
    "%m-%d-%Y",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%m/%d/%y",
)


def _parse_recording_date(doc: dict) -> Optional[datetime]:
    """Robust recording-date parse. Tries common keys and formats.

    Returns ``None`` if no usable date field is present. Never raises.
    """
    raw = None
    for k in _DATE_KEYS:
        v = doc.get(k)
        if v:
            raw = v
            break
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    s = str(raw).strip()
    if not s:
        return None
    # Drop fractional seconds / trailing TZ Z so strptime doesn't choke.
    s_clean = s.replace("Z", "").split(".")[0]
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s_clean, fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Party extraction + normalization
# ---------------------------------------------------------------------------

# Qualifiers stripped from party strings before tokenization. We strip
# AFTER uppercasing so the regex is case-flat.
_QUALIFIER_PATTERNS = (
    re.compile(r",?\s*AS\s+TRUSTEES?\s+OF\s+", re.I),
    re.compile(r",?\s*AS\s+TRUSTEE\s+OF\s+", re.I),
    re.compile(r",?\s*TRUSTEES?\s+OF\s+", re.I),
    re.compile(r",?\s*TRUST\s+DATED\s+\d{1,2}/\d{1,2}/\d{2,4}", re.I),
    re.compile(r",?\s*DATED\s+\d{1,2}/\d{1,2}/\d{2,4}", re.I),
    re.compile(r",?\s*HUSBAND\s+AND\s+WIFE", re.I),
    re.compile(r",?\s*WIFE\s+AND\s+HUSBAND", re.I),
    re.compile(r",?\s*A\s+MARRIED\s+(?:MAN|WOMAN)", re.I),
    re.compile(r",?\s*A\s+SINGLE\s+(?:MAN|WOMAN|PERSON)", re.I),
    re.compile(r",?\s*SINGLE\s+(?:MAN|WOMAN|PERSON)", re.I),
    re.compile(r",?\s*\(DECEASED\)", re.I),
    re.compile(r",?\s*DECEASED", re.I),
    re.compile(r",?\s*AS\s+TENANTS\s+IN\s+COMMON", re.I),
    re.compile(r",?\s*AS\s+JOINT\s+TENANTS", re.I),
    re.compile(r",?\s*WITH\s+RIGHT\s+OF\s+SURVIVORSHIP", re.I),
    re.compile(r",?\s*TENANTS?\s+BY\s+THE\s+ENTIRETY", re.I),
    re.compile(r",?\s*TBE", re.I),
    re.compile(r",?\s*JTWROS", re.I),
    re.compile(r",?\s*AN?\s+UNMARRIED\s+(?:MAN|WOMAN|PERSON)", re.I),
    re.compile(r",?\s*INDIVIDUALLY", re.I),
    re.compile(r"\bAKA\b", re.I),
    re.compile(r"\bFKA\b", re.I),
    re.compile(r"\bNKA\b", re.I),
)

# Filler tokens dropped from the final token set.
_STOPWORD_TOKENS: Set[str] = {
    "AND", "OR", "THE", "A", "AN", "OF",
    "MR", "MRS", "MS", "DR", "JR", "SR", "II", "III", "IV",
    "ETAL", "ETUX", "ETVIR",
    "AS", "TRUST", "TRUSTS", "TRUSTEE", "TRUSTEES",
}

# Entity-marker tokens. When one appears we treat the whole party as an
# entity (LLC / trust / corp) rather than a person — useful for the
# "Stiefel Properties LLC -> Riley h/w" arm's-length boundary detection.
_ENTITY_MARKERS: Set[str] = {
    "LLC", "L.L.C", "LLP", "LP", "L.P", "INC", "CORP", "CORPORATION",
    "COMPANY", "CO", "PROPERTIES", "HOLDINGS", "INVESTMENTS",
    "TRUST", "REVOCABLE", "IRREVOCABLE", "LIVING", "FAMILY",
    "ENTERPRISES", "PARTNERSHIP", "ASSOCIATION", "BANK", "ESTATE",
}


def _normalize_party_name(name: str) -> str:
    """Strip qualifiers, uppercase, collapse punctuation/whitespace."""
    if not name:
        return ""
    s = str(name).upper()
    for pat in _QUALIFIER_PATTERNS:
        s = pat.sub(" ", s)
    # Drop trailing/leading commas + collapse whitespace.
    s = re.sub(r"[,;]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _tokenize(normalized: str) -> Set[str]:
    """Split normalized party string into significant tokens (uppercase)."""
    if not normalized:
        return set()
    # Keep apostrophes and hyphens inside tokens (e.g. O'BRIEN, SMITH-JONES).
    raw = re.findall(r"[A-Z][A-Z0-9'\-\.]*", normalized)
    out: Set[str] = set()
    for t in raw:
        t = t.strip(".-'")
        if not t:
            continue
        if t in _STOPWORD_TOKENS:
            continue
        # Single-letter initials are ambiguous; drop them.
        if len(t) <= 1:
            continue
        out.add(t)
    return out


def _extract_trust_phrase(normalized: str) -> Optional[str]:
    """Return a canonical TRUST identifier (e.g. ``RILEY TRUST``) or None.

    We use this so multiple textual forms of the same trust collapse to
    one identifier:

      "RILEY FAMILY REVOCABLE TRUST DATED 1/1/2020" -> "RILEY TRUST"
      "RILEY TRUST DTD 1/1/20"                       -> "RILEY TRUST"
    """
    if not normalized or "TRUST" not in normalized:
        return None
    # Pick the longest non-stopword token immediately preceding TRUST as
    # the trust surname. e.g. "JOHN AND JANE RILEY FAMILY TRUST" ->
    # surname token = "RILEY" (last non-filler token before TRUST).
    head = normalized.split("TRUST", 1)[0]
    tokens = _tokenize(head)
    # Filter out entity markers and known family-trust filler words.
    family_filler = {"FAMILY", "REVOCABLE", "IRREVOCABLE", "LIVING", "JOINT"}
    surname_candidates = [
        t for t in tokens
        if t not in _ENTITY_MARKERS and t not in family_filler
    ]
    if not surname_candidates:
        return None
    # Prefer the LAST token in the head (closest to TRUST), but tokenize
    # is a set — re-scan the raw head text in left-to-right order.
    ordered = [
        t.strip(".-'")
        for t in re.findall(r"[A-Z][A-Z0-9'\-\.]*", head)
        if t.strip(".-'") in surname_candidates
    ]
    if not ordered:
        return None
    return f"{ordered[-1]} TRUST"


def _is_entity(normalized: str) -> bool:
    """Heuristic: does this party look like a corporate entity / LLC?"""
    if not normalized:
        return False
    tokens = _tokenize(normalized)
    return any(marker in tokens for marker in _ENTITY_MARKERS)


# ---------------------------------------------------------------------------
# Party extraction from OCR text + metadata
# ---------------------------------------------------------------------------

# Grantor/Grantee header patterns we look for inside the OCR markdown.
# Each pattern captures the party-name text following the label.
_GRANTOR_HEADER_RE = re.compile(
    r"(?:^|\n)\s*(?:GRANTOR\(?S?\)?|FROM|BY|MORTGAGOR)\s*[:\-]\s*"
    r"([^\n]+)",
    re.I,
)
_GRANTEE_HEADER_RE = re.compile(
    r"(?:^|\n)\s*(?:GRANTEE\(?S?\)?|TO|MORTGAGEE)\s*[:\-]\s*([^\n]+)",
    re.I,
)

# "X conveys to Y" / "X grants to Y" patterns — used as a fallback when
# headers aren't present in the OCR.
_CONVEY_TO_RE = re.compile(
    r"([A-Z][A-Z0-9 ,&.\-'/]{3,150}?)\s+"
    r"(?:HEREBY\s+)?(?:CONVEYS?|GRANTS?|QUIT[\s\-]?CLAIMS?|RELEASES?)\s+"
    r"(?:AND\s+(?:WARRANTS?|QUITCLAIMS?)\s+)?"
    r"(?:TO|UNTO)\s+"
    r"([A-Z][A-Z0-9 ,&.\-'/]{3,150}?)"
    r"(?:\s+(?:THE\s+FOLLOWING|ALL\s+(?:THAT|THE)|WHOSE))",
    re.I,
)


def _extract_parties_from_text(text: str) -> Tuple[Set[str], Set[str]]:
    """Pull (grantor_tokens, grantee_tokens) out of OCR-extracted deed text.

    Returns empty sets when no parties can be confidently extracted.
    Includes trust phrases (e.g. ``"RILEY TRUST"``) as joined tokens
    AND breaks each party into individual surname tokens.
    """
    if not text:
        return set(), set()

    grantor_norms: List[str] = []
    grantee_norms: List[str] = []

    for m in _GRANTOR_HEADER_RE.finditer(text):
        grantor_norms.append(_normalize_party_name(m.group(1)))
    for m in _GRANTEE_HEADER_RE.finditer(text):
        grantee_norms.append(_normalize_party_name(m.group(1)))

    # Fallback: "X conveys to Y" pattern.
    if not grantor_norms or not grantee_norms:
        m = _CONVEY_TO_RE.search(text)
        if m:
            if not grantor_norms:
                grantor_norms.append(_normalize_party_name(m.group(1)))
            if not grantee_norms:
                grantee_norms.append(_normalize_party_name(m.group(1) and m.group(2)))

    grantors: Set[str] = set()
    grantees: Set[str] = set()
    for n in grantor_norms:
        grantors |= _tokenize(n)
        trust = _extract_trust_phrase(n)
        if trust:
            grantors.add(trust)
    for n in grantee_norms:
        grantees |= _tokenize(n)
        trust = _extract_trust_phrase(n)
        if trust:
            grantees.add(trust)
    return grantors, grantees


def _extract_parties_from_metadata(doc: dict) -> Tuple[Set[str], Set[str]]:
    """Pull party tokens from documents_found.json-style metadata.

    Handles both string and list values for the grantor/grantee fields.
    """
    def _collect(value) -> Set[str]:
        if value is None:
            return set()
        if isinstance(value, (list, tuple, set)):
            parts: List[str] = []
            for v in value:
                if v is None:
                    continue
                parts.append(str(v))
            joined = " ; ".join(parts)
        else:
            joined = str(value)
        normalized = _normalize_party_name(joined)
        tokens = _tokenize(normalized)
        trust = _extract_trust_phrase(normalized)
        if trust:
            tokens.add(trust)
        return tokens

    grantors = _collect(doc.get("grantor") or doc.get("grantors") or doc.get("from"))
    grantees = _collect(doc.get("grantee") or doc.get("grantees") or doc.get("to"))
    return grantors, grantees


def _get_parties(
    doc: dict,
    extracted_texts: Optional[Dict[str, str]],
) -> Tuple[Set[str], Set[str]]:
    """Prefer OCR-text extraction; fall back to metadata."""
    num = _doc_number(doc)
    if extracted_texts:
        txt = extracted_texts.get(num, "") or ""
        if txt:
            g_from, g_to = _extract_parties_from_text(txt)
            if g_from or g_to:
                return g_from, g_to
    return _extract_parties_from_metadata(doc)


# ---------------------------------------------------------------------------
# Overlap detection
# ---------------------------------------------------------------------------


def _compute_party_overlap(
    parties_a: Tuple[Set[str], Set[str]],
    parties_b: Tuple[Set[str], Set[str]],
    *,
    subject_owner_tokens: Optional[Set[str]] = None,
) -> Tuple[bool, str]:
    """Return ``(overlap_detected, reason)`` for two (grantors, grantees) tuples.

    Overlap signals (ANY one is sufficient):

      1. The SAME trust phrase appears on either side of both deeds
         (e.g. ``"RILEY TRUST"`` shows up in A.grantee + B.grantor).
      2. The same surname token appears on either side of both deeds.
      3. Same individual full-name token cluster across both.

    The ``subject_owner_tokens`` hint (derived from
    ``workflow_config.search_requests[].name``) lets us promote a
    surname to "load-bearing" status when OCR text is absent, so the
    overlap check still works on metadata-only inputs.
    """
    a_grantors, a_grantees = parties_a
    b_grantors, b_grantees = parties_b
    a_all = a_grantors | a_grantees
    b_all = b_grantors | b_grantees

    if not a_all or not b_all:
        # Cannot evaluate overlap without parties on both sides.
        return False, ""

    # ---- 1. Trust-phrase overlap -----------------------------------------
    a_trusts = {t for t in a_all if t.endswith(" TRUST")}
    b_trusts = {t for t in b_all if t.endswith(" TRUST")}
    shared_trusts = a_trusts & b_trusts
    if shared_trusts:
        trust = sorted(shared_trusts)[0]
        return True, f"Shared trust on both deeds: {trust}"

    # ---- 2. Surname token overlap ---------------------------------------
    # Filter out very short and clearly-entity-marker tokens.
    def _surname_pool(toks: Set[str]) -> Set[str]:
        return {
            t for t in toks
            if len(t) >= 3
            and t not in _ENTITY_MARKERS
            and not t.endswith(" TRUST")
        }

    a_surnames = _surname_pool(a_all)
    b_surnames = _surname_pool(b_all)
    shared = a_surnames & b_surnames

    if shared:
        # Bias toward subject-owner-hint tokens when available.
        if subject_owner_tokens:
            hint_match = shared & subject_owner_tokens
            if hint_match:
                surname = sorted(hint_match)[0]
                return (
                    True,
                    f"Shared subject-owner surname on both deeds: {surname}",
                )
        surname = sorted(shared)[0]
        return True, f"Shared surname on both deeds: {surname}"

    return False, ""


def _subject_owner_tokens(
    subject_owner_names: Optional[List[str]],
) -> Set[str]:
    """Pre-tokenize the subject-owner-names hint for fast overlap checks."""
    if not subject_owner_names:
        return set()
    out: Set[str] = set()
    for n in subject_owner_names:
        out |= _tokenize(_normalize_party_name(n))
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def walk_vesting_chain(
    documents: List[dict],
    extracted_texts: Optional[Dict[str, str]] = None,
    current_vesting_doc_number: Optional[str] = None,
    subject_owner_names: Optional[List[str]] = None,
    refi_window_days: int = 30,
) -> VestingChainFinding:
    """Detect refi-cycle interim deeds chosen as Prior Vesting.

    Args:
        documents: list of recorder-doc records (documents_found.json
            shape). Each record should have a doc-number key plus
            ``document_type`` (or ``inferred_type``) and a recording
            date. Grantor/grantee fields are used as a fallback when
            no OCR text is available.
        extracted_texts: OPTIONAL mapping ``doc_number -> OCR markdown``.
            When present, party extraction prefers the cover-page text
            over the (often-thin) metadata fields. Missing entries are
            tolerated.
        current_vesting_doc_number: OPTIONAL explicit identifier for
            the Current Vesting deed. When ``None``, the walker infers
            the Current Vesting as the most-recent deed-type document
            in ``documents`` (recording date as tiebreaker).
        subject_owner_names: OPTIONAL list of subject-owner names
            (typically ``workflow_config.search_requests[].name``).
            Improves overlap-detection accuracy when OCR text is absent
            by pre-flagging the expected surname tokens.
        refi_window_days: maximum age (Current - Candidate) considered
            "same-day-ish" for refi-interim purposes. Default ``30``.

    Returns:
        VestingChainFinding describing the candidate Prior Vesting,
        whether it looks like a refi-cycle interim, and (if so) the
        recommended walk target.
    """
    # ---- Sort deeds by recording date (newest first) ----------------------
    deed_entries: List[Tuple[str, dict, Optional[datetime]]] = []
    for d in documents or []:
        if not _is_deed(d):
            continue
        num = _doc_number(d)
        if not num:
            continue
        dt = _parse_recording_date(d)
        deed_entries.append((num, d, dt))

    # No deeds at all -> nothing the walker can do.
    if not deed_entries:
        return VestingChainFinding(
            status="PASS",
            current_vesting_doc_number=None,
            candidate_prior_vesting_doc_number=None,
            candidate_age_days_from_current=None,
            candidate_party_overlap_reason=None,
            recommended_walk_target_doc_number=None,
            recommended_walk_target_reason=None,
        )

    # Date-aware sort: deeds with a parsed date go in date order
    # (descending); deeds with no date sink to the end.
    def _sort_key(entry):
        _num, _doc, dt = entry
        # datetime.max keeps None-dated docs at the tail of "newest first".
        return (dt is None, -(dt.timestamp() if dt else 0))

    deed_entries.sort(key=_sort_key)

    # ---- 1. Identify Current Vesting --------------------------------------
    current_entry: Optional[Tuple[str, dict, Optional[datetime]]] = None
    if current_vesting_doc_number:
        for entry in deed_entries:
            if entry[0] == str(current_vesting_doc_number).strip():
                current_entry = entry
                break
    if current_entry is None:
        # Fall back to the first deed (newest by recording date).
        current_entry = deed_entries[0]

    current_num, current_doc, current_dt = current_entry
    current_chain_row = _chain_row(
        current_entry,
        tenure="current",
        kind="current_vesting",
    )

    # If Current Vesting can't be located, return PASS with None.
    if current_num is None:
        return VestingChainFinding(
            status="PASS",
            current_vesting_doc_number=None,
            candidate_prior_vesting_doc_number=None,
            candidate_age_days_from_current=None,
            candidate_party_overlap_reason=None,
            recommended_walk_target_doc_number=None,
            recommended_walk_target_reason=None,
        )

    # ---- 2. Identify candidate Prior Vesting -----------------------------
    # Strictly older than Current by recording date. Same-day deeds
    # ARE eligible (they're the canonical refi-interim case).
    older_deeds: List[Tuple[str, dict, Optional[datetime]]] = []
    for entry in deed_entries:
        num, _doc, dt = entry
        if num == current_num:
            continue
        if current_dt is None or dt is None:
            # Without dates on both ends we can't reason about ordering;
            # treat the entry as a candidate but the age check will trip
            # the AMBIGUOUS branch below.
            older_deeds.append(entry)
            continue
        if dt <= current_dt:
            older_deeds.append(entry)

    if not older_deeds:
        return VestingChainFinding(
            status="PASS",
            current_vesting_doc_number=current_num,
            candidate_prior_vesting_doc_number=None,
            candidate_age_days_from_current=None,
            candidate_party_overlap_reason=None,
            recommended_walk_target_doc_number=None,
            recommended_walk_target_reason=None,
            ordered_chain=[current_chain_row],
        )

    candidate_num, candidate_doc, candidate_dt = older_deeds[0]

    # Pre-tokenize subject-owner hint for overlap detection.
    owner_tokens = _subject_owner_tokens(subject_owner_names)

    # ---- 3. Tenure-stop deed - never walk past ----------------------------
    # PR/probate, certificate-of-title, and tax deeds start a tenure and must
    # be reported as the tenure boundary regardless of how recent they are.
    if _is_tenure_stop_deed(candidate_doc):
        return VestingChainFinding(
            status="PASS",
            current_vesting_doc_number=current_num,
            candidate_prior_vesting_doc_number=candidate_num,
            candidate_age_days_from_current=(
                (current_dt - candidate_dt).days
                if current_dt and candidate_dt else None
            ),
            candidate_party_overlap_reason=None,
            recommended_walk_target_doc_number=None,
            recommended_walk_target_reason=(
                "Candidate is a tenure-commencing deed "
                "(PR/probate, Certificate of Title, or tax deed); "
                "accepted as Prior Vesting."
            ),
            ordered_chain=[
                current_chain_row,
                _chain_row(
                    (candidate_num, candidate_doc, candidate_dt),
                    tenure="prior",
                    kind="tenure_commencing",
                ),
            ],
        )

    # ---- 4. Age check ----------------------------------------------------
    if current_dt is None or candidate_dt is None:
        return VestingChainFinding(
            status="AMBIGUOUS",
            current_vesting_doc_number=current_num,
            candidate_prior_vesting_doc_number=candidate_num,
            candidate_age_days_from_current=None,
            candidate_party_overlap_reason=None,
            recommended_walk_target_doc_number=None,
            recommended_walk_target_reason=(
                "Could not compute candidate age - missing recording date "
                "on Current or candidate Prior Vesting deed."
            ),
            ordered_chain=[
                current_chain_row,
                _chain_row(
                    (candidate_num, candidate_doc, candidate_dt),
                    tenure="unknown",
                    kind="ambiguous",
                ),
            ],
        )

    age_days = (current_dt - candidate_dt).days

    if age_days > refi_window_days:
        # Candidate is too old for a refi-interim; treat as legitimate.
        return VestingChainFinding(
            status="PASS",
            current_vesting_doc_number=current_num,
            candidate_prior_vesting_doc_number=candidate_num,
            candidate_age_days_from_current=age_days,
            candidate_party_overlap_reason=None,
            recommended_walk_target_doc_number=None,
            recommended_walk_target_reason=None,
            ordered_chain=[
                current_chain_row,
                _chain_row(
                    (candidate_num, candidate_doc, candidate_dt),
                    tenure="prior",
                    kind="tenure_commencing",
                ),
            ],
        )

    # ---- 5. Party-overlap check ------------------------------------------
    current_parties = _get_parties(current_doc, extracted_texts)
    candidate_parties = _get_parties(candidate_doc, extracted_texts)

    overlap, reason = _compute_party_overlap(
        current_parties,
        candidate_parties,
        subject_owner_tokens=owner_tokens,
    )

    if not overlap:
        # Inside refi window but no party overlap -> could legitimately be
        # a quick resale between unrelated parties. Flag for operator.
        return VestingChainFinding(
            status="AMBIGUOUS",
            current_vesting_doc_number=current_num,
            candidate_prior_vesting_doc_number=candidate_num,
            candidate_age_days_from_current=age_days,
            candidate_party_overlap_reason=None,
            recommended_walk_target_doc_number=None,
            recommended_walk_target_reason=(
                "Candidate is within the refi window but shows no party "
                "overlap with Current Vesting. Likely a legitimate quick "
                "resale - operator should review."
            ),
            ordered_chain=[
                current_chain_row,
                _chain_row(
                    (candidate_num, candidate_doc, candidate_dt),
                    tenure="unknown",
                    kind="ambiguous",
                ),
            ],
        )

    # ---- 6. Walk past chained interim deeds ------------------------------
    walked_past: List[str] = [candidate_num]
    walk_target_num: Optional[str] = None
    walk_target_reason: Optional[str] = None

    # Build a quick lookup for prior parties to chain-check overlap.
    prior_parties_chain: List[Tuple[Set[str], Set[str]]] = [
        current_parties,
        candidate_parties,
    ]

    # Walk older_deeds[1:] looking for the first one that is BOTH older
    # than refi_window from the CANDIDATE and has no party overlap with
    # any prior chain entry.
    for entry in older_deeds[1:]:
        next_num, next_doc, next_dt = entry

        # Tenure-stop vesting is always a valid stop.
        if _is_tenure_stop_deed(next_doc):
            walk_target_num = next_num
            walk_target_reason = (
                "Tenure-commencing deed (PR/probate, Certificate of Title, "
                "or tax deed) accepted as the legitimate Prior Vesting."
            )
            break

        if next_dt is None or candidate_dt is None:
            # Can't reason about age without dates; keep walking.
            walked_past.append(next_num)
            continue

        gap_days = (candidate_dt - next_dt).days

        next_parties = _get_parties(next_doc, extracted_texts)

        # Overlap with any prior chain entry disqualifies this hop.
        # IMPORTANT: when walking PAST candidates, we only care about the
        # GRANTOR side of the next deed. An arm's-length acquisition has a
        # FRESH grantor (e.g. STIEFEL PROPERTIES LLC); the subject's surname
        # appearing on the grantee side is EXPECTED (it's how the subject
        # came to own the property). So we mask out the grantee side here.
        next_grantor_only: Tuple[Set[str], Set[str]] = (
            next_parties[0], set(),
        )
        chain_overlap = False
        chain_reason = ""
        for prior in prior_parties_chain:
            ov, why = _compute_party_overlap(
                prior, next_grantor_only, subject_owner_tokens=owner_tokens,
            )
            if ov:
                chain_overlap = True
                chain_reason = why
                break

        if gap_days > refi_window_days and not chain_overlap:
            walk_target_num = next_num
            walk_target_reason = (
                f"Most-recent arm's-length acquisition: {gap_days} days "
                "older than the refi-interim cluster with no party overlap."
            )
            break

        # Otherwise still in the interim cluster - record and continue.
        walked_past.append(next_num)
        prior_parties_chain.append(next_parties)
        if chain_overlap and not walk_target_reason:
            # Capture the chain reason for diagnostics even if we keep walking.
            walk_target_reason = (
                f"Skipped {next_num}: {chain_reason}"
            )

    chain_entries: list[Tuple[str, dict, Optional[datetime]]] = [current_entry]
    walked_set = set(walked_past)
    for entry in older_deeds:
        if entry[0] in walked_set:
            chain_entries.append(entry)
        elif walk_target_num and entry[0] == walk_target_num:
            chain_entries.append(entry)
            break

    ordered_chain: list[dict] = []
    for entry in chain_entries:
        num = entry[0]
        if num == current_num:
            ordered_chain.append(_chain_row(entry, tenure="current", kind="current_vesting"))
        elif num == walk_target_num:
            ordered_chain.append(
                _chain_row(entry, tenure="current", kind="tenure_commencing")
            )
        else:
            ordered_chain.append(_chain_row(entry, tenure="current", kind="interim"))

    return VestingChainFinding(
        status="SAME_DAY_REFI_INTERIM_DETECTED",
        current_vesting_doc_number=current_num,
        candidate_prior_vesting_doc_number=candidate_num,
        candidate_age_days_from_current=age_days,
        candidate_party_overlap_reason=reason,
        recommended_walk_target_doc_number=walk_target_num,
        recommended_walk_target_reason=walk_target_reason,
        walked_past_doc_numbers=walked_past,
        ordered_chain=ordered_chain,
    )


__all__ = [
    "VestingChainFinding",
    "DEED_TYPES",
    "PR_DEED_TYPES",
    "walk_vesting_chain",
    "_extract_parties_from_text",
    "_extract_parties_from_metadata",
    "_normalize_party_name",
    "_compute_party_overlap",
    "_parse_recording_date",
    "_extract_trust_phrase",
    "_is_deed",
    "_is_pr_deed",
]
