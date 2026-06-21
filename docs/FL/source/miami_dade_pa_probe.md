# Miami-Dade County PROPERTY APPRAISER (MDCPA) — Live Portal Probe

**Date:** 2026-06-17
**Egress:** US (Seattle, WA — Proton VPN) — geo-block lifted, county host reachable.
**Probe subject(s):** Stephen P. Clark Government Center (111 NW 1 ST, folio 01-4137-023-0020 — county-owned, no sales) and a Village at Dadeland condo (7500 SW 82 ST G105, folio 30-4035-047-2550 — individually-owned, homestead, 2 sales).
**Fixtures:** `tests/unit/fixtures/miami_dade/` (4 raw JSON captures).

> ⚠️ **This is the PROPERTY APPRAISER probe — distinct from the paywalled RECORDER.**
> The recorder probe (`docs/FL/miami_dade_probe.md`) covers the Clerk Official Records
> SPA at `miamidadeclerk.gov`, which is hard-blocked behind paid registration. The
> Property Appraiser is a SEPARATE, fully-public system probed here. They are not the
> same portal and must not be conflated.

---

## TL;DR — the real backing API

The official PA Property Search SPA is an **Angular app** served at
`https://www.miamidade.gov/Apps/PA/PropertySearch/`, which **302-redirects to the
canonical host** `https://apps.miamidadepa.gov/PropertySearch/` (note: host is
`miamidadepa.gov`, NOT `miamidade.gov`, and NOT the `mdcpaapi.miamidade.gov` host
guessed in the earlier offline build — that guessed host does not resolve, DNS-fails
in 0.001s).

All data comes from a single public proxy endpoint (no auth, no CAPTCHA, plain HTTPS):

```
GET https://apps.miamidadepa.gov/PApublicServiceProxy/PaServicesProxy.ashx
        ?Operation=<OperationName>
        &clientAppName=PropertySearch
        &<operation-specific params...>
```

The host is selected at runtime in the bundle's `GetWebServer()` by
`window.location.hostname`; for the public/production host
(`apps.miamidadepa.gov`) it returns `https://apps.miamidadepa.gov`. (Other cases:
`www.miamidade.gov` → `https://www.miamidade.gov`, plus dev/stage hosts.)

Discovered by fetching the SPA shell + the hashed Angular bundle
`apps.miamidadepa.gov/PropertySearch/main.b29be37fb946b6ef.js` and reading the
`GetWebServer()` + proxy-call template literals.

### Operations (from the bundle, params verified live where marked ✅)

| Operation | Params (besides `Operation` + `clientAppName=PropertySearch`) | Use |
|---|---|---|
| `GetAddress` ✅ | `myAddress=<street>`, `myUnit=<unit-or-empty>`, `from=1`, `to=200` | address → list of {Strap, Owner1..3, SiteAddress} |
| `GetPropertySearchByFolio` ✅ | `folioNumber=<13-digit unhyphenated>` | folio → full parcel + sales |
| `GetPropertySearchByPartialFolio` | `partialFolioNumber=<prefix>`, `from=0`, `to=200` | partial-folio search (not used by CURE) |
| `GetOwners` | `ownerName=<LAST FIRST>`, `from=1`, `to=200` | owner-name search (diagnostics) |
| `GetPropertySearchBySubDivision` | `subDivisionName=<name>`, `from=1`, `to=200` | subdivision search (not used) |
| `GetImportantMessage` | (none) | banner text |

---

## A. `GetAddress` — address → folio (✅ live-validated)

Request (real):
```
GET .../PaServicesProxy.ashx?Operation=GetAddress&clientAppName=PropertySearch
        &myAddress=111 NW 1 ST&myUnit=&from=1&to=200
```

Response shape (`getaddress_govctr.json`):
```json
{
  "Completed": true,
  "Message": "",
  "Total": 1,
  "MinimumPropertyInfos": [
    {
      "Strap": "01-4137-023-0020",          // <-- folio, HYPHENATED display form
      "SiteAddress": "111 NW 1 ST",
      "SiteUnit": "",
      "Owner1": "MIAMI-DADE COUNTY",
      "Owner2": "GSA R/E MGMT-DGC",
      "Owner3": "",
      "Municipality": "Miami",
      "Status": "AC Active",
      "SubdivisionDescription": "DOWNTOWN GOVERNMENT CENTER",
      "NeighborhoodDescription": "Miami CBD"
    }
  ],
  "PrintMessageHeader": null,
  "PrintMessageFooter": null
}
```

- The result-list key is **`MinimumPropertyInfos`** (NOT `Completions`/`d`/`Results`
  as the offline build guessed).
- The folio comes back as **`Strap`** in hyphenated display form
  (`NN-NNNN-NNN-NNNN`); strip hyphens for the folio-detail call.
- One street address can return MANY rows (a condo building → one row per unit:
  the residential probe `7500 SW 82 ST` returned `Total: 12`). Unit disambiguation
  via `SiteUnit` / `myUnit`.

