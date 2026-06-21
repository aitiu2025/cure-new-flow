# County URL Mapping — CA, OH & FL

> ⚠️ **CA work is PAUSED as of 2026-05-20** (focus on FL). Before resuming any CA implementation work, **read `docs/CA_Implementation_Update_2005.md`** for the per-county, per-phase status, what's already verified end-to-end, and the immediate-next-steps checklist.

> **🔒 SOURCE OF TRUTH** — This file (and its sibling `County_URL_Mapping_CUREMasterSheet.xlsx`) is the canonical reference for **all County Recorder URLs, TitlePro247 Image-Download URLs, and County Tax URLs** used by CURE.
>
> **Last sync:** 2026-05-19 (v3) from `~/Downloads/CURE Source of Truth/CA CURE County Search URLs (2).xlsx`. Tony Roveda's phase-one FL platform classification merged in; FL `Platform (Tax)` column added to canonical XLSX FL sheet. CA test-subject details and FL examples live in `CA_Examples.md` and `FL_Examples.md`.
>
> Applies to BOTH workflow modes:
> 1. **Generate Report in One Step** (single-shot pipeline)
> 2. **Step-by-Step Execution** (gated workflow)
>
> When this doc changes, the following code must be reviewed and synced:
> - `src/titlepro/search/ca_recorder/counties/registry.py` (recorder county registry)
> - `src/titlepro/search/ca_recorder/counties/config/*.json` (per-county recorder configs)
> - `config/county_tax_urls.json` (tax/assessor URLs)
> - `src/titlepro/download/selenium_downloader.py` + `secrets.json` `TITLEPRO_URL` (image download base)
> - `src/titlepro/search/ca_recorder/CURE.html` county dropdown options
>
> **Next expected update:** Monday — diff the new version against this file, then update each of the code paths above accordingly.

**Generated:** 2026-05-08
**Source files:**
- Recorder configs: `src/titlepro/search/ca_recorder/counties/config/*.json`
- Recorder registry: `src/titlepro/search/ca_recorder/counties/registry.py`
- Tax URLs: `config/county_tax_urls.json`
- Image download (TitlePro247): `src/titlepro/download/selenium_downloader.py:18` and `src/titlepro/search/titlepro_initial_search.py:12`
- OH pilot subject: `config/mis_pilot_oh_subjects.json`

## Summary

| Coverage | States | Counties |
|---|---|---|
| **Recorder website (CURE search adapters)** | 1 (CA) | 23 (5 RecorderWorks + 18 Tyler) |
| **Recorder URLs catalogued (no adapter yet)** | 1 (FL) | 67 (every FL county) |
| **Tax / assessor lookup** | 3 (CA, OH, FL) | 97 (29 CA + 1 OH + 67 FL) |
| **Image download** | All counties | 1 shared portal: `https://www.titlepro247.com/` |

> Note: Only CA has **recorder-search adapters** built in CURE today. OH (Cuyahoga) has a **tax-lookup config + recorder reference URL** wired through the OH pilot subject file but no automated recorder adapter yet. The **67 FL counties** below are catalogued for the next adapter-build wave — recorder URLs, CAPTCHA flags, and tax URLs are mapped but no FL-specific search adapter or tax recipe exists yet in the codebase.

## California (CA) — 23 recorder counties / 29 tax counties

