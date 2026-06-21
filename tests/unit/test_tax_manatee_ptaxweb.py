"""Unit tests for the Manatee FL ptaxweb tax adapter.

Tests use mocked sessions — no live traffic. Fixture HTML mirrors the live
search-result shape captured during the 2026-05-27 probe.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from titlepro.tax.manatee_ptaxweb import (  # noqa: E402
    _parse_money,
    _parse_tax_rows,
    _split_owner_and_situs,
    lookup_manatee_tax,
)


# Live-shape excerpt (whitespace-normalized) of what the search-result HTML
# de-renders to after BeautifulSoup get_text(' ', strip=True). Each row is
# year + parcel + owner/situs + Paid/Unpaid + amount + paydate + balance.
FERNANDEZ_LIVE_TEXT = (
    " select all rows select PAY NOW PRINT BILL PRINT RECEIPT "
    " 2025 1697719559 FERNANDEZ, PABLO, ROZANES, DANIELA, 4837 SABAL HARBOUR DR Paid 3,423.64 12/01/2025 0.00 "
    " PAY NOW PRINT BILL PRINT RECEIPT "
    " 2024 1697719559 FERNANDEZ, PABLO, ROZANES, DANIELA, 4837 SABAL HARBOUR DR Paid 3,330.27 11/28/2024 0.00 "
    " 2023 1697719559 FERNANDEZ, PABLO, ROZANES, DANIELA, 4837 SABAL HARBOUR DR Paid 3,287.50 11/28/2023 0.00 "
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_parse_money_handles_dollar_commas_and_negatives():
    assert _parse_money("$3,423.64") == 3423.64
    assert _parse_money("3423.64") == 3423.64
    assert _parse_money("0.00") == 0.0
    assert _parse_money("$-1,234.56") == -1234.56
    assert _parse_money(None) == 0.0
    assert _parse_money("nothing here") == 0.0


def test_split_owner_and_situs_fernandez_pattern():
    owner, situs = _split_owner_and_situs(
        "FERNANDEZ, PABLO, ROZANES, DANIELA, 4837 SABAL HARBOUR DR"
    )
    assert "FERNANDEZ" in owner
    assert "ROZANES" in owner
    assert "4837 SABAL HARBOUR DR" in situs


def test_split_owner_and_situs_no_situs_returns_full_blob():
    owner, situs = _split_owner_and_situs("SOMETHING, ELSE WITHOUT ADDR")
    assert owner == "SOMETHING, ELSE WITHOUT ADDR"
    assert situs == ""


# ---------------------------------------------------------------------------
# Row parser
# ---------------------------------------------------------------------------


def test_parse_tax_rows_extracts_three_paid_years_fernandez():
    html = f"<html><body>{FERNANDEZ_LIVE_TEXT}</body></html>"
    rows = _parse_tax_rows(html)
    assert len(rows) == 3
    # Newest-first
    assert [r["year"] for r in rows] == [2025, 2024, 2023]
    # 2025 row checks
    r_2025 = rows[0]
    assert r_2025["apn"] == "1697719559"
    assert r_2025["status"] == "Paid"
    assert r_2025["bill_amount"] == 3423.64
    assert r_2025["balance"] == 0.0
    assert r_2025["pay_date"] == "12/01/2025"


def test_parse_tax_rows_empty_html():
    assert _parse_tax_rows("") == []
    assert _parse_tax_rows("<html><body>no data</body></html>") == []


def test_parse_tax_rows_handles_unpaid_status():
    txt = "<html>2026 1697719559 SOMEONE, X, 100 MAIN ST Unpaid 5,123.45 0.00 5,123.45</html>"
    rows = _parse_tax_rows(txt)
    assert len(rows) == 1
    assert rows[0]["status"] == "Unpaid"
    assert rows[0]["bill_amount"] == 5123.45


# ---------------------------------------------------------------------------
# lookup_manatee_tax end-to-end (mocked session)
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_session():
    sess = MagicMock()
    # First GET = disclaimer landing; first POST = disclaimer accept; second
    # POST = search results
    sess.get.return_value = MagicMock(status_code=200, text="<html>disc</html>")

    def _post(url, **kw):
        m = MagicMock()
        m.status_code = 200
        if "editPropertySearch2.action" in url and kw.get("data", {}).get("action") == "list":
            m.text = "<html>after disclaimer</html>"
        else:
            m.text = f"<html><body>{FERNANDEZ_LIVE_TEXT}</body></html>"
        return m

    sess.post.side_effect = _post
    return sess


def test_lookup_manatee_tax_fernandez_returns_paid_2025(tmp_path, fake_session):
    with patch(
        "titlepro.tax.manatee_ptaxweb.cffi.Session", return_value=fake_session
    ):
        result = lookup_manatee_tax(
            apn="1697719559",
            case_dir=tmp_path,
            safe_owner="fernandez",
            property_address="4837 SABAL HARBOUR DR, BRADENTON, FL",
        )

    assert result.status == "TAX_SUCCESS"
    assert result.apn == "1697719559"
    assert result.tax_year == "2025"
    assert result.annual_total == 3423.64
    assert result.delinquent is False
    assert "SABAL HARBOUR" in result.property_address
    assert len(result.installments) == 1
    inst = result.installments[0]
    assert inst["label"] == "annual"
    assert inst["amount"] == 3423.64
    assert inst["status"] == "PAID"
    assert inst["pay_date"] == "12/01/2025"
    # Capture file written
    assert (tmp_path / "tax_fernandez_capture.html").exists()
    # History note carries older years
    assert "2024" in result.notes
    assert "2023" in result.notes


def test_lookup_manatee_tax_apn_mismatch_returns_failed(tmp_path):
    sess = MagicMock()
    sess.get.return_value = MagicMock(status_code=200, text="")
    sess.post.return_value = MagicMock(
        status_code=200,
        text="<html>2025 9999999999 OTHER, OWNER, 100 ELSE Paid 100.00 12/01/2025 0.00</html>",
    )
    with patch(
        "titlepro.tax.manatee_ptaxweb.cffi.Session", return_value=sess
    ):
        result = lookup_manatee_tax(
            apn="1697719559",
            case_dir=tmp_path,
            safe_owner="x",
        )
    assert result.status == "TAX_FAILED"
    assert "echo mismatch" in result.error.lower()


def test_lookup_manatee_tax_no_rows_returns_no_results(tmp_path):
    sess = MagicMock()
    sess.get.return_value = MagicMock(status_code=200, text="")
    sess.post.return_value = MagicMock(status_code=200, text="<html>nothing</html>")
    with patch(
        "titlepro.tax.manatee_ptaxweb.cffi.Session", return_value=sess
    ):
        result = lookup_manatee_tax(
            apn="1697719559",
            case_dir=tmp_path,
            safe_owner="x",
        )
    assert result.status == "TAX_NO_RESULTS"


def test_lookup_manatee_tax_500_returns_failed(tmp_path):
    sess = MagicMock()
    sess.get.return_value = MagicMock(status_code=200, text="")

    def _post(url, **kw):
        m = MagicMock()
        if kw.get("data", {}).get("action") == "list":
            m.status_code = 200
            m.text = ""
            return m
        m.status_code = 500
        m.text = "boom"
        return m

    sess.post.side_effect = _post
    with patch(
        "titlepro.tax.manatee_ptaxweb.cffi.Session", return_value=sess
    ):
        result = lookup_manatee_tax(
            apn="1697719559",
            case_dir=tmp_path,
            safe_owner="x",
        )
    assert result.status == "TAX_FAILED"
    assert "HTTP 500" in result.error
