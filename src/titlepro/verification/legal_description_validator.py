"""Post-generation Legal Description integrity validator.

After the RAW or Title report markdown is written, this validator compares
the report's Legal Description section against the deterministically-
extracted verbatim block in `legal_descriptions.json`. If the AI silently
paraphrased or dropped substantive clauses, the validator fails loudly.

See `docs/audits/legal_description_ordering_audit_2026-05-18.md` for the
audit evidence and the Phase 3 spec this implements.

Public API:
    validate_legal_description(generated_md_path, legal_descriptions_path,
                               strict=True) -> ValidationResult
    repair_legal_description_section(generated_md_path,
                               legal_descriptions_path) -> RepairResult
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Union


PathLike = Union[str, Path]


@dataclass
class ValidationResult:
    """Outcome of `validate_legal_description`.

    Attributes:
        success: True when at least one verbatim block matched at >= 0.95
            similarity OR all `verification_required` tokens were present
            for at least one deed entry.
        best_similarity: Highest Jaccard similarity across all candidate
            verbatim blocks.
        best_doc_number: Document number of the deed entry that scored
            `best_similarity`.
        matched_tokens: Tokens (e.g. "EXCEPTING THEREFROM", APN with
            check digit) confirmed present in the generated md.
        missing_tokens: Tokens that SHOULD have been present per the
            sidecar but were not found in the generated md.
        details: Free-form notes (e.g. "no sidecar", "no Legal Description
            section").
    """

    success: bool
    best_similarity: float = 0.0
    best_doc_number: Optional[str] = None
    matched_tokens: list[str] = field(default_factory=list)
    missing_tokens: list[str] = field(default_factory=list)
    details: str = ""


_WHITESPACE_RE = re.compile(r"\s+")
_MD_EMPHASIS_RE = re.compile(r"[*_`]+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]")


def _normalize_for_similarity(text: str) -> str:
    """Lowercase, strip markdown emphasis + punctuation, collapse whitespace."""
    if not text:
        return ""
    out = text.lower()
    out = _MD_EMPHASIS_RE.sub(" ", out)
    out = _NON_ALNUM_RE.sub(" ", out)
    out = _WHITESPACE_RE.sub(" ", out).strip()
    return out


def _tokenize(normalized: str) -> set[str]:
    """Token set for Jaccard. Tokens length >= 2 to skip noise."""
    return {tok for tok in normalized.split(" ") if len(tok) >= 2}


def jaccard_similarity(a: str, b: str) -> float:
    """Jaccard similarity over normalized token sets. 0.0 on empty inputs."""
    ta = _tokenize(_normalize_for_similarity(a))
    tb = _tokenize(_normalize_for_similarity(b))
    if not ta or not tb:
        return 0.0
    intersection = ta & tb
    union = ta | tb
    return round(len(intersection) / len(union), 4) if union else 0.0


_LEGAL_HEADER_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"(?im)^##\s+LEGAL\s+DESCRIPTION\b[^\n]*$"),
    re.compile(r"(?im)^###\s+(?:[A-Z]\.\s+)?Legal\s+Description\b[^\n]*$"),
    re.compile(r"(?im)^##\s+Legal\s+Description\b[^\n]*$"),
)


def _extract_legal_section(md: str) -> str:
    """Return the text under the Legal Description heading until the next
    H2 (or H1) heading. If no heading is found, return the whole md so the
    similarity check still operates against the available content (LLMs
    occasionally drop the heading but include the block elsewhere)."""
    if not md:
        return ""
    best_start = -1
    for pattern in _LEGAL_HEADER_PATTERNS:
        m = pattern.search(md)
        if m and (best_start < 0 or m.start() < best_start):
            best_start = m.end()
    if best_start < 0:
        return md
    # Find next H1/H2 boundary
    tail = md[best_start:]
    next_heading = re.search(r"\n##?\s+\S", tail)
    if next_heading:
        return tail[: next_heading.start()].strip()
    return tail.strip()


def _required_tokens_for_entry(entry: dict) -> list[str]:
    """Tokens that MUST appear in the generated md for an entry to pass
    the verification fallback. Specifically the APN with check digit and
    a few high-signal substring tokens from the verbatim block."""
    tokens: list[str] = []
    apn = (entry.get("apn_verbatim") or "").strip()
    if apn:
        tokens.append(apn)
    block = (entry.get("legal_description_verbatim") or "").upper()
    for needle in (
        "EXCEPTING THEREFROM",
        "VOLUME",
        "THIS BEING THE SAME PROPERTY",
        "PARCEL NO",
    ):
        if needle in block:
            tokens.append(needle)
    return tokens


def validate_legal_description(
    generated_md_path: PathLike,
    legal_descriptions_path: PathLike,
    *,
    similarity_threshold: float = 0.95,
    strict: bool = True,
) -> ValidationResult:
    """Validate `generated_md_path` against `legal_descriptions_path`.

    Returns a `ValidationResult`. When `strict=True` and the result is
    not successful, callers should raise (the pipeline does so).

    Pass criteria:
      * `success=True` when ANY entry's verbatim block has Jaccard
        similarity >= `similarity_threshold` against the extracted Legal
        Description section of the generated md, OR
      * All `_required_tokens_for_entry` tokens for at least one entry
        are present (substring match) in the generated md.
    """
    md_path = Path(generated_md_path)
    sidecar_path = Path(legal_descriptions_path)

    if not sidecar_path.exists():
        return ValidationResult(
            success=True,  # nothing to validate against; do not block.
            details=f"sidecar missing: {sidecar_path.name}",
        )
    if not md_path.exists():
        return ValidationResult(
            success=False,
            details=f"generated md missing: {md_path}",
        )

    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return ValidationResult(
            success=True,  # cannot validate; pass through.
            details=f"sidecar unparseable: {exc}",
        )
    if not isinstance(sidecar, dict) or not sidecar:
        return ValidationResult(
            success=True,
            details="sidecar empty",
        )

    md_text = md_path.read_text(encoding="utf-8")
    section = _extract_legal_section(md_text)
    section_norm = _normalize_for_similarity(section)

    best_sim = 0.0
    best_doc = None
    aggregated_matched: list[str] = []
    aggregated_missing: list[str] = []

    any_entry_passed_tokens = False
    any_entry_passed_similarity = False
    any_entry_verbatim_present = False
    entries_with_blocks = 0

    for doc_num, entry in sidecar.items():
        if not isinstance(entry, dict):
            continue
        block = entry.get("legal_description_verbatim") or ""
        if not block.strip():
            # Entry without a verbatim block can't be the source of truth.
            continue
        entries_with_blocks += 1

        sim = jaccard_similarity(section, block)
        if sim > best_sim:
            best_sim = sim
            best_doc = doc_num
        if sim >= similarity_threshold:
            any_entry_passed_similarity = True

        # Strongest signal: the verbatim block appears verbatim (normalized
        # substring) in the Legal Description section. This is exactly what a
        # successful deterministic splice produces, so it must pass even when
        # appended citation/parcel lines dilute the Jaccard score.
        block_norm = _normalize_for_similarity(block)
        if block_norm and len(block_norm) >= 40 and block_norm in section_norm:
            any_entry_verbatim_present = True
            if best_doc is None or sim >= best_sim:
                best_doc = doc_num

        # Token presence check (case-insensitive substring).
        md_upper = md_text.upper()
        section_upper = section.upper()
        required = _required_tokens_for_entry(entry)
        if required:
            present = [t for t in required if t.upper() in md_upper or t.upper() in section_upper]
            absent = [t for t in required if t not in present]
            if present:
                aggregated_matched.extend(present)
            if absent:
                aggregated_missing.extend(absent)
            if not absent:
                any_entry_passed_tokens = True

    # When NO entries had a verbatim block to compare against, there is
    # nothing to validate — treat as passthrough (success=True).
    if entries_with_blocks == 0:
        return ValidationResult(
            success=True,
            details="no entries with verbatim block",
        )

    success = (
        any_entry_passed_similarity
        or any_entry_passed_tokens
        or any_entry_verbatim_present
    )

    details_parts = []
    if any_entry_verbatim_present:
        details_parts.append("verbatim block present")
    if not success:
        details_parts.append(
            f"best similarity {best_sim:.3f} < {similarity_threshold}"
        )
        if aggregated_missing:
            details_parts.append(
                f"missing tokens: {sorted(set(aggregated_missing))}"
            )
    return ValidationResult(
        success=success,
        best_similarity=best_sim,
        best_doc_number=best_doc,
        matched_tokens=sorted(set(aggregated_matched)),
        missing_tokens=sorted(set(aggregated_missing)),
        details="; ".join(details_parts) if details_parts else "ok",
    )


# ---------------------------------------------------------------------------
# Deterministic Legal Description splice (#3, 2026-06-14).
# The verbatim Exhibit A is already extracted into legal_descriptions.json by
# the pipeline's deterministic extractor. Rather than hard-fail (and force a
# full agentic regeneration) when the LLM paraphrases it, splice the canonical
# verbatim block back into the generated report's Legal Description section.
# This is exactly what the prompt's "★ CANONICAL — RENDER VERBATIM" rule asks
# for, made deterministic. Eliminates the single most common regen trigger.
# ---------------------------------------------------------------------------

# Mirror of pipeline._DOT_BOILERPLATE_MARKERS: entries with >=3 of these are
# captured Deed-of-Trust covenant text, not a real Exhibit A.
_DOT_BOILERPLATE_MARKERS = (
    "BORROWER COVENANTS",
    "UNIFORM COVENANTS",
    "Security Instrument",
    "Fannie Mae",
    "Freddie Mac",
    "Form 3005",
    "Ellie Mae",
)

# Signals that a non-boilerplate block is a real legal description. Broad on
# purpose: CA plats say LOT/BLOCK/TRACT; FL legals often use FOLIO/PIN/metes-
# and-bounds ("BEGINNING AT ... THENCE ...") with no LOT at all (this is what
# the FROMER/Hillsborough benchmark exposed — a 669-char folio legal that the
# old LOT/PARCEL-only gate wrongly rejected).
_LEGAL_SIGNAL_TOKENS = (
    "LOT", "BLOCK", "PARCEL", "TRACT", "UNIT", "FOLIO", "PIN NO", "PIN:",
    "PLAT", "SECTION", "TOWNSHIP", "RANGE", "SUBDIVISION", "CONDOMINIUM",
    "BEGINNING AT", "THENCE", "POINT OF BEGINNING", "METES AND BOUNDS",
    "DESCRIBED AS FOLLOWS", "BEING FURTHER DESCRIBED", "ACCORDING TO THE PLAT",
)


def _looks_like_legal_description(block_upper: str) -> bool:
    """True when the (uppercased) block carries at least one legal-description
    signal token. Replaces the old LOT/PARCEL-only gate so FL folio/metes
    legals are not silently rejected."""
    return any(tok in block_upper for tok in _LEGAL_SIGNAL_TOKENS)


# Document-type classification for canonical-entry selection (P1, 2026-06-16).
# The legal-description extractor indexes EVERY document, including mortgages
# and deeds-of-trust whose "Exhibit A" can be longer than the vesting deed's.
# Ranking purely by block length let a security instrument win and get spliced
# over the RAW/Title legal section + source instrument. We now classify each
# entry's `document_type` and prefer current/vesting deeds, strongly
# deprioritizing security instruments. `document_type` values seen in the wild
# carry bullet prefixes + parenthetical codes (e.g. "(D) DEED", "• Deed •",
# "GRANT DEED", "DEED OF TRUST", "TRUST DEED"), so match on normalized
# substrings rather than exact equality. Note: "DEED OF TRUST"/"TRUST DEED"
# both contain the word "DEED", so the security check MUST run first.

# Higher rank wins. Security instruments sort below the unknown/heuristic
# fallback so a deed (or even a type-less entry) always beats a mortgage.
_DOCTYPE_RANK_DEED = 2          # vesting / conveyance deed — preferred
_DOCTYPE_RANK_UNKNOWN = 1       # missing/unrecognized type — fall back to heuristic
_DOCTYPE_RANK_SECURITY = 0      # mortgage / deed-of-trust — strongly deprioritized

# Substrings (uppercased) that mark a security instrument, NOT a vesting deed.
_SECURITY_DOCTYPE_TOKENS = (
    "DEED OF TRUST",
    "TRUST DEED",
    "MORTGAGE",
    "SECURITY INSTRUMENT",
    "SECURITY DEED",
    "ASSIGNMENT OF",
    "SUBORDINATION",
    "MODIFICATION",
    "HELOC",
    "LINE OF CREDIT",
)

# Substrings (uppercased) that mark a current/prior vesting deed. Broad on
# purpose: covers WD/QCD/Special-Rep/Personal-Rep/Trustee/Tax/Grant/Corrective
# deeds and the bullet/parenthetical-prefixed variants the extractor emits.
_DEED_DOCTYPE_TOKENS = (
    "DEED",          # generic — runs AFTER the security check above
    "CONVEYANCE",
    "GRANT",
)


def _classify_doctype_rank(document_type: Optional[str]) -> int:
    """Rank an entry's document_type for canonical selection. Higher wins.

    Security instruments (mortgage / deed-of-trust) → 0; missing/unknown →
    1 (existing length/APN heuristic decides); vesting deeds → 2.
    """
    if not document_type:
        return _DOCTYPE_RANK_UNKNOWN
    up = document_type.upper()
    # Security check FIRST — "DEED OF TRUST"/"TRUST DEED" also contain "DEED".
    if any(tok in up for tok in _SECURITY_DOCTYPE_TOKENS):
        return _DOCTYPE_RANK_SECURITY
    if any(tok in up for tok in _DEED_DOCTYPE_TOKENS):
        return _DOCTYPE_RANK_DEED
    return _DOCTYPE_RANK_UNKNOWN

# Label-like lines worth preserving from the original section (source-instrument
# citation + parcel id), so the splice keeps the report's required citations.
_PRESERVE_LINE_RE = re.compile(
    r"(?im)^\s*(?:[-*>]\s*)?(?:\*\*|__)?\s*"
    r"(source\s+instrument|instrument\s+no|document\s+no|recorded|"
    r"or\s+book|book\s*/?\s*page|book\s+\d|parcel\s+id|parcel\s+no|"
    r"parcel\s+identification|a\.?p\.?n\.?|\bapn\b|\bpin\b)"
)


@dataclass
class RepairResult:
    """Outcome of `repair_legal_description_section`.

    Attributes:
        changed: True when the markdown was rewritten with the canonical block.
        text: The (possibly rewritten) markdown.
        canonical_doc_number: Source document the verbatim block came from.
        reason: Why the repair did or did not run (for the phase summary).
    """

    changed: bool
    text: str
    canonical_doc_number: Optional[str] = None
    reason: str = ""


def pick_canonical_entry(sidecar: dict) -> Optional[tuple[str, dict]]:
    """Pick the (doc_number, entry) whose verbatim legal block is the canonical
    Exhibit A for the subject. Heuristic mirrors pipeline._pick_canonical_legal_doc:
    drop entries with >=3 DoT boilerplate markers and require a legal-description
    signal token. Selection prefers current/vesting **deed** entries and strongly
    deprioritizes mortgage / deed-of-trust / security-instrument entries by
    `document_type` (P1) — a deed must win over a longer mortgage "Exhibit A".
    The existing block-length + APN-length tie-break is applied WITHIN the
    preferred class. When `document_type` is missing/unknown, the entry falls
    back to the length/APN heuristic rather than being dropped.
    Returns None when no entry qualifies.
    """
    candidates: list[tuple[int, int, int, str, dict]] = []
    for doc_num, entry in sidecar.items():
        if not isinstance(entry, dict):
            continue
        block = (entry.get("legal_description_verbatim") or "").strip()
        if not block:
            continue
        junk = sum(1 for m in _DOT_BOILERPLATE_MARKERS if m in block)
        if junk >= 3:
            continue
        upper = block.upper()
        if not _looks_like_legal_description(upper):
            continue
        doctype_rank = _classify_doctype_rank(entry.get("document_type"))
        apn_len = len((entry.get("apn_verbatim") or "").strip())
        candidates.append((doctype_rank, len(block), apn_len, doc_num, entry))
    if not candidates:
        return None
    # Primary key: document_type rank (deed > unknown > security). Tie-break
    # WITHIN the class by block length then APN length, as before.
    candidates.sort(key=lambda c: (c[0], c[1], c[2]), reverse=True)
    best = candidates[0]
    return best[3], best[4]


def _build_canonical_section_body(doc_num: str, entry: dict, original_section: str) -> str:
    """Assemble the replacement body: verbatim block + authoritative APN +
    preserved source-instrument citation lines from the original section."""
    block = (entry.get("legal_description_verbatim") or "").strip()
    apn = (entry.get("apn_verbatim") or "").strip()
    doc_type = entry.get("document_type") or "Deed"

    lines: list[str] = [block]

    block_upper = block.upper()
    apn_line_emitted = bool(apn and apn.upper() not in block_upper)
    # Authoritative parcel id (only if the block didn't already carry it).
    if apn_line_emitted:
        lines.append("")
        lines.append(f"Parcel Identification Number: {apn}")

    # Preserve the report's source-instrument citation lines (dedup, keep order),
    # but skip parcel/APN lines since we just emitted the authoritative one.
    preserved: list[str] = []
    seen: set[str] = set()
    for raw_line in original_section.splitlines():
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if not _PRESERVE_LINE_RE.match(line):
            continue
        low = line.strip().lower()
        if any(tok in low for tok in ("parcel", "apn", "pin")):
            continue  # parcel id already handled authoritatively above
        key = re.sub(r"\s+", " ", low)
        if key in seen:
            continue
        seen.add(key)
        preserved.append(line.strip())

    if preserved:
        # A source citation survived from the original section — keep it.
        if not apn_line_emitted:
            lines.append("")  # APN line already inserted its own blank separator
        lines.extend(preserved)
    else:
        # No source citation preserved — the report prompt REQUIRES one, so emit
        # a deterministic fallback. This must happen REGARDLESS of whether an APN
        # line was emitted (P2a): the APN line is not a source-instrument citation.
        if not apn_line_emitted:
            lines.append("")  # APN line already inserted its own blank separator
        lines.append(f"Source Instrument: Document No. {doc_num} ({doc_type})")

    return "\n".join(lines).strip()


def repair_legal_description_section(
    generated_md_path: PathLike,
    legal_descriptions_path: PathLike,
) -> RepairResult:
    """Splice the canonical verbatim legal description into the generated md.

    Returns a `RepairResult`. Does NOT write to disk — the caller persists
    `result.text` when `result.changed`. No-ops (changed=False) when there is
    no sidecar, no canonical block, or no Legal Description heading to anchor
    the splice (we never fabricate a section).
    """
    md_path = Path(generated_md_path)
    sidecar_path = Path(legal_descriptions_path)

    if not md_path.exists():
        return RepairResult(False, "", reason=f"generated md missing: {md_path}")
    md_text = md_path.read_text(encoding="utf-8")

    if not sidecar_path.exists():
        return RepairResult(False, md_text, reason="sidecar missing")
    try:
        sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return RepairResult(False, md_text, reason=f"sidecar unparseable: {exc}")
    if not isinstance(sidecar, dict) or not sidecar:
        return RepairResult(False, md_text, reason="sidecar empty")

    picked = pick_canonical_entry(sidecar)
    if not picked:
        return RepairResult(False, md_text, reason="no canonical block")
    doc_num, entry = picked

    # Locate the Legal Description heading (earliest match across patterns).
    best_start = -1
    for pattern in _LEGAL_HEADER_PATTERNS:
        m = pattern.search(md_text)
        if m and (best_start < 0 or m.start() < best_start):
            best_start = m.end()
    if best_start < 0:
        return RepairResult(
            False, md_text, canonical_doc_number=doc_num, reason="no legal heading"
        )

    tail = md_text[best_start:]
    next_heading = re.search(r"\n##?\s+\S", tail)
    section_end = best_start + next_heading.start() if next_heading else len(md_text)
    original_section = md_text[best_start:section_end]

    new_body = _build_canonical_section_body(doc_num, entry, original_section)
    new_text = md_text[:best_start] + "\n\n" + new_body + "\n\n" + md_text[section_end:]
    # Collapse any >2 consecutive blank lines introduced at the seam.
    new_text = re.sub(r"\n{3,}", "\n\n", new_text)

    if new_text.strip() == md_text.strip():
        return RepairResult(
            False, md_text, canonical_doc_number=doc_num, reason="already canonical"
        )
    return RepairResult(
        True, new_text, canonical_doc_number=doc_num, reason="spliced canonical block"
    )
