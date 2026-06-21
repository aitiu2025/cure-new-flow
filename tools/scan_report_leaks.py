#!/usr/bin/env python3
"""Pre-ship scan: catch operator-memo leaks and Quality-Gate placeholder phrases.

Treats ``OnE_Report_*.md`` as client-facing (memo markers + Q1-Q4 placeholders are
ERRORS) and ``Title_Examination_Notes*`` / ``RAW_TWO_OWNER_SEARCH_EXAM*`` as
examiner/engineering docs (memos allowed; placeholders surfaced as WARN only).

Real examiner warnings (POTENTIALLY OPEN, DIRECT PAYOFF VERIFICATION REQUIRED,
UNCONFIRMED — verify with the Tax Collector, FL Ch. 2002-302, etc.) are never
flagged — see the allowlist in report_sanitizer.

Usage:
    python3 tools/scan_report_leaks.py <file-or-dir> [<file-or-dir> ...]

Exit code: 0 if no ERRORs, 1 otherwise (suitable for CI / a pre-ship gate).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from titlepro.verification.report_sanitizer import scan_markdown  # noqa: E402


def _classify(path: Path):
    """Return 'client', 'examiner', or None (skip — not a shippable report).

    Only the three deliverable report types are scanned. Internal working files
    (verifier_summary, *_extracted, phase0_probe_*, COMPARISON_VS_PETER,
    WAVE*_STATUS, etc.) legitimately discuss markers/phrases and are NOT
    deliverables, so they are skipped entirely.
    """
    name = path.name.lower()
    if name.startswith(("one_report", "one-report")):
        return "client"
    if name.startswith(("title_examination", "raw_two_owner")):
        return "examiner"
    return None


def _iter_md(targets: list[str]):
    for t in targets:
        p = Path(t)
        if p.is_dir():
            yield from sorted(p.rglob("*.md"))
        elif p.suffix.lower() == ".md":
            yield p


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    total_err = 0
    total_warn = 0
    scanned = 0
    for md in _iter_md(argv):
        # Skip backups / intermediates.
        if any(s in md.name for s in (".bak", "_pdfsrc")):
            continue
        kind = _classify(md)
        if kind is None:
            continue  # not a shippable report — skip internal working files
        client = kind == "client"
        scanned += 1
        findings = scan_markdown(md.read_text(encoding="utf-8"), client_facing=client)
        errs = [f for f in findings if f.severity == "ERROR"]
        warns = [f for f in findings if f.severity == "WARN"]
        total_err += len(errs)
        total_warn += len(warns)
        if findings:
            tag = "CLIENT" if client else "examiner"
            print(f"\n{md}  [{tag}]")
            for f in findings:
                print(f"  {f.severity:5} L{f.line_no:<4} {f.kind:12} {f.phrase!r}")
                print(f"            | {f.line[:160]}")
    print(
        f"\nScanned {scanned} markdown file(s): "
        f"{total_err} ERROR(s), {total_warn} WARN(ing)(s)."
    )
    if total_err == 0:
        print("PASS — no client-facing leaks.")
    else:
        print("FAIL — client-facing leak(s) found; do not ship.")
    return 1 if total_err else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