| State | County | CountyURL (Recorder) | ImageDownloadURL | TaxURL |
|---|---|---|---|---|
| CA | Amador | https://mint.amadorgov.org/RecorderWorksInternet/ | https://www.titlepro247.com/ | https://common1.mptsweb.com/MBC/amador/tax/search |
| CA | Calaveras | https://recorderweb.calaverascounty.gov/Web/ | https://www.titlepro247.com/ | — |
| CA | Del Norte | https://delnortecountyca-web.tylerhost.net/web/user/disclaimer | https://www.titlepro247.com/ | — |
| CA | Fresno | https://fresnocountyca-web.tylerhost.net/web/user/disclaimer | https://www.titlepro247.com/ | https://www.fresnocountyca.gov/Departments/Auditor-Controller-Treasurer-Tax-Collector/Property-Tax-Information |
| CA | Humboldt | https://humboldtcountyca-web.tylerhost.net/web/user/disclaimer | https://www.titlepro247.com/ | — |
| CA | Imperial | https://recorder.co.imperial.ca.us/RecorderWorksInternet/?ln=en | https://www.titlepro247.com/ | — |
| CA | Inyo | https://inyococa-web.tylerhost.net/web/user/disclaimer | https://www.titlepro247.com/ | — |
| CA | Kings | https://kingscountyca-web.tylerhost.net/web/user/disclaimer | https://www.titlepro247.com/ | https://common1.mptsweb.com/MBC/kings/tax/search |
| CA | Lake | https://lakecountyca-web.tylerhost.net/web/user/disclaimer | https://www.titlepro247.com/ | https://common2.mptsweb.com/MBC/lake/tax/search |
| CA | Madera | https://maderacountyca-web.tylerhost.net/web/user/disclaimer | https://www.titlepro247.com/ | — |
| CA | Merced | https://web2.co.merced.ca.us/RWInternet/ | https://www.titlepro247.com/ | — |
| CA | Monterey | https://montereycountyca-web.tylerhost.net/Montereyweb/user/disclaimer | https://www.titlepro247.com/ | — |
| CA | Orange | https://cr.occlerkrecorder.gov/RecorderWorksInternet/ | https://www.titlepro247.com/ | https://taxbill.octreasurer.gov/ |
| CA | San Benito | https://sanbenitocountyca-web.tylerhost.net/web/user/disclaimer | https://www.titlepro247.com/ | https://common2.mptsweb.com/mbc/sanbenito/tax/search |
| CA | San Joaquin | https://sanjoaquincountyca-web.tylerhost.net/Web/user/disclaimer | https://www.titlepro247.com/ | https://propertytax.sjgov.org/ |
| CA | San Luis Obispo | https://sanluisobispocountyca-web.tylerhost.net/SLOWeb/ | https://www.titlepro247.com/ | https://www.slocountytax.org/ |
| CA | Santa Cruz | https://santacruzcountyca-web.tylerhost.net/web/ | https://www.titlepro247.com/ | — |
| CA | Sierra | https://sierraca-web.tylerhost.net/web/user/disclaimer | https://www.titlepro247.com/ | — |
| CA | Stanislaus | https://crweb.stancounty.com/RecorderWorksInternet/?ln=en | https://www.titlepro247.com/ | https://www.stancounty.com/tax/ |
| CA | Trinity | https://trinitycountyca-web.tylerhost.net/web/user/disclaimer | https://www.titlepro247.com/ | — |
| CA | Tulare | https://tularecountyca-web.tylerhost.net/web/user/disclaimer | https://www.titlepro247.com/ | https://common2.mptsweb.com/MBC/tulare/tax/search |
| CA | Tuolumne | https://tuolumnecountyca-web.tylerhost.net/web/user/disclaimer | https://www.titlepro247.com/ | — |
| CA | Yolo | https://yolocountyca-web.tylerhost.net/web/user/disclaimer | https://www.titlepro247.com/ | — |

### CA tax-only counties (no recorder adapter yet)

| State | County | CountyURL (Recorder) | ImageDownloadURL | TaxURL |
|---|---|---|---|---|
| CA | Los Angeles | — | https://www.titlepro247.com/ | https://www.propertytax.lacounty.gov/ |
| CA | San Diego | — | https://www.titlepro247.com/ | https://www.sdttc.com/ |
| CA | Santa Clara | — | https://www.titlepro247.com/ | https://dtac.santaclaracounty.gov/ |
| CA | Alameda | — | https://www.titlepro247.com/ | https://propertytax.alamedacountyca.gov/search |
| CA | Riverside | — | https://www.titlepro247.com/ | https://ca-riverside-ttc.publicaccessnow.com/PropertySearch.aspx |
| CA | San Bernardino | — | https://www.titlepro247.com/ | https://www.sbcountyatc.gov/tax-collector |
| CA | San Mateo | — | https://www.titlepro247.com/ | https://smcacre.gov/assessor/property-tax-look |
| CA | Sacramento | — | https://www.titlepro247.com/ | https://eproptax.saccounty.gov/ |
| CA | Ventura | — | https://www.titlepro247.com/ | https://www.mytaxcollector.com/trSearch.aspx |
| CA | Contra Costa | — | https://www.titlepro247.com/ | https://www.cctax.us/ |
| CA | Kern | — | https://www.titlepro247.com/ | https://ttc.kerncounty.com/ |
| CA | Sonoma | — | https://www.titlepro247.com/ | https://sonomacounty.ca.gov/tax |
| CA | Santa Barbara | — | https://www.titlepro247.com/ | https://www.countyofsb.org/ttc |
| CA | Plumas | — | https://www.titlepro247.com/ | https://common1.mptsweb.com/MBC/plumas/tax/search |
| CA | Tehama | — | https://www.titlepro247.com/ | https://common1.mptsweb.com/mbc/tehama/tax/search |
| CA | Mono | — | https://www.titlepro247.com/ | https://common2.mptsweb.com/mbc/mono/tax/search |
| CA | Butte | — | https://www.titlepro247.com/ | https://common2.mptsweb.com/mbc/butte/tax/search |
| CA | Placer | — | https://www.titlepro247.com/ | https://common3.mptsweb.com/mbc/placer/tax/search |

