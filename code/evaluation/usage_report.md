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
regenerated. At the original checkpoint no key was used and the live Gemini path was
unverified; separate later tests are recorded below.
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

## Separate synthetic connectivity test, 25 October 2026

After the owner confirmed a free-tier Google key and explicitly approved one
synthetic sentence, a single request to gemini-3.5-flash-lite succeeded. The
payload was only "Please delete my account and all my personal data". It
returned explanatory text, not a project classification. Provider counts were
9 input tokens and 252 candidate-output tokens, 261 reported tokens total.
No dataset, names, private chat or media was sent. No billing or paid fallback
was enabled. Current provider pricing lists free input/output for this model
on the Free Tier; the owner confirmed that tier, but no independent project
billing dashboard was inspected. This test is separate from the final
518-request prediction run, whose hosted-model usage remains zero.

The earlier no-key/no-live-test statements describe the prior checkpoint.
The existing optional adapter default remains gemini-2.5-flash; the smoke test
selected gemini-3.5-flash-lite explicitly. Neither a connection test nor Muse
development reviews establish runtime AI participation in the final output or
challenge eligibility.


## Separate reviewed image extraction, 25 October 2026

One explicitly approved participant connector-console PNG was sent to Google
Gemini 3.5 Flash-Lite with the generic extraction prompt in code/vision_prompt.txt.
Provider counts: 1,251 input tokens (185 text, 1,066 image), 245 candidate-output
tokens, 1,496 total tokens. Two canonical connector/selector pairs matched the
actual image. Two descriptive row names returned as resource IDs were rejected.
An experimental replay reproduced the same full output, since independent
sources already cover those resources. That replay hook was not promoted:
visible-token membership and an editable review flag cannot establish row
ownership. The shipped helper only writes extraction output for inspection;
the prediction engine does not load it. The experiment does not establish improved sample accuracy or
AI-powered eligibility, and its tokens are not counted in the zero-call
518-request prediction table above. Source-specific cache content is not shipped.

Across these two separate real experiments: 2 calls, 1,260 input tokens,
497 candidate-output tokens, 1,757 provider-reported tokens. Both used the
owner-confirmed Free Tier and a model whose official pricing lists free input
and output. Estimated API charge is $0.00 under that tier; no billing dashboard
or invoice was inspected, no billing setting changed, and no paid fallback ran.
The exact source-to-cache extraction function was offline-mocked after the
approved live image request; the live request used the same prompt/schema/API
payload shape, not an earlier claim that the finished CLI had already run live.
