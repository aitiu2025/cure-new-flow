# 2Captcha API Integration + reCAPTCHA Token Injection Fix

**Original date:** 2026-02-16 (sibling project)
**Imported to this repo:** 2026-05-20
**Status:** Implementation reference — used as the basis for the 2Captcha integration shipped in this repo on 2026-05-20 (see `docs/CA_Implementation_Update_2005.md` and `docs/FL/FL_Platform_Examination_Guide.md` for the in-repo applied form).

> **Note:** Paths in this doc reference a Windows fork (`C:\10X Door CURE AI\...`). In this repo the equivalent paths are at `~/Desktop/AIProjectsJuly2025/TIUConsulting/10X Door/CA properties/titlePro/`. The conceptual approach (env-loaded API key, registry auto-wire, 4-strategy token injection) is the same. Implementation has been adapted to the existing CURE codebase shape.

---

## Problem Statement

Kings County and other Tyler CAPTCHA counties (13 total) have reCAPTCHA v2 on their disclaimer/search pages. The previous implementation had three issues:

1. **`undetected-chromedriver` was not installed** - The primary CAPTCHA bypass tool was missing from the environment
2. **No CAPTCHA solver was wired up** - The `get_recorder()` factory function created Tyler adapters but never called `set_captcha_solver()`, so even with an API key, the solver was never attached
3. **reCAPTCHA token injection JavaScript was broken** - After 2Captcha successfully solved the CAPTCHA and returned a token, the JavaScript code that injects the token into the page and triggers the reCAPTCHA callback crashed with `N[V[1]] is not a function` because it blindly walked `___grecaptcha_cfg.clients` and called the first function it found (which wasn't the callback)

### Observed Error Log
```
CAPTCHA solved successfully
Auto-solve failed: Message: javascript error: N[V[1]] is not a function
  (Session info: chrome=144.0.7559.134)
```

---

## Solution Overview

### 1. Installed `undetected-chromedriver` (v3.5.5)
Patches Chrome to remove automation detection flags so reCAPTCHA sees a normal browser.

### 2. Created `.env` configuration for 2Captcha API key
Simple environment file where the user pastes their 2Captcha API key. Loaded automatically on server startup via `python-dotenv`.

### 3. Auto-wired captcha solver in registry
The `get_recorder()` factory now automatically creates and attaches a `RecaptchaSolver` when `CAPTCHA_API_KEY` environment variable is set.

### 4. Added persistent Chrome profile
`undetected-chromedriver` now uses `~/.titlepro/chrome_profile/` so cookies and browsing history persist across sessions, building reCAPTCHA trust score over time.

### 5. Added human-like reCAPTCHA checkbox auto-click
Uses `ActionChains` with random delays (1-5 seconds) for realistic mouse movement when clicking the "I'm not a robot" checkbox.

### 6. Fixed token injection with robust multi-strategy approach
Replaced the single fragile callback-finding JavaScript with a new `_inject_recaptcha_token()` method that uses 4 fallback strategies.

---

## Files Changed

### 1. `.env` (NEW FILE)
**Path:** `C:\10X Door CURE AI\Amit-TitlePro-10X-Door-APP\titlePro\.env`

**Purpose:** Configuration file for 2Captcha API key

**Content:**
```env
# 2Captcha API Key for auto-solving reCAPTCHA on county recorder sites
# Purchase your key at: https://2captcha.com
# Steps: 1) Sign up  2) Add $3-5 balance  3) Copy API key from dashboard  4) Paste below
CAPTCHA_API_KEY=<user's API key goes here>

# CAPTCHA service provider (default: 2captcha)
# Options: "2captcha" or "anticaptcha"
CAPTCHA_SERVICE=2captcha
```

---

### 2. `.gitignore` (MODIFIED)
**Path:** `C:\10X Door CURE AI\Amit-TitlePro-10X-Door-APP\titlePro\.gitignore`

**Change:** Added `.env` to prevent API key from being committed to git

**Diff:**
```diff
+# Environment secrets
+.env
+
 # Virtual environments
```

---

### 3. `server.py` (MODIFIED)
**Path:** `C:\10X Door CURE AI\Amit-TitlePro-10X-Door-APP\titlePro\src\titlepro\api\server.py`

**Change:** Added `dotenv` loading at the top of the file so `CAPTCHA_API_KEY` is available as an environment variable before any adapters are created

**Diff:**
```diff
 from pathlib import Path
+
+# Load .env file (CAPTCHA_API_KEY, etc.) before anything else
+from dotenv import load_dotenv
+load_dotenv(Path(__file__).resolve().parents[3] / ".env")
```

**How it works:** `Path(__file__).resolve().parents[3]` navigates from `src/titlepro/api/server.py` up 3 levels to the `titlePro/` root where `.env` lives.

---

### 4. `registry.py` (MODIFIED)
**Path:** `C:\10X Door CURE AI\Amit-TitlePro-10X-Door-APP\titlePro\src\titlepro\search\ca_recorder\counties\registry.py`

**Change:** Auto-wires `RecaptchaSolver` onto Tyler adapters for CAPTCHA counties

**Diff (in `get_recorder()` function):**
```diff
     elif platform == "tyler":
         from .adapters.tyler_adapter import TylerAdapter
-        return TylerAdapter(config, start_date=start_date, end_date=end_date)
+        adapter = TylerAdapter(config, start_date=start_date, end_date=end_date)
+
+        # Auto-wire captcha solver for CAPTCHA counties (uses CAPTCHA_API_KEY env var)
+        if config.get("captcha_required", False):
+            try:
+                from ..captcha.recaptcha_solver import get_captcha_solver
+                solver = get_captcha_solver()
+                if solver:
+                    adapter.set_captcha_solver(solver)
+                    print(f"  CAPTCHA solver configured for {adapter.county_name} County")
+            except Exception as e:
+                print(f"  CAPTCHA solver not available: {e} (will use undetected-chromedriver or manual fallback)")
+
+        return adapter
```

---

### 5. `tyler_adapter.py` (MODIFIED - Major Changes)
**Path:** `C:\10X Door CURE AI\Amit-TitlePro-10X-Door-APP\titlePro\src\titlepro\search\ca_recorder\counties\adapters\tyler_adapter.py`

#### Change A: New `_inject_recaptcha_token()` method (added after `set_captcha_solver()`)

**Purpose:** Robust token injection that replaces the broken single-strategy JavaScript. Uses 4 fallback strategies:

| Strategy | Method | Description |
|----------|--------|-------------|
| A | `data-callback` | Reads callback function name from the `data-callback` HTML attribute on `.g-recaptcha` widget |
| B | Enterprise check | Detects enterprise reCAPTCHA and skips broken callback paths |
| C | Safe `___grecaptcha_cfg` walk | Walks `___grecaptcha_cfg.clients` safely, only calling `.callback` properties (not random functions like the old code) |
| D | Enable buttons | If no callback found, directly enables disabled "I Accept" / "Search" buttons by removing `disabled` attribute and `ui-state-disabled` class |

The token is always set in ALL `g-recaptcha-response` textareas first (both `.innerHTML` and `.value`), then the callback is triggered.

#### Change B: Persistent Chrome profile in `_setup_undetected_driver()`

```diff
+            # Persistent user profile - builds reCAPTCHA trust over sessions
+            profile_dir = os.path.join(os.path.expanduser("~"), ".titlepro", "chrome_profile")
+            os.makedirs(profile_dir, exist_ok=True)
+            uc_options.add_argument(f"--user-data-dir={profile_dir}")
```

Also added post-init scripts to remove `navigator.webdriver` flag and clean up user agent string.

**Profile location:** `C:\Users\<username>\.titlepro\chrome_profile\`

#### Change C: Human-like reCAPTCHA checkbox auto-click in `_handle_disclaimer_recaptcha()`

Replaced direct `.click()` with `ActionChains` + random delays:

```diff
-                    checkbox.click()
-                    time.sleep(3)
+                    import random
+                    time.sleep(random.uniform(1.0, 3.0))  # Random delay before interaction
+                    actions = ActionChains(self.driver)
+                    actions.move_to_element(checkbox)
+                    actions.pause(random.uniform(0.1, 0.3))
+                    actions.click()
+                    actions.perform()
+                    time.sleep(random.uniform(3.0, 5.0))  # Wait for evaluation
```

#### Change D: Added 2Captcha fallback after checkbox image challenge

When the auto-click triggers an image challenge (instead of auto-passing), the code now automatically tries to solve it via 2Captcha API before falling back to manual:

```
Checkbox clicked -> Image challenge appeared -> 2Captcha solves it -> Token injected -> Proceed
```

#### Change E: Updated all 3 token injection sites to use `_inject_recaptcha_token()`

All places that previously had inline JavaScript for token injection now call the shared method:

1. `_handle_disclaimer_recaptcha()` - Strategy 1 (external solver on disclaimer page)
2. `_handle_disclaimer_recaptcha()` - Strategy 2b (image challenge after checkbox click)
3. `_handle_captcha()` - Strategy A (external solver on search page)

---

## CAPTCHA Resolution Flow (After All Changes)

```
Kings/Madera/etc. County search starts
    |
    v
Browser opens (undetected-chromedriver + persistent profile)
    |
    v
reCAPTCHA detected on disclaimer page
    |
    +-- Strategy 1: 2Captcha API solve (if CAPTCHA_API_KEY set)
    |       Token obtained (~15-30s) -> _inject_recaptcha_token() -> Click "I Accept"
    |
    +-- Strategy 2: Auto-click checkbox (undetected-chromedriver)
    |       ActionChains + random delays -> Click checkbox
    |       |
    |       +-- Auto-passed? -> Click "I Accept" -> Done
    |       |
    |       +-- Image challenge? -> 2Captcha solves it -> _inject_recaptcha_token()
    |
    +-- Strategy 3: Manual fallback (180s timeout)
            User clicks in browser window
    |
    v
Disclaimer accepted -> Navigate to Name Search -> Fill form -> Search
```

---

## Counties Affected

All 13 Tyler CAPTCHA counties benefit from these changes:

| # | County | CAPTCHA Type |
|---|--------|-------------|
| 1 | Del Norte | reCAPTCHA v2 |
| 2 | Fresno | reCAPTCHA v2 |
| 3 | Humboldt | reCAPTCHA v2 |
| 4 | Inyo | reCAPTCHA v2 |
| 5 | Kings | reCAPTCHA v2 |
| 6 | Lake | reCAPTCHA v2 |
| 7 | Madera | reCAPTCHA v2 |
| 8 | San Benito | reCAPTCHA v2 |
| 9 | San Joaquin | reCAPTCHA v2 |
| 10 | Sierra | reCAPTCHA v2 |
| 11 | Tulare | reCAPTCHA v2 |
| 12 | Tuolumne | reCAPTCHA v2 |
| 13 | Yolo | reCAPTCHA v2 |

---

## Dependencies Installed

| Package | Version | Purpose |
|---------|---------|---------|
| `undetected-chromedriver` | 3.5.5 | Chrome automation without bot detection |
| `python-dotenv` | 1.2.1 | Already installed, loads `.env` file |

---

## Setup Instructions for User

1. Purchase 2Captcha API key at https://2captcha.com (~$3 for 1000 solves)
2. Paste API key in `titlePro/.env` file:
   ```
   CAPTCHA_API_KEY=your_key_here
   ```
3. Restart the server
4. All 13 CAPTCHA counties will auto-solve reCAPTCHA

---

## Testing Results

- **Madera County:** 2Captcha successfully solved reCAPTCHA (token obtained), but old injection code crashed with `N[V[1]] is not a function` -> Fixed with new `_inject_recaptcha_token()` method
- **Kings County:** `undetected-chromedriver` clicked checkbox but image challenge appeared -> Fixed with 2Captcha fallback after image challenge
- **Registry wiring:** Verified `get_recorder('kings')` auto-attaches `RecaptchaSolver` when `CAPTCHA_API_KEY` env var is set
