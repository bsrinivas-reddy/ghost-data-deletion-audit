# Evaluation report

Current result is a conservative, incomplete implementation, not a correctness guarantee.
No golden labels or per-case answers are used for prediction. Samples are read only by the scorer.

## Reproduce

```sh
python3 code/main.py dataset output.csv
python3 code/evaluation/main.py
python3 code/evaluation/custom_tests.py
python3 code/evaluation/test_model_assist.py
python3 code/evaluation/semantic_audit.py output.csv
```

## Sample metrics

32 published examples, compared with `dataset/sample_output.csv`:

| Metric | Result |
|---|---|
| Row coverage | 32/32 |
| Status accuracy | 28/32 (87.5%) |
| Exact six-field step matches | 143/197 (72.6%) |
| Full ordered step sequences | 7/32 (21.9%) |
| Position-aligned field accuracy | 684/1214 (56.3%) |

Step denominator sums the larger predicted/golden step count for each case.
Fields count the status plus six fields per aligned step (phase, system_id,
resource_id, operation, state, evidence_id); missing positions count as wrong.
Sequence comparison excludes object-key order and step_no; consecutive step_no
is checked separately. This is not hidden-test accuracy.

Sample cases 01, 02 and 04 have no identity-linked admissible footprint after
strict temporal filtering, so they are marked INCOMPLETE rather than guessing
COMPLETE. One additional sample status differs after independent-copy handling. The schema has no UNKNOWN value. This conservative mapping does not
satisfy the full finding/remediation contract when no violation can be proved.

## Full run

518 rows, 2,515 steps: 159 COMPLETE, 349 INCOMPLETE, 10 NOT_APPLICABLE.
The generated `output_uncertainty.md` records unresolved states.

The independent validator currently reports **one contract problem**:
case_63 is INCOMPLETE without a supported finding. It has an identity catalog
link to marketing_platform/marketing_001 but no state evidence under that
system. A screenshot shows marketing_001 under a different email and
marketing_service. That conflict is not silently resolved by conflating
systems or people. No remaining-data finding or remediation is invented.

The validator checks schema, sorted row coverage, legal operation/state pairs,
phase/operation/system/resource ordering, actual citation-ID existence,
citation cutoff, and remediation/verification coverage for findings. It is
not a semantic oracle: it does not independently reconstruct every footprint,
validate every extracted fact, or establish completeness of discovery.

## Participant-created regression cases

46 checks pass across the custom fixtures in `custom_tests.py`:

- T1: shared-window, unattributed workflow claims bind to neither user.
- T2: lookalike-email decoy does not bind.
- T3: 404 lookup binds through its own lookup key, not another user's trace.
- T4: post-audit capture cannot rewrite pre-audit exposure.
- T5/T5b: workflow success/failure does not override state evidence.
- T7: record observed after audit cutoff is excluded.
- T8: a late capture is excluded even with an earlier record timestamp.
- T9: future record timestamp is not clamped into the past.
- T10: empty evidence and a missing mandatory retained record do not certify COMPLETE.
- T11: future identity snapshot/change cannot bind resources.
- T12: nested operational history uses its own system, result and record time.
- T13: unavailable OCR raises instead of silently omitting media.
- T14: catalog document alias links artifact state; a future alias cannot bind it early.
- T15: a clean primary does not hide a residual replica; all observed copies must comply.
- T16: an empty scoped table proves absence only for that store and service.
- T17: retention is checked at audit time; expiry does not invent a missing default rule.
- T18: a reused email is ambiguous, not forcibly assigned.
- T19: resource reuse and actor/agent identifiers cannot import another person's data.
- T20: negation, mixed authorization, access-only requests and prior retention remain distinct.
- T21: redacted headers do not hide an email in retained text; missing process
  booleans are UNKNOWN rather than automatically disabled or blocked.
- T22: inactive legal holds and changed supplied policy actions cannot silently
  reuse the old category constants.
- T23: malformed JSON plan shapes fail validation without a validator crash.
- T24: an absent mandatory tombstone is not certified as redacted or given an
  invented recovery operation.

Fault injection: collapsing store IDs makes T15 fail; removing the identity cutoff
makes T11 fail; removing retention expiry checks makes T17 fail. Disabling scope
filtering also fails the suite. Restored source passes after each mutation.

