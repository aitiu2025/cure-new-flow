# FL Recorder Adapter — Recipe-Style Config Pattern

**Last updated:** 2026-05-21
**Applies to:** All HTTP-first FL county recorder adapters
**Reference adapter:** `tyler_http_adapter.py` (Orange FL — verified live)

This doc describes the JSON-driven `doc_image_url_pattern` field that lets us
add or retune a new FL county's direct-portal PDF download flow without
re-writing any Python. It also explains the supporting plumbing:
`WorkflowConfig.use_titlepro` routing and the `recorder_internal_ids.json`
sidecar that bridges the search and download phases.

---

## 1. Why recipe-style config?

The legacy CA flow downloads PDFs through TitlePro247 — a paid, CA-only
aggregator that's blind to FL portals. For FL counties, every recorder runs its
own image-download endpoint with its own quirks:

| County | Platform | Image flow |
|--------|----------|------------|
| Orange FL | Tyler Self-Service | `pdfJsUrl` scrape from detail page → PDF GET |
| Broward | AcclaimWeb | 4-step: jump → start_image_retrieval → viewer → WebAtalaCache PDF |
| Hillsborough | Custom IIS | Single watermark API GET keyed by opaque server ID |
| Manatee | ASP.NET MVC | Single InstrumentResultFile GET keyed by opaque DocID |

Hard-coding those URL shapes inside each adapter's `download_pdf()` would make
sibling tenants (e.g., a different AcclaimWeb county) impossible to onboard
without a code change. Instead, each adapter reads its URL templates and
extraction regexes from `config.doc_image_url_pattern`, with **sensible
defaults baked in** for the canonical tenant.

---

## 2. The `doc_image_url_pattern` field shape

The shape varies per platform. Each adapter's `__init__` defines its own
defaults and pulls user overrides from the config JSON. Common keys:

### Tyler Self-Service (`tyler_http_adapter.py`)

```jsonc
"doc_image_url_pattern": "document-image-pdfjs/{doc_id}/{uuid}/{doc_number}.pdf?allowDownload=true&index={index}"
```

A single template string. Tokens:
- `{doc_id}` — internal Tyler document ID (cached during search in `_doc_id_by_number`)
- `{uuid}` — per-doc UUID scraped from the detail page's `pdfJsUrl` JS variable
- `{doc_number}` — recorder instrument number
- `{index}` — 1-based image index (1 = primary page set)

### Broward / AcclaimWeb (`acclaimweb_http_adapter.py`)

```jsonc
"doc_image_url_pattern": {
  "jump_url": "details/JumpToInstrumentNumber/{record_type}/{doc_num}",
  "start_image_retrieval": "Image/StartImageRetrieval/{token}/0",
  "viewer_url": "Image/DocumentImage1/{token}",
  "record_type": 27,
  "token_regex_options": [
    "id\\s*=\\s*[\\'\"]hdnTransactionItemId[\\'\"]\\s+value\\s*=\\s*[\\'\"]([A-Za-z0-9_\\-]+)[\\'\"]",
    "DocumentImage1/([A-Za-z0-9_\\-]+)"
  ],
  "pdf_href_regex": "[\\'\"]([^\\'\"]*WebAtalaCache/[A-Za-z0-9_\\-]+_\\d+_docPdf\\.pdf)[\\'\"]",
  "pre_pdf_delay_seconds": 5.5,
  "pdf_fetch_retries": 3,
  "pdf_retry_delay_seconds": 3
}
```

A 4-step routing recipe. The adapter walks each stage with its session,
extracting a transaction token from the jump response, warming the image
cache, scraping the absolute WebAtalaCache PDF href from the viewer HTML, and
finally downloading the PDF with a configurable retry loop. All token-extraction
regexes are tried in order; first non-empty match wins.

### Hillsborough (`hillsborough_http_adapter.py`)

```jsonc
"doc_image_url_pattern": {
  "pdf_url_template": "https://publicaccess.hillsclerk.com/Public/ORIUtilities/OverlayWatermark/api/Watermark/{id}",
  "assert_pdf_magic": true
}
```

Single-GET pattern: `{id}` is the URL-encoded opaque server ID cached during
search. `assert_pdf_magic=true` rejects responses whose first 4 bytes aren't
`%PDF`.

### Manatee (`manatee_http_adapter.py`)

```jsonc
"doc_image_url_pattern": {
  "pdf_url_template": "https://records.manateeclerk.com/OfficialRecords/DisplayInstrument/InstrumentResultFile/{doc_id}/1/1",
  "assert_pdf_magic": true
}
```

Same single-GET shape; `{doc_id}` is the opaque DocID parsed from the view-icon
href in each result row.

---

## 3. The `WorkflowConfig.use_titlepro` flag

The pipeline's download phase routes between TitlePro247 (legacy CA) and the
adapter's `download_pdf()` (FL counties) based on `WorkflowConfig.use_titlepro`:

| `use_titlepro` value | Routing |
|----------------------|---------|
| `None` (default) | Infer from state — `"CA"` → True, else False |
| `True` | Always use TitlePro247 (legacy) |
| `False` | Always call `adapter.download_pdf()` |

