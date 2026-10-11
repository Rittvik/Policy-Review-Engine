# Retrieval milestone review

Method: local BM25 over the supplied policy's 13 section/page chunks. Tokenize
case-insensitively, retain dotted diagnosis codes, remove a small explicit
stop-word list, and index each heading twice. BM25 uses k1=1.2, b=0.75.
There is no stemming, synonym expansion, embedding model, or external API.
Repeated query terms count once. Ties use page number then chunk ID.

Results below are actual top-three results from the supplied PDF. This is a
small retrieval demonstration, not the later approved claim evaluation suite.

| Query | First | Second | Third |
| --- | --- | --- | --- |
| lumbar MRI M54.5 conservative treatment | 5.1 MRI Coverage, p2 (10.798) | 3.2 Documentation Required, p2 (1.626) | 3.1 Services Requiring Prior Authorization, p1 (1.216) |
| documentation clinical note diagnosis treatment history service location | 3.2 Documentation Required, p2 (13.558) | 8 Appeals, p3 (3.285) | 5.1 MRI Coverage, p2 (2.842) |
| duplicate claims member provider NPI billed amount | 7.1 Duplicate Claims, p3 (14.367) | 6 Exclusions, p2 (3.649) | 4 Medical Necessity Standard, p2 (1.911) |
| appeals denial new clinical documentation | 8 Appeals, p3 (12.830) | 3.2 Documentation Required, p2 (3.420) | 2 Member Eligibility and Plan Status, p1 (1.738) |
| MRI coverage diagnosis prior treatment authorization | 5.1 MRI Coverage, p2 (8.463) | 3.2 Documentation Required, p2 (4.347) | 1 Overview of Covered Benefits, p1 (4.217) |

## Observed limitations

- The broad MRI query misses section 3.1 in its top three; the general benefits
  overview ranks higher. Coverage decisions must not assume a single query is
  complete. Focused queries per required check are needed in the controller.
- Shared words produce off-topic results: appeals appear in documentation
  results, medical necessity in duplicate results, and eligibility in appeals
  results. The controller must validate relevance before citing them.
- `back scan` returns section 5.1 only because `back` matches. The system has not
  inferred that a scan means an MRI. Scores are not evidence-sufficiency or
  medical-necessity confidence.
- `xyzzyquux` returns no hits. Empty and stop-word-only queries also return no
  hits, instead of arbitrary policy text.
- Singular/plural variants and paraphrases are not automatically equivalent.
- Wrong policy/index identity or mixed revision chunks raise PolicyError before
  ranking. Review routing on that error belongs to the future controller.
- Search text is only tokenized data. This milestone does not establish
  end-to-end prompt-injection resistance; the model and controller are pending.

## Verification

`uv run --locked --extra dev python -m pytest -q`: 42 tests passed. Retrieval
tests cover five focused policy topics, empty/no-overlap queries, diagnosis
tokens, reproducible ranking, result limits, policy/revision isolation, and
instruction-like query text. Existing ingestion tests also pass.

## Reproduce

From the project directory:

```sh
uv run --locked --extra dev python - <<'PY'
from pathlib import Path
from claims_agent.policy import ingest_policy, resolve_policy
from claims_agent.retrieval import LexicalRetriever

spec = resolve_policy("HorizonCare", "Silver PPO 2500")
index = ingest_policy(spec, Path("policies"), Path(".policy-cache")).index
retriever = LexicalRetriever(index, insurer=spec.insurer, plan_name=spec.plan_name)
queries = [
    "lumbar MRI M54.5 conservative treatment",
    "documentation clinical note diagnosis treatment history service location",
    "duplicate claims member provider NPI billed amount",
    "appeals denial new clinical documentation",
    "MRI coverage diagnosis prior treatment authorization",
    "back scan",
    "xyzzyquux",
]
for query in queries:
    print(query)
    for hit in retriever.search(query):
        print(hit.chunk.section, hit.chunk.heading, hit.chunk.source_page,
              round(hit.score, 3), hit.matched_terms)
PY
```
