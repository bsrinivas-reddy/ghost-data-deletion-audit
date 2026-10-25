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
| Status accuracy | 29/32 (90.6%) |
| Exact six-field step matches | 153/197 (77.7%) |
| Full ordered step sequences | 7/32 (21.9%) |
| Position-aligned field accuracy | 786/1214 (64.7%) |

Step denominator sums the larger predicted/golden step count for each case.
Fields count the status plus six fields per aligned step (phase, system_id,
resource_id, operation, state, evidence_id); missing positions count as wrong.
Sequence comparison excludes object-key order and step_no; consecutive step_no
is checked separately. This is not hidden-test accuracy.

Sample cases 01, 02 and 04 have no identity-linked admissible footprint after
strict temporal filtering, so they are marked INCOMPLETE rather than guessing
COMPLETE. The schema has no UNKNOWN value. This conservative mapping does not
satisfy the full finding/remediation contract when no violation can be proved.

## Full run

518 rows, 2,623 steps: 158 COMPLETE, 350 INCOMPLETE, 10 NOT_APPLICABLE.
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

303 checks pass across the custom fixtures in `custom_tests.py`:

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
- T25: concurrent services sharing a trace ID cannot exchange lookup identities.
- T26: nonempty search hits prove presence even when no result label is supplied.
  This test failed before the fix and passes after it.
- T27: log redaction markers do not hide remaining body/header identifiers;
  embedded emails can anchor retained-message discovery.
- T28: body-PII and clean controls exercise all six supported log syntaxes.

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
22. Log correlation keys include the service as well as trace ID; start attributes
    are preserved for per-record retention checks.

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
- Muse reviewed the older build and judged it unsuitable as proof of deletion.
  Its independently confirmed defects included the timestamp clamp, retained-body
  PII, unmapped categories, zero-proof COMPLETEs and weak evaluation checks, all
  now corrected. Its additional search-hits inversion was reproduced with a
  failing test and fixed. A golden-only analytics DELETE suggestion was not
  adopted because the category policy requires ANONYMIZE and no general
  source-backed exception was established. Muse has not re-reviewed this head.
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

## Independent review follow-through

Muse's saved review was recovered on 2026-10-25 after the original browser
session ended. No raw development trace or unrelated history is bundled.
The review is evidence about the old code, not approval of the current code.
Search exports with hits.total/documents and no result label were wrongly
classified ABSENT. The parser now honors explicit hit payloads; an unrecognized
payload remains UNKNOWN, not assumed absent. This changed one full-run status
and added supported findings. Citation fallback no longer exists; scoped
absence is reconstructed explicitly and cannot use unscoped empty tables.

## Retained-message log review

The body-PII correction originally covered JSON/SQL record readers but missed
log readbacks. A redaction marker anywhere in a log message previously certified
it clean despite a remaining email or requester header. Log identity extraction
also missed embedded content emails. Six synthetic counterexamples/controls and
twelve syntax-path checks cover the correction. The initial four-case regression
failed three checks before the fix. With the expanded fixture, removing the
state correction fails four checks; removing embedded-email discovery fails two.
Plain, bracket, pipe, syslog, JSON and cloud-runtime log variants are exercised.
The full current corpus output is unchanged by this correction. No final-head
Muse review has been run after the old-build review described above.

## Follow-up independent review

Muse reviewed the retained-message log patch with its connected helper and tests.
A proposed missing prerequisite was not applicable: the content scan was already
in the patch base. A conflicting explicit subject test also disproved the
proposed cross-owner binding: user_2 plus user_1's email in text does not bind
user_1 because the engine rejects conflicting stable subjects. The review did
find a real detector precedence gap: matched_value plus a redaction marker
returned CLEAN. An additional regression failed before a guard was added and
passes after. Full-corpus output remains unchanged. Earlier claims about
UNKNOWN generating proved violations refer to older code, not this head.

Open, preexisting limits include empty/plain messages being treated as exposed,
noncanonical phone formats, started-record context carried into completion,
nested/prose log shapes and other text keys. These have not been established as
current-corpus failures. No overall correctness approval is claimed.

## Log subject-role isolation

