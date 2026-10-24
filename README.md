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
