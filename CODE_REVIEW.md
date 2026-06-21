# Code Review: Commit ef9df4e - "Copied selected files from Surecafe feature branch"

**Reviewer**: Claude Opus 4.6 Code Review Agent
**Date**: 2026-02-12
**Scope**: tyler_adapter.py, server.py, CURE.html, county configs, registry.py

---

## 1. Tyler Adapter Review (`tyler_adapter.py` - 1792 lines)

### CRITICAL Issues

**C-1. No explicit browser cleanup / resource leak risk**
The `TylerAdapter` class defines `setup_driver()` but never defines a `cleanup()` or `close()` method. It relies entirely on `BaseRecorderSearch.__exit__()` to call `self.driver.quit()`. However, if an exception occurs between `setup_driver()` and the `with` block exit (e.g., during `navigate_to_search()`), the browser process can be orphaned. Each orphaned Chrome instance consumes ~200-400MB of RAM.

**File**: `src/titlepro/search/ca_recorder/counties/adapters/tyler_adapter.py`, lines 158-193
```python
def setup_driver(self):
    # ... creates self.driver but no __del__ or explicit cleanup
```
**Recommendation**: Add a `cleanup()` method and ensure it is called in a `finally` block or via `__del__`. Consider wrapping `setup_driver()` calls with try/except to quit the driver on setup failure.

---

**C-2. CAPTCHA token injection via string interpolation is vulnerable to injection**
The CAPTCHA token is injected into the page via an f-string embedded in `execute_script`, without any sanitization. If the CAPTCHA solver returns a malicious payload (e.g., from a compromised third-party API), it could execute arbitrary JavaScript in the browser context.

**File**: `tyler_adapter.py`, lines 393-401
```python
self.driver.execute_script(
    f'document.getElementById("g-recaptcha-response").innerHTML = "{token}";'
)
```
**Recommendation**: Pass the token as a script argument instead of string interpolation:
```python
self.driver.execute_script(
    'document.getElementById("g-recaptcha-response").innerHTML = arguments[0];',
    token
)
```

---

**C-3. Headless mode is commented out - browser windows will open in production**
Lines 163-164 have headless mode commented out. This means every search will open a visible Chrome window, which is inappropriate for server-side operation and will fail on headless servers (no display).

**File**: `tyler_adapter.py`, lines 163-164
```python
#options.add_argument("--headless=new")
#options.add_argument("--headless")
```
**Recommendation**: Make headless mode configurable via a constructor parameter (e.g., `headless=True`) defaulting to headless, and only show browser when explicitly requested. The `show_browser` flag from the API already exists but isn't wired through to the adapter.

---

### HIGH Issues

**H-1. Hardcoded `time.sleep()` calls throughout (22 occurrences)**
The adapter uses fixed `time.sleep()` calls (0.3s to 5s) for synchronization instead of explicit WebDriverWait conditions. This leads to:
- Slow execution on fast connections (unnecessary waits)
- Race conditions on slow connections (insufficient waits)
- A single search can accumulate 30-60 seconds of dead wait time

**Key locations**: Lines 230, 284, 313, 323, 339, 423, 450, 477, 515, 639, 656, 770, 789, 833, 859, 871, 955, 965, 1498, 1668, 1680, 1719

**Recommendation**: Replace `time.sleep()` with `WebDriverWait` with appropriate expected conditions. For example:
```python
WebDriverWait(self.driver, 10).until(
    EC.presence_of_element_located((By.XPATH, self.selectors["results_table"]))
)
```

---

**H-2. No timeout on `driver.get()` calls**
The `navigate_to_search()` method and fallback URL navigations call `self.driver.get(url)` without any page load timeout. If a county recorder site is down or slow, the browser will hang indefinitely.

**File**: `tyler_adapter.py`, lines 422, 441, 322, 338, 1491, 1683, 1781
**Recommendation**: Set a page load timeout on the driver:
```python
self.driver.set_page_load_timeout(30)  # 30 second timeout
```

---

