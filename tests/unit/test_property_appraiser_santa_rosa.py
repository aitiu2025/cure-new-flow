"""Santa Rosa County PA adapter tests — parse_detail_html validated against
synthetic HTML matching the live parcelview.srcpa.gov structure (2026-06-19).

The test subject is TIMOTHY WHITE, 1009 RIN CT, MILTON, FL 32583,
parcelNumber=23-1S-28-0003-00A00-0170, parcelKey=10097741.

Live-confirmed values:
  owner: WHITE TIMOTHY
  apn:   23-1S-28-0003-00A00-0170
  situs: 1009 RIN CT, MILTON, 32583
  just_value: 248159   (2025 — last of three columns)
  assessed:   156483   (2025 — last of three columns)
  homestead:  True
  legal: ADRIAN WOODS PHASE I  LOT 17 BLK A  AS DES IN OR 3400 PG 80 …
  sale_history[0]: 01/12/2015 / $152,500 / WD / 3400/80
                   grantor=FEDERAL NATIONAL MORTGAGE ASSOCIATION
                   grantee=WHITE TIMOTHY

Tests are parameterised against synthetic HTML so no network calls are made.
"""

import pytest
from titlepro.property_appraiser.counties.santa_rosa_pa import SantaRosaPA

# ---------------------------------------------------------------------------
# Synthetic HTML fixture
# ---------------------------------------------------------------------------
# This reproduces the label→value pattern that parse_detail_html expects from
# soup.get_text("\n").  Only the fields exercised by tests need to be present.

_DETAIL_HTML = """<!DOCTYPE html>
<html>
<head><title>Parcel Detail</title></head>
<body>
<div>
  <p>Parcel Number</p>
  <p>23-1S-28-0003-00A00-0170</p>
  <p>Situs/Physical Address</p>
  <p>1009 RIN CT, MILTON, 32583</p>
  <p>Property Usage</p>
  <p>SINGLE FAMILY (000100)</p>
  <p>Section-Township-Range</p>
  <p>23-1S-28</p>
  <p>Acreage</p>
  <p>0.281</p>
  <p>Exemptions</p>
  <p>HOMESTEAD EXEMPTION</p>
  <p>Brief Legal Description</p>
  <p>ADRIAN WOODS PHASE I  LOT 17 BLK A  AS DES IN OR 3400 PG 80    SBJT TO DOT ESMNT AS DES IN OR 3333 PG 1087</p>
  <p>Primary Owner</p>
  <p>WHITE TIMOTHY</p>
  <p>1009 RIN CT</p>
  <p>MILTON, FL 32583-7806</p>
  <p>Just (Market) Value</p>
  <p>$249,418</p>
  <p>$251,502</p>
  <p>$248,159</p>
  <p>Co. Assessed Value</p>
  <p>$147,644</p>
  <p>$152,073</p>
  <p>$156,483</p>
  <p>Sales</p>
  <p>Multi-Parcel</p>
  <p>Sale Date</p>
  <p>Sale Price</p>
  <p>Instrument</p>
  <p>Book</p>
  <p>/</p>
  <p>Page</p>
  <p>Book</p>
  <p>/</p>
  <p>Page</p>
  <p>Qualification</p>
  <p>Sale Type</p>
  <p>Grantor</p>
  <p>Grantee</p>
  <p>N</p>
  <p>01/12/2015</p>
  <p>$152,500</p>
  <p>WD</p>
  <p>3400</p>
  <p>/</p>
  <p>80</p>
  <p>3400</p>
  <p>/</p>
  <p>80</p>
  <p>Q</p>
  <p>I</p>
  <p>FEDERAL NATIONAL MORTGAGE ASSOCIATION</p>
  <p>WHITE TIMOTHY</p>
  <p>Map</p>
</div>
</body>
</html>
"""

# A second synthetic HTML with TWO sales (to verify newest-first ordering and
# multi-sale parsing).
_DETAIL_HTML_TWO_SALES = """<!DOCTYPE html>
<html>
<body>
<div>
  <p>Parcel Number</p>
  <p>07-1N-28-0000-00400-0000</p>
  <p>Situs/Physical Address</p>
  <p>5000 TEST BLVD, NAVARRE, 32566</p>
  <p>Exemptions</p>
  <p>HOMESTEAD EXEMPTION</p>
  <p>Brief Legal Description</p>
  <p>SOME LEGAL DESCRIPTION HERE</p>
  <p>Primary Owner</p>
  <p>DOE JOHN</p>
  <p>5000 TEST BLVD</p>
  <p>NAVARRE, FL 32566-1234</p>
  <p>Just (Market) Value</p>
  <p>$300,000</p>
  <p>$310,000</p>
  <p>$320,000</p>
  <p>Co. Assessed Value</p>
  <p>$200,000</p>
  <p>$210,000</p>
  <p>$220,000</p>
  <p>Sales</p>
  <p>Multi-Parcel</p>
  <p>Sale Date</p>
  <p>Sale Price</p>
  <p>Instrument</p>
  <p>Book</p>
  <p>/</p>
  <p>Page</p>
  <p>Book</p>
  <p>/</p>
  <p>Page</p>
  <p>Qualification</p>
  <p>Sale Type</p>
  <p>Grantor</p>
  <p>Grantee</p>
  <p>N</p>
  <p>03/15/2020</p>
  <p>$290,000</p>
  <p>WD</p>
  <p>5100</p>
  <p>/</p>
  <p>200</p>
  <p>5100</p>
  <p>/</p>
  <p>200</p>
  <p>Q</p>
  <p>I</p>
  <p>SMITH JANE</p>
  <p>DOE JOHN</p>
  <p>N</p>
  <p>06/01/2008</p>
  <p>$150,000</p>
  <p>WD</p>
  <p>3000</p>
  <p>/</p>
  <p>50</p>
  <p>3000</p>
  <p>/</p>
  <p>50</p>
  <p>U</p>
  <p>I</p>
  <p>JONES BOB</p>
  <p>SMITH JANE</p>
  <p>Map</p>
</div>
</body>
</html>
"""

