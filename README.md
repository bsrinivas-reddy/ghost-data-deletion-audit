# Ghost Data Deletion Audit

Deletion-audit engine for HackerRank's "Ghost Data Still Exists" challenge.
Reads participant-facing evidence, resolves identities, reconstructs resource
state at audit_at, applies policy and writes ordered findings and next steps.

This is a working but incomplete solution. Current sample status accuracy is
29/32; ordered sequences match 7/32. Read the evaluation report and generated
uncertainty report before relying on the output. No hidden-test result is known.

## Setup and run

Python 3.10+ with standard-library modules. Media extraction additionally
requires the `tesseract` and `pdftotext` executables (Debian/Ubuntu packages
`tesseract-ocr` and `poppler-utils`). Missing or empty extraction stops the run.

```sh
git clone https://github.com/interviewstreet/hackerrank-orchestrate-october26 /tmp/hr-challenge
ln -s /tmp/hr-challenge/dataset dataset
python3 code/main.py dataset output.csv
```

The first run extracts 15 PNG/PDF sources into an uncommitted cache. Later runs
reuse source-hash-matched extraction. No dataset or extracted corpus is bundled.
The output is 518 rows with header `case_id,deletion_status,steps_json`.
`output_uncertainty.md` identifies missing state evidence. INCOMPLETE is used
conservatively where UNKNOWN would be more precise; case_63 currently lacks a
supported finding, which is an unresolved output-contract limitation.

## Evaluation

```sh
python3 code/evaluation/main.py
python3 code/evaluation/custom_tests.py
python3 code/evaluation/test_model_assist.py
python3 code/evaluation/semantic_audit.py output.csv
```

The scorer prints metrics and does not rewrite Markdown reports. The validator
currently exits nonzero for the disclosed case_63 contract problem. It checks
structure and citation cutoffs, not complete semantic correctness.

## Layout

- `code/main.py`: prediction entry point and media-cache bootstrap
- `code/audit/`: evidence parsing, identities, intent, policy and step generation
- `code/extract_media.py`: local OCR/PDF extraction and conservative associations
- `code/evaluation/`: scorer, custom tests, validator and evaluation/usage reports
- `code/model_assist.py`: optional model backend, off by default

## Model usage

The shipped prediction run uses zero model calls and costs $0.00. AI-powered
eligibility is not established by that fact. Optional Gemini paths exist but
have not been live-tested; they require owner-confirmed free quota before use.
Intent assistance can affect an UNKNOWN request's classification. Verification
review is advisory. Actual returned tokens go to `code/usage_log.jsonl`; mock
entries are excluded from real totals. No automatic Markdown report generation
is claimed.

## Packaging

```sh
zip -r code.zip README.md code \
  -x '*/__pycache__/*' '*/extracted/*' '*/usage_log.jsonl' '*/.venv/*' '*/venv/*'
```

Upload code.zip, the generated output.csv, and the authentic root log.txt in
HackerRank's separate slots. The reports belong in `code/evaluation/` inside
code.zip. Do not bundle dataset/, caches, credentials or nested archives.
A reconstructed development summary is not represented as a complete per-turn
session log; missing history must be disclosed, never invented.
