# Local review desk

The optional FastAPI interface uses the same controller, Gemini adapter,
source-bound assessment bridge and SQLite history as the CLI. It adds a browser
workflow, not a second set of coverage rules. All bundled claims are synthetic.

## Start

From the extracted project root, run:

```sh
uv run --locked --extra web python -m uvicorn claims_agent.web:app --host 127.0.0.1 --port 8000
```

Open **http://127.0.0.1:8000**. The command installs locked dependencies if needed.
No API key or Gemini SDK is needed for rules or the recorded-response demo. Stop
with Ctrl+C. If port 8000 is occupied, choose another port and open that address.

For live Gemini, put your own key in `.env` as shown in the main README, then use:

```sh
uv run --locked --extra web --extra gemini --env-file .env python -m uvicorn claims_agent.web:app --host 127.0.0.1 --port 8000
```

The application does not automatically load key files. Change the `--env-file`
path if yours is elsewhere. Keys stay in the server process and are never sent
to the browser. Starting the server alone makes no model calls.

## Five-minute demonstration

1. The page opens with **MRI — Clinical assessment needed** loaded. Choose **Recorded
   Gemini demo** and select NOTE and HISTORY. This uses the bundled, real recorded
   response, makes no external call, and requires the unchanged sample snapshot.
2. Click **Run review**. The initial result routes to senior review. Open policy
   evidence, the rule trace, model findings and the source documents.
3. In **Assess clinical findings**, enter a reviewer label. A new review ID is
   suggested. All service-specific verdicts are initially blank; reasons and explicit source
   confirmation are required.
4. For this synthetic fixture only, establish diagnosis support, necessity and
   attempted treatment with reasons grounded in the supplied clinician statements.
   Keep contraindication **Unknown**: absence of a statement does not establish
   its opposite. Existing model quotations are editable, not automatically trusted.
5. Inspect and explicitly select the existing coding, treatment-history
   applicability and exclusion assessments. Confirm source review and submit.
   The new result approves pre-authorization and shows two linked history records.

These are simulated reviewer choices, not authenticated clinical sign-off. The
source statements are intentionally simple; this demonstrates integration rather
than proving clinical sufficiency or model accuracy. You can also assess a finding
as unknown/not established to demonstrate continued senior routing.

Choose **Covered MRI**, **Missing documentation**, **High-value review**,
**Inactive membership** or **Covered payment**, click **Load sample**, and use
**Rules only** for the other demonstrations. Payment displays the supplied $900
amount. Modes do not silently change when a sample changes.

For a fresh model call, use **Live Gemini** on a claim with clinical source text.
**Preview selected model input** shows the reduced payload locally. **Run review**
then sends selected documents, notes and policy excerpts to Google. Free text is
not automatically de-identified. A failed/unavailable extraction leaves the
ordinary decision visible and offers no confirmation form.

## Inputs, persistence and recovery

- Upload a claim `.json` file or edit the expanded JSON field. There is no PDF
  document uploader or free-form chatbot. The bundled policy PDF remains the
  source of truth. The HTTP request limit is 2 MiB; Gemini also has its own smaller
  request limit. Uploads are read as JSON, not saved as arbitrary server files.
- Clinical document selections are visible and editable. Model extraction is an
  explicit mode. Every clinical verdict and carry-forward choice needs review.
- Ordinary reviews save only when **Save initial review** is selected. A completed
  confirmation saves both linked reviews and complete provenance. The UI uses
  `.review-history/web.sqlite3`, separate from default CLI history. The CLI can
  inspect/use this store by passing its path explicitly.
- Saving another claim under an existing review ID is rejected; choose a new ID.
  Never rewrite bound assessment snapshots merely to bypass a stale-input error.
- History lookup uses a saved review ID and returns that claim's records. A result
  can be downloaded as JSON. Reloading loses an unsaved form; saved reviews remain.
- **Clearing History:** A dedicated **Clear History** button is available exclusively on the **Saved History** tab (`#history`). It removes all test records from the SQLite audit database with instant UI feedback.
- **Simplified Samples & Manual Editing:** All 12 sample claims loaded in the dropdown have been streamlined (reduced by ~74% lines), eliminating redundant empty blocks while staying 100% compliant with Pydantic schemas. Refer to the [Codes, Schema & Determinations Reference](codes_and_determinations_reference.md) when making manual edits in the browser editor.
- After a server restart, reload the page before submitting: the browser request
  token changes. Use one server process; multiple workers are not supported by
  this local token design. No automatic retries or background model calls occur.
- **Unified Appeals Process:** Formal appeals are adjudicated directly within the **Claim Process** desk (select *Appeal — Reassessment with new clinical evidence* from the sample dropdown, upload an appeal JSON, or click *Appeal ➔* on any saved denial in history). It runs the same saved-denial, documentation, timing, relevance and service reassessment gates as the CLI, preserving linked audit records. Unverified links cannot approve.

## Implementation and verification

`web.py` defines a configurable app factory and bounded JSON routes. The HTML
shell is server-rendered with Jinja; a small script handles forms and results.
There is no Node/React build step, CDN or browser-side provider credential.
Slow synchronous reviews run in a thread pool. Templates, scripts and styles are
included in the Python package and submission archive.

Endpoints: sample loading, local extraction preview, review, confirmation and
saved history. They are a local UI API, not a published service contract. Safe
errors do not echo provider exceptions or submitted input. Host validation,
a per-process submission token, no CORS allowance, no-store headers, content
security policy and text-only rendering reduce browser-origin risks. These
controls do not authenticate the local operator or protect a compromised machine.
Do not expose this server publicly or bind it to all network interfaces.

```sh
uv run --locked --extra dev --extra web --extra gemini python -m pytest -q
```

Tests cover API flows, invalid/oversized input, source mismatch, unconfirmed
findings, forged quotes, negative assessments, persistence errors, host/token
checks and provider failure. Browser testing in Chrome exercised the recorded
extraction, explicit assessment and linked saved approval. A separate real Gemini
request through the FastAPI endpoint returned validated candidates and a pending
review form. See [web verification](../evaluation/web-verification.md).

Framework references: [FastAPI templates](https://fastapi.tiangolo.com/advanced/templates/),
[Starlette middleware](https://www.starlette.io/middleware/) and
[thread pool](https://www.starlette.io/threadpool/).

## Expanded services

The sample menu now covers all families in the supplied policy. See the
[coverage matrix](policy-coverage.md) and [service demos](../examples/services/README.md).
Recorded mode supports both the original MRI sample (NOTE + HISTORY) and the
CT assessment sample (NOTE only). The UI selects clinical topics per service.
Formulary documents can be explicitly selected for drug extraction.
