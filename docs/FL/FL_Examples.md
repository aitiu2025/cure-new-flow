# FL Examples — County URLs & Test Subjects

> **Source of truth:** `docs/FL/FL_CURE_County_Search_URLs.xlsx` (FL sheet) — synced **2026-06-14**. This file is generated from that sheet; edit the sheet, then regenerate.
>
> Per-county reference files: `docs/FL/counties/<rank>_<county>.md` (one per county).
>
> Companion docs: `docs/FL/FL_Platform_Examination_Guide.md`, `docs/FL/FL_Implementation_Plan.md`

## Coverage Summary

- **67 / 67 FL counties** mapped (population-rank ordered)
- **Recorder platforms:** Clericus (23), z-Proprietary (17), Landmark (16), Tyler Technologies (4), OneCare (4), DuProcess (3)
- **Reviewed counties:** 12 — Palm Beach, Hillsborough, Orange, Duval, Lee, Polk, Pasco, Brevard, Volusia, Seminole, Sarasota, Manatee
- **Counties with test subjects:** 15 / 67

## Test Subjects (counties with at least one subject)

| # | County | Platform | Subject A | Addr A | Subject B | Addr B |
|---|---|---|---|---|---|---|
| 1 | **Miami-Dade** | z-Proprietary | Luis H Navas + Maria Dolores Navas | 10630 SW 128th Terrace, MIAMI | Rachel Anne Haugabook | 4941 NW 188th Terrace, Miami Gardens |
| 2 | **Broward** | z-Proprietary | Shantell Simmons + Deston Simmons | 2151 NW 93rd Ave, Pembroke Pines | RISHI G ANAND + PAYAL ANAND | 2856 NE 27TH ST, FORT LAUDERDALE |
| 3 | **Palm Beach** | Landmark | ANDREW THOMAS VOLLMAN + GRACE MELINDA WU | 102 SEGOVIA WAY, JUPITER | DANA M HABER + MARK HABER | 21831 PALM GRASS DR, BOCA RATON |
| 4 | **Hillsborough** | z-Proprietary | ALANA FROMER + MICHAEL FROMER | 4004 W NORTH B ST, TAMPA | ANGEL DEL MONTE + CHRISTINE DEL MONTE | 13519 ESTSHIRE DR, TAMPA |
| 5 | **Orange** | Tyler Technologies | DIANA V GREER + BRETT B GREER | 17748 DEER ISLE CIR, WINTER GARDEN | RAMON MIRANDA + LEONORA MATTOS MENESES MIRANDA | 7313 TWILIGHT BAY DR, WINTER GARDEN |
| 6 | **Duval** | OneCare | MICHAEL W SKINNER + SALLY JANE SKINNER | 4409 CROOKED BROOK COURT, JACKSONVILLE | EDWARD M DAVIS + ANDREA J DAVIS | 2364 COVINGTON CREEK DR W, JACKSONVILLE |
| 7 | **Pinellas** | OneCare | MARY N GRENESKO + ERIK T GRENESKO | 5630 11TH AVE N, SAINT PETERSBURG | BEVERLEE HARRIS-WEISMANN + THOMAS D WEISMANN | 6333 8TH AVE N, SAINT PETERSBURG |
| 8 | **Lee** | Landmark | STEVEN R OSTIGUY + CHRISTINA J OSTIGUY | 2137 CORAL POINT DR, CAPE CORAL | RICHARD HEDGE JR + APRIL L HEDGE | 3390 TRAIL DARY CIR NORTH, FORT MYERS |
| 9 | **Polk** | z-Proprietary | WILLIAM JOSEPH BUNKER + JULIE CHAMBERS BUNKER | 6836 HAMPSHIRE BLVD, LAKELAND | RUTH BRITO BAUTISTA | 1001 PRADO GRANDE ST, HAINES CITY |
| 10 | **Pasco** | z-Proprietary | ROBERT S RILEY + LYN M RILEY | 36700 CHRISTIAN RD, DADE CITY | ALLAN SCHECKLER + CAROL SCHECKLER | 38231 BOXWOOD DR, ZEPHYRHILLS |
| 11 | **Brevard** | OneCare | NICHOLAS A MURDOCK + JENNY E MURDOCK | 22 PARKWAY ST, COCOA | ANGELA D LEWIS | 977 HAMMACHER AVE SW, PALM BAY |
| 12 | **Volusia** | z-Proprietary | MARYKE Y GUILD + JUSTIN P GUILD | 435 ELSIE AVE, DAYTONA BEACH | JAY N CUDDY + SUZETTE M CUDDY | 11 LITTLE TOMOKA WAY, ORMOND BEACH |
| 13 | **Seminole** | DuProcess | MARK PORTILLA + ANGELA PORTILLA | 3136 SPLENDID STOWE LN, LONGWOOD | CLYDE WATSON III + STEFANIE SCHIMKE WATSON | 2666 RED FOX RUN, CHULUOTA |
| 14 | **Sarasota** | z-Proprietary | EMELIA M BRUNO | 1016 SCHERER WAY, OSPREY | ENRIQUE ORDUNO + MARIA ORDUNO | 1006 MEADOW BREEZE LN, SARASOTA |
| 15 | **Manatee** | z-Proprietary | PABLO FERNANDEZ + DANIELA ROZANES | 4837 DABAL HARBOUR DR, BRADENTON | DANIEL C SHAUL + DIANA R SHAUL | 10304 SPOONBILL RD W, BRADENTON |