**H-3. Massive JavaScript blocks embedded as strings (~300 lines total)**
The `extract_results()`, `_extract_results_via_detail_pages()`, and `_find_results_list_js()` methods contain very large JavaScript code blocks as Python multi-line strings. This makes the code:
- Very hard to debug (no JS linting/formatting)
- Impossible to unit test the JavaScript logic
- Prone to escaping errors

**File**: `tyler_adapter.py`, lines 988-1295, 1359-1425, 1501-1639
**Recommendation**: Extract JavaScript code into separate `.js` files and load them at runtime, or at minimum, add comprehensive comments explaining the parsing logic.

---

**H-4. `_set_party_type` uses bare `except:` clauses**
Lines 469-472 use bare `except:` which catches all exceptions including `KeyboardInterrupt` and `SystemExit`.

**File**: `tyler_adapter.py`, lines 469-472
```python
try:
    select.select_by_visible_text(value)
except:
    try:
        select.select_by_value(value)
    except:
```
**Recommendation**: Catch specific exceptions (`NoSuchElementException`, `Exception`) instead of bare `except:`.

---

**H-5. Duplicated list-finding logic across three methods**
The priority-based list selection logic (find list with "N total", find list with dates, fallback to most items) is duplicated nearly identically in:
1. `extract_results()` (lines 1017-1080)
2. `_find_results_list_js()` (lines 1359-1425)
3. `_extract_results_via_detail_pages()` uses the output of `_find_results_list_js()`

The first two are separate JavaScript implementations of the same algorithm. If one is updated, the other can easily drift out of sync.

**Recommendation**: Consolidate into a single shared JavaScript function used by both extraction strategies.

---

### MEDIUM Issues

**M-1. `doc_number_pattern` config parameter is accepted but never used**
The constructor stores `self.doc_number_pattern` (line 127) and it's passed to `execute_script` as an argument (line 1297), but the JavaScript code inside `extract_results()` never references `arguments[0]` -- it uses hardcoded regex patterns instead.

**File**: `tyler_adapter.py`, line 1297
```python
js_data = self.driver.execute_script(extract_script, self.doc_number_pattern)
```
**Recommendation**: Either use the configurable pattern in the JavaScript, or remove the unused parameter to avoid confusion.

---

**M-2. `import re` inside method body**
Line 958 imports `re` inside `extract_results()`, and line 1345 imports `traceback` inside the same method. These should be top-level imports.

**File**: `tyler_adapter.py`, lines 958, 1345

---

**M-3. Strategy 2 in `_safe_clear_and_type` uses Ctrl+A which is Mac-incompatible**
Line 641 uses `Keys.CONTROL + "a"` for select-all, which won't work on macOS (should be `Keys.COMMAND + "a"`). Since the server runs on macOS (per the environment info), this fallback strategy will silently fail.

**File**: `tyler_adapter.py`, line 641
**Recommendation**: Detect platform or use JavaScript to clear the field instead.

---

**M-4. `print()` used for all logging instead of `logging` module**
The entire adapter uses `print()` statements for logging (50+ occurrences). This makes it impossible to control log levels, route logs to files, or filter by severity.

**Recommendation**: Use Python's `logging` module with appropriate log levels (DEBUG, INFO, WARNING, ERROR).

---

### LOW Issues

**L-1. Anti-detection flags may trigger bot detection on some sites**
Lines 171-173 disable automation indicators, which is standard practice but may conflict with some Tyler Technologies security configurations.

**L-2. `wait` attribute set with 15-second timeout may be too short for slow county sites**
Line 191 sets `WebDriverWait(self.driver, 15)`. Some rural county recorder sites (e.g., Trinity, Sierra) may take longer to respond.

**L-3. The `set_partial_match` method is a no-op**
Lines 1691-1704: The method stores the value but has a `pass` statement and a comment saying Tyler uses partial matching by default. This is fine for now but could be confusing.

---

## 2. Server.py Review (`server.py` - 2361 lines)

### CRITICAL Issues

