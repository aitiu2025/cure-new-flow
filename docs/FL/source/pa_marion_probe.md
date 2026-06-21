# Marion County (FL) Property Appraiser — Live Probe 2026-06-19

## Portal Status
- Intended URL: https://pa.marion.fl.us/ (Marion County Clerk recorder BrowserView, NOT the PA)
  - DNS: SOA record exists but NO A record → domain points nowhere (unmaintained)
  - Earlier curl loaded content because of OS DNS cache; curl_cffi gets NXDOMAIN
  - The BrowserView at that URL is the **recorder** search (not the PA)
- mcpafl.org → **Monroe County** Property Appraiser (wrong county)
- marioncountypa.com / pamarion.com → all 000 (not reachable)
- marioncountyfl.org → Granicus-hosted county site, blocks datacenter (Akamai 403 for direct pages)
- gis.marioncountyfl.org → resolves but returns no HTML in time (likely geo-blocked)
- pa.marioncountyfl.org → NXDOMAIN

## Platform Assessment
- Marion County FL Property Appraiser uses an **unknown portal** not reachable from this datacenter
- The county government site is Akamai-gated at the datacenter IP (403 Access Denied via edgesuite.net)
- `pa.marion.fl.us` is an old subdomain with no A record → **abandoned/migrated**
- The actual PA search portal URL could NOT be determined from datacenter IP during this probe

## Status: DEFERRED — DNS/Geo-blocked
- Cannot identify the live PA search URL from datacenter
- Residential IP required to access marioncountyfl.org government site
- **Unblock path**: Access https://www.marioncountyfl.org/ from residential IP → navigate to Property Appraiser → capture the actual PA portal URL → probe the search endpoints
- Known: the actual FL Marion County Property Appraiser is Gerald Seier; office uses a product not yet identified
- Alternate: check the FL Department of Revenue's county PA directory from a residential browser

## Config snippet (scaffold to add)
```json
"fl_marion": {
  "county_name": "Marion",
  "base_url": "UNKNOWN — probe from residential IP",
  "platform": "landmark_pa_scaffold",
  "status": "scaffold",
  "notes": "pa.marion.fl.us has no A record (abandoned). Actual PA portal URL unknown — requires residential access to marioncountyfl.org to identify. Unblock: residential proxy → navigate county site → capture PA URL → probe."
}
```
