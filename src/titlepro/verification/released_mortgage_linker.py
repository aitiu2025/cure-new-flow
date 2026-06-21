"""Released Mortgage Linker.

Given a corpus of recorder documents and their extracted-markdown text,
classify each mortgage as `open`, `released`, `modified`, or `subordinate`
and capture the cross-reference link (which satisfaction/release/discharge
instrument cleared which mortgage).

Motivated by Tony Roveda's Broward Test Review (2026-05-21):
  CURE's ANAND report showed mortgages `111249687`, `112424642`,
  `110509371` as still open even though all three had been satisfied.
  This module rebuilds the release graph from raw doc text so the
  downstream report can render the correct status.

2026-05-23 update — `classify_mortgages` now accepts an optional
``recovered_docs`` kwarg. Use this to splice satisfactions/releases that
were silently dropped by an upstream search-side filter (Broward F9 bug)
back into the working corpus. See ``not_needed_audit.audit_not_needed``
for the producer.

Public API:
    classify_mortgages(documents, extracted_texts, *, inferred_types=None,
                       recovered_docs=None) -> Dict[doc_num, MortgageClassification]
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Set


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ReleaseLink:
    mortgage_doc_number: str
    satisfaction_doc_number: str
    satisfaction_type: str  # "satisfaction" | "release" | "discharge"
    evidence_text: str

    def to_dict(self) -> dict:
        return {
            "mortgage_doc_number": self.mortgage_doc_number,
            "satisfaction_doc_number": self.satisfaction_doc_number,
            "satisfaction_type": self.satisfaction_type,
            "evidence_text": self.evidence_text,
        }


@dataclass
class MortgageClassification:
    doc_number: str
    status: str  # "open" | "released" | "modified" | "subordinate"
    release_chain: List[ReleaseLink] = field(default_factory=list)
    related_modifications: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "doc_number": self.doc_number,
            "status": self.status,
            "release_chain": [r.to_dict() for r in self.release_chain],
            "related_modifications": list(self.related_modifications),
        }


# ---------------------------------------------------------------------------
# Doc-type classification
# ---------------------------------------------------------------------------

SATISFACTION_TYPE_MARKERS = {
    "satisfaction": ("SATISFACTION",),
    "release": ("RELEASE",),
    "discharge": ("DISCHARGE",),
}

MODIFICATION_MARKERS = ("MODIFICATION", "MODIFY")
SUBORDINATION_MARKERS = ("SUBORDINATION", "SUBORDINATE")
ASSIGNMENT_MARKERS = ("ASSIGNMENT",)

# A doc type that contains MORTGAGE/MTG but ALSO any of these is NOT a mortgage.
NOT_MORTGAGE_IF_PRESENT = (
    "SATISFACTION",
    "RELEASE",
    "DISCHARGE",
    "MODIFICATION",
    "SUBORDINATION",
    "ASSIGNMENT",
)


def _doc_type(doc: dict) -> str:
    return (doc.get("document_type") or doc.get("doc_type") or "").upper()


def _doc_number(doc: dict) -> str:
    for k in ("doc_number", "document_number", "instrument_number", "instrument", "number"):
        v = doc.get(k)
        if v:
            return str(v).strip()
    return ""


def is_mortgage(doc: dict) -> bool:
    t = _doc_type(doc)
    if not t:
        return False
    if not ("MORTGAGE" in t or re.search(r"\bMTG\b", t)):
        return False
    return not any(marker in t for marker in NOT_MORTGAGE_IF_PRESENT)


def satisfaction_kind(doc: dict) -> Optional[str]:
    t = _doc_type(doc)
    if not t:
        return None
    for kind, markers in SATISFACTION_TYPE_MARKERS.items():
        if any(m in t for m in markers):
            return kind
    return None


def is_modification(doc: dict) -> bool:
    t = _doc_type(doc)
    return any(m in t for m in MODIFICATION_MARKERS)


def is_subordination(doc: dict) -> bool:
    t = _doc_type(doc)
    return any(m in t for m in SUBORDINATION_MARKERS)


# ---------------------------------------------------------------------------
# Inferred-type helpers (used when the search-result `document_type`
# column is unreliable, e.g. Broward where the column holds a grantee
# name rather than the legal doc type).
# ---------------------------------------------------------------------------


def _is_mortgage_inferred(inferred: str) -> bool:
    return inferred == "MORTGAGE"


def _satisfaction_kind_inferred(inferred: str) -> Optional[str]:
    if inferred == "SATISFACTION":
        return "satisfaction"
    if inferred == "RELEASE":
        return "release"
    # `discharge` doesn't have a dedicated canonical type in the
    # classifier; treat anything with "DISCHARGE" wording as a RELEASE.
    return None


def _is_modification_inferred(inferred: str) -> bool:
    return inferred == "MODIFICATION"


def _is_subordination_inferred(inferred: str) -> bool:
    return inferred == "SUBORDINATION"


# ---------------------------------------------------------------------------
# Cross-reference extraction
# ---------------------------------------------------------------------------

# Trigger phrases that indicate the *following* number is a referenced
# instrument number. We look at a window AROUND each numeric candidate.
TRIGGER_PHRASES = (
    "SATISFIES",
    "SATISFACTION OF",
    "SATISFACTION OF MORTGAGE",
    "RELEASES",
    "RELEASE OF",
    "DISCHARGES",
    "DISCHARGE OF",
    "INSTRUMENT NUMBER",
    "INSTRUMENT NO",
    "INSTRUMENT #",
    "INSTRUMENT",
    "RECORDED AS",
    "RECORDED UNDER",
    "MODIFIES",
    "MODIFICATION OF",
    "SUBORDINATES",
    "SUBORDINATION OF",
    "CLERK FILE",
    "CFN",
    "DOC #",
    "DOCUMENT NUMBER",
    "DOCUMENT NO",
    "REC#",
    "BOOK",  # weak trigger but harmless given mortgage-set filtering
)

# Instrument-number candidate (8-12 digits). Allow optional surrounding
# punctuation but not embedded in a longer digit sequence.
_INSTRUMENT_RE = re.compile(r"(?<!\d)(\d{8,12})(?!\d)")

# Refined Book/Page regex. Catches:
#   "OR BK 48462 Page 1412"   "Book: OR 49410 Page: 211"
#   "Book 48462, Page 1412"   "Bk 49468 Pg 396"
_BOOK_PAGE_RE = re.compile(
    r"(?:BOOK|BK)\s*:?\s*(?:OR\s+)?(\d{4,6})[,\s]+(?:PAGE|PG)\s*:?\s*(\d{1,5})",
    re.I,
)

# MERS MIN.
_MIN_RE = re.compile(r"MIN\s*[:#]?\s*(\d{15,20})", re.I)

# Anchored principal-amount regex.
_PRINCIPAL_RE = re.compile(
    r"original\s+principal\s+amount\s+of\s+\$?([\d,]+(?:\.\d{2})?)",
    re.I,
)

# Recorder banner end marker (Broward).
_BANNER_END_RE = re.compile(
    r"Recorded\s+\d{1,2}/\d{1,2}/\d{4}.*?(?:Deputy\s+Clerk[^\n]*|\n)",
    re.I | re.S,
)


def _strip_banner(text: str) -> str:
    """Cut off everything up to and including the recorder banner so the
    document's OWN Book/Page slot isn't confused for a cited mortgage."""
    if not text:
        return ""
    m = _BANNER_END_RE.search(text)
    if not m:
        return text
    return text[m.end():]


def _norm_money(raw: str) -> str:
    s = raw.replace("$", "").replace(",", "").strip()
    if "." not in s:
        return s
    head, _, tail = s.partition(".")
    return f"{head}.{tail[:2]}"


def _normalize_text(text: str) -> str:
    return (text or "").upper()


def _trigger_window_indices(text: str) -> List[int]:
    """Return character offsets where any trigger phrase begins."""
    offsets: List[int] = []
    for phrase in TRIGGER_PHRASES:
        start = 0
        while True:
            idx = text.find(phrase, start)
            if idx == -1:
                break
            offsets.append(idx)
            start = idx + len(phrase)
    return offsets


def find_referenced_instruments(
    text: str,
    mortgage_doc_numbers: Set[str],
    *,
    window: int = 80,
    mortgage_metadata: Optional[Dict[str, Any]] = None,
    strip_banner: bool = True,
) -> List[tuple]:
    """Extract instrument-number references from `text` that hit a mortgage.

    Returns a list of (mortgage_doc_number, snippet) tuples. A candidate
    only counts if BOTH:
      (a) it appears within `window` characters of a trigger phrase, AND
      (b) it appears in `mortgage_doc_numbers` (filters false positives).

    When ``mortgage_metadata`` is provided (mapping mortgage_doc# ->
    ``{"book": str, "page": str, "min_number": str, "original_principal":
    str}``), this function ALSO matches by Book/Page citation and MIN
    in the body. Banner-skip is applied by default so a satisfaction's
    OWN Book/Page slot isn't confused with the mortgage cite.
    """
    if not text or not mortgage_doc_numbers:
        return []

    # Banner-skip prevents the document's own recording slot from being
    # confused with a cited mortgage's slot.
    body_text = _strip_banner(text) if strip_banner else text
    upper = _normalize_text(body_text)
    triggers = _trigger_window_indices(upper)

    matches: List[tuple] = []
    seen: Set[str] = set()

    # ---- (1) Direct instrument-number reference ----
    for m in _INSTRUMENT_RE.finditer(upper):
        candidate = m.group(1)
        if candidate not in mortgage_doc_numbers:
            continue
        if candidate in seen:
            continue
        pos = m.start()
        near_trigger = any(abs(pos - t) <= window for t in triggers)
        if not near_trigger:
            continue
        snip_start = max(0, pos - 60)
        snip_end = min(len(body_text), pos + 60)
        snippet = body_text[snip_start:snip_end].replace("\n", " ").strip()
        matches.append((candidate, snippet))
        seen.add(candidate)

    if not mortgage_metadata:
        return matches

    # ---- (2) Book/Page citation match ----
    for bp in _BOOK_PAGE_RE.finditer(body_text):
        book = bp.group(1)
        page = bp.group(2)
        for mtg_num, meta in mortgage_metadata.items():
            if mtg_num in seen:
                continue
            if not isinstance(meta, dict):
                continue
            if meta.get("book") == book and meta.get("page") == page:
                snippet = body_text[
                    max(0, bp.start() - 60): min(len(body_text), bp.end() + 60)
                ].replace("\n", " ").strip()
                matches.append((mtg_num, snippet))
                seen.add(mtg_num)

    # ---- (3) MERS MIN match ----
    for mm in _MIN_RE.finditer(body_text):
        candidate_min = mm.group(1)
        for mtg_num, meta in mortgage_metadata.items():
            if mtg_num in seen:
                continue
            if not isinstance(meta, dict):
                continue
            if meta.get("min_number") and meta.get("min_number") == candidate_min:
                snippet = body_text[
                    max(0, mm.start() - 60): min(len(body_text), mm.end() + 60)
                ].replace("\n", " ").strip()
                matches.append((mtg_num, snippet))
                seen.add(mtg_num)

    # ---- (4) Principal amount (anchored keyword) ----
    for pm in _PRINCIPAL_RE.finditer(body_text):
        candidate_amt = _norm_money(pm.group(1))
        for mtg_num, meta in mortgage_metadata.items():
            if mtg_num in seen:
                continue
            if not isinstance(meta, dict):
                continue
            mtg_amt = meta.get("original_principal")
            if mtg_amt and _norm_money(str(mtg_amt)) == candidate_amt:
                snippet = body_text[
                    max(0, pm.start() - 60): min(len(body_text), pm.end() + 60)
                ].replace("\n", " ").strip()
                matches.append((mtg_num, snippet))
                seen.add(mtg_num)

    return matches


# ---------------------------------------------------------------------------
# Top-level classifier
# ---------------------------------------------------------------------------


def classify_mortgages(
    documents: List[dict],
    extracted_texts: Dict[str, str],
    inferred_types: Optional[Dict[str, str]] = None,
    *,
    recovered_docs: Optional[List[Any]] = None,
) -> Dict[str, MortgageClassification]:
    """Classify each mortgage doc as open/released/modified/subordinate.

    Args:
      documents: list of doc records (documents_found.json shape). Each
        must have at least `document_type` and a doc-number-ish field.
      extracted_texts: doc_num -> extracted markdown content. Missing
        entries are tolerated (treated as empty string).
      inferred_types: OPTIONAL doc_num -> canonical inferred type from
        ``document_type_classifier.classify_all_documents``. When
        provided, this takes priority over the (often unreliable)
        ``document_type`` field on each doc record. Use this whenever
        the recorder feed's ``document_type`` column is known to be
        wrong (e.g. Broward, where it holds the grantee name).
        When ``None``, types are auto-derived from ``extracted_texts``
        using ``classify_document_type`` — this is the common case
        and means existing call sites don't need to be patched.
      recovered_docs: OPTIONAL list of
        ``not_needed_audit.RecoveredDocument`` records. Each recovered
        doc is spliced into ``documents`` + ``extracted_texts`` at the
        top of this function so the linker treats it like any other
        downloaded doc. See ``not_needed_audit.audit_not_needed`` for
        the producer.

    Returns:
      Mapping doc_number -> MortgageClassification, one entry per mortgage.
    """
    # ---- Splice recovered docs into the working corpus ----------------
    if recovered_docs:
        # Copy to avoid mutating caller's lists/dicts.
        documents = list(documents)
        extracted_texts = dict(extracted_texts)
        for rd in recovered_docs:
            # RecoveredDocument is a dataclass; defensively handle dict-form too.
            doc_num = getattr(rd, "doc_number", None) or (
                rd.get("doc_number") if isinstance(rd, dict) else None
            )
            classified = getattr(rd, "classified_type", None) or (
                rd.get("classified_type") if isinstance(rd, dict) else None
            )
            file_path = getattr(rd, "file_path", None) or (
                rd.get("file_path") if isinstance(rd, dict) else None
            )
            if not doc_num:
                continue
            # Avoid duplicate splice if already present.
            existing_nums = {_doc_number(d) for d in documents}
            if doc_num not in existing_nums:
                documents.append({
                    "doc_number": doc_num,
                    "document_type": classified or "OTHER",
                })
            # Load text from file_path if not already in extracted_texts.
            if doc_num not in extracted_texts and file_path:
                try:
                    from pathlib import Path as _Path
                    extracted_texts[doc_num] = _Path(file_path).read_text(
                        encoding="utf-8", errors="replace"
                    )
                except Exception:
                    extracted_texts[doc_num] = ""

    # ---- Auto-derive inferred_types if recovered_docs is provided -----
    # When the caller is splicing in recovered_docs from the not_needed
    # audit, the production setting is "Broward F9 bug is in play" —
    # the doc_type field is unreliable. In that case we ALSO re-classify
    # all original docs (not just the recovered ones) by content so the
    # linker sees a consistent corpus. Legacy callers that don't pass
    # recovered_docs keep the old contract (inferred_types=None means
    # "trust doc_type", consistent with all existing tests).
    if inferred_types is None and recovered_docs:
        inferred_types = {}
        try:
            from titlepro.verification.document_type_classifier import (
                classify_document_type,
            )
            for d in documents:
                num = (
                    d.get("doc_number") or d.get("document_number")
                    or d.get("instrument_number") or d.get("instrument")
                    or d.get("number") or ""
                )
                num = str(num).strip()
                if not num:
                    continue
                text = extracted_texts.get(num, "") or ""
                if not text:
                    continue
                c = classify_document_type(
                    num, text,
                    grantee_hint=d.get("document_type"),
                )
                if c.inferred_type and c.inferred_type != "OTHER":
                    inferred_types[num] = c.inferred_type
            # Forced override for recovered docs (audit already vetted them).
            for rd in recovered_docs:
                doc_num = getattr(rd, "doc_number", None) or (
                    rd.get("doc_number") if isinstance(rd, dict) else None
                )
                classified_type = getattr(rd, "classified_type", None) or (
                    rd.get("classified_type") if isinstance(rd, dict) else None
                )
                if doc_num and classified_type:
                    inferred_types[doc_num] = classified_type
        except Exception:
            inferred_types = {}
    inferred_types = inferred_types or {}

    # ---- Predicate helpers that prefer inferred_types when present ----
    # When inferred_types yields a positive answer, use it. When it yields
    # OTHER/None (e.g. classifier had no signal because text was empty),
    # FALL BACK to the legacy ``document_type``-field predicate. This
    # keeps backward compatibility with tests/fixtures that pass valid
    # ``document_type`` strings but empty extracted_texts.
    def _mortgage_check(num: str, doc: dict) -> bool:
        inf = inferred_types.get(num)
        if inf and inf != "OTHER":
            return _is_mortgage_inferred(inf)
        return is_mortgage(doc)

    def _satisfaction_check(num: str, doc: dict) -> Optional[str]:
        inf = inferred_types.get(num)
        if inf and inf != "OTHER":
            kind = _satisfaction_kind_inferred(inf)
            if kind:
                return kind
        return satisfaction_kind(doc)

    def _modification_check(num: str, doc: dict) -> bool:
        inf = inferred_types.get(num)
        if inf and inf != "OTHER":
            return _is_modification_inferred(inf)
        return is_modification(doc)

    def _subordination_check(num: str, doc: dict) -> bool:
        inf = inferred_types.get(num)
        if inf and inf != "OTHER":
            return _is_subordination_inferred(inf)
        return is_subordination(doc)

    # Index docs by number for quick lookup.
    docs_by_num: Dict[str, dict] = {}
    for d in documents:
        num = _doc_number(d)
        if num:
            docs_by_num[num] = d

    mortgage_nums: Set[str] = {
        n for n, d in docs_by_num.items() if _mortgage_check(n, d)
    }

    # ---- Build mortgage metadata (Book/Page/MIN/Principal) ----
    # Used by find_referenced_instruments so satisfactions can match by
    # Book/Page or MIN when the doc-number isn't echoed verbatim.
    mortgage_metadata: Dict[str, dict] = {}
    for num in mortgage_nums:
        text = extracted_texts.get(num, "") or ""
        meta: Dict[str, Optional[str]] = {
            "book": None, "page": None,
            "min_number": None, "original_principal": None,
        }
        bp = _BOOK_PAGE_RE.search(text)
        if bp:
            meta["book"] = bp.group(1)
            meta["page"] = bp.group(2)
        mm = _MIN_RE.search(text)
        if mm:
            meta["min_number"] = mm.group(1)
        pm = _PRINCIPAL_RE.search(text)
        if pm:
            meta["original_principal"] = _norm_money(pm.group(1))
        mortgage_metadata[num] = meta

    # Pre-init result map.
    result: Dict[str, MortgageClassification] = {
        n: MortgageClassification(doc_number=n, status="open") for n in mortgage_nums
    }

    # ---- Sweep satisfaction/release/discharge docs ---------------------
    for sat_num, sat_doc in docs_by_num.items():
        kind = _satisfaction_check(sat_num, sat_doc)
        if not kind:
            continue
        text = extracted_texts.get(sat_num, "") or ""
        # Also fall back to embedded text on the doc record itself.
        if not text:
            text = sat_doc.get("extracted_text") or sat_doc.get("text") or ""
        hits = find_referenced_instruments(
            text, mortgage_nums, mortgage_metadata=mortgage_metadata,
        )
        for mortgage_num, snippet in hits:
            link = ReleaseLink(
                mortgage_doc_number=mortgage_num,
                satisfaction_doc_number=sat_num,
                satisfaction_type=kind,
                evidence_text=snippet,
            )
            result[mortgage_num].release_chain.append(link)
            result[mortgage_num].status = "released"

    # ---- Sweep modifications (only matters if NOT already released) ----
    for mod_num, mod_doc in docs_by_num.items():
        if not _modification_check(mod_num, mod_doc):
            continue
        text = extracted_texts.get(mod_num, "") or ""
        if not text:
            text = mod_doc.get("extracted_text") or mod_doc.get("text") or ""
        hits = find_referenced_instruments(
            text, mortgage_nums, mortgage_metadata=mortgage_metadata,
        )
        for mortgage_num, _snippet in hits:
            if mod_num not in result[mortgage_num].related_modifications:
                result[mortgage_num].related_modifications.append(mod_num)
            if result[mortgage_num].status == "open":
                result[mortgage_num].status = "modified"

    # ---- Sweep subordinations (lowest priority) -----------------------
    for sub_num, sub_doc in docs_by_num.items():
        if not _subordination_check(sub_num, sub_doc):
            continue
        text = extracted_texts.get(sub_num, "") or ""
        if not text:
            text = sub_doc.get("extracted_text") or sub_doc.get("text") or ""
        hits = find_referenced_instruments(
            text, mortgage_nums, mortgage_metadata=mortgage_metadata,
        )
        for mortgage_num, _snippet in hits:
            if result[mortgage_num].status == "open":
                result[mortgage_num].status = "subordinate"

    return result


__all__ = [
    "ReleaseLink",
    "MortgageClassification",
    "classify_mortgages",
    "find_referenced_instruments",
    "is_mortgage",
    "satisfaction_kind",
    "_strip_banner",
    "_norm_money",
]