State inference lives in `pipeline.py:_should_use_titlepro()`. A CA Tyler
county (`platform: "tyler"`) keeps routing through TitlePro247 because
`config.state == "CA"`; an FL Tyler county (`platform: "tyler_http"`) routes
through the adapter because `config.state == "FL"`.

### Per-case override

If you need to force a route for a specific case (debugging, FL OCR fallback,
etc.):

```python
WorkflowConfig(
    state="FL",
    county="fl_broward",
    use_titlepro=False,  # explicit; same as default for state=FL
    ...
)
```

---

## 4. The `recorder_internal_ids.json` sidecar

FL adapters often need a per-instrument opaque ID (Tyler doc_id, Hillsborough
ID, Manatee DocID) to build the PDF URL. That ID is captured during search
(`extract_results` populates `self._doc_id_by_number`) but the download phase
creates a **fresh adapter instance** — the in-memory cache is gone.

The bridge: at the end of the search phase, `pipeline.py` writes the
adapter's `_doc_id_by_number` cache to disk:

```json
{
  "20220421546": "DOC3379S37800",
  "20221234567": "DOC9999X11111"
}
```

The file lives at `<case_dir>/recorder_internal_ids.json`. The download phase
reads it and writes it back onto the new adapter:

```python
# pipeline._download_via_adapter:
sidecar = self.case_dir / "recorder_internal_ids.json"
if sidecar.exists():
    ids = json.loads(sidecar.read_text(encoding="utf-8"))
    if isinstance(ids, dict):
        adapter._doc_id_by_number = ids
```

**Canonical attribute name: `_doc_id_by_number`.** All FL adapters MUST cache
their per-Instrument internal IDs under this name (Hillsborough used to use
`_id_cache`; that's now an alias for backwards compatibility). Tyler is the
reference.

---

## 5. Adding a new FL county adapter end-to-end

1. **Pick a platform family.** If the county runs Tyler Self-Service, subclass
   or directly use `TylerHTTPAdapter`. If AcclaimWeb (Cloudflare-fronted MVC),
   start from `AcclaimWebHTTPAdapter`. For a unique stack, write a new adapter
   that subclasses `BaseRecorderSearch`.
2. **Author the JSON config.** Drop it under
   `src/titlepro/search/recorder/counties/config/fl/<county>.json`. Required
   fields: `county_id`, `county_name`, `state: "FL"`, `platform`, `base_url`,
   `search_url`, `http_search_endpoint`, and platform-specific form-field
   mappings. Add `doc_image_url_pattern` per the shape above.
3. **Register in `counties/registry.py`.** Map `platform: "<your platform>"`
   to your adapter class.
4. **Write unit tests.** Mirror `tests/unit/test_<platform>_http_adapter_scaffold.py`:
   * Construction from config
   * `extract_results()` parses a canonical response fixture
   * `download_pdf()` walks the configured recipe and returns the success/error
     dict shapes
   * No Selenium / Playwright / undetected-chromedriver imports leak
5. **Smoke-validate.** Import the adapter, construct it from JSON, assert
   `callable(a.download_pdf)`.
6. **Live test.** Run the pipeline against a known-good subject with
   `use_titlepro=False`. Verify PDFs land in the case directory with non-zero
   size and `%PDF` magic bytes.

### `download_pdf()` return shape (contract)

Success:
```python
{
  "status": "success",
  "size": <int — len(content)>,
  "src_via": <str — short identifier of which path produced the bytes>,
  "pdf_url": <str — absolute URL the PDF was fetched from>,
  # optional but common:
  "file": <str — str(dest_path)>,
  "token": <str — transaction/session token (Broward)>,
  "doc": <str — instrument number>,
}
```

Failure:
```python
{
  "status": "error",
  "doc": <str — instrument number>,
  "message" | "error": <str — diagnostic>,
  # optional:
  "phase": <str — which stage failed, e.g. "jump", "viewer", "fetch_pdf">,
  "pdf_url": <str>,
  "token": <str>,
}
```

The pipeline reads `status` and surfaces either `message` or `error` to the
download manifest. Per-adapter convention is to populate both fields when the
specific extractor uses a different key.

---

## 6. Sanity checks before shipping

* `python3 -c "from titlepro.search.recorder.counties.adapters.<module> import <Adapter>; a = <Adapter>(json.load(open('<config>.json'))); assert callable(a.download_pdf)"` must succeed.
* `pytest tests/unit/test_<adapter>_scaffold.py` must be green with at least:
  * 1 method-exists test
  * 1 happy-path test (mocked session)
  * 2 failure-mode tests (missing token / non-PDF response)
* No live HTTP calls from unit tests. Live regeneration is a separate phase.

---

## 7. Related references

* `tyler_http_adapter.py` — canonical reference implementation.
* `pipeline.py:_download_via_adapter` — pipeline-side adapter call.
* `pipeline.py:_should_use_titlepro` — state-defaulted routing logic.
* `docs/FL/FL_Platform_Examination_Guide.md` — Tony Roveda's per-platform
  examination playbook.
* `docs/implementation_references/2Captcha_reCAPTCHA_Integration.md` — captcha
  handling spec (applies when an FL Tyler tenant has reCAPTCHA enabled).
