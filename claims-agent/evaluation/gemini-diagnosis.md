# Gemini integration diagnosis

Resolved with a replacement key and Gemini 3.5 Flash-Lite. All six live extraction cases passed. See [live verification](live-verification.md). The original diagnosis below is preserved as history.

Live diagnostics on 2026-10-09 identified two independent blockers:

1. `gemini-2.5-flash` returned HTTP 404: unavailable to new users.
2. After switching to `gemini-3.8-flash`, Google returned HTTP 403: the API key was reported as leaked and a replacement key is required.

The adapter now uses `gemini-3.8-flash` with low thinking and thought summaries disabled. It accepts opaque thought-signature metadata on text parts without returning or storing that metadata. Schema/provenance validation and advisory-only decisions remain unchanged.

Google currently documents structured outputs and free-tier input/output for this model. Account-specific availability and quotas still apply.

- [Model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
- [Pricing](https://ai.google.dev/gemini-api/docs/pricing)

No validated live findings were produced. The remaining blocker is a replacement API key; no further requests were made after the leaked-key response. This response does not establish where or when the key was exposed.

The user should revoke the rejected key and replace it locally. Do not paste credentials into chat. Authorization to finish the integration and test the existing synthetic cases persists; another approval is not required merely because the key changes.