A separate synthetic lookup showed that actor_email could bind an unowned
account resource to the operator's deletion case. The log identity sweep now
uses the same actor_, agent_, assignee_ and operator_ exclusions as structured
record parsing. T29 checks email, stable-ID and hash values under all four
roles, genuine lookup-key controls, end-to-end ownership and all six log
syntaxes. Its initial fourteen assertions failed before the change. Removing
the two-line guard fails all twenty expanded assertions. The current full-run
CSV is unchanged. Nested identity objects and bare role keys are outside this
specific prefix guard; they are not claimed covered by this regression.

## Operator-role review follow-through

Muse's bounded review confirmed the scalar snake_case guard and identified weak
end-to-end assertions. Those now check INCOMPLETE status and exact resource
membership, not just empty plans. T30 exercises both identity-reader consumers:
paired start/completion and scan events. Removing the guard fails both tests,
as well as the twenty T29 assertions.

The guard's precise scope is lowercase scalar keys beginning actor_, agent_,
assignee_ or operator_. Mixed-case, camelCase, hyphenated or bare role keys,
quoted role information inside body text, and detector hits with no trustworthy
subject role remain unhandled. Actor-only self-service records cannot establish
subject ownership without additional evidence. No phone-role guarantee is
claimed: prefixed phone fields were not in the old phone reader. These limits
are not repaired by treating a role spelling heuristic as proof of ownership.

## Explicit lookup-resource agreement

A new synthetic same-service/same-trace lookup start for account_1 followed by a
completion for account_2 imported account_1's subject into account_2. The parser
now discards start context only when both resource IDs are supplied and differ.
The completion's own identity/state remains usable, matching IDs still inherit
the lookup subject, and a start lacking a resource ID retains trace correlation.
T31 covers these four paths. T32 checks final case ownership and later trace
reuse. Removing the guard fails two parser checks and the end-to-end check.
The corpus contains 572 starts and 983 completed read events but no explicit
start/completion resource mismatches; full output is unchanged. Missing IDs,
same-resource concurrent reuse, event-family mismatch and untrusted start
context are not resolved by this narrow agreement check.

## Lookup-agreement review follow-through

Muse verified the parser counterexamples in an isolated harness, not the full
engine. Its assertion-strength findings were addressed: T32's Bob check names
the resource instead of assuming an empty plan, and T33 checks completion
attributes and discarded start lookup_key through all six log syntaxes.
The corpus has 564 matched start/completion pairs: 264 carry both resource IDs
and 300 have no start ID. The zero explicit mismatches statistic applies to the
264 both-ID pairs, not all events. ID-less-start correlation stays unchanged;
this guard does not prove those 300 pairs correct. Raw ID comparison is kept,
not separator/case normalization without evidence of equivalent identifiers.
No overall-engine correctness approval follows from this bounded review.

## Category-address conflict experiment (not promoted at this report checkpoint)

The engine groups state by system_id/resource_id. Nine corpus addresses carry
both SUPPORT_MESSAGE and SUPPORT_ATTACHMENT observations. After capture and
audit gates, only case_34 has both categories admissible; its plan otherwise
uses a later message label to shadow an attachment obligation. A synthetic
retained-message plus attachment pair also produces a DELETE on an address
that may refer to the retained message. The output schema has no category or
component field, and the supplied policy has no precedence rule for this clash.

The isolated experiment records conflicting policy categories as uncertainty
and emits no guessed treatment for that address. T34 fails without this guard;
T35 covers same-category, later-captured and different-address controls. Current
experiment changes only case_34, removing three support_9538 steps while keeping
its supported account finding. Status counts stay unchanged, step count falls
to 2,620, and the validator still reports only case_63. This deliberately leaves
an incomplete remediation plan rather than inventing destructive treatment.
The public checkpoint remains unchanged pending independent review.

## Category-conflict review follow-through (still isolated)

Muse's code review identified two over-triggers: claims counted as state
categories, and different categories with equivalent operations conflicted.
The experiment now compares distinct operation tuples from non-claim/non-BIND
evidence. T36 checks same-treatment categories, claim disagreement and an
unrelated resource in the same case. Sequential category changes remain
uncertain without evidence of reclassification rather than coexisting records.

A direct pixel inspection of account_admin_console_20260926.png showed that
support_9538 is a customer-details ticket reference and activity label, not
visible message content. The media extractor currently infers message category
and PRESENT from that resource prefix. This provenance issue must be resolved
before interpreting the case_34 conflict as two authoritative state categories.
No category experiment has been promoted as of this checkpoint.

