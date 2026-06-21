# Escambia County PA (ESCPA) — live probe (observed 2026-06-14, via VPN'd browser)

Captured by driving the live portal through an authorized browser session.
Everything below is **observed**, not assumed.

## Portal
- Home: `https://www.escpa.org/`  (Appraiser: Gary "Bubba" Peters)
- Record Search: `https://www.escpa.org/CAMA/Search.aspx`
- Platform: **ASP.NET WebForms** (VIEWSTATE / EVENTVALIDATION postbacks) — same family as the LeePA reference adapter, so `lee_leepa.py` is the closest template.
- No Cloudflare/Akamai/CAPTCHA observed (loads cleanly over VPN). Reachable from a US residential egress; **not reachable from the CURE sandbox egress** (build/test the adapter where the portal is reachable).

## Search
- Single search box: form field **`ctl00$MasterPlaceHolder$txtValue`**.
- One box accepts: Location Address (`123 Main`), Owner Name (`Doe John` = Last First), Complex Name (`Aragon`), 16-digit Parcel ID, or 9-digit Account Number.
- Match mode selector: **Like** (default — "contained anywhere"), **Begins**, **Exact Match**. Enclose partial exact text in quotes. (Address search is mode-sensitive — bare token like `Palafox` under "Like" returns rows; `221 Palafox` under stricter modes returned none.)
- Checkbox **"Include parcels for Subdivision, Header or Complex Search"** toggles per-parcel list vs. complex/header list.
- Submit = ASP.NET postback to `Search.aspx` → **302 → `SearchResultList.aspx?s=<token>`** (server-saved query; token observed e.g. `prq`). Replayed deterministically via an in-page `fetch` POST of the live form (status 200, landed on the result list).

## Results grid
- GridView id **`ctl00_MasterPlaceHolder_grdv`**.
- Per-parcel columns: **Card · Map · Account (9-digit) · Parcel ID (16-char) · Name · Site Address · Hmstd · Bldgs · Last Sale · Last Sale Price · Acreage · Est. Assmt · Sub/Cmplx**.
- Complex-list columns (when the "include parcels" box is off): Card · Map · Name · Parcel ID · CmplxType.
- Sample rows captured (public):
  - Account `130235000` / Parcel `000S009001001113` — ESCAMBIA COUNTY COURT HOUSE, 213/221/223 PALAFOX PL, Est. 2025 Assmt 30,969,369.
  - Account `130735000` / Parcel `000S009007003004` — WARDENS & VESTRYMEN OF CHRISTS, 211/221 N PALAFOX ST, Last Sale 06/2007 $750,000, Est. Assmt 816,465.

## Detail page — RESOLVED (direct GET by Parcel ID)
- The parcel detail is a **direct GET keyed by the 16-digit Parcel ID**:
  **`https://www.escpa.org/CAMA/Detail_a.aspx?s=<16-digit-ParcelID>`**
  (e.g. `…?s=000S009001001113`). My earlier failed attempt used the 9-digit
  *account* (`?s=130735000`) — wrong key. With the Parcel ID it loads directly,
  **no postback / no session token needed.** This makes the adapter simple:
  search only to resolve address→ParcelID; APN lookups skip search entirely.
- Search submit button = `ctl00$MasterPlaceHolder$btnSubmit`; the
  "include parcels" checkbox = `ctl00$MasterPlaceHolder$chkSubParcels` (must be
  checked to get the per-parcel grid with Account/Parcel ID/Site Address rows).

## Detail page fields (confirmed on two live parcels)
General Information: `Parcel ID`, `Account`, `Owners` (may wrap 2 lines),
`Mail`, `Situs` (subject address), `Use Code`, `Taxing Authority`.
`Assessments` table: Year · Land · Imprv · Total · **Cap Val** (multi-year,
newest first — Cap Val = Save-Our-Homes capped/assessed).
`Sales Data` table (newest-first; the deed back-chain): **Sale Date (MM/YYYY) ·
Book · Page · Value · Type (WD/CT/QC/…) · Multi Parcel · Records**. Govt parcel
shows "None".
`…Certified Roll Exemptions` (e.g. RELIGIOUS / COUNTY OWNED / HOMESTEAD).
`Legal Description` (short legal). `Approx. Acreage`. `Buildings` (Year Built).

Captured text fixtures: `tests/fixtures/escambia/` — `detail_church_000S009007003004.txt`
(4 sales) and `detail_courthouse_000S009001001113.txt` (no sales).

## Adapter implications (for `escambia_pa.py`)
- Mirror `lee_leepa.py`: `curl_cffi` session → GET `Search.aspx` (harvest `__VIEWSTATE`/`__VIEWSTATEGENERATOR`/`__EVENTVALIDATION`) → POST search (`txtValue` + match-mode) → parse `grdv` rows (Account, Parcel ID, owner, situs, last sale) → fire the row-select postback → parse the detail page (owner/legal/values/homestead/sales).
- `lookup_by_apn`: feed the 16-digit Parcel ID (or 9-digit Account) into `txtValue` with Exact mode for a single hit.

## Blocker (why this isn't finished here)
The detail HTML (and parts of the result list) carry owner PII + session/query tokens; pulling that raw HTML back **through this assistant** trips the privacy guard ("BLOCKED: Cookie/query string data"), so I can't extract a clean detail fixture this way. The deterministic capture should be done **on the VPN'd machine** with `tools/probe_landmark_pa.py` (writes raw HTML to disk locally, nothing echoed through the guard), then the parser is built + unit-tested against those saved files.