# Minimal HTML with no homestead exemption
_DETAIL_HTML_NO_HOMESTEAD = """<!DOCTYPE html>
<html>
<body>
<div>
  <p>Parcel Number</p>
  <p>05-1N-29-0001-00100-0010</p>
  <p>Situs/Physical Address</p>
  <p>200 OAK ST, PACE, 32571</p>
  <p>Exemptions</p>
  <p>NONE</p>
  <p>Brief Legal Description</p>
  <p>PACE ESTATES LOT 10 BLK 1</p>
  <p>Primary Owner</p>
  <p>CORP ACME LLC</p>
  <p>200 OAK ST</p>
  <p>PACE, FL 32571-0000</p>
  <p>Just (Market) Value</p>
  <p>$100,000</p>
  <p>$105,000</p>
  <p>$110,000</p>
  <p>Co. Assessed Value</p>
  <p>$100,000</p>
  <p>$105,000</p>
  <p>$110,000</p>
  <p>Sales</p>
  <p>Multi-Parcel</p>
  <p>Sale Date</p>
  <p>Sale Price</p>
  <p>Instrument</p>
  <p>Book</p>
  <p>/</p>
  <p>Page</p>
  <p>Book</p>
  <p>/</p>
  <p>Page</p>
  <p>Qualification</p>
  <p>Sale Type</p>
  <p>Grantor</p>
  <p>Grantee</p>
  <p>Map</p>
</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _parse(html: str):
    return SantaRosaPA.parse_detail_html(html)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestParseOwnerAndAPN:
    """Test 1: owner_of_record and apn are extracted correctly."""

    def test_owner_name(self):
        r = _parse(_DETAIL_HTML)
        assert r.owner_of_record == "WHITE TIMOTHY"

    def test_apn(self):
        r = _parse(_DETAIL_HTML)
        assert r.apn == "23-1S-28-0003-00A00-0170"

    def test_status_success(self):
        r = _parse(_DETAIL_HTML)
        assert r.status == "PA_SUCCESS"


class TestParseSitusAddress:
    """Test 2: situs_address parsed correctly."""

    def test_situs(self):
        r = _parse(_DETAIL_HTML)
        assert r.situs_address == "1009 RIN CT, MILTON, 32583"

    def test_situs_no_state_abbreviation_in_value(self):
        # situs should not contain "FL" — portal omits it
        r = _parse(_DETAIL_HTML)
        assert "FL" not in r.situs_address


class TestParseJustValue:
    """Test 3: just_value takes the LAST of three year columns (most recent)."""

    def test_just_value_is_most_recent_year(self):
        r = _parse(_DETAIL_HTML)
        # 2025 value = $248,159 (last of $249,418 / $251,502 / $248,159)
        assert r.just_value == 248159

    def test_assessed_value_is_most_recent_year(self):
        r = _parse(_DETAIL_HTML)
        # 2025 assessed = $156,483 (last of $147,644 / $152,073 / $156,483)
        assert r.assessed_value == 156483

    def test_two_sales_just_value(self):
        r = _parse(_DETAIL_HTML_TWO_SALES)
        # Last of $300,000 / $310,000 / $320,000
        assert r.just_value == 320000

    def test_two_sales_assessed_value(self):
        r = _parse(_DETAIL_HTML_TWO_SALES)
        # Last of $200,000 / $210,000 / $220,000
        assert r.assessed_value == 220000


class TestParseHomestead:
    """Test 4: homestead_active flag is set from the Exemptions section."""

    def test_homestead_true_when_exemption_present(self):
        r = _parse(_DETAIL_HTML)
        assert r.homestead_active is True

    def test_homestead_false_when_none(self):
        r = _parse(_DETAIL_HTML_NO_HOMESTEAD)
        assert r.homestead_active is False


class TestParseSalesHistory:
    """Test 5: sale_history parsed correctly — newest-first ordering."""

    def test_single_sale_count(self):
        r = _parse(_DETAIL_HTML)
        assert len(r.sale_history) == 1

    def test_sale_date(self):
        r = _parse(_DETAIL_HTML)
        assert r.sale_history[0].sale_date == "01/12/2015"

    def test_sale_price(self):
        r = _parse(_DETAIL_HTML)
        assert r.sale_history[0].sale_price == 152500

    def test_deed_type(self):
        r = _parse(_DETAIL_HTML)
        assert r.sale_history[0].deed_type == "WD"

    def test_book_page(self):
        r = _parse(_DETAIL_HTML)
        assert r.sale_history[0].deed_book_page == "3400/80"

    def test_grantor(self):
        r = _parse(_DETAIL_HTML)
        assert r.sale_history[0].grantor == "FEDERAL NATIONAL MORTGAGE ASSOCIATION"

    def test_grantee(self):
        r = _parse(_DETAIL_HTML)
        assert r.sale_history[0].grantee == "WHITE TIMOTHY"

    def test_qualified_flag(self):
        r = _parse(_DETAIL_HTML)
        assert r.sale_history[0].qualified is True  # "Q" → True

    def test_two_sales_count(self):
        r = _parse(_DETAIL_HTML_TWO_SALES)
        assert len(r.sale_history) == 2

    def test_two_sales_newest_first(self):
        r = _parse(_DETAIL_HTML_TWO_SALES)
        assert r.sale_history[0].sale_date == "03/15/2020"
        assert r.sale_history[1].sale_date == "06/01/2008"

    def test_two_sales_unqualified(self):
        r = _parse(_DETAIL_HTML_TWO_SALES)
        # Second sale has "U" → qualified=False
        assert r.sale_history[1].qualified is False

    def test_no_sales_when_empty(self):
        r = _parse(_DETAIL_HTML_NO_HOMESTEAD)
        assert r.sale_history == []


class TestParseEdgeCases:
    """Additional edge-case coverage."""

    def test_empty_html_returns_failed(self):
        r = _parse("")
        assert r.status == "PA_FAILED"

    def test_short_html_returns_failed(self):
        r = _parse("<html></html>")
        assert r.status == "PA_FAILED"

    def test_legal_description(self):
        r = _parse(_DETAIL_HTML)
        assert "ADRIAN WOODS PHASE I" in r.legal_description
        assert "LOT 17 BLK A" in r.legal_description

    def test_mailing_address_captured(self):
        r = _parse(_DETAIL_HTML)
        # Mailing address lines after owner name: "1009 RIN CT" + "MILTON, FL 32583-7806"
        assert "1009 RIN CT" in r.mailing_address or "MILTON" in r.mailing_address


class TestSearchJsonParsing:
    """Test _parse_search_json with canned API response."""

    def test_parse_results_list(self):
        data = {
            "results": [
                {
                    "parcelKey": 10097741,
                    "parcelNumber": "23-1S-28-0003-00A00-0170",
                    "ownerName": "WHITE TIMOTHY",
                    "situsAddress": "1009 RIN CT",
                    "homestead": "Y",
                    "vacantImproved": "I",
                    "zoning": "RR1",
                    "checked": False,
                }
            ]
        }
        results = SantaRosaPA._parse_search_json(data)
        assert len(results) == 1
        assert results[0]["parcelNumber"] == "23-1S-28-0003-00A00-0170"
        assert results[0]["ownerName"] == "WHITE TIMOTHY"

    def test_parse_empty_results(self):
        assert SantaRosaPA._parse_search_json({"results": []}) == []

    def test_parse_missing_results_key(self):
        assert SantaRosaPA._parse_search_json({}) == []

    def test_parse_null_results(self):
        assert SantaRosaPA._parse_search_json({"results": None}) == []


class TestDetailUrl:
    """Test the detail URL builder."""

    def test_detail_url_encodes_parcel(self):
        adapter = SantaRosaPA({})
        url = adapter._detail_url("23-1S-28-0003-00A00-0170")
        assert "parcel=23-1S-28-0003-00A00-0170" in url
        assert "baseUrl=http" in url
        assert "parcelview.srcpa.gov" in url

    def test_detail_url_encodes_special_chars(self):
        adapter = SantaRosaPA({})
        url = adapter._detail_url("23-1S-28-0003-00A00-0170")
        # Hyphens and digits should pass through unencoded (safe chars)
        assert "23-1S-28" in url


class TestFactoryRoutesSantaRosa:
    """Test that the factory routes fl_santa_rosa to SantaRosaPA.

    Factory branch and config entry wired 2026-06-19.
    """

    def test_factory_dispatch(self, monkeypatch):
        import titlepro.property_appraiser as pa

        captured = {}

        def fake_apn(self, apn):
            captured["apn"] = apn
            from titlepro.property_appraiser.result import PropertyAppraiserResult
            return PropertyAppraiserResult(status="PA_SUCCESS", apn=apn)

        monkeypatch.setattr(SantaRosaPA, "lookup_by_apn", fake_apn)
        res = pa.fetch_property_appraiser(
            "fl_santa_rosa", apn="23-1S-28-0003-00A00-0170"
        )
        assert res.status == "PA_SUCCESS"
        assert captured["apn"] == "23-1S-28-0003-00A00-0170"