## All Counties (rank 1-67) — full URLs + flags

| # | County | Reviewed | Platform | Recorder URL | Rec APN | Doc-Type | CAPTCHA | Tax URL | Tax Platform |
|---|---|---|---|---|---|---|---|---|---|
| 1 | Miami-Dade |  | z-Proprietary | https://onlineservices.miamidadeclerk.gov/officialrecords/ | Yes - Pay Site / No - Free Site | Yes | No | https://county-taxes.net/fl-miamidade/property-tax | Grant Street |
| 2 | Broward |  | z-Proprietary | https://officialrecords.broward.org/AcclaimWeb/ | Yes | Yes | No | https://county-taxes.net/broward/property-tax | Grant Street |
| 3 | Palm Beach | ✅ | Landmark | https://www.mypalmbeachclerk.com/records/official-records | Yes | Yes | T&C | https://pbctax.publicaccessnow.com/PropertyTax.aspx | Aumentum Technologies |
| 4 | Hillsborough | ✅ | z-Proprietary | https://publicaccess.hillsclerk.com/oripublicaccess/ | No | Yes | No | https://county-taxes.net/hillsborough/property-tax | Grant Street |
| 5 | Orange | ✅ | Tyler Technologies | https://selfservice.or.occompt.com/ssweb/user/disclaimer | Yes - Advanced Search Tab | Yes | Yes | https://county-taxes.net/fl-orange/property-tax | Grant Street |
| 6 | Duval | ✅ | OneCare | https://or.duvalclerk.com/ | No | Yes | T&C | https://county-taxes.net/fl-duval/property-tax | Grant Street |
| 7 | Pinellas |  | OneCare | https://officialrecords.mypinellasclerk.gov/ | No | Yes | T&C | https://county-taxes.net/pinellas/property-tax | Grant Street |
| 8 | Lee | ✅ | Landmark | https://or.leeclerk.org/LandMarkWeb/ | Yes | Yes | T&C | https://county-taxes.net/fl-lee/property-tax | Grant Street |
| 9 | Polk | ✅ | z-Proprietary | https://apps.polkcountyclerk.net/browserviewor/ | No | Yes | No | https://polk.floridatax.us/AccountSearch?s=pt | PublicSoft |
| 10 | Pasco | ✅ | z-Proprietary | https://app.pascoclerk.com/appdot-public-online-services-forms-or-search.asp | No | Yes | No | https://county-taxes.net/fl-pasco/property-tax | Grant Street |
| 11 | Brevard | ✅ | OneCare | https://vaclmweb1.brevardclerk.us/AcclaimWeb/ | No | Yes | T&C | https://county-taxes.net/brevard/property-tax | Grant Street |
| 12 | Volusia | ✅ | z-Proprietary | https://app02.clerk.org/or_m/ | No | No | T&C | https://county-taxes.net/vctaxcollector/property-tax | Grant Street |
| 13 | Seminole | ✅ | DuProcess | https://recording.seminoleclerk.org/DuProcessWebInquiry/index.html | Yes | Yes | T&C | https://county-taxes.net/fl-seminole/fl-seminole/property-tax | Grant Street |
| 14 | Sarasota | ✅ | z-Proprietary | https://secure.sarasotaclerk.com/OfficialRecords.aspx | No | Yes | No | https://sarasotataxcollector.publicaccessnow.com/TaxCollector/PropertyTaxSearch.aspx | Aumentum Technologies |
| 15 | Manatee | ✅ | z-Proprietary | https://records.manateeclerk.com/OfficialRecords/Search | No | Yes | No | https://secure.taxcollector.com/ptaxweb/ | Pacific Blue |
| 16 | St. Lucie |  | z-Proprietary | https://stlucieclerk.gov/public-search-gen/official-records-search | No | Yes | No | https://county-taxes.net/stlucie/property-tax | Grant Street |
| 17 | Collier |  | z-Proprietary | https://cor.collierclerk.com/coraccess/ | Yes | Yes | No | https://county-taxes.net/fl-collier/property-tax | Grant Street |
| 18 | Marion |  | z-Proprietary | https://nvweb.marioncountyclerk.org/searchng_SSL/ | tbd | tbd | T&C | https://www.mariontax.com/itm/PropertySearchName.aspx | Unnamed 1 |
| 19 | Escambia |  | Landmark | https://dory.escambiaclerk.com/LandmarkWeb1.4.6.134 | Yes | Yes | T&C | https://county-taxes.net/fl-escambia/property-tax | Grant Street |
| 20 | Osceola |  | z-Proprietary | https://officialrecords.osceolaclerk.org/browserview/ | No | Yes | No | https://county-taxes.net/osceola/property-tax | Grant Street |
| 21 | Lake |  | OneCare | https://officialrecords.lakecountyclerk.org/ | No | Yes | T&C | https://county-taxes.net/lake/property-tax | Grant Street |
| 22 | St. Johns |  | Landmark | https://apps.stjohnsclerk.com/Landmark | Yes | Yes | T&C | https://www.stjohnstax.us/AccountSearch?s=pt | PublicSoft |
| 23 | Leon |  | z-Proprietary | https://cvweb.leonclerk.com/public/clerk_services/official_records/index.asp | No | Yes (Book Type Choice Needed) | YES | https://wwwtax2.leoncountyfl.gov/itm/PropertySearchName.aspx?AspxAutoDetectCookieSupport=1 | Unnamed 1 |
| 24 | Alachua |  | z-Proprietary | https://www.alachuacounty.us/Depts/Clerk/PublicRecords/Pages/Disclaimer.aspx | Yes | Yes | T&C | https://county-taxes.net/alachua/property-tax | Grant Street |
| 25 | Clay |  | Landmark | https://landmark.clayclerk.com/LandmarkWeb/home/index | Yes | Yes | T&C | https://county-taxes.net/fl-clay/property-tax | Grant Street |
| 26 | Okaloosa |  | Tyler Technologies | https://okaloosacountyfl-web.tylerhost.net/web/user/disclaimer | Yes - Advanced Search Tab | Yes | T&C | https://county-taxes.net/okaloosa/property-tax | Grant Street |
| 27 | Hernando |  | Landmark | https://or.hernandoclerk.com/LandmarkWeb/ | Yes | Yes | T&C | https://county-taxes.net/fl-hernando/property-tax | Grant Street |
| 28 | Bay |  | Landmark | https://records2.baycoclerk.com/Recording/ | Yes | Yes | T&C | https://county-taxes.net/fl-bay/property-tax | Grant Street |
| 29 | Charlotte |  | z-Proprietary | https://recording.charlotteclerk.com/ | No | Yes | No | https://county-taxes.net/charlotte/property-tax | Grant Street |
| 30 | Martin |  | Landmark | https://or.martinclerk.com/LandmarkWeb | Yes | Yes | T&C | https://county-taxes.net/fl-martin/property-tax | Grant Street |
| 31 | Indian River |  | Landmark | https://ori.indian-river.org/ | Yes | Yes | T&C | https://county-taxes.net/indianriver/property-tax | Grant Street |
| 32 | Santa Rosa |  | z-Proprietary | https://secure.sarasotaclerk.com/OfficialRecords.aspx | No | Yes | No | https://county-taxes.net/fl-santarosa/property-tax | Grant Street |
| 33 | Citrus |  | Landmark | https://search.citrusclerk.org/LandmarkWeb/home/index | Yes | Yes | T&C | https://county-taxes.net/citrus/property-tax | Grant Street |
| 34 | Flagler |  | Landmark | https://records.flaglerclerk.gov/ | Yes | Yes | T&C | https://county-taxes.net/fl-flagler/fl-flagler/property-tax | Grant Street |
| 35 | Nassau |  | Clericus | https://www.myfloridacounty.com/orisearch/45 | No | Yes | No | https://county-taxes.net/fl-nassau/property-tax | Grant Street |
| 36 | Sumter |  | Clericus | https://www.myfloridacounty.com/orisearch/60 | No | Yes | No | https://county-taxes.net/sumter/property-tax | Grant Street |
| 37 | Highlands |  | z-Proprietary | https://acclaim.highlandsclerkfl.gov/AcclaimWeb | No | Yes | No | https://highlands.floridatax.us/AccountSearch?s=pt | PublicSoft |
| 38 | Monroe |  | Landmark | https://or.monroe-clerk.com/LandmarkWeb/Home/Index | Yes | Yes | T&C | https://county-taxes.net/fl-monroe/property-tax | Grant Street |
| 39 | Columbia |  | Clericus | https://www.myfloridacounty.com/orisearch/12 | No | Yes | No | https://columbia.floridatax.us/AccountSearch?s=pt | PublicSoft |
| 40 | Putnam |  | Clericus | https://www.myfloridacounty.com/orisearch/54 | No | Yes | No | https://ptaxweb.putnamtax.com/ptaxweb/ | Pacific Blue |
| 41 | Jackson |  | Clericus | https://www.myfloridacounty.com/orisearch/32 | No | Yes | No | https://www.jacksoncountytaxcollector.com/Property/SearchSelect?Accept=true&ClearData=True | VisualGov |
| 42 | Walton |  | Landmark | https://orsearch.clerkofcourts.co.walton.fl.us/ | Yes | Yes | T&C | https://county-taxes.net/fl-walton/property-tax | Grant Street |
| 43 | Hendry |  | Clericus | https://www.myfloridacounty.com/orisearch/26 | No | Yes | No | https://hendry.floridatax.us/AccountSearch?s=pt | PublicSoft |
| 44 | Gadsden |  | Tyler Technologies | https://www.gadsdenclerk.com/PublicInquiry/Search.aspx?Type=Name | Yes - Advanced Search Tab | Yes | T&C | https://fl-gadsden.publicaccessnow.com/TaxCollector/PropertyTaxSearch.aspx | Aumentum Technologies |
| 45 | DeSoto |  | Clericus | https://www.myfloridacounty.com/orisearch/14 | No | Yes | No | https://www.desotocountytaxcollector.com/Property/SearchSelect?Accept=true&ClearData=True | VIsualGov |
| 46 | Wakulla |  | Landmark | http://www.wakullaclerk.com/Landmarkweb/Home/Index | Yes | Yes | T&C | https://www.wakullacountytaxcollector.com/Property/SearchSelect?Accept=true&ClearData=True | VIsualGov |
| 47 | Levy |  | Landmark | https://online.levyclerk.com/landmarkweb | Yes | Yes | T&C | https://levy.floridatax.us/AccountSearch?s=pt | PublicSoft |
| 48 | Okeechobee |  | Landmark | https://pioneer.okeechobeelandmark.com/LandmarkWebLive | Yes | Yes | T&C | https://okeechobeecountytaxcollector.com/Property/SearchSelect?Accept=true&ClearData=True | VisualGov |
| 49 | Suwannee |  | Clericus | https://www.myfloridacounty.com/orisearch/61 | No | Yes | No | https://suwannee.floridatax.us/AccountSearch?s=pt | PublicSoft |
| 50 | Baker |  | DuProcess | https://recording.bakerclerk.com/DuProcessWebInquiry/index.html | Yes | Yes | T&C | https://www.bakertaxcollector.com/Property/SearchSelect?Accept=true&ClearData=True | VisualGov |
| 51 | Hardee |  | Clericus | https://www.myfloridacounty.com/orisearch/25 | No | Yes | No | https://www.hardeecountytaxcollector.com/Property/SearchSelect?Accept=true&ClearData=True | VIsualGov |
| 52 | Taylor |  | Tyler Technologies | https://pubrecords.taylorclerk.com/PublicInquiry/Search.aspx?Type=Name | Yes - Advanced Search Tab | Yes | T&C | https://taylor.floridatax.us/AccountSearch?s=pt | PublicSoft |
| 53 | Bradford |  | Clericus | https://www.myfloridacounty.com/orisearch/04 | No | Yes | No | https://www.bradfordtaxcollector.com/Property/SearchSelect?Accept=true&ClearData=True | VisualGov |
| 54 | Washington |  | Clericus | https://www.myfloridacounty.com/orisearch/67 | No | Yes | No | https://www.washingtoncountytaxcollector.com/Property/SearchSelect?Accept=true&ClearData=True | VIsualGov |
| 55 | Holmes |  | Clericus | https://www.myfloridacounty.com/orisearch/30 | No | Yes | No | https://www.holmescountytaxcollector.com/Property/SearchSelect?Accept=true&ClearData=True | VIsualGov |
| 56 | Gulf |  | Clericus | https://www.myfloridacounty.com/orisearch/23 | No | Yes | No | x | VIsualGov |
| 57 | Gilchrist |  | Clericus | https://www.myfloridacounty.com/orisearch/21 | No | Yes | No | https://gilchrist.floridatax.us/AccountSearch?s=pt | PublicSoft |
| 58 | Madison |  | Clericus | https://www.myfloridacounty.com/orisearch/40 | No | Yes | No | https://www.madisoncountytaxcollector.com/Property/SearchSelect?Accept=true&ClearData=True | VIsualGov |
| 59 | Union |  | DuProcess | https://recording.unionclerk.com/DuProcessWebInquiry/index.html | Yes | Yes | T&C | https://www.unioncountytc.com/Property/SearchSelect?Accept=true&ClearData=True | VIsualGov |
| 60 | Dixie |  | Clericus | https://www.myfloridacounty.com/orisearch/15 | No | Yes | No | https://dixie.floridatax.us/AccountSearch?s=pt | PublicSoft |
| 61 | Hamilton |  | Clericus | https://www.myfloridacounty.com/orisearch/24 | No | Yes | No | https://www.hamiltoncountytaxcollector.com/Property/SearchSelect?Accept=true&ClearData=True | VisualGov |
| 62 | Calhoun |  | Clericus | https://www.myfloridacounty.com/orisearch/07 | No | Yes | No | https://www.calhouncountytaxcollector.com/Property/SearchSelect?Accept=true&ClearData=True | VisualGov |
| 63 | Jefferson |  | Clericus | https://www.myfloridacounty.com/orisearch/33 | No | Yes | No | https://www.jeffersoncountytaxcollector.com/Property/SearchSelect?ClearData=True | VIsualGov |
| 64 | Franklin |  | Clericus | https://www.myfloridacounty.com/orisearch/19 | No | Yes | No | https://www.franklincountytaxcollector.com/Property/SearchSelect?Accept=true&ClearData=True | VisualGov |
| 65 | Glades |  | Clericus | https://www.myfloridacounty.com/orisearch/22 | No | Yes | No | https://www.mygladescountytaxcollector.com/Property/SearchSelect?Accept=true&ClearData=True | VisualGov |
| 66 | Lafayette |  | Clericus | https://www.myfloridacounty.com/orisearch/34 | No | Yes | No | https://lafayette.floridatax.us/AccountSearch?s=pt | PublicSoft |
| 67 | Liberty |  | Clericus | https://www.myfloridacounty.com/orisearch/39 | No | Yes | No | https://www.libertycountytaxcollector.com/Property/SearchSelect?Accept=true&ClearData=True | VIsualGov |

