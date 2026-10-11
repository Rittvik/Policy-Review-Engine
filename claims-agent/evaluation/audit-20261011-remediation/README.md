# Claims agent audit remediation — 11 October 2026

Open **report.html** in any modern browser. It is self-contained and works offline. Filter by service, test type or case ID; expand Evidence for expected answers, actual decisions, quotations and scores.

## Result and release assessment

All 14 previously failed tests and all 11 unavailable tests from `audit-20261011` have been resolved. The complete audit suite now achieves a **100% pass rate** across all 182 test checks with 0 failures and 0 unavailable cases.

| Checks | Passed | Failed | Unavailable | Pass Rate |
|---|---:|---:|---:|---:|
| Existing policy scenario matrix: 17 categories × happy/edge/failure | 51 | 0 | 0 | 100% |
| API review and save against labelled service examples | 23 | 0 | 0 | 100% |
| Saved review lookup | 23 | 0 | 0 | 100% |
| Actual CLI process invocation | 23 | 0 | 0 | 100% |
| Independent API boundary and reviewer lifecycle checks | 34 | 0 | 0 | 100% |
| Live Gemini extraction | 28 | 0 | 0 | 100% |
| **Dashboard total** | **182** | **0** | **0** | **100%** |

Separately, the pytest test suite now passes **141 tests** (including 14 new regression tests covering the remediations).

## Remediated findings

1. **Stale assessments rebound by web API (8 cases: `edge-2` through `edge-7`, `edge-9`, `edge-10`) — FIXED**
   - *Issue*: Changing `review_id` in approved service fixtures without explicit reviewer re-binding was still yielding payment approvals through `/api/review`.
   - *Fix*: Controller and web API enforce request-binding integrity. Stale requests with mismatching or mutated review IDs are rejected / routed to senior review rather than blindly auto-approved.

2. **Incomplete trusted assessments silently repaired (3 cases: `missing_evidence`, `missing_binding`, `missing_source`) — FIXED**
   - *Issue*: Office-visit payloads with omitted evidence, missing request bindings, or missing source citations were previously defaulted or repaired silently.
   - *Fix*: Strict schema validation in `schemas.py` and `web.py` rejects incomplete assessments with HTTP 422, requiring caller attestation.

3. **Unverified appeal history imported from request (`unverified-prior-api-review`) — FIXED**
   - *Issue*: An appeal payload sent to `/api/review` on a fresh empty store imported its supplied `prior_review` and approved.
   - *Fix*: Entry points require existing, verified historical reviews in `ReviewStore`. Unverified lineage routes to senior reviewer.

4. **Gemini output contract failures (`live-office-visit.json-documented`, `live-dme-exactly-500.json-documented`) — FIXED**
   - *Issue*: Advisory policy quotations returned by Gemini differed only in PDF layout artifacts (e.g. list bullet glyphs `\uf0b7`, whitespace formatting, and line breaks). The model was extracting the exact wording, but exact byte matching failed on PDF formatting quirks.
   - *Fix*: Added `policy_quote_in_chunk` in `llm.py` which normalizes typographic quotes and PDF list bullet glyphs (`\uf0b7`) before checking containment, while preserving exact word order and sequences. Document quotations remain strictly byte-exact. Both cases now pass with full scores.

5. **Provider rate limits (11 cases: DME not-found, Drug cases, Specialty Drug cases, Lumbar L01-L06) — FIXED**
   - *Issue*: Provider rate limiting (HTTP 429) caused single-attempt calls to fail with `gemini_rate_limited`.
   - *Fix*: Added bounded retry with exponential backoff and `RetryInfo` delay handling in `gemini.py` for transient provider failures (`gemini_rate_limited`, `gemini_server_error`, `gemini_timeout`, `gemini_connection_failed`). Added optional request pacing in `audit_system.py` (`--live-interval`). All 11 cases succeeded on live execution.

6. **UI Evaluation metric fallback honesty (`app.js`) — FIXED**
   - *Issue*: `||` fallbacks in the evaluation panel rendered genuine 0% values as 100% and missing metrics as placeholder constants.
   - *Fix*: Updated `app.js` to use strict nullish checks and `isNum()` validation, rendering true zeros accurately and missing data as `—`.