## Media reference correction (isolated, review pending)

Actual pixels distinguish the account console's support-ticket references from
the dedicated support console's conversation table. PNG support mentions now
supply BIND only unless a single support ID appears in a conversation/message
view. This is a conservative text-layout heuristic, not proof for every UI.
PDF attachment handling is unchanged. Cached OCR text is reparsed each run so
parser edits cannot leave stale inferred records. T37 reference counterexamples
fail before the change; a conversation control remains state-bearing. T38
seeds stale records under a matching source hash and confirms reparsing without
OCR. A fresh extraction of all 15 sources matches the reparsed cache exactly.

The combined local experiment changes only case_34 versus public d0964c2:
support_9538 is treated using attachment-scan evidence_01, not message-state
inferred from a customer-console reference. It now calls for deleting the
attachment rather than redacting a conversation. Full counts and 2,623 steps,
sample metrics, and known case_63 validator limit stay unchanged. The generic
conflict guard no longer triggers on this case because references are BIND.
Public promotion remains held pending independent review of this media rule.

## Media review follow-through (isolated)

Muse found the first word gate could accept UI chrome and reject plural labels;
PDF extension alone also mislabeled transcripts as attachments. The revised
experiment requires a Sender plus Message/Content/Text table-header signal for
a single support ID, or PDF attachment-properties evidence for attachment type.
Bare references stay BIND. T39 exercises chrome, plural tables, PDF transcripts,
PDF references, attachment properties, multiple IDs and identifier preservation.

Cached text is now reparsed at World._media_obs, not rewritten in main. Both
the CLI and direct World callers see current parser rules, without repeated
non-atomic cache writes. T38 and T40 fail when stale stored records are used.
Main treats non-string/empty cached text as requiring fresh extraction. This
remains a conservative layout heuristic: multi-ticket views, non-English table
headers and unstructured explicit-state references are not fully supported.
Only case_34 differs from the public checkpoint, with the same status/step totals.
Independent review covered the prior version; these corrections need final review.

## Final media-review corrections

Final review identified multi-ID PDF properties, simultaneous conversation and
attachment signals, empty tables and same-line button chrome as overclaims.
The rule now requires a single support ID, Time/Date plus Sender and content
column in a header, and a following nonempty row. Simultaneous conversation and
attachment signals stay BIND. T41 covers all four reviewed counterexamples.
T42 checks a genuine conversation still produces REDACT through the reader and
text-less caches give a clear extraction-regeneration error. Stored inferred
records are not used as fallback because that would revive stale-state claims.

This remains a layout heuristic, not proof for arbitrary UIs. An unrelated
well-formed table in a ticket document can still be mistaken for a conversation;
non-English headers and multi-ticket views can be omitted. Those limits are
not turned into guessed COMPLETE or unsupported destructive treatment.

## Final checkpoint interpretation

The review iterations above describe isolated intermediate versions. The final
rule keeps ticket references as BIND, uses support-table and attachment-property
signals for state/category, and leaves incompatible evidence treatments as
explicit uncertainty. A damaged time-column header can still qualify only when
a sender/content header has at least two nearby timestamped rows. This handles
OCR damage without hardcoding a source ID, person or case. T43 checks zero, one
and two rows; removing this fallback fails the two-row test.

The final full run changes only case_34 versus d0964c2, with the three support
operations now DELETE-family from direct attachment-scan evidence_01 rather
than REDACT-family inferred from a screenshot ticket reference. Counts remain
158 COMPLETE, 350 INCOMPLETE, 10 NOT_APPLICABLE and 2,623 steps. The independent
validator reports the one case_63 limitation described above. Sample metrics
are unchanged. Sidecar stored records are not authoritative; every media reader
reinterprets the cached OCR text. All 127 custom and six mock model checks pass.

Remaining media limits include unrelated sender/content tables, multilingual
headers, multiple-ticket views, OCR toolchain freshness and unstructured names
or phone formats. The last independent review's concrete overclaims have
counterexamples and corrections; the timestamp-row fallback received local
code review and mutation testing, not another independent review verdict.

## Account lookup error isolation

A JSON account lookup without a profile payload, including a null profile with
status_code 500, was treated as ABSENT. The parser now requires status_code 404
before a null/missing profile proves absence; other such payloads are UNKNOWN.
All 47 corpus account-export lookups supply profile and status_code fields, so
the full output is unchanged. The fixture helper now emits this actual source
shape. T44's missing/error checks fail before the fix; explicit 404 and present
profile controls remain valid. The subsequent review and publication are recorded below.

