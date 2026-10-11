# Reviewer-confirmed Gemini verification — 2026-10-09

A fresh, actual Gemini 3.5 Flash-Lite call used the existing extraction prompt and
the synthetic claim in [clinical_review](../examples/clinical_review/README.md).
The API key was loaded locally and is excluded from the examples and archive.
The model returned `validated_candidates`: diagnosis, necessity and attempted
treatment documented; contraindication not found. Exact source quotations and
request binding passed validation. This is an integration demonstration, not
clinical validation.

| Step | Observed outcome |
| --- | --- |
| Original claim, clinical assessment absent | route_to_senior_reviewer |
| Real Gemini extraction | validated_candidates, three documented / one not_found |
| Prepared reviewer template | All four verdicts pending; confirmation false |
| Explicit synthetic reviewer response | Three established; contraindication unknown; three existing assessments acknowledged |
| New deterministic review | approve_pre_authorization |
| Persistence | Original and new review linked; model packet and reviewer response retained |

The completed response is a **simulated reviewer fixture**, not a real clinician's
approval. Its choices were explicitly written for this example; the application
has no automatic confirmation operation. This fixture trusts the synthetic
clinician's stated assessment and does not establish real-world sufficiency.

The 30 tests in `tests/test_assessment_review.py` cover pending/invalid responses,
negative and conflicting findings, fabricated quotations, stale policy/source
bindings, reused IDs, unchanged original history, explicit carry-forward, storage
failure, payment amount gates, inactive/high-value rules and CLI execution.
A documented *negative* necessity statement remains pending until reviewed and
cannot approve when assessed as not established. Missing prerequisites still route
to review. Full project suite: 682 passed with the Gemini extra installed.

Reproduce this integration offline using the recorded response, or run a new
live call and provide a new matching assessment using the walkthrough. The earlier
six-case [live extraction evaluation](live-verification.md) remains separate.
