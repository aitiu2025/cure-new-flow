"""Tests for report_sanitizer — strip must remove memos but PRESERVE examiner flags."""

from titlepro.verification.report_sanitizer import (
    scan_markdown,
    strip_operator_memos,
)

# A realistic OnE tail: a real examiner warning block, then an operator memo.
ONE_WITH_MEMO = """\
## 3. Open / Active Mortgages

| Lien | Status | Note |
|---|---|---|
| Pulte first 2020109156 | OPEN | Senior lien |
| AVCO 1997 | POTENTIALLY OPEN | ⚠️ DIRECT PAYOFF VERIFICATION REQUIRED |

## 6. Tax

| Installment Status | UNCONFIRMED — verify with the Pasco County Tax Collector |

> **Critical Issues:** none of record.

---

*Report compiled by CURE TitlePro. Confidential.*

---

`[INTERNAL MEMO — READ BEFORE SHARING; DELETE BEFORE SENDING TO CLIENT]`

- Cloudflare-403'd on the tax endpoint; re-run lookup_grant_street_tax(...) from a clean egress.
- Peter's benchmark 2025 = $12,121.43 PAID — do NOT publish uncited.

`[REMOVE EVERYTHING BELOW THIS MARKER — AND THIS MEMO — BEFORE SENDING TO CLIENT]`
"""

HILLSBOROUGH_STYLE = """\
## 8. Exhibit A

Legal text here.

---

## [INTERNAL MEMO — READ BEFORE SHARING; DELETE BEFORE SENDING TO CLIENT]

> **FOR OPERATOR/REVIEWER EYES ONLY. DELETE THIS ENTIRE SECTION BEFORE FORWARDING.**

### F17 Audit
Engineering detail not for the client.

[END INTERNAL MEMO — REMOVE EVERYTHING BETWEEN THE [INTERNAL MEMO] AND [END INTERNAL MEMO] MARKERS BEFORE FORWARDING THIS REPORT]

*Report compiled by CURE TitlePro. Confidential.*
"""


def test_strip_removes_memo_block():
    clean, removed = strip_operator_memos(ONE_WITH_MEMO)
    assert len(removed) == 1
    assert "INTERNAL MEMO" not in clean
    assert "REMOVE EVERYTHING BELOW" not in clean
    assert "Cloudflare" not in clean
    assert "do NOT publish" not in clean


def test_strip_preserves_examiner_flags():
    clean, _ = strip_operator_memos(ONE_WITH_MEMO)
    # The exact flags a title examiner needs must survive verbatim.
    assert "POTENTIALLY OPEN" in clean
    assert "DIRECT PAYOFF VERIFICATION REQUIRED" in clean
    assert "UNCONFIRMED — verify with the Pasco County Tax Collector" in clean
    assert "Critical Issues" in clean
    assert "Open / Active Mortgages" in clean
    # The client footer survives; the dangling separators are cleaned up.
    assert "Report compiled by CURE TitlePro" in clean


def test_strip_handles_mid_document_close_marker():
    clean, removed = strip_operator_memos(HILLSBOROUGH_STYLE)
    assert len(removed) == 1
    assert "INTERNAL MEMO" not in clean
    assert "F17 Audit" not in clean
    # Content AFTER the [END INTERNAL MEMO] marker is preserved.
    assert "Report compiled by CURE TitlePro" in clean
    assert "Exhibit A" in clean


def test_strip_noop_when_no_memo():
    body = "## Section\n\nNothing internal here.\n"
    clean, removed = strip_operator_memos(body)
    assert removed == []
    assert clean == body


def test_strip_ignores_mid_sentence_prose_mention():
    # Regression: client-facing prose that merely mentions "internal memo" must
    # NOT be treated as a memo OPEN marker. Previously this matched and the strip
    # deleted everything from this sentence to the next close marker, silently
    # truncating §4 through §8 of an OnE that carried a real memo further down.
    body = (
        "## 4. Judgments\n\n"
        "A recorded satisfaction is recommended. *(See internal memo below.)*\n\n"
        "## 6. Tax\n\nAnnual tax $617.01 PAID.\n\n"
        "## 8. Exhibit A\n\nLots 15 & 16, Block 1633.\n\n"
        "**[INTERNAL MEMO — READ BEFORE SHARING; DELETE BEFORE SENDING TO CLIENT]**\n\n"
        "- Operator note: pull the recorded release on direct retrieval.\n\n"
        "REMOVE EVERYTHING BELOW (this line) AND THIS MEMO BEFORE SENDING TO CLIENT.\n"
    )
    clean, removed = strip_operator_memos(body)
    # Exactly one memo block removed — the real one, not the prose mention.
    assert len(removed) == 1
    assert "Operator note" not in clean
    # All real report sections survive the strip.
    assert "4. Judgments" in clean
    assert "6. Tax" in clean
    assert "$617.01" in clean
    assert "8. Exhibit A" in clean
    assert "Lots 15 & 16" in clean
    # The prose mention itself is preserved (it is real §4 content).
    assert "See internal memo below" in clean


def test_scan_flags_memo_and_placeholder_in_client_report():
    findings = scan_markdown(ONE_WITH_MEMO, client_facing=True)
    kinds = {f.kind for f in findings}
    assert "memo_marker" in kinds
    assert all(f.severity == "ERROR" for f in findings)


def test_scan_does_not_flag_legit_examiner_warnings():
    body = (
        "| AVCO | POTENTIALLY OPEN | ⚠️ DIRECT PAYOFF VERIFICATION REQUIRED |\n"
        "| Tax | UNCONFIRMED — verify with the Pasco County Tax Collector |\n"
        "| BK | operator-verify via PACER |\n"
        "Statutory notice under FL Ch. 2002-302 applies.\n"
    )
    findings = scan_markdown(body, client_facing=True)
    assert findings == []


def test_scan_clean_after_strip():
    clean, _ = strip_operator_memos(ONE_WITH_MEMO)
    findings = scan_markdown(clean, client_facing=True)
    assert [f for f in findings if f.severity == "ERROR"] == []


def test_title_doc_keeps_memo_unflagged_as_error():
    # The relocated examiner memo lives in the Title; not client-facing, so the
    # 'engineering item' phrase etc. should not be ERRORs there.
    title = (
        "## Internal Examiner Memo — relocated from OnE\n\n"
        "ENGINEERING ITEM: re-run the tax fetch.\n"
    )
    findings = scan_markdown(title, client_facing=False)
    assert [f for f in findings if f.severity == "ERROR"] == []
