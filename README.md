# Ghost Data Deletion Audit

Deterministic deletion-audit engine for the HackerRank "Ghost Data Still Exists"
challenge (orchestrate-october26).

For each deletion request it reconstructs the user's data footprint from the
evidence corpus (SQL dumps, JSON exports/snapshots, logs, documents), derives
each resource's state at the case's audit time, applies the deletion policy
rules, and writes `output.csv` with `case_id,deletion_status,steps_json`.

## Layout

- `code/main.py` - run the audit over `dataset/`, writes `output.csv`
- `code/audit/` - engine: parsers, identity resolution, request intent,
  workflow-claim binding, state reconstruction, policy, step emission
- `code/evaluation/main.py` - scorer against `sample_output.csv` (32 golden)
- `AGENTS.md`, `problem_statement.md` - challenge docs (from challenge repo)

## Run

```bash
# 1. get the dataset (not committed here)
git clone https://github.com/interviewstreet/hackerrank-orchestrate-october26 /tmp/hr-challenge
ln -s /tmp/hr-challenge/dataset dataset

# 2. run the audit
python3 code/main.py            # writes output.csv

# 3. score against the 32 golden samples
python3 code/evaluation/main.py
```

No external APIs, accounts, or keys required. Pure Python 3 standard library.

## Status

Working deterministic core. Sample-set validation is in progress; current
scores and known limitations are tracked in `code/evaluation/evaluation_report.md`.

## Optional model-assisted pass

The deterministic engine decides every input on its own. `code/model_assist.py`
adds two optional, measured assists on runtime inputs only: a second opinion
for request texts the rule-based classifier cannot decide, and structuring of
noisy OCR text. Both are off by default (`MODEL_ASSIST_BACKEND=none`) and
policy decisions never depend on model output.

    export GEMINI_API_KEY=...        # free Google AI Studio tier is sufficient
    MODEL_ASSIST_BACKEND=gemini python3 code/main.py dataset output.csv
    python3 code/model_assist.py verify output.csv gemini 518   # advisory review pass

Real per-call token counts from the API response land in
`code/evaluation/usage_log.jsonl`, and `code/evaluation/usage_report.md` is
regenerated from that log (the committed copy documents the zero-usage
deterministic run that produced this output.csv).

## Evaluation

    python3 code/evaluation/main.py              # golden-sample metrics
    python3 code/evaluation/semantic_audit.py    # independent spec-contract audit (0 problems)
    python3 code/evaluation/custom_tests.py      # participant-created cases (12/12)
    python3 code/evaluation/test_model_assist.py # mock-backend pipeline tests (6/6)

## Submission packaging

    zip -r code.zip code README.md          # source + evaluation reports
    python3 code/main.py dataset output.csv # the output to upload
    # log.txt: capture from your own authorized run/session
