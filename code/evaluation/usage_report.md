# Model usage and cost

## Full 518-request prediction run

| Provider | Model | Calls | Input tokens | Output tokens | Total tokens | Tokens/request | Total cost | Cost/request |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| None, deterministic execution | None | 0 | 0 | 0 | 0 | 0 | $0.00 | $0.00 |
| Overall | | 0 | 0 | 0 | 0 | 0 | $0.00 | $0.00 |

The prediction run uses Python rules, SQLite parsing, local Tesseract OCR and
pdftotext, not a hosted model. These are execution usage totals, not a claim
that no AI coding assistance was used during development. Development
assistant token counts are not available as a verified aggregate and are not
invented or included in the execution totals. Muse development reviews are separate; their usage totals are not available.

## Optional model path

`code/model_assist.py` has none, mock and gemini backends. The default is none.
The intent path can classify UNKNOWN requests; media and per-case verification
helpers are optional separate calls. A model's intent result can affect whether
deletion is authorized, so it is not described as universally advisory-only.
Verification annotations do not rewrite prediction rows.

Real Gemini calls read GEMINI_API_KEY from the environment and log API-returned
input/output token counts to `code/usage_log.jsonl`. `summarize_usage()` groups
these by model and excludes mock entries. Markdown totals are not automatically
regenerated. No key was used and the live Gemini API path has not been verified.
No paid calls are authorized; a free-looking key is not proof of zero-cost quota.
The account owner must confirm their project tier and limits before any call.

Offline pipeline tests pass 22/22. Mock tokens are synthetic, explicitly labeled,
and excluded from real usage and cost. No mock call is reported as a real model
call. No credentials or API keys are included.

## Optional verification safety follow-up

No real call was made for this follow-up. Empty/whitespace replies become
UNPARSED rather than aborting the batch. Plans over6000 serialized characters
are SKIPPED_OVERSIZE without sending partial JSON. Explicit zero, negative,
boolean or noninteger limits are rejected before reading the input. Omit the
limit to retain the manual verifier's previous all-rows mode. CLI counts skip
annotations separately from actually reviewed cases. The prediction CSV is
never rewritten by this helper. Missing keys still skip real calls.

The optional adapter still defaults to gemini-2.5-flash. Current provider docs
limit2.5 access to prior active users; a new project must check availability.
A current free-tier candidate is gemini-3.5-flash-lite, but no project-specific
free access or key was verified here. No model was silently switched on, and
nothing in this safety follow-up establishes challenge eligibility. Provider
free-service terms permit prompt/response use for product improvement and
human review; no private data should be sent.
