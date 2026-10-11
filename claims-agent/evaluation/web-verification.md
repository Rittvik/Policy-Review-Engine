# Web milestone verification — 2026-10-09

Implemented a local FastAPI/Jinja interface over the existing domain services.
No deterministic policy rule, model prompt or transmitted data scope was changed.

- **20 web integration tests passed.** Full suite with dev, Gemini and web extras:
  **702 passed**. Starlette emits one upstream deprecation warning for its current
  httpx-backed TestClient; this does not affect test outcomes or application use.
- **Chrome browser walkthrough passed:** page rendered; recorded Gemini extraction
  produced initial senior routing; explicit synthetic reviewer verdicts, reasons,
  carry-forward choices and confirmation produced a saved approval. Both original
  and new reviews appeared in linked history. The source review was retained.
- **Real provider through web endpoint passed:** a fresh synthetic request returned
  HTTP 200, `validated_candidates` from Gemini 3.5 Flash-Lite and a review template
  with all verdicts pending. Original decision remained senior review.
  [Recorded response](web-live-verification.json).
- Rules-only sample actions, preview without a model call, unknown samples, host
  and submission-token rejection, malformed/duplicate/oversized JSON, stale
  recorded extraction, unconfirmed responses, fabricated quotes, negative clinical
  assessments, reused IDs, failed persistence and unavailable provider are tested.

Browser confirmation used a clearly named `synthetic-browser-reviewer`; it is
not a real clinician's sign-off. Desktop Chrome was inspected; mobile CSS is
provided but mobile browser operation has not been verified. The web model call
is an integration smoke check, not a new accuracy benchmark. The earlier six-case
live extraction evaluation remains the model-quality demonstration.

Current workspace test suite: 141 passed in ~3s.
Packaged assets, key-free sample reviews, confirmed approval and linked history
passed. Offline evaluation remained 20/20 decisions and 6/6 mock extractions.
