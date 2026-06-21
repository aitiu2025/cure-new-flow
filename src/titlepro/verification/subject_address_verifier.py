"""Subject Address Verifier.

NLP-lite verifier that compares a property address extracted from a deed
against the subject property address declared for the title-exam case.

Motivated by Tony Roveda's Broward Test Review (2026-05-21): CURE pulled
a QCD for "6830 Falconsgate Ave, Davie, FL" when the subject was
"2151 NW 93rd Ave, Pembroke Pines, FL" and shipped it as the vesting
deed. This module surfaces that mismatch BEFORE the deed is promoted.

Design notes:
  * stdlib-only (difflib + re); no fuzzywuzzy.
  * Component-weighted similarity: street_number (0.30) + street_name
    (0.30) + city (0.20) + state (0.10) + directional/street_type (0.10).
  * Hard penalty when street_number or city differ - these are
    near-certain "different property" signals.

Public API:
    verify_subject_address(extracted, subject, *, match_threshold=0.85,
                            ambiguous_threshold=0.55) -> AddressMatchResult
    extract_subject_address_from_text(text, *, subject_hint=None,
                                       return_all_candidates=False)

The extract_subject_address_from_text helper was added 2026-05-22 to fix
a real ANAND-run failure mode: the first address-shaped string in a
mortgage doc is often the LENDER's office (e.g. "7455 Chancellor Drive,
Orlando, FL" for SunTrust). It uses keyword-proximity scoring to prefer
the actual subject property over lender/preparer/return-address strings.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple, Union

# ---------------------------------------------------------------------------
# Normalization tables
# ---------------------------------------------------------------------------

STREET_TYPE_ALIASES: Dict[str, str] = {
    "AVE": "AVENUE", "AV": "AVENUE", "AVENUE": "AVENUE",
    "ST": "STREET", "STR": "STREET", "STREET": "STREET",
    "BLVD": "BOULEVARD", "BOULEVARD": "BOULEVARD",
    "DR": "DRIVE", "DRV": "DRIVE", "DRIVE": "DRIVE",
    "LN": "LANE", "LANE": "LANE",
    "CT": "COURT", "COURT": "COURT",
    "PL": "PLACE", "PLACE": "PLACE",
    "RD": "ROAD", "ROAD": "ROAD",
    "HWY": "HIGHWAY", "HIGHWAY": "HIGHWAY",
    "TERR": "TERRACE", "TER": "TERRACE", "TERRACE": "TERRACE",
    "CIR": "CIRCLE", "CIRCLE": "CIRCLE",
    "PKWY": "PARKWAY", "PARKWAY": "PARKWAY",
    "WAY": "WAY", "TRL": "TRAIL", "TRAIL": "TRAIL",
    "SQ": "SQUARE", "SQUARE": "SQUARE", "PT": "POINT", "POINT": "POINT",
}

DIRECTIONAL_ALIASES: Dict[str, str] = {
    "N": "N", "S": "S", "E": "E", "W": "W",
    "NE": "NE", "NW": "NW", "SE": "SE", "SW": "SW",
    "NORTH": "N", "SOUTH": "S", "EAST": "E", "WEST": "W",
    "NORTHEAST": "NE", "NORTHWEST": "NW",
    "SOUTHEAST": "SE", "SOUTHWEST": "SW",
}

STATE_ALIASES: Dict[str, str] = {
    "FLORIDA": "FL", "FL": "FL", "CALIFORNIA": "CA", "CA": "CA",
    "TEXAS": "TX", "TX": "TX", "NEW YORK": "NY", "NY": "NY",
    "OHIO": "OH", "OH": "OH", "GEORGIA": "GA", "GA": "GA",
}

UNIT_MARKERS = {"APT", "APARTMENT", "UNIT", "STE", "SUITE", "#",
                "BLDG", "FL", "FLOOR", "LOT"}

# Component weights (must sum to ~1.0).
WEIGHTS = {
    "street_number": 0.30, "street_name": 0.30,
    "city": 0.20, "state": 0.10, "extras": 0.10,
}


@dataclass
class AddressMatchResult:
    status: str  # "MATCH" | "NO_MATCH" | "AMBIGUOUS"
    similarity: float
    extracted_normalized: str
    subject_normalized: str
    matched_components: Dict[str, bool] = field(default_factory=dict)
    evidence: str = ""


# ---------------------------------------------------------------------------
# Tokenization / normalization
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[^\w\s#-]")
_MULTI_WS_RE = re.compile(r"\s+")
_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")


def _normalize_raw(text: str) -> str:
    """Uppercase, strip extraneous punctuation, collapse whitespace."""
    if not text:
        return ""
    t = _PUNCT_RE.sub(" ", text.upper().strip())
    return _MULTI_WS_RE.sub(" ", t).strip()


def _expand_token(tok: str) -> str:
    """Map abbreviations to canonical forms; pass-through unknown tokens."""
    if tok in DIRECTIONAL_ALIASES:
        return DIRECTIONAL_ALIASES[tok]
    if tok in STREET_TYPE_ALIASES:
        return STREET_TYPE_ALIASES[tok]
    if tok in STATE_ALIASES:
        return STATE_ALIASES[tok]
    return tok


def _ocr_repair_number(token: str) -> str:
    """Repair common OCR confusions in numeric-looking tokens.

    "215l" (lowercase L) -> "2151"; "O" -> "0"; "I" -> "1".
    """
    repaired = token.upper().replace("L", "1").replace("O", "0").replace("I", "1")
    return repaired if repaired.isdigit() else token


def _looks_numeric(token: str) -> bool:
    if not token:
        return False
    if token.isdigit():
        return True
    return _ocr_repair_number(token).isdigit()


# ---------------------------------------------------------------------------
# Component extraction
# ---------------------------------------------------------------------------


@dataclass
class _Components:
    street_number: str = ""
    directional: str = ""
    street_name: str = ""
    street_type: str = ""
    unit: str = ""
    city: str = ""
    state: str = ""
    zip_code: str = ""
    normalized: str = ""


def parse_address(raw: str) -> _Components:
    """Best-effort address parser. Splits on commas; tokenizes street chunk."""
    if not raw:
        return _Components()
    parts = [p.strip() for p in re.split(r",", raw) if p.strip()]

    street_chunk = parts[0] if parts else _normalize_raw(raw)
    city_chunk = parts[1] if len(parts) >= 2 else ""
    state_zip_chunk = parts[2] if len(parts) >= 3 else ""

    comp = _Components()

    # ---- street chunk ---------------------------------------------------
    street_tokens = [_expand_token(t) for t in _normalize_raw(street_chunk).split()]

    if street_tokens and _looks_numeric(street_tokens[0]):
        comp.street_number = _ocr_repair_number(street_tokens[0])
        street_tokens = street_tokens[1:]

    if street_tokens and street_tokens[0] in {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}:
        comp.directional = street_tokens[0]
        street_tokens = street_tokens[1:]

    # Unit marker handling - chop the unit off the tail.
    unit_idx: Optional[int] = None
    for i, tok in enumerate(street_tokens):
        if tok in UNIT_MARKERS or tok.startswith("#"):
            unit_idx = i
            break
    if unit_idx is not None:
        comp.unit = " ".join(street_tokens[unit_idx:])
        street_tokens = street_tokens[:unit_idx]

    if street_tokens and street_tokens[-1] in STREET_TYPE_ALIASES.values():
        comp.street_type = street_tokens[-1]
        comp.street_name = " ".join(street_tokens[:-1])
    else:
        comp.street_name = " ".join(street_tokens)

    # ---- city chunk (may carry trailing state + zip if jammed) ---------
    city_tokens = _normalize_raw(city_chunk).split()
    while city_tokens:
        tail = city_tokens[-1]
        zm = _ZIP_RE.fullmatch(tail)
        if zm:
            comp.zip_code = zm.group(1)
            city_tokens = city_tokens[:-1]
            continue
        if tail in STATE_ALIASES:
            comp.state = STATE_ALIASES[tail]
            city_tokens = city_tokens[:-1]
            continue
        break
    comp.city = " ".join(city_tokens).strip()

    # ---- third part (explicit state/zip) -------------------------------
    if len(parts) >= 3:
        for tok in _normalize_raw(state_zip_chunk).split():
            zm = _ZIP_RE.fullmatch(tok)
            if zm and not comp.zip_code:
                comp.zip_code = zm.group(1)
            elif tok in STATE_ALIASES and not comp.state:
                comp.state = STATE_ALIASES[tok]

    comp.normalized = _render_normalized(comp)
    return comp


def _render_normalized(c: _Components) -> str:
    head_bits = [b for b in (c.street_number, c.directional, c.street_name, c.street_type) if b]
    tail_bits = [b for b in (c.unit, c.city, c.state, c.zip_code) if b]
    head = " ".join(head_bits)
    return f"{head}, {', '.join(tail_bits)}" if tail_bits else head


# ---------------------------------------------------------------------------
# Similarity scoring
# ---------------------------------------------------------------------------


def _ratio(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def _score_components(a: _Components, b: _Components) -> Tuple[float, Dict[str, bool]]:
    matched: Dict[str, bool] = {}

    # street_number (with OCR forgiveness)
    if a.street_number and b.street_number:
        sn_match = a.street_number == b.street_number
        sn_score = 1.0 if sn_match else 0.0
        if not sn_match and _ratio(a.street_number, b.street_number) >= 0.75:
            sn_score = 0.6
    else:
        sn_match = False
        sn_score = _ratio(a.street_number, b.street_number)
    matched["street_number"] = sn_match

    name_score = _ratio(a.street_name, b.street_name)
    matched["street_name"] = name_score >= 0.85

    city_score = _ratio(a.city, b.city)
    matched["city"] = city_score >= 0.90 and bool(a.city) and bool(b.city)

    state_score = (
        1.0 if (a.state and b.state and a.state == b.state)
        else (0.0 if (a.state and b.state) else _ratio(a.state, b.state))
    )
    matched["state"] = bool(a.state and b.state and a.state == b.state)

    dir_score = 1.0 if a.directional == b.directional else _ratio(a.directional, b.directional)
    type_score = 1.0 if a.street_type == b.street_type else _ratio(a.street_type, b.street_type)
    extras_score = (dir_score + type_score) / 2.0
    matched["directional"] = a.directional == b.directional
    matched["street_type"] = a.street_type == b.street_type

    weighted = (
        WEIGHTS["street_number"] * sn_score
        + WEIGHTS["street_name"] * name_score
        + WEIGHTS["city"] * city_score
        + WEIGHTS["state"] * state_score
        + WEIGHTS["extras"] * extras_score
    )

    # Hard penalties per spec: differing street_number or city tank the score.
    if a.street_number and b.street_number and a.street_number != b.street_number and sn_score < 0.6:
        weighted *= 0.30
    if a.city and b.city and city_score < 0.60:
        weighted *= 0.50

    # Same building, different unit -> cap at AMBIGUOUS band.
    if (
        matched["street_number"] and matched["street_name"] and matched["city"]
        and a.unit and b.unit and a.unit != b.unit
    ):
        weighted = min(weighted, 0.75)

    return min(weighted, 1.0), matched


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def verify_subject_address(
    extracted_address: str,
    subject_address: str,
    *,
    match_threshold: float = 0.85,
    ambiguous_threshold: float = 0.55,
) -> AddressMatchResult:
    """Compare extracted-from-deed address against the subject address.

    Returns AddressMatchResult; status in {"MATCH","NO_MATCH","AMBIGUOUS"}.
    """
    a = parse_address(extracted_address or "")
    b = parse_address(subject_address or "")
    similarity, matched = _score_components(a, b)

    if similarity >= match_threshold:
        status = "MATCH"
    elif similarity >= ambiguous_threshold:
        status = "AMBIGUOUS"
    else:
        status = "NO_MATCH"

    return AddressMatchResult(
        status=status,
        similarity=round(similarity, 4),
        extracted_normalized=a.normalized,
        subject_normalized=b.normalized,
        matched_components=matched,
        evidence=_build_evidence(a, b, similarity, matched, status),
    )


def _build_evidence(a, b, similarity, matched, status) -> str:
    lines = [f"status={status}, similarity={similarity:.3f}"]
    if a.street_number != b.street_number:
        lines.append(f"street_number MISMATCH: '{a.street_number}' vs '{b.street_number}'")
    else:
        lines.append(f"street_number match: '{a.street_number}'")
    if not matched.get("city", False):
        lines.append(f"city MISMATCH: '{a.city}' vs '{b.city}'")
    else:
        lines.append(f"city match: '{a.city}'")
    if not matched.get("street_name", False):
        lines.append(f"street_name diff: '{a.street_name}' vs '{b.street_name}'")
    else:
        lines.append(f"street_name match: '{a.street_name}'")
    if a.unit or b.unit:
        if a.unit != b.unit:
            lines.append(f"unit differs: '{a.unit}' vs '{b.unit}'")
        else:
            lines.append(f"unit match: '{a.unit}'")
    return "; ".join(lines)


# ---------------------------------------------------------------------------
# Address-from-free-text extraction
# ---------------------------------------------------------------------------
#
# Context: deed/mortgage texts almost always contain *several* address-shaped
# strings -- the lender's office, the preparer, "after recording return to",
# and finally the subject property. A naive "first match wins" regex picks
# the lender address in 4-of-5 mortgages we examined for the 0522 ANAND run.
# Solution: extract ALL candidates, score by proximity to context keywords,
# pick the highest scorer.

# Street-type alternation, ordered longest-first so re's leftmost-longest
# semantics prefer "BOULEVARD" over "BLVD" when both happen to match.
_STREET_TYPE_PATTERN = (
    r"(?:AVENUE|AVE\.?|"
    r"STREET|ST\.?|"
    r"TERRACE|TERR\.?|TER\.?|"
    r"BOULEVARD|BLVD\.?|"
    r"DRIVE|DR\.?|DRV\.?|"
    r"ROAD|RD\.?|"
    r"LANE|LN\.?|"
    r"COURT|CT\.?|"
    r"PLACE|PL\.?|"
    r"HIGHWAY|HWY\.?|"
    r"PARKWAY|PKWY\.?|"
    r"CIRCLE|CIR\.?|"
    r"TRAIL|TRL\.?|"
    r"POINT|PT\.?|"
    r"CROSSING|XING|"
    r"WAY|"
    r"SQUARE|SQ\.?"
    r")"
)

# Build a single mega-pattern. We use (?ix) so it's case-insensitive and
# verbose (allows comments + whitespace in the pattern itself).
_ADDRESS_RE = re.compile(
    r"""
    \b
    (?P<num>\d+(?:-\d+)?)                            # street number e.g. 2856 or 10-12
    \s+
    (?:(?P<dir1>N|S|E|W|NE|NW|SE|SW|NORTH|SOUTH|EAST|WEST|NORTHEAST|NORTHWEST|SOUTHEAST|SOUTHWEST)\s+)?
    (?P<name>
        (?:[A-Z0-9][A-Za-z0-9.'-]*(?:\s+(?!(?:UNIT|APT|STE|SUITE|FLOOR|FL|BLDG)\b)[A-Z0-9][A-Za-z0-9.'-]*){0,5})
        (?:\s+(?:1st|2nd|3rd|\d{1,3}(?:st|nd|rd|th)?))?     # ordinal "27th"/"27"
    )
    \s+
    (?P<stype>""" + _STREET_TYPE_PATTERN + r""")\.?
    (?:\s+(?P<dir2>N|S|E|W|NE|NW|SE|SW))?            # trailing directional
    (?P<unit>\s+(?:UNIT|APT|STE|SUITE|\#)\s*\S+)?
    \s*,\s*
    (?P<city>[A-Za-z][A-Za-z .'-]{1,40}?)
    \s*,\s*
    (?P<state>
        FL|FLORIDA|CA|CALIFORNIA|TX|TEXAS|NY|NEW\sYORK|OH|OHIO|GA|GEORGIA
    )
    (?:\s+(?P<zip>\d{5}(?:-\d{4})?))?
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Context keywords with score deltas. Keys are lowercase; we lowercase the
# context window before matching. The window is +/- KEYWORD_WINDOW chars.
_POSITIVE_KEYWORDS: List[Tuple[str, float]] = [
    ("currently has the address of", 5.0),
    ("property address",              4.0),
    ("subject property",              4.0),
    ("commonly known as",             3.5),
    ("property:",                     3.0),
    ("located at",                    3.0),
    ("situate at",                    3.0),
    ("real property",                 2.0),
    ("premises:",                     2.0),
]

_NEGATIVE_KEYWORDS: List[Tuple[str, float]] = [
    ("lender's address",       -3.0),
    ("lender address",         -3.0),
    ("notice to lender",       -3.0),
    ("after recording return", -3.0),
    ("when recorded mail",     -3.0),
    ("recording requested by", -2.5),
    ("prepared by",            -2.0),
    ("return to:",             -2.5),
    ("loan number",            -2.0),
    ("mortgagee:",             -2.0),
]

# Look this many characters BEFORE the address match for keyword evidence.
# Most deed preambles ("which currently has the address of <ADDR>") put the
# keyword immediately before, so we weight the preceding window heavier.
_KEYWORD_PRE_WINDOW = 200
_KEYWORD_POST_WINDOW = 40


def _hint_tokens(subject_hint: str) -> Tuple[str, set]:
    """Extract (street_number, set-of-name-tokens) from a subject hint."""
    comp = parse_address(subject_hint)
    name_toks = set()
    if comp.street_name:
        for tok in comp.street_name.split():
            # Strip ordinal suffixes so "27th" / "27" / "27TH" all match.
            t = re.sub(r"(?i)(st|nd|rd|th)$", "", tok)
            if t:
                name_toks.add(t.upper())
    return comp.street_number, name_toks


def _score_candidate(
    text: str,
    match: re.Match,
    candidate_str: str,
    subject_hint_number: str,
    subject_hint_name_toks: set,
) -> Tuple[float, List[str]]:
    """Return (score, list-of-evidence-keywords-fired) for a single candidate."""
    score = 0.0
    fired: List[str] = []

    start = max(0, match.start() - _KEYWORD_PRE_WINDOW)
    end = min(len(text), match.end() + _KEYWORD_POST_WINDOW)
    window = text[start:end].lower()

    for kw, delta in _POSITIVE_KEYWORDS:
        if kw in window:
            score += delta
            fired.append(f"+{delta}:{kw}")
    for kw, delta in _NEGATIVE_KEYWORDS:
        if kw in window:
            score += delta  # delta is negative
            fired.append(f"{delta}:{kw}")

    # Hint boost: candidate shares the subject's street# or any street-name token.
    if subject_hint_number or subject_hint_name_toks:
        cand_comp = parse_address(candidate_str)
        cand_name_toks = set()
        for tok in cand_comp.street_name.split():
            t = re.sub(r"(?i)(st|nd|rd|th)$", "", tok)
            if t:
                cand_name_toks.add(t.upper())

        if subject_hint_number and cand_comp.street_number == subject_hint_number:
            score += 1.5
            fired.append("+1.5:hint_street_number")
        overlap = cand_name_toks & subject_hint_name_toks
        if overlap:
            score += 1.5
            fired.append(f"+1.5:hint_name_tokens={sorted(overlap)}")

    return score, fired


def extract_subject_address_from_text(
    text: str,
    *,
    subject_hint: Optional[str] = None,
    return_all_candidates: bool = False,
) -> Union[str, Tuple[str, List[Tuple[str, float, str]]]]:
    """Find the most likely SUBJECT-PROPERTY address in a deed/mortgage text.

    Strategy:
      1. Extract ALL address-shaped candidates from `text` (street# +
         name + street-type + city + state [+ zip]).
      2. Score each candidate by proximity to context keywords. Positive
         keywords (e.g. "currently has the address of", "Property Address:",
         "Subject Property:") add score; negative keywords (e.g. "Lender's
         address", "After recording return to:", "Prepared by") subtract.
      3. If `subject_hint` is given, give candidates that share the subject's
         street-number or street-name-tokens a +1.5 boost.
      4. Return the highest-scoring candidate. With `return_all_candidates=True`
         return (best, [(candidate_str, score, evidence), ...]).

    The function NEVER raises on bad input -- it returns "" (or ("", []))
    when no address-shaped substring is found.
    """
    if not text:
        return ("", []) if return_all_candidates else ""

    hint_num, hint_name_toks = ("", set())
    if subject_hint:
        hint_num, hint_name_toks = _hint_tokens(subject_hint)

    candidates: List[Tuple[str, float, str, int]] = []  # str, score, evidence, start
    seen_spans: set = set()
    for m in _ADDRESS_RE.finditer(text):
        # Trim trailing punctuation/whitespace from the matched span.
        cand = m.group(0).strip().rstrip(".,;:")
        # Skip duplicates from overlapping matches.
        key = (m.start(), m.end())
        if key in seen_spans:
            continue
        seen_spans.add(key)

        score, fired = _score_candidate(
            text, m, cand, hint_num, hint_name_toks
        )
        candidates.append((cand, score, ", ".join(fired), m.start()))

    if not candidates:
        return ("", []) if return_all_candidates else ""

    # Sort by (score desc, position asc) -- ties go to whichever appears first
    # in the document, which matches the legacy "first match" behaviour.
    candidates.sort(key=lambda c: (-c[1], c[3]))
    best = candidates[0][0]

    if return_all_candidates:
        public_candidates = [(c[0], c[1], c[2]) for c in candidates]
        return best, public_candidates
    return best


# ---------------------------------------------------------------------------
# F7: Lender-HQ rescue
# ---------------------------------------------------------------------------
#
# F7 is the failure mode where the highest-scored candidate in a mortgage
# document is the lender's office (e.g. "6850 Miller Road, Brecksville, OH
# 44141" for CrossCountry, or "7455 Chancellor Drive, Orlando, FL" for
# SunTrust) and the negative-keyword window didn't catch it because the
# document is dense and the keyword sits >200 chars upstream.
#
# When the primary extraction returns NO_MATCH or AMBIGUOUS against the
# declared subject address, the rescuer re-examines ALL candidates and
# promotes the first one that satisfies BOTH:
#   (a) it shares the subject's street-number, AND
#   (b) it shares >= 1 street-name token with the subject.
#
# Only if a rescued candidate exists do we re-verify; otherwise we leave
# the primary verdict in place. This was the per-case glue code in
# Manatee_FERNANDEZ_v1; promoted here so it runs on every Phase 1 verify
# without per-case patches.


def verify_with_lender_hq_rescue(
    document_text: str,
    subject_address: str,
    *,
    primary_extracted_address: Optional[str] = None,
    match_threshold: float = 0.85,
    ambiguous_threshold: float = 0.55,
    use_subject_hint_on_primary: bool = False,
) -> Tuple[AddressMatchResult, Optional[str]]:
    """Verify the primary-extracted address against the subject; if it doesn't
    MATCH, scan ALL address candidates in ``document_text`` and promote the
    first one matching the subject's street# + street-name tokens.

    Designed for the F7 lender-HQ failure mode (see module docstring).

    Args:
      document_text: Full OCR'd document body.
      subject_address: Declared subject property address.
      primary_extracted_address: The address the caller's primary extractor
        already chose. If None, this function runs its own primary pass over
        ``document_text``. Pass the original extractor's output when the
        upstream pipeline does NOT pass a subject_hint (i.e. it's vulnerable
        to F7) — the rescue then upgrades only when the primary failed.
      use_subject_hint_on_primary: When ``primary_extracted_address`` is None,
        controls whether the internal primary pass passes a subject_hint
        boost. Default False so the rescue function defends against the
        no-hint failure mode that the original Manatee glue was patched
        against. Set True to mimic newer pipelines that already use the
        hint boost during primary extraction.

    Returns:
      (result, rescued_address_or_None). When the rescue fires,
      ``rescued_address_or_None`` is the candidate string that was promoted
      and ``result`` carries the re-verification of that candidate with
      evidence annotated with "F7 lender-HQ rescue".
    """
    # Determine the primary extraction.
    if primary_extracted_address is None:
        hint = subject_address if use_subject_hint_on_primary else None
        primary = extract_subject_address_from_text(
            document_text, subject_hint=hint
        )
    else:
        primary = primary_extracted_address

    primary_result = verify_subject_address(
        primary or "", subject_address,
        match_threshold=match_threshold,
        ambiguous_threshold=ambiguous_threshold,
    )
    if primary_result.status == "MATCH":
        return primary_result, None

    hint_num, hint_name_toks = _hint_tokens(subject_address)
    if not hint_num and not hint_name_toks:
        return primary_result, None

    # Pull ALL candidates (with subject hint so the scorer's hint boost
    # surfaces the buried subject candidate first).
    _best, all_candidates = extract_subject_address_from_text(
        document_text, subject_hint=subject_address, return_all_candidates=True
    )

    for cand_str, _score, _evidence in all_candidates:
        if cand_str == primary:
            continue
        cand_comp = parse_address(cand_str)
        cand_name_toks = set()
        for tok in cand_comp.street_name.split():
            t = re.sub(r"(?i)(st|nd|rd|th)$", "", tok)
            if t:
                cand_name_toks.add(t.upper())
        same_number = bool(
            hint_num and cand_comp.street_number == hint_num
        )
        name_overlap = bool(cand_name_toks & hint_name_toks)
        if same_number and name_overlap:
            rescued_result = verify_subject_address(
                cand_str, subject_address,
                match_threshold=match_threshold,
                ambiguous_threshold=ambiguous_threshold,
            )
            if rescued_result.status == "MATCH":
                rescued_result.evidence = (
                    f"PRIMARY EXTRACTION ({primary!r}) returned {primary_result.status} "
                    f"(probable lender/preparer address); "
                    f"body contains subject address — promoted via F7 lender-HQ rescue. "
                    f"{rescued_result.evidence}"
                )
                return rescued_result, cand_str

    return primary_result, None


__all__ = [
    "AddressMatchResult",
    "verify_subject_address",
    "verify_with_lender_hq_rescue",
    "parse_address",
    "extract_subject_address_from_text",
]
