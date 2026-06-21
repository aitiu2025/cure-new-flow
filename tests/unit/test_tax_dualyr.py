"""Unit tests for the dual-year tax echo."""
from __future__ import annotations
import pytest
from titlepro.tax.result import TaxLookupResult


def test_T1_taxresult_dataclass_accepts_prior_year_fields():
    r = TaxLookupResult(apn="x", tax_year="2025",
        property_address="a", status="TAX_SUCCESS",
        prior_year_tax_year=2024,
        prior_year_annual_amount=46100.00,
        prior_year_just_value=2611580.0,
        prior_year_net_taxable=2611580.0,
        prior_year_installment_status="PAID/CURRENT",
        prior_year_paid_date="2024-11-30",
        prior_year_source_url="https://example.test/bills/abc",
        prior_year_captured_at="2026-06-03T12:00:00",
    )
    assert r.prior_year_tax_year == 2024
    assert r.prior_year_annual_amount == 46100.00
    assert r.prior_year_installment_status == "PAID/CURRENT"
    d = r.to_json_dict()
    assert d["prior_year_tax_year"] == 2024
    assert d["prior_year_installment_status"] == "PAID/CURRENT"


def test_T1b_defaults_prior_year_to_none():
    r = TaxLookupResult(apn="y", tax_year="2025",
        property_address="a", status="TAX_SUCCESS")
    assert r.prior_year_tax_year is None
    assert r.prior_year_annual_amount is None
    assert r.prior_year_just_value is None
    assert r.prior_year_net_taxable is None
    assert r.prior_year_installment_status is None
    assert r.prior_year_paid_date is None
    assert r.prior_year_source_url is None
    assert r.prior_year_captured_at is None


BH_TWO = """
<table>
  <tr><td><a href="https://example.test/bills/uuid-2025">2025 Annual bill</a></td><td>Paid $48,027.63</td></tr>
  <tr><td><a href="https://example.test/bills/uuid-2024">2024 Annual bill</a></td><td>Paid $46,100.00</td></tr>
  <tr><td><a href="https://example.test/bills/uuid-2023">2023 Annual bill</a></td><td>Paid $44,500.00</td></tr>
</table>
"""

BH_ONE = """
<table>
  <tr><td><a href="https://example.test/bills/uuid-2025">2025 Annual bill</a></td><td>Paid $48,027.63</td></tr>
</table>
"""

BILL_2024 = """
<html><body>
<h1>Real Estate Account #494225-04-0800</h1>
<h2>2024 Annual bill</h2>
<table class="bills">
  <tr><th>Alternate Key</th><th>Escrow</th><th>Millage</th><th>Amount due</th><th>Print</th></tr>
  <tr><td>338251</td><td>-</td><td>0312</td><td>$0.00</td><td>paid Print</td></tr>
</table>
<table>
  <tr><th>Taxing authority</th><th>Millage</th><th>Assessed</th><th>Exemption</th><th>Taxable</th><th>Tax</th></tr>
  <tr><td>BROWARD COUNTY GOVERNMENT</td><td>5.6690</td><td>$2,500,000</td><td>$0</td><td>$2,500,000</td><td>$14,172.50</td></tr>
  <tr><td>Total</td><td></td><td></td><td></td><td></td><td>$46,100.00</td></tr>
</table>
</body></html>
"""


def test_T2_parse_all_annual_bills_returns_sorted_list():
    from titlepro.tax.grant_street_http import _parse_all_annual_bills
    bills = _parse_all_annual_bills(BH_TWO)
    assert len(bills) == 3
    assert [b["year"] for b in bills] == [2025, 2024, 2023]
    assert "Paid" in bills[0]["status_text"]
    assert "46,100" in bills[1]["status_text"]


class _StubResp:
    def __init__(self, status_code, text):
        self.status_code = status_code
        self.text = text


class _StubSession:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []
    def get(self, url, timeout=30):
        self.calls.append(url)
        return self._resp


def test_T3_populate_prior_year_fills_fields_on_success():
    from titlepro.tax.grant_street_http import (
        COUNTY_DEFAULTS, _populate_prior_year)
    cfg = dict(COUNTY_DEFAULTS["broward"])
    result = TaxLookupResult(apn="494225-04-0800", tax_year="2025",
        property_address="addr", status="TAX_SUCCESS",
        annual_total=48027.63)
    stub_session = _StubSession(_StubResp(200, BILL_2024))
    _populate_prior_year(result=result, bh_html=BH_TWO,
        current_year=2025, cfg=cfg, session=stub_session)
    assert result.prior_year_tax_year == 2024
    assert result.prior_year_annual_amount == pytest.approx(46100.00)
    assert result.prior_year_installment_status == "PAID/CURRENT"
    assert result.prior_year_source_url is not None
    assert "bills/uuid-2024" in result.prior_year_source_url
    assert result.prior_year_captured_at is not None
    assert len(stub_session.calls) == 1


def test_T4_populate_prior_year_noop_when_no_prior_row():
    from titlepro.tax.grant_street_http import (
        COUNTY_DEFAULTS, _populate_prior_year)
    cfg = dict(COUNTY_DEFAULTS["broward"])
    result = TaxLookupResult(apn="494225-04-0800", tax_year="2025",
        property_address="addr", status="TAX_SUCCESS",
        annual_total=48027.63)
    stub_session = _StubSession(_StubResp(200, ""))
    _populate_prior_year(result=result, bh_html=BH_ONE,
        current_year=2025, cfg=cfg, session=stub_session)
    assert result.prior_year_tax_year is None
    assert result.prior_year_annual_amount is None
    assert result.prior_year_just_value is None
    assert result.prior_year_net_taxable is None
    assert result.prior_year_installment_status is None
    assert result.prior_year_paid_date is None
    assert result.prior_year_source_url is None
    assert result.prior_year_captured_at is None
    assert stub_session.calls == []


def test_T5_dispatcher_legacy_path_defaults_prior_year_to_none(tmp_path, monkeypatch):
    """Dispatcher legacy-scraper wrap path constructs TaxLookupResult
    from a dict that has no prior_year_* keys. New fields must default
    to None and the wrap must not raise."""
    from titlepro.tax import fetch_tax
    import titlepro.tax as tax_pkg
    import sys, types
    fake_raw = {
        "success": True,
        "apn": "493-21-101-22",
        "tax_year": "2024-2025",
        "annual_tax": "5,000.00",
        "first_installment_amount": "2,500.00",
        "first_installment_status": "PAID",
        "second_installment_amount": "2,500.00",
        "second_installment_status": "PAID",
        "property_address": "addr",
        "source_url": "https://common1.mptsweb.com/?parcel=49321101022",
    }
    def _stub_mbc(apn, county, headless=True):
        return fake_raw
    fake_mod = types.ModuleType("titlepro.tax.mbc_tax_scraper")
    fake_mod.lookup_mbc_tax = _stub_mbc
    monkeypatch.setitem(sys.modules, "titlepro.tax.mbc_tax_scraper", fake_mod)
    monkeypatch.setattr(tax_pkg, "_load_county_tax_config",
        lambda county_id: {"platform": "mbc"})
    result = fetch_tax(county_id="manatee", apn="493-21-101-22",
        owner_name="OWNER", property_address="addr",
        case_dir=tmp_path)
    assert isinstance(result, TaxLookupResult)
    assert result.prior_year_tax_year is None
    assert result.prior_year_annual_amount is None
    assert result.prior_year_installment_status is None
    d = result.to_json_dict()
    assert d["prior_year_tax_year"] is None
    assert "prior_year_installment_status" in d