**C-4. Path traversal vulnerability in `/pdf/<owner>/<filename>` endpoint**
The sanitization on lines 98-99 only strips `..`, `/`, and `\` characters. An attacker could potentially craft paths using URL encoding or other bypass techniques. More critically, the check only validates the suffix is `.pdf`, but doesn't verify the resolved path is within DOWNLOAD_BASE.

**File**: `src/titlepro/api/server.py`, lines 97-106
```python
safe_owner = owner.replace('..', '').replace('/', '').replace('\\', '')
safe_filename = filename.replace('..', '').replace('/', '').replace('\\', '')
pdf_path = DOWNLOAD_BASE / safe_owner / safe_filename
# Missing: if not str(pdf_path.resolve()).startswith(str(DOWNLOAD_BASE.resolve())):
```
**Recommendation**: Add the same `resolve()` + `startswith()` check used in `/api/files` (line 2142) and `/api/file/<path>` (line 2230).

---

**C-5. Hardcoded user path in Claude CLI invocation**
Lines 1352-1354 and 1446-1448 hardcode `/Users/ag/.local/bin/claude` as the Claude CLI path. This will fail on any other machine or deployment environment.

**File**: `server.py`, lines 1352-1354
```python
claude_path = '/Users/ag/.local/bin/claude'
env = os.environ.copy()
env['PATH'] = '/Users/ag/.local/bin:' + env.get('PATH', '')
```
**Recommendation**: Use `shutil.which('claude')` to find the CLI in PATH, or make it configurable via environment variable.

---

**C-6. Hardcoded local file path in CURE.html**
Line 2855 of CURE.html and line 2989 contain a hardcoded absolute path to the download directory on a specific developer's machine:
```javascript
let baseFolderPath = '/Users/ag/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/downloaded_doc/';
```
This will display incorrect paths for any other user/deployment.

**File**: `src/titlepro/search/ca_recorder/CURE.html`, line 2855

**Recommendation**: Derive the path from the API server's response (the `folder_path` field is already returned by search endpoints) or make it configurable.

---

### HIGH Issues

**H-6. Thread safety: shared mutable dictionaries without locks**
`active_downloads`, `batch_jobs`, `dedup_batch_jobs`, and `server_logs` are plain Python dictionaries/lists modified from background threads and read from request handlers. While CPython's GIL provides some protection for simple dict operations, compound operations (read-modify-write patterns in batch job tracking) can still produce race conditions.

**File**: `server.py`, lines 32-34, 263
```python
active_downloads = {}
batch_jobs = {}
dedup_batch_jobs = {}
```
**Recommendation**: Use `threading.Lock()` to protect shared state, or use `concurrent.futures` with proper synchronization.

---

**H-7. No cleanup of completed job entries -- memory leak**
`active_downloads`, `batch_jobs`, and `dedup_batch_jobs` grow indefinitely as jobs complete. There is no TTL, eviction policy, or cleanup mechanism. Over time (especially during long running sessions), this will consume increasing amounts of memory.

**File**: `server.py`, lines 32-34
**Recommendation**: Add a periodic cleanup task or TTL-based eviction (e.g., remove completed jobs after 30 minutes).

---

**H-8. `debug=True` in production -- enables Werkzeug debugger and code reloader**
Line 2361 runs the Flask server with `debug=True`, which:
1. Enables the interactive Werkzeug debugger (allows arbitrary code execution if accessible)
2. Enables the auto-reloader (can kill long-running background threads)
3. Runs the startup code twice (once for the reloader process)

**File**: `server.py`, line 2361
```python
app.run(host='0.0.0.0', port=5555, debug=True, threaded=True)
```
**Recommendation**: Use `debug=False` for production, or make it configurable via environment variable. The MEMORY.md explicitly warns that "Flask debug reloader kills long synchronous requests."

---

**H-9. `subprocess.run` with shell commands accepts unsanitized user input**
The `/analyze-documents` and `/tax-lookup` endpoints pass user-provided `owner_name` and `property_address` directly into prompt strings that are passed to `subprocess.run`. While they're passed as `-p` argument (not shell-interpreted), the prompt content could potentially manipulate the Claude CLI behavior.

**File**: `server.py`, lines 1332-1363, 1450-1508
**Recommendation**: Validate and sanitize `owner_name` and `property_address` before embedding in prompts. At minimum, strip shell-dangerous characters.

---

**H-10. `server_logs` list used as circular buffer has O(n) pop(0) operation**
Line 2283 uses `list.pop(0)` which is O(n) for Python lists. With `MAX_LOG_LINES = 500` and high-frequency logging, this creates unnecessary overhead.

**File**: `server.py`, lines 2281-2284
```python
self.log_buffer.append(log_entry)
while len(self.log_buffer) > MAX_LOG_LINES:
    self.log_buffer.pop(0)