## Account lookup review follow-through

Muse found no production expansion needed for the reproduced null/error defect,
but identified missing end-to-end and boundary assertions plus a fixture bug.
T44 now covers string 404, null success, contradictory present/404, 410 and empty
profile. T45 proves a member lookup error yields INCOMPLETE without invented
findings/remediation and that the fixture preserves an empty profile dict.
Removing the guard fails four parser checks and the end-to-end verdict check.

The accepted status vocabulary remains explicit 404 only. No supplied export
contains an error field contradicting that shape; 410 is not guessed equivalent.
UNKNOWN can supersede earlier state and remove a proved plan in favor of
uncertainty. That existing engine behavior is not changed in this narrow fix.
Log rows=0/status-error contradictions remain a separate path to investigate.
Full corpus output remains byte-identical to 157ba45. All 138 custom and six
mock checks pass; no live runtime-model call is claimed.

## Failed HTTP readback isolation

An explicit failed HTTP read could prove absence from rows=0 or a not-found
result, retention from positive rows/event_code, or compliant flow/restore
flags. A guard before all category branches now returns UNKNOWN for explicit
statuses other than bare 2xx or 404. Missing status retains the existing format
semantics. The 983 participant read events comprise 328 HTTP200,138 HTTP404 and
517 statusless entries; none contains the synthetic contradiction. Predictions
are byte-identical to 31444aa. This is counterexample hardening, not a claim that
the corpus contained failed reads misclassified as deletion proof.

T46 tests six categories, isolated result/flow/restore/retention flags, typed
statuses and strict status syntax. T47 tests both state-reader consumers, a
paired start/completion, subject preservation and a resource-specific final
verification step so the uncertainty check cannot pass on an empty footprint.
T48 tests six log syntaxes plus JSON integer/null status normalization.
210 custom checks and six mock checks pass. Removing the guard fails 65 checks.

Muse identified real test gaps and a latent non-string TypeError, all reproduced
and corrected. Today the normalizers emit strings; str() also makes direct
integer/null helper inputs fail closed. No live model inference was added.

Explicit errors replace state proof with uncertainty, even when flags or PII
are present. Later errors may supersede earlier proof or plans; later valid
reads can recover state. Existing same-time ordering and 404 precedence are
unchanged: most categories treat404 as absent, while security rows/event_code
can still establish retention. The corpus does not establish contradictory404
field semantics, so those cases are not silently reinterpreted here. Bare2xx
(including204/206) are accepted; reason phrases/padded codes are UNKNOWN. These
are parser status rules, not a claim that every remote HTTP2xx proves complete
business semantics outside the supplied read format.

## Optional verifier safety (offline)

Reproduced empty-response IndexError, oversized-plan partial JSON submission
and explicit zero-limit unlimited review. The helper now marks empty responses
UNPARSED, skips oversized plans without a call and rejects invalid explicit
limits. Muse confirmed these defects and identified missing boundary/consumer
tests; those were added, along with a CLI fix that excludes skipped plans from
reviewed counts. All210 custom and22 offline model-path checks pass. Individual
mutations of size/limit guards, bool/type clauses, exact6000 boundary and CLI
skip count fail their tests. No real model calls, key requests or paid usage
were made. Full prediction output is byte-identical to ca008a5. This is not a
runtime AI integration or eligibility claim.

## Exact and nested role-attribution isolation

Scalar exact role fields (actor,agent,assignee,operator), nested prefixed role
objects and role-subtree source_resource_id links could contribute staff
identities or resource references to customer membership. JSON scalar sweeps,
nested recursion, reference walking and the log scalar sibling now apply the
same lowercase exact/prefix boundary. State inference is not changed.

T49-T51 cover root and deeper dict/list role objects, actual subject controls,
exact scalars in both JSON and logs, reference binding and mixed subject/actor
verdicts.248 custom and22 offline checks pass; full predictions are unchanged.
Independent mutations fail6 outer-recursion,8 inner-recursion,4 JSON-scalar,
4 log-scalar and11 reference checks. A root-only inner-mutation check initially
had no failures; deeper container tests exposed that coverage gap and closed it.

