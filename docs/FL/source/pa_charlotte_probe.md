# Charlotte County (FL) Property Appraiser — Live Probe 2026-06-19

## Portal
- URL: https://www.ccappraiser.com/
- Platform: **County-custom Classic ASP** (Microsoft-IIS/8.5, ASP.NET 4.0)
- Anti-bot: NONE — no Cloudflare, no CAPTCHA, plain IIS
- Datacenter reachable: YES (Seattle Proton confirmed 200)

## Search Flow
Two-step:
1. **GET** `/RPSearchEnter.asp?` → renders the search form (no TOU gate, no VIEWSTATE — pure classic ASP)
2. **POST** `/RPSearchQuery.asp` with form fields:
   - `ParcelID_number` — Charlotte APN (format: `412024203012`)
   - `PropertyAddressNumber` — house number (e.g. `100`)
   - `PropertyAddressStreetName` — street name (e.g. `LONG MEADOW`)
   - `owner` — owner name
   - `ShortLegal` — short legal description
   - `CurrentLandUse` — land use filter (default `Any`)
   Response is a **302 redirect** to `/RPSearchSelect.asp` with results stored in session.
3. **GET** `/RPSearchSelect.asp` (with session cookie) → HTML results table with:
   - Columns: Parcel ID | Owner | Property Address | Short Legal | Just Value | Taxable Value | Use Code
   - Parcel ID links to `/Show_Parcel.asp?acct=<ParcelID>&gen=T&tax=T&bld=T&oth=T&sal=T&lnd=T&leg=T`

## Detail Page
- URL: `/Show_Parcel.asp?acct=<ParcelID>&gen=T&tax=T&bld=T&oth=T&sal=T&lnd=T&leg=T`
- **Direct access works** (GET with session cookie from homepage; no search step needed)
- Fields available:
  - Owner: `OLAR IVAN & ERICA` (full name block in `.w3-border-blue` div)
  - Property Address: `100 LONG MEADOW LN`
  - APN: `412024203012` (from URL `acct=` param and page title "Property Record Information for 412024203012")
  - Certified Just Value: `$499,242` (in td after "Certified Just Value" label)
  - Certified Assessed Value: `$499,242`
  - Homestead: YES (`01 Homestead` exemption + `17 Additional Homestead`)
  - Short Legal: `RLM 000 0000 0271`
  - Long Legal: `ROTONDA WEST LONG MEADOW LT 271 843/1971 1347/525 2047/2043 CD2583/1451 3981/1444 3986/2070 4835/1444`
  - Sales Table headers: Date | Book/Page | Instrument Number | Selling Price | Sales code | Qualification Code
  - Sales data (OLAR parcel):
    - 9/3/2021 | 4835/1444 | 2993739 | $47,000 | VACANT | 01
    - 5/15/2015 | 3986/2070 | 2363085 | $100 | VACANT | 11
    - 5/15/2015 | 3981/1444 | 2358799 | $100 | VACANT | 11
    - 9/1/2004 | 2583/1451 | 1291249 | $100 | VACANT | 19
    - 5/1/2002 | 2047/2043 | 921659 | $100 | VACANT | (blank)
    - 11/1/1993 | 1347/525 | 298320 | $100 | VACANT | (blank)
    - 11/1/1985 | 843/1971 | 1985084301971 | $6,600 | VACANT | (blank)

## APN Format
- Charlotte uses numeric-only APNs: `412024203012` (12 digits, no dashes)
- Direct detail URL: `Show_Parcel.asp?acct=412024203012&gen=T&tax=T&bld=T&oth=T&sal=T&lnd=T&leg=T`
  → Works with only session cookie from homepage GET; no search step required for APN lookup.

## Key Gotchas
- Search POST must include `CurrentLandUse=Any` (the select default) or it returns 0 results
- The POST redirects 302 to `RPSearchSelect.asp` — must follow with the same session cookie
- Street name search: full street name works ("LONG MEADOW"), not just the keyword
- The `owner` search field accepts partial last-name matches
- `Instrument Number` column in sales = the recorder document number (cross-ref key)

## Recommended Adapter Pattern
- Platform: `charlotte_ccpa_http` (county-custom classic ASP)
- Two-step: GET homepage (set session cookie) → POST search → GET RPSearchSelect.asp results → GET Show_Parcel.asp
- APN lookup: GET homepage → GET Show_Parcel.asp?acct=<APN> directly (no search step needed)
- `deed_doc_number` = Instrument Number column in sales table
- `deed_book_page` = Book/Page column

## Config snippet (add to county_property_appraiser_urls.json)
```json
"fl_charlotte": {
  "county_name": "Charlotte",
  "base_url": "https://www.ccappraiser.com",
  "platform": "charlotte_ccpa_http",
  "status": "live",
  "live_confirmed": "2026-06-19",
  "description": "Charlotte County Property Appraiser (classic ASP, IIS 8.5, no CF)",
  "notes": "Direct Show_Parcel.asp?acct=<APN> works with only homepage session cookie. Search: POST RPSearchQuery.asp → GET RPSearchSelect.asp."
}
```