```
**Recommendation**: Use `collections.deque(maxlen=MAX_LOG_LINES)` instead, which provides O(1) append and automatic eviction.

---

**H-11. `/api/files` endpoint sanitization is incomplete**
Line 2135 only strips `..` from the path, but doesn't handle sequences like `....//` which would reduce to `../` after a single replace pass.

**File**: `server.py`, line 2135
```python
safe_path = relative_path.replace('..', '').strip('/')
```
However, line 2142 does perform a proper `resolve()` + `startswith()` check, which provides defense-in-depth. The initial replace is redundant but not harmful. This is a minor concern since the secondary check is robust.

---

### MEDIUM Issues

**M-5. `import re` inside `render_table()` function body**
Line 2109 imports `re` inside the `render_table()` helper function, which is called once per table. This should be a top-level import.

**File**: `server.py`, line 2109

---

**M-6. `sys.stdout` and `sys.stderr` replacement is fragile**
Lines 2291-2292 replace `sys.stdout` and `sys.stderr` with `LogCapture` wrappers. This can interfere with Flask's internal logging, break `pdb` debugging, and cause issues with any library that checks `isinstance(sys.stdout, io.TextIOWrapper)`.

**File**: `server.py`, lines 2291-2292
**Recommendation**: Use Python's `logging` module with a custom handler instead of replacing stdout/stderr.

---

**M-7. Bare `except:` on legacy import**
Line 77 uses a bare `except:` which catches everything including `SystemExit`.

**File**: `server.py`, lines 76-78
```python
try:
    from titlepro.search.ca_recorder.counties.orange import OrangeCountyRecorder
except:
    OrangeCountyRecorder = None
```

---

**M-8. `owner_name` sanitization is inconsistent across endpoints**
Different endpoints sanitize `owner_name` differently:
- Line 360: `owner_name.replace(" ", "_").replace(",", "")`
- Line 655: same pattern
- Line 808: same pattern
- But no length limits, no character whitelist, and special characters like `&`, `'`, `(`, `)` are preserved in folder names

**Recommendation**: Create a single `sanitize_owner_name()` utility function with consistent rules.

---

### LOW Issues

**L-4. Response includes `folder_path` which leaks server filesystem structure**
Multiple endpoints (lines 384, 622, 904, 1148, 1516) return the full server-side filesystem path in the JSON response.

**L-5. `with_note()` appends a note to every response, adding ~100 bytes of overhead per response**
The `RECORDER_NOTE` is appended to every API response. While informational, it increases response payload size unnecessarily.

**L-6. `render_table()` function defined outside of `markdown_to_styled_html()` but only used by it**
Minor organizational issue -- the function could be nested or clearly documented as a helper.

---

## 3. CURE.html Review (`CURE.html` - 4519 lines)

### CRITICAL Issues

**C-7. XSS vulnerability via unsanitized document data in innerHTML**
Multiple locations inject user-controlled data (document numbers, types, filenames, dates) directly into `innerHTML` without escaping:

