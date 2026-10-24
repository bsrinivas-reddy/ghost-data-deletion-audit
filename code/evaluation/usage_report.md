# Token Usage and Cost Analysis - final full-dataset run

## Summary

| Provider | Model | Calls | Input tokens | Output tokens | Total tokens | Avg tokens/request | Estimated cost |
|---|---|---|---|---|---|---|---|
| none (deterministic run) | - | 0 | 0 | 0 | 0 | 0 | $0.00 |
| **Overall** | | **0** | **0** | **0** | **0** | **0** | **$0.00** |

The `output.csv` submitted here was produced by a fully deterministic run:
identity resolution, footprint reconstruction, state-at-audit, policy
application, and step emission are all rule-based Python over the supplied
dataset, with no model calls of any kind. The challenge brief asks agents to
"keep behavior deterministic where possible"; this solution takes that to the
limit and reports zero usage honestly rather than fabricating model activity.

## What was used instead of model calls

- Request-intent classification: multilingual rule-based classifier
  (518/518 decided deterministically; 0 needed review).
- Media evidence (11 PNGs, 4 PDFs): local OCR/text extraction
  (tesseract, pdftotext) plus a conservative identifier-association policy,
  with provenance sidecars that cite the original evidence file.
- Identity resolution: exact matching on emails (including historical chains
  and their sha256 hashes), phone numbers, user ids, and log correlation keys.

## Optional measured model path

`code/model_assist.py` implements two optional assists on runtime inputs -
intent second opinions for requests the rules cannot classify, and structuring
of noisy OCR text - behind `MODEL_ASSIST_BACKEND`. With the default `none`
backend nothing is called and the usage log stays empty. The `gemini` backend
reads GEMINI_API_KEY from the environment only (a free-tier Google AI Studio
key, 250 requests/day at the time of writing, is sufficient because assists
fire only on uncertain inputs) and appends real per-call token counts from the
API response to `code/evaluation/usage_log.jsonl`; this report is then
regenerated from that log with per-model and overall totals. Policy decisions
never depend on model output either way.

No API keys, credentials, or sensitive configuration values are included in
this submission.