## Ohio (OH) — 1 county

| State | County | CountyURL (Recorder) | ImageDownloadURL | TaxURL |
|---|---|---|---|---|
| OH | Cuyahoga | https://cr.cuyahogacounty.us/ | https://www.titlepro247.com/ | https://myplace.cuyahogacounty.gov/ |

> Cuyahoga recorder URL comes from `config/mis_pilot_oh_subjects.json` and the `notes` field of the Cuyahoga tax entry. There is no Tyler/RecorderWorks adapter for it — searches are run via the MyPlace portal documented in the `navigation` block of `county_tax_urls.json`.

## Florida (FL) — 67 counties (population-rank ordered)

**5 recorder platforms** identified by Tony Roveda (phase-one classification, 2026-05-19):
Clericus (23), LandMark (16), Proprietary one-offs (17, includes VisualGov + PublicSoft variants — 10/20 largest FL counties fall here), Tyler Technologies (4, **already covered** by CURE Tyler adapter), DueProcess (3).

Tax-portal vendors (from v3 sheet's `Platform` column) cover all 67: Grant Street 31, VisualGov 18, PublicSoft 11, Aumentum Technologies 3, Pacific Blue 2, Proprietary 2.

| Rank | County | CountyURL (Recorder) | Platform (Tax) | CAPTCHA | POST-CAPTCHA URL | TaxURL |
|---|---|---|---|---|---|---|
| 1 | Miami-Dade | https://onlineservices.miamidadeclerk.gov/officialrecords/ | Grant Street | No | — | https://county-taxes.net/fl-miamidade/property-tax |
| 2 | Broward | https://officialrecords.broward.org/AcclaimWeb/ | Grant Street | No | — | https://county-taxes.net/broward/property-tax |
| 3 | Palm Beach | https://www.mypalmbeachclerk.com/records/official-records | Aumentum Technologies | YES (disclaimer) | https://erec.mypalmbeachclerk.com/ | https://pbctax.publicaccessnow.com/PropertyTax.aspx |
| 4 | Hillsborough | https://publicaccess.hillsclerk.com/oripublicaccess/ | Grant Street | No | — | https://county-taxes.net/hillsborough/property-tax |
| 5 | Orange | https://selfservice.or.occompt.com/ssweb/user/disclaimer | Grant Street | Yes | https://selfservice.or.occompt.com/ssweb/search/DOCSEARCH2950S1 | https://county-taxes.net/fl-orange/property-tax |
| 6 | Duval | https://or.duvalclerk.com/ | Grant Street | YES (disclaimer) | https://or.duvalclerk.com/search/SearchTypeName | https://county-taxes.net/fl-duval/property-tax |
| 7 | Pinellas | https://officialrecords.mypinellasclerk.gov/ | Grant Street | YES (disclaimer) | https://officialrecords.mypinellasclerk.gov/search/SearchTypeName | https://county-taxes.net/pinellas/property-tax |
| 8 | Lee | https://or.leeclerk.org/LandMarkWeb/ | Grant Street | YES (disclaimer) | https://or.leeclerk.org/LandMarkWeb/search/index?theme=.blue&section=searchCriteriaName | https://county-taxes.net/fl-lee/property-tax |
| 9 | Polk | https://apps.polkcountyclerk.net/browserviewor/ | PublicSoft | No | — | https://polk.floridatax.us/AccountSearch?s=pt |
| 10 | Brevard | https://vaclmweb1.brevardclerk.us/AcclaimWeb/ | Grant Street | YES (disclaimer) | https://vaclmweb1.brevardclerk.us/AcclaimWeb/search/SearchTypeName | https://county-taxes.net/brevard/property-tax |
| 11 | Pasco | https://app.pascoclerk.com/appdot-public-online-services-forms-or-search.asp | Grant Street | No | — | https://county-taxes.net/fl-pasco/property-tax |
| 12 | Volusia | https://app02.clerk.org/or_m/ | Grant Street | YES (disclaimer) | https://app02.clerk.org/or_m/inquiry.aspx | https://county-taxes.net/vctaxcollector/property-tax |
| 13 | Seminole | https://recording.seminoleclerk.org/DuProcessWebInquiry/index.html | Grant Street | YES (disclaimer) | https://recording.seminoleclerk.org/DuProcessWebInquiry/index.html | https://county-taxes.net/fl-seminole/fl-seminole/property-tax |
| 14 | Sarasota | https://secure.sarasotaclerk.com/OfficialRecords.aspx | Aumentum Technologies | No | — | https://sarasotataxcollector.publicaccessnow.com/TaxCollector/PropertyTaxSearch.aspx |
| 15 | Manatee | https://records.manateeclerk.com/OfficialRecords/Search | Pacific Blue | No | https://records.manateeclerk.com/OfficialRecords/Search/Party | https://secure.taxcollector.com/ptaxweb/editPropertySearch2.action |
| 16 | Osceola | https://officialrecords.osceolaclerk.org/browserview/ | Grant Street | No | — | https://county-taxes.net/osceola/property-tax |
| 17 | Lake | https://officialrecords.lakecountyclerk.org/ | Grant Street | YES (disclaimer) | https://officialrecords.lakecountyclerk.org/search/SearchTypeName | https://county-taxes.net/lake/property-tax |
| 18 | Marion | https://nvweb.marioncountyclerk.org/searchng_SSL/ | (Proprietary) | YES (disclaimer) | — | https://www.mariontax.com/itm/PropertySearchName.aspx |
| 19 | Collier | https://cor.collierclerk.com/coraccess/ | Grant Street | No | https://cor.collierclerk.com/coraccess/search/document | https://county-taxes.net/fl-collier/property-tax |
| 20 | St. Lucie | https://stlucieclerk.gov/public-search-gen/official-records-search | Grant Street | No | https://acclaimweb.stlucieclerk.gov/AcclaimWeb/Home/Index | https://county-taxes.net/stlucie/property-tax |
| 21 | Escambia | https://dory.escambiaclerk.com/LandmarkWeb1.4.6.134 | Grant Street | YES (disclaimer) | https://dory.escambiaclerk.com/LandmarkWeb1.4.6.134/search/index?theme=.blue&section=searchCriteriaName | https://county-taxes.net/fl-escambia/property-tax |

> Full FL county list — including CAPTCHA disclaimers, exam notes, tax notes, recorder platform per-county, and rank order 22-67 — lives in `FL_Examples.md`. The XLSX sibling (`County_URL_Mapping_CUREMasterSheet.xlsx`, FL sheet) is the authoritative machine-readable form (now includes `Platform (Tax)` column as of v3 sync 2026-05-19). Platform-driven build wave plan is in `FL_Implementation_Plan.md`.

## Notes

- **ImageDownloadURL** is the same TitlePro247 portal (`https://www.titlepro247.com/`) for every county; per-county overrides come from the `TITLEPRO_URL` / `TITLEPRO_WEBSITE` keys in `secrets.json` (see `selenium_downloader.py:99-103`).
- **CountyURL** values for CA come from each `*.json` file's `base_url` field under `src/titlepro/search/ca_recorder/counties/config/`.
- **TaxURL** values come from `config/county_tax_urls.json` `counties.<key>.base_url`. A dash (—) means there is no tax entry for that county yet.
- The Cuyahoga recorder/tax URLs are the only OH entries currently configured anywhere in the repo.