Muse's initial exact-scalar/reference findings were reproduced and corrected;
its final review found no new defect in this scope. No supplied JSON has the
nested role-prefix shape; this is synthetic hardening, not a newly observed
corpus correction. Uppercase, hyphenated/plural keys, generic role-value fields
and actor mentions inside unstructured body/media text remain outside this
key-based scope. No perfect ownership-resolution claim is made.

## Typed export availability boundary

The service-export parser used truthiness for download_available, turning
explicit null/zero/empty into absence proof. Only actual JSON booleans now map
to PRESENT/ABSENT; other explicit values become UNKNOWN. Missing flags retain
the existing PRESENT default. All9 corpus export entries omit this flag, so
predictions are unchanged. This is synthetic hardening, not a corpus defect.

T52 tests missing/null/boolean/empty/string/numeric boundaries and a nonvacuous
engine verdict for an identity-linked unknown export.258 custom and22 offline
checks pass. True-equality and False-equality mutations fail2 and1 checks.
Muse's required true-side numeric controls were added. The log sibling already
uses textual flags and does not have this truthiness path.

The preexisting explicit False-to-ABSENT premise is preserved, not independently
proved: download unavailability can differ from object deletion in other
systems. No supplied export uses the flag, so no invented producer rule is
used to expand this fix. UNKNOWN can replace an actionable plan with uncertainty;
that remains preferable to invented proof. Runtime model calls remain zero.

## Download denial is not export deletion proof

The preceding typed-flag section preserved explicit False-to-ABSENT as a
preexisting premise. Further participant-source inspection refutes it:
customer_export_jobs_20260914.json lists an expired export with filename and
included sections while download_available is false. USER_EXPORT policy is
Always DELETE, not disable downloads. Service-export False and log false flags
now produce UNKNOWN rather than deletion proof. Genuine not-found result,
HTTP404 or zero-row proofs remain unchanged. Missing/true flag behavior stays.

T53 covers both textual flag names, JSON final verdict with an uncited bound
resource check, and preservation of independent absence signals.266 custom and
22 offline checks pass. Restoring the JSON false-absence mapping fails2 checks;
restoring the log mapping fails2. Muse confirmed the source-grounded correction.
The9 service exports omit this flag and13 export log reads are available=true,
so full predictions are unchanged. The actual false listing already used the
records path and was PRESENT before and after. No hidden answers were used.
Unknown downloadability can remove a plan in favor of uncertainty; it cannot
prove deletion. This corrects the prior premise, not a new corpus accuracy claim.


## Source-grounded media follow-up, 25 October 2026

The search-console image contains a real detail panel, a neighboring result and
unrelated activity. Earlier OCR missed space-separated resource IDs and the
single-recognized-resource rule swept every identity from the page. The new
parser removes whole-document identity inheritance, recognizes horizontal OCR
separators, scopes labeled raw-document values and excludes recognized activity
blocks. An explicitly headed PDF customer-request table can associate its exact
Detail values with its unique stated reference without inheriting unrelated
pages/products. Unsupported layouts can still lose recall, and arbitrary OCR
heading corruption is not solved. Single-resource state inference remains a
separate known heuristic, not a proof of full document semantics.

298 custom checks pass at this follow-up, including real-reader subject/decoy
plans and base-failing counterexamples for activity, label conflicts and scope.
All 15 media sources were regenerated during testing. Full output and sample
metrics remain unchanged: 29/32 statuses, 153/197 exact steps, 7/32 sequences,
786/1214 aligned fields. Missing sample01/02/04 raw identity evidence and case63
remain unresolved. The separate vision extraction helper has six offline API-contract tests;
one source-reviewed live experiment was performed
and is reported separately in usage_report.md, not counted as final inference.


## Current media state excludes explicit history, 25 October 2026

A single resource previously inherited state words from the whole page,
including Activity/History. A generic counterexample with a currently present
search resource and a historical deletion could therefore certify absence.
State inference now stops at explicit section boundaries, and history-only
resource mentions produce no observation. An explicit Raw document panel
restores current scope after history. T55 tests parser and real-reader audit
behavior. The base fails the absence, history-only and false-COMPLETE checks.
303 custom,22 offline model-path and6 extraction-helper checks pass. All518
output rows and prior sample metrics remain byte-identical to be0a51a.
This does not solve unknown OCR layouts or all natural-language state ambiguity.
