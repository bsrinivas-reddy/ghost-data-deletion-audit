# Evaluation Report - Ghost Data Deletion Audit

All numbers below are produced by `python3 code/evaluation/main.py` (sample
metrics) and `python3 code/evaluation/custom_tests.py` (custom cases) against
the final engine that generated `output.csv`.

## 1. Sample-set accuracy (32 golden cases, dataset/sample_output.csv)

| Metric | Result |
|---|---|
| Case-level deletion-status accuracy | 32/32 = 100% |
| Step-level accuracy (field-exact step match) | 154/193 = 79.8% |
| Field-level accuracy | identical to step-level: a step only counts when every field (phase, system_id, resource_id, operation, state, evidence_id) matches |
| Sequence accuracy (full ordered match) | 9/32 = 28.1% |

The remaining step gap is dominated by one class: resources whose only trace
is a deletion-workflow claim in `system_activity.csv` (deleted accounts that
read 404, anonymized analytics profiles). They carry no identity in any
evidence file, so attributing them to a specific case would require guessing
from overlapping time windows. This engine does not guess (see section 4).

## 2. Custom evaluation cases (participant-created)

`code/evaluation/custom_tests.py` builds six synthetic datasets with known
ground truth and runs the real engine over them. Result: 12/12 checks pass.

1. **T1 - shared-window claim isolation**: two users with overlapping deletion
   windows; an unattributed workflow claim inside both windows binds to
   neither case, while identity-bound audit records bind correctly.
2. **T2 - lookalike-email decoy**: a record carrying
   `smartinez6461.jr@...` does not bind to the `smartinez6461@...` case and
   cannot flip its status.
3. **T3 - 404 binding discipline**: a 404 profile lookup binds through its own
   `lookup_key`; another user's unrelated 404 in the same log does not leak in.
4. **T4 - temporal discipline**: evidence captured after `audit_at` cannot
   rewrite the state at `audit_at`; violations visible only in post-audit
   captures produce no findings.
5. **T5/T5b - claims are not state proof**: a SUCCESS deletion claim cannot
   override PRESENT evidence (stays INCOMPLETE); a FAILED claim cannot
   override 404 evidence (stays COMPLETE).

## 3. Full-dataset run (518 evaluation cases)

| Metric | Result |
|---|---|
| Rows produced | 518 (one per request, schema-validated) |
| COMPLETE | 212 |
| INCOMPLETE | 296 |
| NOT_APPLICABLE (not deletion requests) | 10 |
| Run time | ~1 second, pure Python stdlib, no network |
| Deletion-workflow resources in system_activity | 1,545 |
| of which attributable through identity-bearing evidence | 752 |
| of which not attributable to any case | 793 (374 accounts, 196 audit records, 140 analytics, 45 others) |
| COMPLETE cases with an empty (unverifiable) footprint | 24 (4.6%) |

## 4. Known limitations (honest)

- **Unattributable workflow resources.** When a resource appears only in
  workflow claims and no identity-linked evidence ties it to a person,
  assigning it to a case would be inference from shared time windows, which
  produces false bindings (custom test T1 pins this). The engine excludes
  such resources and decides each case from attributable evidence. On the
  sample set this costs most of the remaining step accuracy; on the full set
  793 resources are affected. 24 cases therefore verify as COMPLETE with an
  empty footprint - these are the cases where the audit found no
  identity-linked data at all, which is also what a genuinely completed
  deletion looks like.
- **Media evidence quality.** PNG consoles are read with local OCR
  (tesseract); garbled text can hide a resource id. Association of
  identifiers to resources is deliberately conservative (same-line, or
  whole-document only when a single resource is present) to avoid false
  bindings from multi-resource screens.
- **Sample vs hidden set.** The 32 golden cases were used only to validate,
  never as input to the engine. No golden labels, case ids, or per-case
  constants are present in the code.

## 5. Failures found and improvements made

1. JSON-payload structured logs were parsed as key=value and silently dropped
   - added a dual-format line reader (found via missing audit records).
2. The media extractor's context window swept identifiers from neighbouring
   rows of multi-resource consoles, falsely binding two users' connectors -
   replaced with the conservative association policy above.
3. The discovery gate used evidence-file capture time and dropped records
   that existed at audit time (snapshots exported later) - discovery now
   gates on the record's own timestamp; citation still requires the file to
   have been captured by `audit_at`.
4. Identities nested inside search-document payloads were missed - identity
   extraction now recurses.
5. Snapshot-bundle collection names were unmapped, silently losing category
   and state for support/backup/connector records.
6. Data-catalog LINK events were treated as state evidence - they are now
   binding-only, and identity links older than the request no longer pull
   prior-lifecycle resources into the current footprint.
7. OCR-mangled resource ids (`data_flow.9846`) defeated exact id matching -
   the extractor normalizes separator noise.
8. Historical email changes had no explicit hash rows - sha256 hashes are now
   derived for every known email (the dataset's documented hash convention),
   which is what binds hash-correlated log lines to the right user.
