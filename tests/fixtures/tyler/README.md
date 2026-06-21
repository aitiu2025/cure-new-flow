# Tyler HTML Fixtures

Saved page snippets used by `tests/unit/test_tyler_extract_results.py` to
catch silent selector / footer-false-positive drift in
`tyler_adapter.extract_results` and related helpers.

These are NOT replayed in a real browser — they are consumed as plain text
by the fixture-driven tests (which exercise the Python-level guards in the
adapter, not the JS extraction). The full JS extraction path is covered by
the integration tests against a live recorder.

## Fixtures

| File                              | Layout                              | Purpose                                                  |
| --------------------------------- | ----------------------------------- | -------------------------------------------------------- |
| `results_success.txt`             | Listview with two doc rows + total  | Sanity: guards must NOT raise on healthy results.        |
| `no_results.txt`                  | "No records found" message page     | Guards must NOT raise; result count = 0 legitimately.    |
| `results_count_cap.txt`           | "more documents than the maximum"   | Cap-detection trigger; guards must NOT raise.            |
| `footer_only.txt`                 | Footer-only page (false positive)   | Captcha-guard MUST raise (no real results).              |
| `empty_search_error.txt`          | "Empty searches are not allowed"    | `_check_empty_search_error` MUST raise RetryableSubmit.  |
