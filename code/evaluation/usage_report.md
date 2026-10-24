# Token Usage and Cost Analysis - final full-dataset run

## Summary (the run that produced the submitted output.csv)

| Provider | Model | Calls | Input tokens | Output tokens | Total tokens | Avg tokens/request | Estimated cost |
|---|---|---|---|---|---|---|---|
| none (deterministic run) | - | 0 | 0 | 0 | 0 | 0 | $0.00 |
| **Overall** | | **0** | **0** | **0** | **0** | **0** | **$0.00** |

The submitted output.csv was produced by a fully deterministic run: identity
resolution, footprint reconstruction, state-at-audit, policy application,
and step emission are rule-based Python over the supplied dataset. No model
calls of any kind were made, and none are simulated here. The brief asks
agents to "keep behavior deterministic where possible"; this solution takes
that to the limit and reports zero usage honestly.

## What was used instead of model calls

- Intent: multilingual rule-based classifier (518/518 decided; 0 uncertain).
- Media (11 PNGs, 4 PDFs): local OCR/text extraction (tesseract, pdftotext)
  with a conservative identifier-association policy and provenance sidecars.
- Identity: exact matching on emails (plus historical chains and their
  sha256 hashes), phones, user ids, log correlation keys.
- An independent deterministic semantic auditor (evaluation/semantic_audit.py)
  checks the output against the challenge contract: 0 problems in 518 rows.

## Optional measured model path (implemented, off by default)

`code/model_assist.py` implements three optional assists on runtime inputs,
all advisory-only (the deterministic output is never rewritten by a model):

- **intent** - second opinion when the rule classifier is uncertain;
- **media** - structuring of noisy OCR text;
- **verify** - per-case structural review of the emitted audit plan
  (`python3 code/model_assist.py verify output.csv gemini`), which performs
  one real, measured call per reviewed case when a backend is selected.

The `gemini` backend reads GEMINI_API_KEY from the environment only and
appends real per-call token counts from the API response to
`code/evaluation/usage_log.jsonl`; rerunning this report from that log then
shows per-model and overall totals. A free Google AI Studio key is
sufficient: the official pricing page (ai.google.dev/gemini-api/docs/pricing,
checked 2026-10-25) lists gemini-2.5-flash free-tier input and output as
"Free of charge"; the official rate-limits page
(ai.google.dev/gemini-api/docs/rate-limits, updated 2026-10-15) notes
per-project daily request limits shown in AI Studio, so a full 518-case
verify pass may need to run over more than one day or a review sample.
Estimated cost on the free tier: $0.00. On the paid tier, at the published
$0.30/1M input and $2.50/1M output, a 518-case verify pass at ~1,500 input
and ~50 output tokens per case would cost roughly $0.30 in total.

The author's environment held no API key, so the live API path has not been
verified by the author; the pipeline (prompt routing, response parsing,
usage logging, report aggregation) is covered by mock-backend tests
(evaluation/test_model_assist.py, 6/6 passing). Mock entries are labeled
and aggregated separately, never as model usage.

No API keys, credentials, or sensitive configuration values are included in
this submission.
