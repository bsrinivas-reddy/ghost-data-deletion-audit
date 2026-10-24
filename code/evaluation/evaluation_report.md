# Evaluation Report - Ghost Data Deletion Audit

All numbers are reproducible: `python3 code/main.py dataset output.csv`,
then `python3 code/evaluation/main.py` (sample metrics),
`python3 code/evaluation/semantic_audit.py` (spec-contract audit),
`python3 code/evaluation/custom_tests.py`, `python3 code/evaluation/test_model_assist.py`.

## 1. Sample-set accuracy (32 golden cases, dataset/sample_output.csv)

| Metric | Result |
|---|---|
| Case-level deletion-status accuracy | 32/32 = 100% |
| Step-level accuracy (field-exact step match) | 154/193 = 79.8% |
| Field-level accuracy | identical to step-level: a step counts only when every field matches |
| Sequence accuracy (full ordered match) | 9/32 = 28.1% |

The remaining step gap is dominated by one class: resources whose only trace
is a deletion-workflow claim in `system_activity.csv`. 16 of the 31
sample-missing resources have zero occurrences in any evidence file; most of
the rest occur only with all identifier fields explicitly null (anonymous
404 lookups, anonymized analytics profiles). See section 4 for the measured
investigation.

## 2. Independent semantic coverage audit (not golden-based)

`code/evaluation/semantic_audit.py` validates output.csv against the
challenge contract itself: row set/order, legal (operation, state) pairs,
phase/operation/system/resource ordering, citation rules (COMPLETE steps and
all findings must cite existing file/activity/audit ids; INCOMPLETE
remediation and future verification must be uncited), and full
remediation-plus-verification coverage of every finding.

Result: **518 rows, 0 problems.** (Its first run found 44 real defects -
findings and COMPLETE verifications whose only state proof sat in files
captured after `audit_at`; the engine now falls back to citing the truthful
state-establishing observation, and drops COMPLETE verifications it cannot
cite at all.)

## 3. Custom evaluation cases (participant-created)

`code/evaluation/custom_tests.py`: six synthetic datasets with known ground
truth run through the real engine. Result: 14/14 checks pass.

1. **T1 - shared-window claim isolation**: two users, overlapping deletion
   windows, one unattributed workflow claim: binds to neither case.
2. **T2 - lookalike-email decoy**: `smartinez6461.jr@...` does not bind to
   the `smartinez6461@...` case.
3. **T3 - 404 binding discipline**: a 404 lookup binds through its own
   `lookup_key`; another user's 404 in the same log does not leak in.
4. **T4 - temporal discipline**: evidence captured after `audit_at` cannot
   rewrite the state at `audit_at`.
5. **T5/T5b - claims are not state proof**: SUCCESS claim cannot override
   PRESENT evidence; FAILED claim cannot override 404 evidence.

`code/evaluation/test_model_assist.py` adds 6/6 checks for the optional
model pipeline (mock backend; no live calls).

## 4. Unattributable workflow resources - measured investigation

`system_activity.csv` contains 1,545 deletion-workflow claims. 928 of their
resources are tied to a person through identity-bearing evidence after the
full parse (SQL replicas, snapshot bundles, service exports, six log
syntaxes, media consoles, cross-resource references). The remaining 617:

- **453 occur in no evidence file at all** (238 accounts, 188 audit records,
  others) - the only trace is the workflow claim itself.
- **164 occur only in records with no identifiers** (anonymous 404
  profile lookups in service exports, analytics profiles with all identity
  fields explicitly null).

We investigated every source-supported assignment route:
- system_activity has no request/case id column; `details` texts are generic
  ("Deletion worker submitted primary profile X to account_service").
- request execution windows overlap heavily: a bare claim has a median of 4
  candidate cases (only 58/1,545 claims have exactly one).
- workflow bursts segmented at "submitted primary profile" markers mix
  multiple requests (e.g. one burst holds three cases' resources), and
  claims regularly land after the request's `reported_at`.
- the best temporal assignment we could construct (ordered unique-window
  matching) scored **0.04 precision** against golden ground truth.

Conclusion (unresolved, not a proven ceiling): we found no source-supported
link for these resources, and the measurable alternative (temporal
assignment) is wrong often enough to be unusable, so the engine excludes
them and decides each case from attributable evidence. On the sample set
this accounts for most of the remaining step gap; the golden answers appear
to use information not visible in participant-facing files. 0 of 518 cases
are decided with an empty footprint; every emitted status rests on cited
evidence. If a source-supported link for these resources is later found,
the engine can bind them without structural changes.

## 5. Full-dataset run (518 evaluation cases)

| Metric | Result |
|---|---|
| Rows produced | 518, schema- and semantic-audit clean |
| COMPLETE / INCOMPLETE / NOT_APPLICABLE | 168 / 340 / 10 |
| Run time | ~2 s core + one-time media extraction (~20 s), stdlib only |
| Identity-bound resources | 1,876 (was 849 before the log-syntax work) |

## 6. Failures found and improvements made

1. Four log syntaxes (cloud-runtime `message=` payloads, bracket, pipe,
   syslog) were invisible to the parser - a universal line normalizer fixed
   the largest coverage gap (bound resources 849 -> 1,726 overnight).
2. Identity extraction keyed on field names missed emails carried in
   `lookup_value` / `subject_reference` / `correlation_key` - replaced with
   value-classified extraction.
3. Findings and COMPLETE verifications could go uncited when the only state
   proof sat in a post-`audit_at` capture - fixed with truthful fallback
   citation; uncitable COMPLETE verifications are dropped. Admissibility was
   pinned empirically against the golden samples: all 75 golden manifest
   citations reference files captured at/before audit_at (so pre-audit
   captures are preferred for citation), while gating STATE on capture time
   drops golden step recall (a controlled experiment loses a dozen matched
   steps and two sequence-exact cases) - records whose own timestamp
   precedes audit_at belong to the state at audit_at even when their file
   was captured later. T7/T8 pin both directions.
4. JSON-payload structured logs parsed as key=value - dual-format reader.
5. Media extractor context windows false-bound neighbouring rows of
   multi-resource consoles - conservative same-line/single-resource policy.
6. Discovery gate used file capture time and dropped records existing at
   audit time - record-time discovery gate with capture-time citation gate.
7. Nested search-document identities missed - recursive identity walk.
8. Snapshot-bundle collection names unmapped - category mapping added.
9. Data-catalog LINK events treated as state evidence - binding-only now,
   with prior-lifecycle exclusion.
10. OCR-mangled resource ids (`data_flow.9846`) - separator-tolerant matching.
11. Historical email hashes - sha256 derived for every known email per the
    dataset's documented hash convention.
12. Clean-room gap: a fresh clone silently lost media evidence - main.py
    now self-bootstraps extraction; a fresh clone reproduces output.csv
    byte-identically (verified).
