# Osceola County (FL) Property Appraiser — Live Probe 2026-06-19

## Portal Candidates Tried
- https://property.osceola.org/ → 404 (Microsoft-HTTPAPI/2.0)
- https://ocpaweb.osceola.org/ → resolves (IP: 198.140.240.14) but ALL paths 404
  - /default.aspx, /PropertySearch.aspx, /Search/, /ParcelSearch/, /Home/, /index.aspx — all 404
  - http://ocpaweb.osceola.org/ redirects to https://ocpaweb.osceola.org/ then 404
  - The server (IIS HTTPAPI/2.0) is running but has no routes configured
- https://apps.osceola.org/assessor/ → 404
- https://apps.osceola.org/pa/ → 404
- https://gis.osceola.org/arcgis/rest/services → 404 (no ArcGIS REST here)
- https://gis.osceola.org/HTML5Viewer/Index.html → 404
- qpublic.schneidercorp.com + beacon.schneidercorp.com → 403 (Schneider CF, datacenter-blocked)
- https://www.osceola.org/agencies-departments/constitutional-officers/property-appraiser/ → 404 (county site path not found)
- The county government site links to "My-Property" section but no PA search link was found

## Platform Assessment
- Osceola County FL previously ran **ocpaweb.osceola.org** as their PA portal — the domain resolves but is functionally dead (no routes return 200)
- The Schneider/qPublic CF block confirms they MAY use that platform but the datacenter IP is blocked
- No alternative accessible endpoint found from datacenter

## Status: DEFERRED — Portal infrastructure offline/blocked
- ocpaweb.osceola.org is the registered PA search hostname but is returning 404 on all paths
- Schneider qPublic is CF-blocked (same as other Schneider counties: bay/clay/walton etc.)
- **Unblock path options**:
  1. Residential IP → check if ocpaweb.osceola.org responds correctly (may be geo-blocked like Schneider)
  2. Residential IP → navigate https://www.osceola.org → find actual current PA portal URL
  3. If Schneider: drop residential cf_clearance cookie at `~/.titlepro/schneider_cookies.json` → existing qpublic_schneider_pa_http adapter handles it

## Config snippet (scaffold to add)
```json
"fl_osceola": {
  "county_name": "Osceola",
  "base_url": "https://ocpaweb.osceola.org",
  "platform": "landmark_pa_scaffold",
  "status": "deferred_infra_offline",
  "notes": "ocpaweb.osceola.org resolves (198.140.240.14) but all paths return 404. Schneider qPublic CF-blocks datacenter. Unblock: residential IP → confirm if ocpaweb responds or if county migrated to new portal. If Schneider: existing qpublic_schneider_pa_http adapter + residential cf_clearance cookie handles it."
}
```