**File**: `CURE.html`, lines 3321-3334
```javascript
tbody.innerHTML = documentsData.map(doc => `
    <tr ...onclick="viewDocument('${doc.num}')">
        <td>${doc.num}</td>
        <td><span class="doc-type ${doc.typeClass}">${doc.type}</span></td>
        ...
    </tr>
`).join('');
```
If a county recorder returns a document type containing HTML/JavaScript (e.g., `<img src=x onerror=alert(1)>`), it would execute in the browser context.

**Recommendation**: Use the existing `escapeHtml()` function (line 4392) on all user-controlled data before inserting into innerHTML. Or better yet, use DOM APIs (`createElement`, `textContent`) instead of string templates.

---

### HIGH Issues

**H-12. Duplicate `DOMContentLoaded` event listeners**
Lines 2705-2709 and lines 4511-4516 both register `DOMContentLoaded` listeners that call the same functions (`setDefaultDates()`, `checkApiStatus()`, `loadCounties()`). This means these functions run twice on page load, causing duplicate API calls and potential race conditions.

**File**: `CURE.html`, lines 2705-2709, 4511-4516
```javascript
// First listener (line 2705)
document.addEventListener('DOMContentLoaded', () => {
    setDefaultDates();
    checkApiStatus();
    loadCounties();
});

// Second listener (line 4511)
document.addEventListener('DOMContentLoaded', () => {
    setDefaultDates();
    checkApiStatus();
    loadCounties();
    loadSavedTheme();
});
```
**Recommendation**: Remove the first listener (lines 2705-2709). The second one at the bottom already includes all the necessary calls plus `loadSavedTheme()`.

---

**H-13. Logs polling interval not cleaned up on page unload**
The `setInterval` for logs polling (line 4420) is only cleared when switching tabs. If the user closes the page or navigates away while on the logs tab, the interval continues to fire (in some browsers) and can cause console errors.

**File**: `CURE.html`, lines 4417-4428
**Recommendation**: Add a `beforeunload` event listener to stop polling:
```javascript
window.addEventListener('beforeunload', stopLogsPolling);
```

---

**H-14. `pollBatchStatus` and `pollSingleDownload` use recursive `setTimeout` without cleanup**
These polling functions use `setTimeout(poll, 1000)` recursively. If the user clicks "Reset" or starts a new search while polling is active, the old polling continues in the background, potentially updating stale UI elements.

**File**: `CURE.html`, lines 3262-3308, 3559-3592
**Recommendation**: Store the timeout ID and clear it on reset:
```javascript
let batchPollTimeout = null;
// In poll: batchPollTimeout = setTimeout(poll, 1000);
// In resetForm: clearTimeout(batchPollTimeout);
```

---

**H-15. `startSearch()` function references steps 1-8 but `resetForm()` only resets steps 1-8, while HTML may only define steps 1-7**
Line 2982 resets steps 1-7 (`for (let i = 1; i <= 7; i++)`), but the function later references step 8 (line 3208). The `resetForm()` on line 3604 resets steps 1-8. This inconsistency suggests the step count was changed at some point. If step 8 doesn't exist in the HTML, `updateStep(8, ...)` will silently fail (the function has a null guard).

**File**: `CURE.html`, lines 2982-2984, 3208, 3604
**Recommendation**: Verify the HTML has all 8 step elements, or update the loop range to match.

---

### MEDIUM Issues

**M-9. `event.target` used without event parameter in `setFileView()`**
Line 4293 references `event.target` but `setFileView()` doesn't receive an `event` parameter. This relies on the implicit `event` global in some browsers, which is non-standard.

**File**: `CURE.html`, line 4293
```javascript
function setFileView(view) {
    // ...
    event.target.classList.add('active');  // 'event' is not a parameter!
}
```
**Recommendation**: Pass the event explicitly: `onclick="setFileView('grid', event)"` and accept it as a parameter.

---

**M-10. `viewGeneratedFile()` renders content without HTML escaping**
Line 4030 renders markdown content directly into `<pre>` tag without escaping:
```javascript
<pre ...>${content}</pre>
```
While the content comes from the server (not direct user input), if the report markdown contains HTML entities, they could render unexpectedly.

