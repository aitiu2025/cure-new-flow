"""Report sanitizer — strip operator-only internal memos and detect placeholder leaks.

Two jobs, kept deliberately separate so neither can damage a real report:

1. ``strip_operator_memos`` — DETERMINISTIC removal of operator-only memo blocks
   delimited by explicit markers (``[INTERNAL MEMO ...]`` / ``[END INTERNAL MEMO]`` /
   ``REMOVE EVERYTHING BELOW ...``). This is the render-time safety net for the
   client-facing OnE. Because it only ever removes text *between explicit operator
   markers*, it can never strip a legitimate title-examiner flag or warning
   (POTENTIALLY OPEN, ⚠️ DIRECT PAYOFF VERIFICATION REQUIRED, UNCONFIRMED — verify
   with the Tax Collector, FL Ch. 2002-302 statutory notice, Critical Issues, etc.)
   — those carry no memo markers.

2. ``scan_markdown`` — DETECTION ONLY (never mutates). Flags, in a *client-facing*
   report, (a) any leftover memo marker and (b) the Quality-Gate Q1-Q4 forbidden
   placeholder phrases. An allowlist of real examiner warnings keeps legitimate
   "verify with…" language from being flagged.

The OnE is client-facing; the Title Examination Notes and RAW exam are
examiner/engineering-facing and may legitimately carry memos — so the strip is
applied to the OnE/RAW PDF + OnE DOCX paths but NOT to the Title.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# --- memo markers (operator-only; safe to strip from a shippable artifact) ----
# An OPEN marker begins an operator memo. "[INTERNAL MEMO", "INTERNAL MEMO —",
# wrapped in backticks, bold, or a heading, all match. Note "Internal Examiner
# Memo" does NOT match (no "INTERNAL MEMO" adjacency), so the relocated Title
# memo heading is intentionally untouched.
#
# The marker is ANCHORED to the start of the line (after optional markdown
# prefix chars: whitespace, blockquote `>`, emphasis `*`/`_`/`~`, backtick,
# heading `#`, brackets). This is deliberate: a memo opener is always its own
# line, never mid-sentence. Without the anchor, ordinary client-facing prose
# that merely mentions the words "internal memo" (e.g. a §4 lien note reading
# "see internal memo below") was matched as an OPEN marker and the strip then
# deleted everything from that sentence to the next close marker — silently
# truncating half the report. The anchor confines matching to genuine memo
# heading lines.
_OPEN_MARKER = re.compile(r"^[\s>*`#\[\]_~-]*INTERNAL\s+MEMO\b", re.IGNORECASE)
# A CLOSE marker ends the block (inclusive). Any of these terminates a memo.
_CLOSE_MARKER = re.compile(
    r"(END\s+INTERNAL\s+MEMO|REMOVE\s+EVERYTHING\s+BELOW|DELETE\s+EVERYTHING\s+BELOW)",
    re.IGNORECASE,
)

# Markers used purely for *detection* (a client report should contain none of
# these). Superset of the strip markers.
_MEMO_DETECT_MARKERS = (
    "internal memo",
    "remove everything below",
    "delete everything below",
    "delete before sending",
    "delete this entire section",
    "before forwarding this report",
    "before sending to client",
    "for operator/reviewer eyes only",
    "not customer-facing",
    "engineering item",
    "do not publish",
)

# --- Quality-Gate Q1-Q4 forbidden placeholder phrases (client OnE only) -------
FORBIDDEN_PLACEHOLDER_PHRASES = (
    "manual fetch required",
    "to be confirmed",
    "not available",
    "outside search window",
)

# --- legitimate examiner warnings / dispositions that must NEVER be flagged ---
# These are real, required client/examiner content. If a forbidden phrase happens
# to sit inside one of these (it never should, but be safe), we do not flag it.
ALLOWED_WARNING_PHRASES = (
    "potentially open",
    "direct payoff verification required",
    "unconfirmed — verify",
    "unconfirmed - verify",
    "verify with the",
    "operator-verify",
    "operator verify",
    "tax-collector verify",
    "tax collector verify",
    "pacer",
    "ch. 2002-302",
    "chapter 2002-302",
    "§713",
    "construction-lien window",
)


@dataclass
class Finding:
    severity: str          # "ERROR" | "WARN"
    line_no: int           # 1-based
    kind: str              # "memo_marker" | "placeholder"
    phrase: str
    line: str


def _normalize(text: str) -> str:
    """Collapse separators/blank runs left behind after removing a block."""
    text = re.sub(r"(?:\n[ \t]*---[ \t]*){2,}", "\n\n---\n", text)  # merge adjacent <hr>
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.rstrip()
    while text.endswith("---"):
        text = text[:-3].rstrip()
    return text + "\n"


def strip_operator_memos(md_text: str) -> tuple[str, list[str]]:
    """Remove every operator-marked memo block. Returns (clean_text, removed_blocks).

    Deterministic and marker-bounded: only text between an OPEN marker and the
    next CLOSE marker (or EOF, if a memo opens with no close) is removed. Content
    that carries no memo marker — i.e. every real examiner flag/warning — is left
    exactly as-is.
    """
    removed: list[str] = []
    # HTML comment blocks (<!-- ... -->) are never client-facing content and are a
    # common operator-memo wrapper (e.g. "<!-- OPERATOR MEMO (strips on render): ... -->").
    # python-markdown passes HTML comments through to the rendered output, so strip
    # them here. Safe: real examiner flags/warnings are never HTML comments.
    def _capture_comment(m: "re.Match") -> str:
        removed.append(m.group(0).strip())
        return ""
    md_text = re.sub(r"<!--.*?-->", _capture_comment, md_text, flags=re.DOTALL)
    lines = md_text.split("\n")
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        if _OPEN_MARKER.search(lines[i]):
            start = i
            j = i
            closed = False
            while j < n:
                if _CLOSE_MARKER.search(lines[j]):
                    closed = True
                    break
                j += 1
            end = j if closed else n - 1  # no close -> strip to EOF (don't ship a memo)
            removed.append("\n".join(lines[start : end + 1]).strip())
            i = end + 1
            continue
        out.append(lines[i])
        i += 1
    if not removed:
        return md_text, []
    return _normalize("\n".join(out)), removed


def _line_has_allowed_warning(line_lower: str) -> bool:
    return any(w in line_lower for w in ALLOWED_WARNING_PHRASES)


def scan_markdown(md_text: str, *, client_facing: bool) -> list[Finding]:
    """Detect leaks. Never mutates.

    For a *client-facing* report (the OnE), flag any memo marker (ERROR) and any
    forbidden placeholder phrase not part of a legitimate examiner warning (ERROR).
    For examiner/engineering docs (Title, RAW), memos are allowed, so only
    forbidden placeholders are surfaced — and only as WARN, since those docs may
    quote source language.
    """
    findings: list[Finding] = []
    for idx, line in enumerate(md_text.split("\n"), start=1):
        low = line.lower()
        if client_facing:
            for m in _MEMO_DETECT_MARKERS:
                if m in low:
                    findings.append(Finding("ERROR", idx, "memo_marker", m, line.strip()))
        for p in FORBIDDEN_PLACEHOLDER_PHRASES:
            if p in low and not _line_has_allowed_warning(low):
                findings.append(
                    Finding(
                        "ERROR" if client_facing else "WARN",
                        idx,
                        "placeholder",
                        p,
                        line.strip(),
                    )
                )
    return findings