## Tax Detail (rank 1-67)

| # | County | Tax Platform | Tax CAPTCHA | APN Search | Tax Notes |
|---|---|---|---|---|---|
| 1 | Miami-Dade | Grant Street | No | Yes | — |
| 2 | Broward | Grant Street | No | Yes | — |
| 3 | Palm Beach | Aumentum Technologies | No | Yes | — |
| 4 | Hillsborough | Grant Street | No | Yes | — |
| 5 | Orange | Grant Street | No | Yes | — |
| 6 | Duval | Grant Street | No | Yes | — |
| 7 | Pinellas | Grant Street | No | Yes | — |
| 8 | Lee | Grant Street | No | Yes | — |
| 9 | Polk | PublicSoft | No | Yes | — |
| 10 | Pasco | Grant Street | No | Yes | — |
| 11 | Brevard | Grant Street | No | Yes | — |
| 12 | Volusia | Grant Street | No | Yes | — |
| 13 | Seminole | Grant Street | No | Yes | — |
| 14 | Sarasota | Aumentum Technologies | No | Yes | — |
| 15 | Manatee | Pacific Blue | Yes Disclaimer | Yes | — |
| 16 | St. Lucie | Grant Street | No | Yes | — |
| 17 | Collier | Grant Street | No | Yes | — |
| 18 | Marion | Unnamed 1 | na | No | — |
| 19 | Escambia | Grant Street | No | Yes | — |
| 20 | Osceola | Grant Street | No | Yes | — |
| 21 | Lake | Grant Street | No | Yes | — |
| 22 | St. Johns | PublicSoft | No | Yes | — |
| 23 | Leon | Unnamed 1 | Yes Disclaimer | No | — |
| 24 | Alachua | Grant Street | No | Yes | — |
| 25 | Clay | Grant Street | No | Yes | — |
| 26 | Okaloosa | Grant Street | No | Yes | — |
| 27 | Hernando | Grant Street | No | Yes | — |
| 28 | Bay | Grant Street | No | Yes | — |
| 29 | Charlotte | Grant Street | No | Yes | — |
| 30 | Martin | Grant Street | No | Yes | — |
| 31 | Indian River | Grant Street | No | Yes | — |
| 32 | Santa Rosa | Grant Street | No | Yes | — |
| 33 | Citrus | Grant Street | No | Yes | — |
| 34 | Flagler | Grant Street | No | Yes | — |
| 35 | Nassau | Grant Street | No | Yes | — |
| 36 | Sumter | Grant Street | No | Yes | — |
| 37 | Highlands | PublicSoft | No | Yes | — |
| 38 | Monroe | Grant Street | No | Yes | — |
| 39 | Columbia | PublicSoft | No | Yes | — |
| 40 | Putnam | Pacific Blue | Yes Disclaimer | Yes | — |
| 41 | Jackson | VisualGov | No | Yes | — |
| 42 | Walton | Grant Street | No | Yes | — |
| 43 | Hendry | PublicSoft | No | Yes | — |
| 44 | Gadsden | Aumentum Technologies | No | Yes | — |
| 45 | DeSoto | VIsualGov | No | Yes | — |
| 46 | Wakulla | VIsualGov | No | Yes | — |
| 47 | Levy | PublicSoft | No | Yes | — |
| 48 | Okeechobee | VisualGov | No | Yes | — |
| 49 | Suwannee | PublicSoft | No | Yes | — |
| 50 | Baker | VisualGov | No | Yes | — |
| 51 | Hardee | VIsualGov | No | Yes | — |
| 52 | Taylor | PublicSoft | No | Yes | — |
| 53 | Bradford | VisualGov | No | Yes | — |
| 54 | Washington | VIsualGov | No | Yes | — |
| 55 | Holmes | VIsualGov | No | Yes | — |
| 56 | Gulf | VIsualGov | No | Yes | — |
| 57 | Gilchrist | PublicSoft | No | Yes | — |
| 58 | Madison | VIsualGov | No | Yes | — |
| 59 | Union | VIsualGov | No | Yes | — |
| 60 | Dixie | PublicSoft | No | Yes | — |
| 61 | Hamilton | VisualGov | No | Yes | — |
| 62 | Calhoun | VisualGov | No | Yes | — |
| 63 | Jefferson | VIsualGov | Yes Disclaimer | Yes | — |
| 64 | Franklin | VisualGov | No | Yes | — |
| 65 | Glades | VisualGov | No | Yes | — |
| 66 | Lafayette | PublicSoft | No | Yes | — |
| 67 | Liberty | VIsualGov | No | Yes | — |