**Recommendation**: Use `escapeHtml(content)` here as well.

---

**M-11. No loading/error states for county dropdown**
`loadCounties()` silently catches errors on line 2806 and shows a degraded message, but the dropdown remains empty. If the API is temporarily down during page load, the user has no way to retry loading counties without refreshing the page.

**Recommendation**: Add a retry button or auto-retry logic.

---

### LOW Issues

**L-7. `printReport()` calls `print()` twice (lines 3906 and 3911)**
The `onload` handler calls `print()`, and a `setTimeout` at 1000ms calls `print()` again. This will show the print dialog twice on some browsers.

**L-8. `currentFileView` variable is initialized to `'grid'` (line 4124) but may not match the initial HTML state.**

**L-9. Hardcoded county recorder URLs in JavaScript (lines 2728-2752)**
These URLs are duplicated from the JSON config files and will drift out of sync when configs are updated.

---

## 4. County Config Review

### Reviewed Configs:
- `calaveras.json`
- `monterey.json`
- `san_luis_obispo.json`
- `santa_cruz.json`
- `trinity.json`

### HIGH Issues

**H-16. Calaveras config has no disclaimer step but other Tyler counties do**
Calaveras is the only config among the five that does NOT have `"action": "accept_disclaimer"` as its first navigation step. Its notes say "no disclaimer" but this should be verified, as Tyler platforms commonly have disclaimers and the navigation could silently fail.

**File**: `src/titlepro/search/ca_recorder/counties/config/calaveras.json`, lines 20-37

---

**H-17. Calaveras uses a non-standard URL pattern (not tylerhost.net)**
Calaveras uses `recorderweb.calaverascounty.gov` instead of the standard `*-web.tylerhost.net` pattern. This is likely correct (self-hosted Tyler deployment), but it means URL patterns in the adapter that assume tylerhost.net domains may not apply.

---

### MEDIUM Issues

**M-12. Four of five configs have identical selector blocks**
Monterey, San Luis Obispo, Santa Cruz, and Trinity all have identical `selectors` objects. This is correct (same Tyler platform) but represents duplication that will need to be updated in multiple places if the platform UI changes.

**Recommendation**: Consider defining a `DEFAULT_TYLER_SELECTORS` in the adapter and only overriding in config files when needed.

---

**M-13. Trinity config sets `base_url` to the disclaimer URL**
Trinity's `base_url` is `https://trinitycountyca-web.tylerhost.net/web/user/disclaimer`, which is the disclaimer page, not the landing page. While this works (the adapter navigates to `disclaimer_url` first), it's semantically incorrect.

**File**: `src/titlepro/search/ca_recorder/counties/config/trinity.json`, line 6

---

### Structure Validation

All five configs share consistent structure:
- `county_id`, `county_name`, `state`, `platform` fields present
- `base_url`, `disclaimer_url`, `search_url` properly set
- `captcha_required: false` consistent with registry
- `name_format: "split"` (Tyler standard)
- `date_format: "MM/DD/YYYY"`
- `doc_number_pattern` with proper regex escaping
- `party_types` and `party_type_map` present
- `navigation_steps` with proper multi-step flow
- `selectors` with comprehensive XPath selectors
- `notes` field documenting county specifics

**All configs pass structural validation.**

---

## 5. Registry Review (`registry.py` - 340 lines)

### Structure
The registry correctly:
- Defines 23 counties (5 RecorderWorks + 18 Tyler)
- Maps each county to its platform, config file, CAPTCHA status, and display name
- Provides factory function `get_recorder()` with lazy imports
- Supports multiple query patterns (by platform, by CAPTCHA status)

### Issues

**M-14. Registry declares 13 CAPTCHA counties but only 5 no-CAPTCHA Tyler counties have configs reviewed**
The remaining 13 CAPTCHA-required Tyler counties (del_norte, fresno, humboldt, inyo, kings, lake, madera, san_benito, san_joaquin, sierra, tulare, tuolumne, yolo) reference config files that were not part of this review scope. Their configs should be verified separately.

