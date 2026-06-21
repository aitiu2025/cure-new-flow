# CA Examples — Test Subjects (Subject A + Subject B per county)

> ⚠️ **CA work is PAUSED as of 2026-05-20** (pivoted to FL). Before resuming any CA subject runs, **read `docs/CA_Implementation_Update_2005.md`** — it's the canonical handoff doc with per-county/per-phase status, what's already complete, immediate next steps, and long-term improvements.

> **Source:** `docs/source_sheets/CA_CURE_County_Search_URLs_2026-06-17.xlsx` (CA sheet, last sync **2026-06-17**)
>
> Each county in the source sheet ships **two** test subjects (Subject A + Subject B) for end-to-end CURE validation. Already-run cases are marked ✅; un-run subjects are next-up candidates for batch report generation.

## Counties + Subjects

| # | County | Subject A | Address A | Subject B | Address B |
|---|---|---|---|---|---|
| 1 | **Alameda** | NATALIE AGUILERA + SOLIS J AGUILERA | 164 PURCELL DR, ALAMEDA | WING WAI SCARLET TAM | 7233 CRONIN CIR, DUBLIN |
| 2 | **Contra Costa** | MARCELINO MONTOYA + SARA MONTOYA | 1724 WESLEY AVE, EL CERRITO | JESSE JAMES WALTERS + NICHOLE LYNNE WALTERS | 4042 REGATTA DR, DISCOVERY BAY |
| 3 | **Fresno** | JANINE AMAYA + CRISTIAN AMAYA | 5041 E HEDGES AVE, FRESNO | DANIEL ENCISO | 4691 N FARRIS AVE, FRESNO |
| 4 | **Los Angeles** | Not available per sheet | — | Not available per sheet | — |
| 5 | **Orange** | HECTOR G QUINTANA + KAREN J QUINTANA | 2356 S CUTTY WAY # 37, ANAHEIM | GONZALO NAVA + GUADALUPE NAVA | 631 S EMILY ST, ANAHEIM |
| 6 | **Riverside** | DEBORAH ELLEN FINKELSTEIN | 3922 MANCHESTER PL, RIVERSIDE | JOHN W STINSON + KATHLEEN M STINSON | 22264 SUMMER HOLLY AVE, MONENO VALLEY |
| 7 | **Sacramento** | SHAUN BURGER + MARGARET BASIAGA | 8244 NORTHWIND WAY, ORANGEVALE | ARI MICHAEL CORNMAN + NENEKO KATO CORNMAN | 8617 WHITE FRONT WAY, ELK GROVE |
| 8 | **San Bernardino** | CHEYNE A MILES | 11432 HELENA ST, ADELANTO | JASON ENGLISH + JESSICA ENGLISH | 2191 LARIMORE LN, MENTONE |
| 9 | **San Diego** | JASON THURSTON | 3634 LLOYD TERRACE, SAN DIEGO | DAVID A HEPLER + ERIN M FORBES | 3670 8TH AVE, SAN DIEGO |
| 10 | **Santa Clara** | Not available per sheet | — | Not available per sheet | — |

## Already-Run Cases (Reports On Disk)

Located under `src/titlepro/api/downloaded_doc/0513/`:

- `Alameda_AGIULERA/`
- `ContraCosta_MONTOYA_Marcelino/` ✅ canonical Exhibit A
- `ContraCosta_WALTERS_Jesse/`
- `Fresno_AMAYA_Janine/`
- `Orange_Quintana/`

## Pending Cases (Next Up)

These have full Subject + Address data but no reports generated yet:

1. **Riverside / FINKELSTEIN** — 3922 MANCHESTER PL, RIVERSIDE
2. **Riverside / STINSON** — 22264 SUMMER HOLLY AVE, MORENO VALLEY
3. **Sacramento / BURGER** — 8244 NORTHWIND WAY, ORANGEVALE
4. **Sacramento / CORNMAN** — 8617 WHITE FRONT WAY, ELK GROVE
5. **San Bernardino / MILES** — 11432 HELENA ST, ADELANTO
6. **San Bernardino / ENGLISH** — 2191 LARIMORE LN, MENTONE
7. **San Diego / THURSTON** — 3634 LLOYD TERRACE, SAN DIEGO
8. **San Diego / HEPLER** — 3670 8TH AVE, SAN DIEGO
9. **Fresno / ENCISO** — 4691 N FARRIS AVE, FRESNO
10. **Orange / NAVA** — 631 S EMILY ST, ANAHEIM
11. **Alameda / TAM** — 7233 CRONIN CIR, DUBLIN

## Blocked

- **Los Angeles** and **Santa Clara** are marked "No Data Online" — both pending Tapestry Plant access. Do not attempt CURE recorder runs against these until access is sourced.

## Notes

- Name format is **LAST FIRST [MIDDLE]** for recorder searches (CURE's name parser expects this order).
- The "+" between two names indicates a multi-party search (Grantor + Spouse). The pipeline handles these as two `SearchRequest` entries.
- Subject A and Subject B per county are independent — they don't share parties or property.