## B. `GetPropertySearchByFolio` — folio → full parcel (✅ live-validated)

Request (real):
```
GET .../PaServicesProxy.ashx?Operation=GetPropertySearchByFolio
        &clientAppName=PropertySearch&folioNumber=3040350472550
```
`folioNumber` is the **13-digit unhyphenated** string.

Top-level keys: `PropertyInfo`, `OwnerInfos`, `SiteAddress`, `MailingAddress`,
`LegalDescription`, `Assessment`, `Benefit`, `SalesInfos`, `Land`, `Building`,
`Taxable`, `District`, `GeoParcel`, `Additionals`, `ExtraFeature`, `Completed`, …

### Field map (the ones CURE consumes) — all live-confirmed

| PropertyAppraiserResult field | MDCPA JSON path | Notes |
|---|---|---|
| `folio` (13-digit) | `PropertyInfo.FolioNumber` (hyphenated → strip) | e.g. `30-4035-047-2550` |
| `apn` (display) | same, kept hyphenated | |
| `owner_of_record` | `OwnerInfos[0].Name` | owners are objects with **`.Name`** (NOT `.Owner`) |
| `co_owners` | `OwnerInfos[1:].Name` | |
| `situs_address` | `SiteAddress[0].Address` | **`SiteAddress` is a LIST**; `.Address` is the full one-line string incl. city/zip |
| `mailing_address` | `MailingAddress.{Address1,City,State,ZipCode}` | `MailingAddress` is a single OBJECT (not a list) |
| `legal_description` | `LegalDescription.Description` | pipe-delimited segments |
| `just_value` | `Assessment.AssessmentInfos[0].TotalValue` | newest year is index 0; integer dollars (no `$`/commas) |
| `assessed_value` | `Assessment.AssessmentInfos[0].AssessedValue` | |
| `year_built` | `PropertyInfo.YearBuilt` | may be a string like `"Multiple (See Building Info.)"` for multi-building parcels → `_safe_int` yields 0 |
| `living_area_sqft` | `PropertyInfo.BuildingHeatedArea` | can be `-1` (unknown) → guard |
| `homestead_active` | `Benefit.BenefitInfos[*]` where `Type=="Exemption"` and `Description` startswith `"Homestead"` | |

### Sales — `SalesInfos` (✅ live-validated; the back-chain anchor)

`SalesInfos` is a **bare JSON list** (no wrapper). **Rows are returned
OLDEST-FIRST**; `SaleId` 1 = the newest sale. The `sale_history` contract is
newest-first, so the adapter **sorts by `SaleId` ascending** (1, 2, 3 …) to flip
to newest-first.

Real `SalesInfo` row (`folio_residential_condo.json`):
```json
{
  "SaleId": 1,
  "DateOfSale": "5/1/2005",            // M/D/YYYY (no zero-pad)
  "SalePrice": 187900,                 // integer dollars
  "OfficialRecordBook": "23430",
  "OfficialRecordPage": "4362",
  "SaleInstrument": "",                // CIN/instrument — often EMPTY for older sales
  "QualifiedFlag": "Q",                // "Q" qualified / "U" unqualified
  "QualificationDescription": "Sales which are qualified",
  "ReasonCode": "00",
  "GrantorName1": "", "GrantorName2": "",   // EMPTY in this dataset
  "GranteeName1": "", "GranteeName2": "",
  "DocumentStamps": 0,
  "EncodedRecordBookAndPage": "...url-token..."
}
```

- **No `DeedType` field exists in the API.** MDCPA does not classify the deed
  type. (BCPA does; this is a genuine PA-parity gap — deed type must come from the
  recorder cross-ref, same as grantor/grantee, which are also blank here.)
- Book/page split: use `OfficialRecordBook`/`OfficialRecordPage` → `deed_book_page`;
  if both empty but `SaleInstrument` present, use `deed_doc_number`.

---

## C. Anti-bot / headers

- **No Cloudflare, no Akamai, no CAPTCHA.** Plain `curl` with a desktop UA + the
  `Referer: https://apps.miamidadepa.gov/PropertySearch/` returns `200`
  `application/json` on every call. curl_cffi impersonation is sufficient (and not
  even strictly required, but kept for consistency with the other adapters).
- Calls were spaced 4 s apart; no rate-limit observed.

## D. Gaps / open items for a future round

1. **Deed type** is not in the PA feed (no `DeedType`) — recorder cross-ref fills it.
2. **Grantor/Grantee** are present in the schema (`GrantorName1/2`, `GranteeName1/2`)
   but were EMPTY in both probed parcels — unknown whether they are ever populated.
3. **Multi-unit address search** returns one row per unit; for a unit subject the
   caller must pass `myUnit`. CURE's by-address path picks the exact `SiteAddress`+
   unit match or returns `PA_AMBIGUOUS`.
4. `YearBuilt` can be a non-numeric string for multi-building parcels.
5. `BuildingHeatedArea` can be `-1` (sentinel for unknown).