---

**M-15. Tuolumne and Yolo use `captcha_type: "image"` but adapter only handles `recaptcha_v2`**
Registry lines 177 and 184 set `captcha_type: "image"` for Tuolumne and Yolo. However, `_handle_captcha()` in the adapter (lines 347-408) only handles reCAPTCHA v2 (looks for recaptcha iframe, extracts site key). Image CAPTCHA would require a completely different solving approach.

**File**: `src/titlepro/search/ca_recorder/counties/registry.py`, lines 173-186
**Recommendation**: Either implement image CAPTCHA support or mark these counties as unsupported for automated search.

---

**L-10. `load_county_config()` opens files without explicit encoding**
Line 236 opens JSON files without specifying encoding. While JSON is typically UTF-8 and Python 3 defaults to UTF-8 on most platforms, it's best practice to be explicit.

---

## Positive Notes

**P-1. Excellent multi-strategy pattern in the Tyler adapter**
The adapter consistently implements 2-3 fallback strategies for every operation (XPath -> JavaScript -> URL fallback). This makes it remarkably resilient to Tyler platform variations across counties. The approach is well-documented with inline comments.

**P-2. Good separation of concerns in the config system**
The registry + JSON config + adapter pattern cleanly separates county-specific configuration from platform-specific automation logic. Adding a new Tyler county only requires a JSON file and a registry entry.

**P-3. Comprehensive multi-step navigation support**
The `navigation_steps` system with `_execute_navigation_step()` is well-designed and handles the complexity of Tyler's SPA-based UIs with proper fallback chains.

**P-4. Robust jQuery Mobile SPA handling**
The adapter correctly scopes element searches to `.ui-page-active` to avoid reading from cached/hidden SPA pages. This is a common source of bugs with jQuery Mobile and the code handles it well.

**P-5. Good deduplication architecture in server.py**
The `DocumentDeduplicator` and `BatchDownloadDeduplicator` pattern in the multi-name search and batch download endpoints is well-structured, with clear state tracking and useful statistics.

**P-6. Proper path traversal protection in file serving endpoints**
The `/api/files` and `/api/file/<path>` endpoints use `resolve()` + `startswith()` to validate paths, which is the correct approach. This pattern should be applied to `/pdf/<owner>/<filename>` as well (see C-4).

**P-7. Good error recovery in batch downloads**
The batch download endpoints properly handle per-document failures without aborting the entire batch, and track error states for each document independently.

**P-8. Clean UI with modern design system**
CURE.html uses CSS custom properties consistently, has a well-organized dark theme with proper contrast ratios, and uses semantic class names.

---

## Summary

| Severity | Count | Key Concerns |
|----------|-------|-------------|
| CRITICAL | 7 | Browser cleanup, CAPTCHA injection, headless mode, path traversal, hardcoded paths, XSS |
| HIGH | 17 | Sleep-based waits, no page timeouts, thread safety, memory leaks, debug mode, duplicate listeners |
| MEDIUM | 15 | Dead code, inconsistent sanitization, duplicated config, platform-specific issues |
| LOW | 10 | Minor organizational issues, redundant code, cosmetic concerns |
| POSITIVE | 8 | Multi-strategy resilience, clean architecture, good error handling |

### Priority Recommendations (Top 5)

1. **Fix the CAPTCHA token injection** (C-2) -- immediate security fix, one line change
2. **Add path traversal check to `/pdf/` endpoint** (C-4) -- copy existing pattern from `/api/file/`
3. **Make headless mode configurable** (C-3) -- wire `show_browser` flag through to adapter
4. **Add XSS protection in CURE.html** (C-7) -- use `escapeHtml()` on all dynamic content
5. **Remove duplicate DOMContentLoaded listener** (H-12) -- delete lines 2705-2709

---

*Review generated by Claude Opus 4.6 Code Review Agent on 2026-02-12*
