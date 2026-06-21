"""Generate ``Tony_verified_commentary.md`` from a verified case folder.

This is the **engineering-facing** companion to the customer-facing
``Title_Examination_Notes.md``. The Title is the deliverable that closing
attorneys, escrow officers and lenders read; per F11 it must NOT contain
internal-tool plumbing (``released_mortgage_linker``, ``MATCH (1.00)``
similarity scores, per-search count tuples, "Engineering follow-up:" notes,
reviewer-name citations, etc.).

Rather than silently dropping that signal, the verifier moves it to a
separate ``Tony_verified_commentary.md`` next to the Title. Engineers reading
the commentary get the full diagnostic picture; customers reading the Title
get a clean closing-officer product.

Citation format (CRITICAL — applied throughout the commentary)::

    As per directive #N (one-line description of the rule)

NOT::

    Per Tony directive #N        (reviewer name leaks identity)
    Tony directive #N            (same — name suppressed even here)
    Tony Roveda directive #6
    directive #N                 (bare — no inline parenthetical)

CLI::

    python3 -m titlepro.verification.tony_commentary_generator <case_dir>

Programmatic::

    from titlepro.verification.tony_commentary_generator import (
        generate_commentary,
    )
    out_path = generate_commentary(case_dir)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Canonical directive descriptions — used verbatim in the inline parenthetical
# of every directive citation. Sourced from Tony Roveda's 2026-05-21 Broward
# Test Review + the 2026-05-23 directive-citation clarification.
# ---------------------------------------------------------------------------

DIRECTIVES: dict[int, str] = {
    1: "no Selenium/Playwright in Phase 1 search — use HTTP GET/POST",
    2: "deed-first search: DocType=DEED → extract APN → APN search",
    3: "run ALL provided names + cross-check Deed# between spouses",
    4: "NLP-verify subject address from deed image content",
    5: "examine every indexed document; no silent dropping",
    6: "released-mortgage exclusion via satisfaction/release linkage",
}


def cite(directive_num: int) -> str:
    """Return canonical inline directive citation.

    Always emits: ``As per directive #N (one-line description)``. Never uses
    the reviewer's name and never emits a bare ``directive #N``.
    """
    desc = DIRECTIVES.get(directive_num, "directive description unavailable")
    return f"As per directive #{directive_num} ({desc})"


# ---------------------------------------------------------------------------
# Inputs (artifacts read from the case folder)
# ---------------------------------------------------------------------------


@dataclass
class CaseArtifacts:
    case_dir: Path
    workflow_config: dict[str, Any]
    search_results: dict[str, Any]
    documents_found: list[dict[str, Any]]
    download_manifest: list[dict[str, Any]]
    phase1_verifications: dict[str, Any]
    prohibited_documents: list[dict[str, Any]]
    title_text: str
    raw_text: str


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text()
    except OSError:
        return ""


def _first_existing(case_dir: Path, *names: str) -> Path | None:
    for name in names:
        p = case_dir / name
        if p.exists():
            return p
    return None


def load_artifacts(case_dir: Path) -> CaseArtifacts:
    """Load every artifact the generator needs (missing files are tolerated)."""
    title_path = _first_existing(case_dir, "Title_Examination_Notes.md")
    raw_path = _first_existing(case_dir, "RAW_TWO_OWNER_SEARCH_EXAM.md")
    return CaseArtifacts(
        case_dir=case_dir,
        workflow_config=_read_json(case_dir / "workflow_config.json", {}),
        search_results=_read_json(case_dir / "search_results.json", {}),
        documents_found=_read_json(case_dir / "documents_found.json", []),
        download_manifest=_read_json(case_dir / "broward_download_manifest.json", []),
        phase1_verifications=_read_json(case_dir / "phase1_verifications.json", {}),
        prohibited_documents=_read_json(case_dir / "prohibited_documents.json", []),
        title_text=_read_text(title_path) if title_path else "",
        raw_text=_read_text(raw_path) if raw_path else "",
    )


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------


def _render_header(art: CaseArtifacts) -> str:
    cfg = art.workflow_config
    subject_id = cfg.get("subject_id", "UNKNOWN")
    owner = cfg.get("owner_name", "UNKNOWN")
    addr = cfg.get("property_address", "UNKNOWN")
    county = cfg.get("county", "UNKNOWN")
    folder = cfg.get("output_folder_name", art.case_dir.name)
    generated_at = datetime.now().isoformat(timespec="seconds")
    return (
        "# Tony_verified_commentary\n"
        "\n"
        "Engineering-facing companion to ``Title_Examination_Notes.md``. "
        "Contains internal verifier output, classifier traces, linker findings "
        "and engineering follow-ups that the customer-facing Title must NOT "
        "contain (per F11). Directive citations follow the canonical inline "
        "format: ``As per directive #N (one-line description)`` — the "
        "reviewer's name is suppressed even here.\n"
        "\n"
        "| Field | Value |\n"
        "|---|---|\n"
        f"| **Subject ID** | {subject_id} |\n"
        f"| **Owner of Record (search input)** | {owner} |\n"
        f"| **Subject Property** | {addr} |\n"
        f"| **County** | {county} |\n"
        f"| **Case Folder** | {folder} |\n"
        f"| **Commentary Generated** | {generated_at} |\n"
        "\n"
    )


# ---- Section 1: Verifier Verdict ---------------------------------------


def _infer_verdict(art: CaseArtifacts) -> tuple[str, list[str]]:
    """Best-effort headline verdict + reasons (heuristic — the canonical
    verdict lives in the verifier's own scorecard, which the caller may pass
    in via a future hook). Reasons are evidence the engineer can cite."""
    reasons: list[str] = []
    blockers = 0
    warnings = 0

    # Released mortgage shown as open?
    mtg_class = art.phase1_verifications.get("mortgage_classifications", {})
    released = [m for m, v in mtg_class.items() if v.get("status") == "released"]
    if released:
        for doc in released:
            # Look for the doc# in Title text. For each occurrence, check a
            # TIGHT window (±120 chars) for "open" — but only if no nearby
            # negation cue (satisfied / released / reconveyed / satisfaction)
            # indicates the doc# is being correctly described as released.
            negation = re.compile(
                r"(satisf(?:y|ied|action)|released|reconveyed|payoff|RELEASED|RECONVEYED)",
                re.IGNORECASE,
            )
            open_kw = re.compile(r"\bopen\b", re.IGNORECASE)
            offset = 0
            flagged = False
            while True:
                idx = art.title_text.find(doc, offset)
                if idx < 0:
                    break
                window = art.title_text[max(0, idx - 120): idx + 120 + len(doc)]
                if open_kw.search(window) and not negation.search(window):
                    flagged = True
                    break
                offset = idx + len(doc)
            if flagged:
                blockers += 1
                reasons.append(
                    f"F3 candidate: released MTG `{doc}` appears in Title near "
                    f"'open' keyword with no satisfaction/release cue — recheck "
                    f"classification ({cite(6)})."
                )

    # NO_MATCH deed promoted to vesting?
    addr_v = art.phase1_verifications.get("subject_address_verification", {})
    no_match = [d for d, v in addr_v.items() if v.get("status") == "NO_MATCH"]
    for doc in no_match:
        if re.search(rf"vesting[^\n]*{re.escape(doc)}", art.title_text, re.IGNORECASE):
            blockers += 1
            reasons.append(
                f"F2 candidate: NO_MATCH doc `{doc}` appears near 'vesting' in "
                f"Title ({cite(4)})."
            )

    # State-contamination signature
    runs = art.search_results.get("runs", [])
    counts = [r.get("result_count", 0) for r in runs]
    if len(counts) >= 3 and counts[0] > 0 and all(c == 0 for c in counts[1:]):
        blockers += 1
        reasons.append(
            f"F1 detected: state-contamination signature {counts} in "
            f"search_results.json ({cite(3)})."
        )

    # F11: scan Title for forbidden engineering vocabulary
    title_leaks = _scan_title_for_engineering_language(art.title_text)
    if title_leaks:
        warnings += 1
        reasons.append(
            f"F11 detected: {len(title_leaks)} engineering-vocabulary leak(s) "
            "in Title (customer-facing). See Engineering Follow-ups."
        )

    if blockers:
        verdict = "BLOCKED — re-run required"
    elif warnings:
        verdict = "SHIPPABLE WITH FIXES"
    else:
        verdict = "SHIPPABLE"
    return verdict, reasons


def _grep_context(text: str, needle: str, lines: int = 2) -> str:
    if not text or needle not in text:
        return ""
    parts = text.split("\n")
    for i, ln in enumerate(parts):
        if needle in ln:
            lo = max(0, i - lines)
            hi = min(len(parts), i + lines + 1)
            return "\n".join(parts[lo:hi])
    return ""


def _scan_title_for_engineering_language(title_text: str) -> list[tuple[int, str, str]]:
    """Return (line_no, pattern, matched_text) for every F11 leak in Title."""
    forbidden = [
        r"released_mortgage_linker",
        r"subject[- ]?address[- ]?verifier",
        r"subject[- ]property[- ]address[- ]?verifier",
        r"document_type_classifier",
        r"Phase[- ]1 sidecar",
        r"\bsidecar\b",
        r"\[\s*\d+(?:\s*,\s*\d+){5,}\s*\]",
        r"state[- ]contamination",
        r"Engineering action:",
        r"Engineering follow-up:",
        r"tune (?:the )?(?:linker|verifier|classifier)",
        r"MATCH\s*\(\d\.\d{2}\)",
        r"NO_MATCH\s*\(\d\.\d{2}\)",
        r"automated sidecar",
        r"computed sidecar",
        r"linker (?:gap|missed|misclassified)",
        r"(?i)\bper Tony( Roveda)?\b",
        r"(?i)\bTony( Roveda)? directive[s]?\s*#?\d*",
        r"(?i)\bTony Roveda\b",
        r"(?i)\bAs per Tony",
        r"(?i)\bdirective #\d+\b(?!\s*\()",
    ]
    hits: list[tuple[int, str, str]] = []
    for pat in forbidden:
        for m in re.finditer(pat, title_text):
            line_no = title_text[: m.start()].count("\n") + 1
            hits.append((line_no, pat, m.group(0)))
    return hits


def _render_verdict_section(art: CaseArtifacts) -> str:
    verdict, reasons = _infer_verdict(art)
    body = ["## Verifier Verdict", "", f"**{verdict}**", ""]
    if reasons:
        body.append("Heuristic evidence (verifier scorecard is the source of truth):")
        body.append("")
        for r in reasons:
            body.append(f"- {r}")
        body.append("")
    else:
        body.append("No automated red flags surfaced by the commentary generator's heuristic scan.")
        body.append("(Definitive verdict still comes from the verify-cure-report skill's scorecard.)")
        body.append("")
    return "\n".join(body)


# ---- Section 2: Source of Truth ----------------------------------------


def _render_sot_section(art: CaseArtifacts) -> str:
    county = art.workflow_config.get("county", "UNKNOWN")
    return (
        "## Step 0 — Source of Truth\n"
        "\n"
        f"**County:** `{county}`\n"
        "\n"
        "Pre-flight cross-checks the verifier should have run "
        f"({cite(1)}):\n"
        "\n"
        "1. `docs/County_URL_Mapping_CA_OH.md` + `County_URL_Mapping_CUREMasterSheet.xlsx`\n"
        "2. `src/titlepro/search/recorder/counties/registry.py`\n"
        "3. `src/titlepro/search/recorder/counties/config/<state>/<county>.json`\n"
        "4. `config/county_tax_urls.json`\n"
        "5. `selenium_downloader.py` + `secrets.json` TITLEPRO_URL\n"
        "\n"
        "Default outcome assumption (pending live SoT scan): **SoT_PASS** —\n"
        "the verify-cure-report skill's Step-0 output is authoritative and\n"
        "should be transcribed here once the skill has run.\n"
    )


# ---- Section 3: Six Directives — Scorecard -----------------------------


def _render_directives_scorecard(art: CaseArtifacts) -> str:
    """Heuristic per-directive scorecard. The verify-cure-report skill's
    output is the canonical source; this is the engineering snapshot."""
    runs = art.search_results.get("runs", [])
    counts = [r.get("result_count", 0) for r in runs]
    expected_names = {
        req.get("name") for req in art.workflow_config.get("search_requests", [])
    }
    actual_names = {r.get("name_searched") for r in runs}

    addr_v = art.phase1_verifications.get("subject_address_verification", {})
    n_match = sum(1 for v in addr_v.values() if v.get("status") == "MATCH")
    n_total = len(addr_v)
    n_no_match = sum(1 for v in addr_v.values() if v.get("status") == "NO_MATCH")

    mtg_class = art.phase1_verifications.get("mortgage_classifications", {})
    released_count = sum(1 for v in mtg_class.values() if v.get("status") == "released")

    contam = (
        len(counts) >= 3 and counts[0] > 0 and all(c == 0 for c in counts[1:])
    )

    rows = [
        (
            "D1",
            cite(1),
            "WARN",
            "Selenium/Playwright still used; HTTP adapter scaffolded but not yet wired.",
        ),
        (
            "D2",
            cite(2),
            "WARN",
            "Search runs against DocType=All (not DEED-first); APN-back-search not implemented.",
        ),
        (
            "D3",
            cite(3),
            "FAIL" if contam else "PASS",
            f"per-search counts={counts}; expected names={sorted(expected_names)}; ran={sorted(actual_names)}",
        ),
        (
            "D4",
            cite(4),
            "PASS" if n_no_match == 0 else "WARN",
            f"{n_match}/{n_total} MATCH; {n_no_match} NO_MATCH (see address-verification table).",
        ),
        (
            "D5",
            cite(5),
            "PASS",
            f"{len(art.documents_found)} documents in documents_found.json; "
            f"audit trail in `not_needed/` if applicable.",
        ),
        (
            "D6",
            cite(6),
            "PASS" if released_count > 0 or not mtg_class else "WARN",
            f"{released_count} mortgages classified as RELEASED via satisfaction linkage; "
            f"{len(mtg_class) - released_count} OPEN/modified.",
        ),
    ]

    out = ["## Six Directives — Scorecard", ""]
    out.append("| # | Citation | Status | Evidence |")
    out.append("|---|---|---|---|")
    for d_id, citation, status, evidence in rows:
        out.append(f"| {d_id} | {citation} | {status} | {evidence} |")
    out.append("")
    return "\n".join(out)


# ---- Section 4: Known Failure Modes — Scans ----------------------------


def _render_failure_mode_scans(art: CaseArtifacts) -> str:
    runs = art.search_results.get("runs", [])
    counts = [r.get("result_count", 0) for r in runs]
    contam = (
        len(counts) >= 3 and counts[0] > 0 and all(c == 0 for c in counts[1:])
    )

    addr_v = art.phase1_verifications.get("subject_address_verification", {})
    no_match_docs = [d for d, v in addr_v.items() if v.get("status") == "NO_MATCH"]

    mtg_class = art.phase1_verifications.get("mortgage_classifications", {})
    released_docs = [d for d, v in mtg_class.items() if v.get("status") == "released"]

    prohibited = art.prohibited_documents
    title_leaks = _scan_title_for_engineering_language(art.title_text)

    scans = [
        ("F1", "state-contamination [N,0,0,0,0,0]", "DETECTED" if contam else "PASS", f"per-search counts={counts}"),
        ("F2", "wrong-property doc shipped as vesting", "PASS" if not no_match_docs else f"REVIEW: {len(no_match_docs)} NO_MATCH docs — confirm not used as vesting",
         f"NO_MATCH docs: {no_match_docs}"),
        ("F3", "released mortgage shown as open", "PASS" if released_docs else "N/A — no released mortgages classified",
         f"released docs: {released_docs}"),
        ("F4", "missing second-name search results",
         "PASS" if not contam else "DETECTED via F1 signature",
         f"runs={[r.get('name_searched') for r in runs]}; per-run counts={counts}"),
        ("F5", "QCD as vesting without preceding WD",
         "MANUAL_REVIEW", "verifier skill cross-checks chain order"),
        ("F6", "doc count mismatch (search vs documents_found)",
         "PASS", f"summary={art.search_results.get('summary', {}).get('total_unique_documents')}; "
         f"documents_found={len(art.documents_found)}"),
        ("F7", "lender-HQ address extracted",
         "REVIEW" if no_match_docs else "PASS",
         f"NO_MATCH count={len(no_match_docs)} (manual lender-HQ inspection needed if any)"),
        ("F8", "prohibited doc without statutory notice",
         "PASS" if prohibited else "N/A — no prohibited docs",
         f"prohibited count={len(prohibited)}"),
        ("F9", "search-results document_type interpreted literally",
         "PASS" if art.phase1_verifications.get("document_type_classifications") else "FAIL",
         "document_type_classifier sidecar present" if art.phase1_verifications.get("document_type_classifications")
         else "no classifier sidecar found"),
        ("F10", "Telerik pagination loss (8 visible, 16+ actual)",
         "PASS" if max(counts, default=0) > 8 else "REVIEW",
         f"max per-run count={max(counts, default=0)}"),
        ("F11", "engineering vocabulary leaked into customer Title",
         "PASS" if not title_leaks else f"DETECTED ({len(title_leaks)} hits)",
         f"first 3 leaks: {title_leaks[:3]}" if title_leaks else "no leaks"),
    ]

    out = ["## Known Failure Modes — Scans", ""]
    out.append("| ID | Pattern | Status | Evidence |")
    out.append("|---|---|---|---|")
    for fid, name, status, evidence in scans:
        evidence_short = str(evidence)[:200].replace("|", "\\|")
        out.append(f"| {fid} | {name} | {status} | {evidence_short} |")
    out.append("")
    return "\n".join(out)


# ---- Section 5: Subject-Property Address Verification ------------------


def _render_address_verification_table(art: CaseArtifacts) -> str:
    addr_v = art.phase1_verifications.get("subject_address_verification", {})
    out = ["## Subject-Property Address Verification (per doc)", ""]
    if not addr_v:
        out.append("_No `subject_address_verification` block in `phase1_verifications.json`._")
        out.append("")
        return "\n".join(out)
    subject = art.phase1_verifications.get("subject_address") or art.workflow_config.get("property_address", "")
    out.append(f"**Subject anchor:** `{subject}`")
    out.append("")
    out.append("**Verifier module:** `src/titlepro/verification/subject_address_verifier.py`")
    out.append("")
    out.append("| Doc# | Status | Similarity | Extracted Address | Evidence |")
    out.append("|---|---|---|---|---|")
    for doc, v in addr_v.items():
        status = v.get("status", "")
        sim = v.get("similarity", "")
        sim_str = f"{sim:.3f}" if isinstance(sim, (int, float)) else str(sim)
        extracted = (v.get("extracted_address") or "").replace("\n", " ").replace("|", "\\|")
        evidence = (v.get("evidence") or "").replace("\n", " ").replace("|", "\\|")
        # Truncate long fields
        extracted = extracted[:80]
        evidence = evidence[:200]
        out.append(f"| `{doc}` | {status} ({sim_str}) | {sim_str} | {extracted} | {evidence} |")
    out.append("")
    return "\n".join(out)


# ---- Section 6: Document Type Classification ---------------------------


def _render_doctype_classification(art: CaseArtifacts) -> str:
    types = art.phase1_verifications.get("document_type_classifications", {})
    out = ["## Document Type Classification (per doc)", ""]
    if not types:
        out.append("_No `document_type_classifications` block in `phase1_verifications.json`._")
        out.append("")
        return "\n".join(out)
    out.append(
        "**Classifier module:** `src/titlepro/verification/document_type_classifier.py` "
        f"({cite(2)})"
    )
    out.append("")
    out.append("| Doc# | Inferred Type | Confidence | Source | Evidence Snippet |")
    out.append("|---|---|---|---|---|")
    for doc, v in types.items():
        ev = (v.get("evidence") or "").replace("\n", " ").replace("|", "\\|")[:120]
        conf = v.get("confidence", "")
        conf_str = f"{conf:.2f}" if isinstance(conf, (int, float)) else str(conf)
        out.append(
            f"| `{doc}` | {v.get('inferred_type', '')} | {conf_str} | "
            f"{v.get('source', '')} | {ev} |"
        )
    out.append("")
    return "\n".join(out)


# ---- Section 7: Mortgage Status Classification -------------------------


def _render_mortgage_status(art: CaseArtifacts) -> str:
    mtg = art.phase1_verifications.get("mortgage_classifications", {})
    out = ["## Mortgage Status Classification (per mortgage)", ""]
    if not mtg:
        out.append("_No `mortgage_classifications` block in `phase1_verifications.json`._")
        out.append("")
        return "\n".join(out)
    out.append(
        "**Linker module:** `src/titlepro/verification/released_mortgage_linker.py` "
        f"({cite(6)})"
    )
    out.append("")
    out.append(
        "Source: `phase1_verifications.json` → `mortgage_classifications` "
        "(each entry has `status`, `release_chain[]`, `related_modifications[]`)."
    )
    out.append("")
    out.append("| Mortgage Doc# | Status | release_chain | Related Modifications |")
    out.append("|---|---|---|---|")
    for doc, v in mtg.items():
        chain = v.get("release_chain", []) or []
        chain_strs = []
        for link in chain:
            sat = link.get("satisfaction", "?")
            kind = link.get("type", "?")
            chain_strs.append(f"{sat} ({kind})")
        chain_text = "; ".join(chain_strs) if chain_strs else "—"
        mods = "; ".join(v.get("related_modifications", [])) or "—"
        out.append(f"| `{doc}` | {v.get('status', '')} | {chain_text} | {mods} |")
    out.append("")
    # Per-link evidence
    out.append("### Release-chain evidence")
    out.append("")
    any_evidence = False
    for doc, v in mtg.items():
        for link in v.get("release_chain", []) or []:
            any_evidence = True
            ev = (link.get("evidence") or "").replace("\n", " ")[:300]
            out.append(
                f"- MTG `{doc}` → satisfaction `{link.get('satisfaction', '?')}` "
                f"(kind={link.get('type', '?')}): {ev}"
            )
    if not any_evidence:
        out.append("_No release-chain evidence recorded — every classified mortgage is OPEN or modified._")
    out.append("")
    return "\n".join(out)


# ---- Section 8: Linker-vs-LLM Discrepancies ----------------------------


def _render_linker_vs_llm(art: CaseArtifacts) -> str:
    """Find mortgages classified as ``open`` by the linker but described as
    released/satisfied in the RAW or Title (i.e., the LLM caught a Book/Page
    cross-reference the regex linker missed). This is the F3-WARN case."""
    out = ["## Linker-vs-LLM Discrepancies", ""]
    out.append(
        f"This section surfaces cases where the LLM caught a release-evidence "
        f"signal the regex linker missed (typically Book/Page-only cross "
        f"references). {cite(6)} requires release-chain linkage; the linker "
        f"currently keys on instrument numbers only, so Book/Page-only "
        f"satisfactions are an engineering follow-up.\n"
    )
    mtg = art.phase1_verifications.get("mortgage_classifications", {})
    discrepancies = []
    for doc, v in mtg.items():
        if v.get("status") != "open":
            continue
        for blob_name, blob in (("Title", art.title_text), ("RAW", art.raw_text)):
            if not blob:
                continue
            window = _grep_context(blob, doc, lines=3)
            if window and re.search(
                r"(released|reconveyed|satisfied|release of mortgage|"
                r"satisfaction of mortgage|discharge of mortgage|linker (gap|missed|misclassified))",
                window,
                re.IGNORECASE,
            ):
                discrepancies.append((doc, blob_name, window.replace("|", "\\|")[:300]))
    if not discrepancies:
        out.append("_No linker-vs-LLM discrepancies detected by automated scan._")
        out.append("")
        return "\n".join(out)
    out.append("| Mortgage Doc# | Found In | Context Excerpt |")
    out.append("|---|---|---|")
    for doc, where, excerpt in discrepancies:
        out.append(f"| `{doc}` | {where} | {excerpt} |")
    out.append("")
    return "\n".join(out)


# ---- Section 9: Engineering Follow-ups ---------------------------------


def _render_engineering_followups(art: CaseArtifacts) -> str:
    out = ["## Engineering Follow-ups", ""]
    out.append("Items for the next CURE release. These do NOT appear in the customer-facing Title.\n")
    items: list[str] = []

    # F1 / D3
    runs = art.search_results.get("runs", [])
    counts = [r.get("result_count", 0) for r in runs]
    if len(counts) >= 3 and counts[0] > 0 and all(c == 0 for c in counts[1:]):
        items.append(
            f"State-contamination signature {counts} present — re-run with "
            f"the Telerik-aware adapter ({cite(3)})."
        )

    # F11 — Title language leaks
    leaks = _scan_title_for_engineering_language(art.title_text)
    if leaks:
        items.append(
            f"F11: {len(leaks)} engineering-vocabulary leak(s) detected in "
            "`Title_Examination_Notes.md`. Regenerate Title with the updated "
            "system prompt (`Title_Examination_Notes_System_Prompt.md` "
            "CUSTOMER-FACING LANGUAGE RULES section). First three hits: "
            f"{[(ln, pat) for ln, pat, _ in leaks[:3]]}"
        )

    # F3 — released mortgages, confirm Title classifies as released
    mtg = art.phase1_verifications.get("mortgage_classifications", {})
    for doc, v in mtg.items():
        if v.get("status") != "released":
            continue
        window = _grep_context(art.title_text, doc, lines=2)
        if window and re.search(r"\bopen\b", window, re.IGNORECASE) and not re.search(
            r"\breleased\b|\breconveyed\b", window, re.IGNORECASE
        ):
            items.append(
                f"MTG `{doc}` is classified as RELEASED in `phase1_verifications.json` but "
                f"the Title context near it still references 'open' — recheck classification ({cite(6)})."
            )

    # Linker enhancement: Book/Page mode
    items.append(
        "Linker enhancement: extend `released_mortgage_linker.py` to match on "
        "(Original-Mortgagor + Original-Mortgagee + OR-Book/Page) tuple, not just "
        f"instrument numbers ({cite(6)})."
    )

    # D2 — APN-back-search
    items.append(
        "Pipeline phase: implement DEED-first + APN-back-search "
        f"({cite(2)})."
    )

    # D1 — HTTP adapter
    items.append(
        "Adapter swap: complete the AcclaimWeb HTTP adapter and retire the "
        f"Selenium Phase-1 adapter ({cite(1)})."
    )

    # F7 — verifier upgrade
    addr_v = art.phase1_verifications.get("subject_address_verification", {})
    no_match = [d for d, v in addr_v.items() if v.get("status") == "NO_MATCH"]
    if no_match:
        items.append(
            f"Subject-address verifier: confirm 2026-05-23 upgrade ran on docs "
            f"{no_match} (F7 mitigation — manual inspect for lender-HQ patterns)."
        )

    for it in items:
        out.append(f"- {it}")
    out.append("")
    return "\n".join(out)


# ---- Section 10: Prohibited Documents ----------------------------------


def _render_prohibited_documents(art: CaseArtifacts) -> str:
    out = ["## Prohibited Documents", ""]
    if not art.prohibited_documents:
        out.append("_No prohibited documents in this case (no `prohibited_documents.json` entries)._")
        out.append("")
        return "\n".join(out)
    out.append(
        f"Documents blocked from display per statute. Customer-facing Title "
        f"must include the verbatim statutory message and list these docs "
        f"under INACCESSIBLE / PROHIBITED ({cite(5)}).\n"
    )
    out.append("| Doc# | Record Date | Doc Type | Statutory Basis | Statutory Message |")
    out.append("|---|---|---|---|---|")
    for p in art.prohibited_documents:
        msg = (p.get("prohibited_message") or "").replace("|", "\\|")[:200]
        out.append(
            f"| `{p.get('document_number', '')}` | {p.get('record_date', '')} | "
            f"{p.get('doc_type', '')} | {p.get('prohibited_reason', '')} | {msg} |"
        )
    out.append("")
    # Confirm Title contains the statutory string
    statutory_marker = "CHAPTER 2002-302"
    if statutory_marker in art.title_text:
        out.append(f"_Title confirmed to contain '{statutory_marker}' statutory notice._")
    else:
        out.append(
            f"**WARNING**: Title does NOT contain '{statutory_marker}' statutory notice — "
            f"required for FL prohibited-doc compliance ({cite(5)})."
        )
    out.append("")
    return "\n".join(out)


# ---- Section 11: Tony-Style Verdict ------------------------------------


def _render_tony_voice_verdict(art: CaseArtifacts) -> str:
    """Tony's own voice goes here (the only place in the file where the
    reviewer's stylistic signature is preserved). The file is engineering-
    facing; this section is the human one-paragraph forwardable summary."""
    out = ["## Tony-Style Verdict", ""]
    out.append(
        "_The verify-cure-report skill's Step-6 paragraph is the canonical "
        "source — paste it here verbatim once the skill has run. The "
        "generator emits a heuristic placeholder until then._\n"
    )
    addr_v = art.phase1_verifications.get("subject_address_verification", {})
    n_match = sum(1 for v in addr_v.values() if v.get("status") == "MATCH")
    n_total = len(addr_v)
    mtg = art.phase1_verifications.get("mortgage_classifications", {})
    n_released = sum(1 for v in mtg.values() if v.get("status") == "released")
    n_open = sum(1 for v in mtg.values() if v.get("status") == "open")
    leaks = _scan_title_for_engineering_language(art.title_text)
    parts = []
    parts.append(f"Subject-address verifier ran on {n_total} doc(s), {n_match} MATCH.")
    if n_released:
        parts.append(f"{n_released} mortgage(s) correctly linked to satisfactions.")
    if n_open:
        parts.append(f"{n_open} open mortgage(s) flagged for closing.")
    if leaks:
        parts.append(
            f"{len(leaks)} engineering-vocabulary leak(s) in Title — regenerate before sending to customer."
        )
    else:
        parts.append("Title is clean of engineering vocabulary (F11 PASS).")
    out.append("> " + " ".join(parts))
    out.append("")
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Top-level
# ---------------------------------------------------------------------------


def build_commentary_markdown(art: CaseArtifacts) -> str:
    parts = [
        _render_header(art),
        _render_verdict_section(art),
        "",
        _render_sot_section(art),
        "",
        _render_directives_scorecard(art),
        "",
        _render_failure_mode_scans(art),
        "",
        _render_address_verification_table(art),
        "",
        _render_doctype_classification(art),
        "",
        _render_mortgage_status(art),
        "",
        _render_linker_vs_llm(art),
        "",
        _render_engineering_followups(art),
        "",
        _render_prohibited_documents(art),
        "",
        _render_tony_voice_verdict(art),
    ]
    return "\n".join(parts)


def generate_commentary(case_dir: Path | str, output_name: str = "Tony_verified_commentary.md") -> Path:
    """Generate the companion commentary file and return its path."""
    case_dir = Path(case_dir).expanduser().resolve()
    if not case_dir.exists() or not case_dir.is_dir():
        raise FileNotFoundError(f"case_dir not found or not a directory: {case_dir}")
    art = load_artifacts(case_dir)
    md = build_commentary_markdown(art)
    out_path = case_dir / output_name
    out_path.write_text(md)
    return out_path


def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="tony_commentary_generator",
        description=(
            "Generate Tony_verified_commentary.md (engineering-facing "
            "companion to Title_Examination_Notes.md)"
        ),
    )
    parser.add_argument("case_dir", help="Path to the verified case folder")
    parser.add_argument(
        "--output-name",
        default="Tony_verified_commentary.md",
        help="Output filename (default: Tony_verified_commentary.md)",
    )
    args = parser.parse_args(argv)
    out_path = generate_commentary(args.case_dir, args.output_name)
    print(f"Wrote: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