Optional model-path mock tests: 6/6. These are pipeline tests, not live model calls.

## Failures found and changes made

1. Added parsers for plain, JSON, cloud-message, bracket, pipe and syslog logs.
2. Classified identifier values and nested payloads rather than trusting only field names.
3. Removed post-audit evidence fallback and timestamp clamping. Both record time
   and file capture must be at/before audit_at. Earlier reports claiming late
   captures were admissible were wrong and are superseded by this report.
4. Separated identity links and workflow claims from state proof.
5. Used same-line identity association in multi-resource media to avoid linking
   neighboring rows. Single-resource documents can associate dispersed fields.
6. Parsed nested operational_record_history rows using their own system,
   record_type, result and recorded_at, rather than the container's service.
7. Mapped ticket attachments and retained order collections to their policy categories.
8. Enforced as-of identity availability and excluded ambiguous email ownership.
9. Added catalog aliases for document references, object filenames and retained
   reference registries. Artifact text supplies state, catalog supplies membership.
10. Added fail-closed uncertainty for missing state, unsupported categories,
    missing mandatory retention and missing verification citations.
11. Media caches include source hashes; changed corpora are re-extracted. Missing
    OCR dependencies or empty extraction are errors, not empty successful runs.
12. Validator now checks real activity/audit IDs and post-cutoff citations.
13. Reconstructed latest state per physical store; added scoped empty-table captures.
14. Removed the unsupported prior-closed-cycle footprint exclusion. A prior
    compliant observation is not proof that a retained resource left scope.
15. Added actor/subject-role guards and cross-owner resource reuse uncertainty.
16. Added conservative negation/mixed-intent handling without case/template labels.
17. Checked retained message content for direct email/phone exposure, not only
    header fields. Exact embedded emails remain discoverable subject anchors.
18. Missing enabled/restore_allowed fields are uncertainty, not assumed safety.
19. Checked inactive hold flags and supplied policy actions; unsupported changes
    are explicit uncertainty rather than silent default treatment.
20. Validator checks exact field names/types and operation-to-phase placement.
21. Preservation/redaction categories require the preserved record, not absence;
    unsupported recovery is reported as uncertainty.

## Limits and next work

- Some workflow resources have no source-supported subject link. They remain
  excluded rather than assigned by execution windows or golden labels. This is
  an unresolved coverage gap, not a proven information ceiling.
- SQL copies retain stable primary/replica names, not per-snapshot identities.
  State is latest within each copy and residual copies defeat completion.
  Non-SQL service evidence is service-level and does not prove every SQL replica
  changed state. Stronger explicit copy-link provenance remains useful.
- SQL absence uses actual snapshot_scope, table/store and per-service time;
  empty unscoped tables are not proof. A capture cannot invent a new missing
  copy when the resource was only observed in a different store.
- Retention timestamps are preserved and expiry is checked. Missing conditional
  policy outcomes remain uncertainty, not an invented delete/default rule.
- OCR association is conservative and may miss facts. Tombstone clean-state
  inference from visible registry fields needs further adversarial review.
- The deterministic intent classifier is a phrase matcher; ambiguous requests
  and mixed non-deletion/deletion instructions need stronger handling.
- The primary run has zero model calls. Whether that meets the challenge's
  AI-powered requirement is not established by these metrics.
- Muse independent review is still pending at the time of this report. No
  final external-review verdict has been received.
- Transcript history is separate from prediction quality; no complete authentic
  development log or submission-compliance claim is made here.

## Research basis

The challenge contract remains authoritative for task semantics. These sources
informed the design, not hidden labels or extra output operations:

- https://martinfowler.com/articles/bitemporal-history.html: distinguish actual
  event time from knowledge/record time; both are gated in this audit.
- https://lunadong.com/publication/tempoRL_vldb.pdf: identity attributes change
  over time; ambiguity and as-of provenance matter.
- https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/individual-rights/right-to-erasure:
  backups can be retained beyond use; the rules CSV determines BLOCK_RESTORE.
- https://platform.openai.com/docs/guides/structured-outputs: schema-constrained
  extraction controls format, not factual correctness. Model output would still
  require source checks and deterministic policy/order emission.

These sources do not establish a globally best architecture or competition rank.
