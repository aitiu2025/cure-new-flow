---
name: tony-review-directives
description: Tony Roveda's six methodology directives from the 2026-05-22 Broward Test Review — apply to every CURE recorder workflow
type: feedback
originSessionId: 3c98fcd9-98fe-4b81-b8f0-026a72f93e20
---
Tony Roveda reviewed CURE's 2026-05-21 Broward Test (SIMMONS + ANAND) and shipped a 6-directive correction sheet (`/Users/ag/Downloads/Broward County Test Review.docx` → summarized at `~/Downloads/Cure_Response/01_tony_review_findings.md`). These are the goalposts for every Phase 1 design decision going forward.

**Why:** SIMMONS shipped with a wrong-property QCD (6830 Falconsgate Davie vs subject 2151 NW 93rd Pembroke Pines). ANAND was 80% accurate — missed NOCs, showed released MTGs as open, only ran the first name. Tony's verbatim: "I have stated countless times that all names provided must be run." These six directives are the prevention.

**How to apply** to every recorder adapter, pipeline phase, and report-generation step:

1. **No Selenium/Playwright for Phase 1 search.** Use HTTP GET/POST via `curl_cffi` + Safari iOS TLS impersonation (proven to pass Cloudflare). The legacy Selenium adapter is a fallback while the HTTP search-submit blocker is being unwound — see `broward_http_adapter.md` for status. Per Tony: "We should not run any selenium or playwright runs we should run python http GET or POST request."

2. **Deed-first search.** The first search MUST be `DocType=DEED`, not "all documents". Locate the vesting deed → NLP-extract APN from the deed body → re-search by parcel number to capture corporate-grantor priors. Per Tony: "Please adopt the DocType Deed as the initial exam. This will allow you to quickly locate the vesting deed for our party using NLP and pull the APN."

3. **Run EVERY provided name.** Husband + wife always. No silent dropping of second-name searches because the first found docs. Cross-check the vesting Deed# across both spouses' results — if it appears in both, that's the joint conveyance. If only in one, flag for review (per Tony: "I am surprised that Truist Bank... allowed the loan to be recorded without putting Deston on record with a QCD"). Apply the co-developer's spouse-delta trick (`set(insts_husband) - set(insts_wife)`) to catch alias-only liens.

4. **NLP-verify subject address.** Pull the deed image, OCR + parse, run `subject_address_verifier.verify_subject_address(extracted, subject)`. If status != `MATCH`, the deed candidate MUST be rejected with the mismatch evidence in the report — this is the SIMMONS gate (Falconsgate Davie was the wrong property). Per Tony: "The document images must be pulled and reviewed with NLP. I don't know how else to say it."

5. **Examine EVERY indexed document.** Tony's manual count for ANAND was 23 per party — our automated 11 was a 52% miss. No selective dropping in extraction; if dedup or filter removes a doc, the report MUST itemize it as "examined and excluded because X". Per Tony: "It appears to have selectively picked some and not all. It missed a NOC and satisfactions."

6. **Released-mortgage exclusion.** Run `released_mortgage_linker.classify_mortgages(documents, extracted_texts)` after extraction. Any mortgage with a linked satisfaction/release MUST be classified `released` and excluded from the open-mortgages section of the report. Per Tony: "It appears to have identified satisfactions but didn't connect the dots to remove them."

## Anti-patterns Tony explicitly called out
- ❌ "Standing on" a QCD as the vesting deed without showing the chain-of-title warranty deed first. "We cannot stand on a QCD; we need to show the Warranty Deed and any subsequent QCDs, oldest to newest."
- ❌ Shipping a partial result set silently when the input names were wrong. CURE should surface a RED LIGHT for human review when (a) no deed matches the subject address, or (b) only one of multiple provided names returned any results. "This should have triggered a red flag and a call to the client."

## Tony's final note
He asked for the verbatim system prompts. Send him the contents of:
- `Title_Examination_Notes_System_Prompt.md` (Title-notes prompt)
- `ph1_oneshot/docs/RAW_Report_Generation_System_Prompt.md` (RAW-exam prompt — moved to ph1_oneshot/docs/ during the 2026-04-22 restructure)
