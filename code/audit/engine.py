"""Deletion-audit engine: reconstruct state at audit_at, apply policy, emit steps."""
import csv, json, os, sys
from dataclasses import replace
from .model import *
from . import parsers, logparsers, activity, identity, intent

# Operation order within each phase (problem-statement table order)
FINDING_ORDER = ["REPORT_REMAINING_RECORD", "REPORT_EXPOSED_PII",
                 "REPORT_ACTIVE_DATA_FLOW", "REPORT_RESTORE_RISK"]
REMEDIATION_ORDER = ["DISABLE_DATA_FLOW", "BLOCK_RESTORE", "DELETE_RECORD",
                     "REDACT_RECORD", "ANONYMIZE_RECORD"]
VERIFICATION_ORDER = ["VERIFY_RECORD_ABSENT", "VERIFY_RECORD_PRESENT",
                      "VERIFY_RECORD_REDACTED", "VERIFY_RECORD_ANONYMIZED",
                      "VERIFY_DATA_FLOW_DISABLED", "VERIFY_RESTORE_BLOCKED"]

COMPLIANT = {  # category -> (set of compliant states, verification op, remediation op, finding op)
    CAT_PROFILE:    ({ABSENT}, "VERIFY_RECORD_ABSENT", "DELETE_RECORD", "REPORT_REMAINING_RECORD"),
    CAT_SECONDARY:  ({ABSENT}, "VERIFY_RECORD_ABSENT", "DELETE_RECORD", "REPORT_REMAINING_RECORD"),
    CAT_SEARCH:     ({ABSENT}, "VERIFY_RECORD_ABSENT", "DELETE_RECORD", "REPORT_REMAINING_RECORD"),
    CAT_CACHE:      ({ABSENT}, "VERIFY_RECORD_ABSENT", "DELETE_RECORD", "REPORT_REMAINING_RECORD"),
    CAT_SUPPORT_ATT:({ABSENT}, "VERIFY_RECORD_ABSENT", "DELETE_RECORD", "REPORT_REMAINING_RECORD"),
    CAT_EXPORT:     ({ABSENT}, "VERIFY_RECORD_ABSENT", "DELETE_RECORD", "REPORT_REMAINING_RECORD"),
    CAT_MARKETING:  ({ABSENT}, "VERIFY_RECORD_ABSENT", "DELETE_RECORD", "REPORT_REMAINING_RECORD"),
    CAT_SUPPORT_MSG:({CLEAN, ABSENT}, "VERIFY_RECORD_REDACTED", "REDACT_RECORD", "REPORT_EXPOSED_PII"),
    CAT_EMAILLOG:   ({CLEAN, ABSENT}, "VERIFY_RECORD_REDACTED", "REDACT_RECORD", "REPORT_EXPOSED_PII"),
    CAT_TOMBSTONE:  ({CLEAN, ABSENT}, "VERIFY_RECORD_REDACTED", "REDACT_RECORD", "REPORT_EXPOSED_PII"),
    CAT_ANALYTICS:  ({ANONYMIZED, ABSENT}, "VERIFY_RECORD_ANONYMIZED", "ANONYMIZE_RECORD", "REPORT_EXPOSED_PII"),
    CAT_TELEMETRY:  ({ANONYMIZED, ABSENT}, "VERIFY_RECORD_ANONYMIZED", "ANONYMIZE_RECORD", "REPORT_EXPOSED_PII"),
    CAT_SECURITY:   ({RETAINED}, "VERIFY_RECORD_PRESENT", None, None),
    CAT_LEGAL:      ({RETAINED}, "VERIFY_RECORD_PRESENT", None, None),
    CAT_DATAFLOW:   ({DISABLED, ABSENT}, "VERIFY_DATA_FLOW_DISABLED", "DISABLE_DATA_FLOW", "REPORT_ACTIVE_DATA_FLOW"),
    CAT_BACKUP:     ({BLOCKED, ABSENT}, "VERIFY_RESTORE_BLOCKED", "BLOCK_RESTORE", "REPORT_RESTORE_RISK"),
}
VERIFY_STATE = {"VERIFY_RECORD_ABSENT": "ABSENT", "VERIFY_RECORD_PRESENT": "PRESENT",
                "VERIFY_RECORD_REDACTED": "REDACTED", "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED",
                "VERIFY_DATA_FLOW_DISABLED": "DISABLED", "VERIFY_RESTORE_BLOCKED": "BLOCKED"}
REM_STATE = {"DISABLE_DATA_FLOW": "DISABLED", "BLOCK_RESTORE": "BLOCKED",
             "DELETE_RECORD": "ABSENT", "REDACT_RECORD": "REDACTED",
             "ANONYMIZE_RECORD": "ANONYMIZED"}
FIND_STATE = {"REPORT_REMAINING_RECORD": "PRESENT", "REPORT_EXPOSED_PII": "PRESENT",
              "REPORT_ACTIVE_DATA_FLOW": "ACTIVE", "REPORT_RESTORE_RISK": "ACTIVE"}

class World:
    def __init__(self, ds, extracted_dir=None):
        self.ds = ds
        self.manifest = parsers.load_manifest(ds)
        self.obs = []            # evidence observations
        self.claims = []         # system_activity claim observations
        self.captures = []       # scoped Capture records, including empty tables
        for fid, meta in self.manifest.items():
            path = os.path.join(ds, meta["file_path"])
            cap = meta["captured_at"]
            ext = os.path.splitext(path)[1].lower()
            if ext == ".sql":
                o, c = parsers.parse_sql_file(path, fid, cap)
            elif ext == ".json":
                o, c = parsers.parse_json_file(path, fid, cap)
            elif ext == ".log":
                o, c = logparsers.parse_log_file(path, fid, cap), {}
            elif ext == ".txt":
                o, c = logparsers.parse_handover_txt(path, fid, cap), {}
            elif ext in (".png", ".pdf"):
                o, c = self._media_obs(fid, meta, extracted_dir), {}
            else:
                o, c = [], {}
            self.obs.extend(o)
            for (system, coll, store, observed_at), rids in c.items():
                self.captures.append(Capture(fid, cap, observed_at, system, coll, store, frozenset(rids)))
        self.claims = activity.parse_activity(os.path.join(ds, "system_activity.csv"))
        self._link_media_aliases(extracted_dir)
        self.ident = identity.Identities(ds)
        self.ident_at = {}
        with open(os.path.join(ds, "deletion_rules.csv")) as f:
            self.rules = {r["data_category"]: r for r in csv.DictReader(f)}

    def _link_media_aliases(self, extracted_dir):
        if not extracted_dir:
            extracted_dir = os.path.join(os.path.dirname(__file__), "..", "extracted")
        aliases = []
        import re
        for claim in self.claims:
            if claim.state != BIND:
                continue
            match = re.search(r"\(([^)]+)\)", claim.detail)
            if match:
                aliases.append((match.group(1), claim))
        for fid, meta in self.manifest.items():
            path = os.path.join(extracted_dir, fid + ".json")
            if not os.path.exists(path):
                continue
            text = json.load(open(path)).get("text", "")
            for alias, claim in aliases:
                if alias == claim.resource_id or not re.search(r"(?<![\w@])" + re.escape(alias) + r"(?![\w@])", text, re.I):
                    continue
                artifact_emails = {e.lower() for e in parsers.EMAIL_FULL.findall(text)}
                artifact_users = set(parsers.UID_FULL.findall(text))
                if artifact_users and claim.user_ids and not artifact_users.intersection(claim.user_ids):
                    continue
                if artifact_emails and claim.emails and not artifact_emails.intersection(claim.emails):
                    continue
                if claim.category == CAT_TOMBSTONE:
                    if not re.search(r"reference\s+registry|retained\s+reference", text, re.I):
                        continue
                    if parsers.EMAIL_FULL.search(text) or re.search(r"\+\d[\d ()-]{6,}\d", text) or re.search(r"\b[0-9a-f]{64}\b", text):
                        state = IDENTIFIABLE
                    elif re.search(r"\bname\b|\bemail\b|\bphone\b", text, re.I):
                        continue
                    else:
                        state = CLEAN
                elif claim.category == CAT_SUPPORT_ATT:
                    if not re.search(r"objects|storage", text, re.I) or not re.search(r"\.(pdf|png|jpg|jpeg)$", alias, re.I):
                        continue
                    state = PRESENT
                elif claim.category == CAT_EXPORT:
                    if not re.search(r"statement|export", text, re.I):
                        continue
                    state = PRESENT
                else:
                    continue
                # The catalog is identity provenance; the artifact is state proof.
                self.obs.append(Observation(fid, "evidence", meta["captured_at"], max(meta["captured_at"], claim.obs_time),
                    claim.system_id, claim.resource_id, claim.category, state,
                    detail="catalog-alias artifact"))

    def _media_obs(self, fid, meta, extracted_dir):
        """Observations from generic media-extraction sidecars.

        code/extract_media.py regenerates these from the actual media files
        (local OCR/PDF backends). Sidecar JSON carries the source file_id, so the
        engine cites the original evidence, not the extraction cache.
        """
        if not extracted_dir:
            extracted_dir = os.path.join(os.path.dirname(__file__), "..", "extracted")
        sidecar = os.path.join(extracted_dir, f"{fid}.json")
        if not os.path.exists(sidecar):
            raise RuntimeError(f"Missing media extraction for {fid}; run code/main.py to generate it")
        with open(sidecar) as f:
            data = json.load(f)
        out = []
        for r in data.get("records", []):
            cat = r["category"]
            out.append(Observation(
                fid, "evidence", meta["captured_at"], r.get("observed_at", meta["captured_at"]),
                r["system_id"], r["resource_id"], cat, r["state"],
                frozenset(e.lower() for e in r.get("emails", [])),
                frozenset(r.get("user_ids", [])), frozenset(parsers.norm_phone(p) for p in r.get("phones", []) if parsers.norm_phone(p)),
                frozenset(r.get("hashes", [])), detail="media-extraction"))
        return out

def _ts(o):
    return (o.obs_time, o.captured_at, o.evidence_id)

class CaseAudit:
    def __init__(self, world, case):
        self.w = world
        self.case = case
        self.audit_at = case["audit_at"]
        self.requested_at = case["requested_at"]
        if self.audit_at not in world.ident_at:
            world.ident_at[self.audit_at] = identity.Identities(world.ds, self.audit_at)
        ident = world.ident_at[self.audit_at]
        self.ident = ident
        self.uid = ident.resolve_email(case["email"])
        self.idset = ident.identifier_set(case["email"], self.uid)
        self.issues = []  # explicit uncertainty, never invented findings
        if case["email"].strip().lower() in ident.ambiguous_emails:
            self.issues.append("Request email has multiple documented owners; no forced identity assignment.")

    def _conflicts(self, obs):
        if self.uid and obs.user_ids and self.uid not in obs.user_ids:
            return True
        if self.uid and not obs.user_ids:
            owners = set().union(*(self.ident.email_owners.get(e, set()) for e in obs.emails)) if obs.emails else set()
            if owners and self.uid not in owners:
                return True
        return False

    def _bound(self, obs):
        if self._conflicts(obs):
            return False
        return bool(obs.emails & self.idset["emails"] or
                    obs.user_ids & self.idset["uids"] or
                    obs.phones & self.idset["phones"] or
                    obs.hashes & self.idset["hashes"])

    def _assisted_intent(self):
        """Optional model second opinion for requests the deterministic
        classifier cannot decide. Dormant unless MODEL_ASSIST_BACKEND is set;
        invalid or unavailable answers fall back to UNKNOWN."""
        backend = os.environ.get("MODEL_ASSIST_BACKEND", "none")
        if backend == "none":
            return "UNKNOWN"
        try:
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            import model_assist
            answer = model_assist.assist("intent", self.case["request_text"], backend=backend)
        except Exception:
            return "UNKNOWN"
        if not answer:
            return "UNKNOWN"
        word = answer.strip().split()[0].upper() if answer.strip() else ""
        return word if word in ("DELETION", "NOT_DELETION", "AMBIGUOUS") else "UNKNOWN"

    def run(self):
        label = intent.classify(self.case["request_text"])
        if label == "UNKNOWN":
            label = self._assisted_intent()
        if label != "DELETION":
            if label not in ("NOT_DELETION",):
                self.issues.append("Deletion authorization is ambiguous or unclassified; no deletion actions authorized.")
            return "NOT_APPLICABLE", []
        w = self.w
        # Both observation and file capture must be at/before audit_at.
        # Challenge input/time and evidence rules prohibit later evidence.
        bound_ev = [o for o in w.obs if o.obs_time <= self.audit_at and o.captured_at <= self.audit_at and self._bound(o)]
        bound_cl = [o for o in w.claims if o.obs_time <= self.audit_at and o.captured_at <= self.audit_at and self._bound(o)]
        # phase 2: once a resource belongs to the case, every observation of
        # that resource informs its state (404 lookups, anonymized reads and
        # clean listings carry no identifiers by definition).
        member = {(o.system_id, o.resource_id) for o in bound_ev + bound_cl}
        for o in w.obs:
            if ((o.system_id, o.resource_id) in member and o.obs_time <= self.audit_at
                    and o.captured_at <= self.audit_at and self._conflicts(o)):
                self.issues.append(f"{o.system_id}/{o.resource_id}: conflicting owner evidence excluded; resource reuse is unresolved.")
        bound_ev = bound_ev + [o for o in w.obs
                               if o.obs_time <= self.audit_at and o.captured_at <= self.audit_at and not self._bound(o) and not self._conflicts(o)
                               and (o.system_id, o.resource_id) in member]
        # A prior observation is not evidence that a resource left the subject's scope.
        footprint = {}
        for o in bound_ev + bound_cl:
            footprint.setdefault((o.system_id, o.resource_id), []).append(o)
        for obs in footprint.values():
            obs.sort(key=_ts)
        # Collection absence is scoped to the named service, collection and copy.
        for key, obs in footprint.items():
            system, rid = key
            categories = [o.category for o in obs if o.category in COMPLIANT]
            cat = categories[-1] if categories else "UNKNOWN"
            known_colls = {o.collection.split("/", 1)[1] for o in obs if o.collection}
            if not known_colls:
                coll = {"account_service": "customer_profiles", "search_service": "customer_search_documents",
                        "analytics_platform": "customer_analytics_profiles", "support_platform": "support_records",
                        "export_service": "customer_exports", "integration_service": "connector_subscriptions",
                        "backup_service": "backup_restore_entries", "security_service": "security_audit_records"}.get(system)
                if coll:
                    known_colls.add(coll)
            first_seen = min(o.obs_time for o in obs)
            observed_stores = {o.store_id for o in obs if not o.claim and o.state != BIND}
            for cap in w.captures:
                if (cap.observed_at >= first_seen and (not observed_stores or cap.store_id in observed_stores)
                        and cap.system_id == system and cap.collection in known_colls and rid not in cap.resource_ids
                        and cap.captured_at <= self.audit_at and cap.observed_at <= self.audit_at):
                    obs.append(Observation(cap.evidence_id, "evidence", cap.captured_at, cap.observed_at,
                                           system, rid, cat, ABSENT, store_id=cap.store_id,
                                           collection=system + "/" + cap.collection, authoritative=True))
            obs.sort(key=_ts)
        resources = {}
        for key, obs in footprint.items():
            ev = [o for o in obs if not o.claim and o.state != BIND]
            by_store = {}
            for o in ev:
                by_store.setdefault(o.store_id, []).append(o)
            latest = []
            for store_obs in by_store.values():
                stamp = max(o.obs_time for o in store_obs)
                tied = [o for o in store_obs if o.obs_time == stamp]
                # At the same timestamp, a known residual copy defeats a clean claim.
                tied.sort(key=lambda o: (o.state not in COMPLIANT.get(o.category, (set(),))[0], _ts(o)))
                latest.append(tied[-1])
            violations = [o for o in latest if o.state not in COMPLIANT.get(o.category, (set(),))[0]]
            state_obs = max(violations or latest, key=_ts) if latest else None
            resources[key] = {
                "obs": obs, "latest": latest,
                "state_obs": state_obs,
                "state": state_obs.state if state_obs else None,
                "category": (state_obs.category if state_obs else obs[-1].category),
            }
        if not resources:
            self.issues.append("No identity-linked, temporally admissible resource evidence; completion cannot be proved.")
        findings, remediations = [], []
        verifications = []
        for (system, rid), info in resources.items():
            cat = info["category"]
            if cat not in COMPLIANT:
                self.issues.append(f"{system}/{rid}: unsupported evidence category {cat}.")
                continue
            compliant_states, ver_op, rem_op, find_op = COMPLIANT[cat]
            st = info["state"]
            rule = w.rules.get(cat)
            if cat != CAT_DATAFLOW and rule is None:
                self.issues.append(f"{system}/{rid}: no supplied policy rule for {cat}.")
                continue
            if rule:
                expected_action = ("DELETE" if cat in DELETE_CATS else "REDACT" if cat in REDACT_CATS else
                                   "ANONYMIZE" if cat in ANONYMIZE_CATS else "RETAIN")
                if rule["required_action"] != expected_action:
                    self.issues.append(f"{system}/{rid}: supplied action {rule['required_action']} differs from supported {expected_action} policy; no action invented.")
                    continue
            if cat in (CAT_SECURITY, CAT_LEGAL):
                for record in info["latest"]:
                    active = record.attributes.get("hold_active", record.attributes.get("legal_hold_active"))
                    if cat == CAT_LEGAL and str(active).lower() in ("false", "0"):
                        self.issues.append(f"{system}/{rid}: legal hold is inactive; supplied conditional rule gives no default treatment.")
                    until = record.attributes.get("retention_until") or record.attributes.get("retained_until") or record.attributes.get("hold_until")
                    if until and until < self.audit_at:
                        self.issues.append(f"{system}/{rid}: retention/hold expired at {until}; supplied conditional rule gives no default treatment.")
            if st == "UNKNOWN":
                self.issues.append(f"{system}/{rid}: required state attributes are missing or unrecognized.")
            violated = st not in (None, "UNKNOWN") and st not in compliant_states
            if st is None:
                self.issues.append(f"{system}/{rid}: identity link has no admissible state evidence.")
            if violated and find_op is None:
                self.issues.append(f"{system}/{rid}: required retained record is not proved present; the allowed operation table has no recovery action.")
            if violated and find_op:
                ev_id = self._cite(info, want_states={st})
                findings.append((find_op, system, rid, FIND_STATE[find_op], ev_id))
                remediations.append((rem_op, system, rid, REM_STATE[rem_op], ""))
            verifications.append((ver_op, system, rid, VERIFY_STATE[ver_op], None))
        status = "INCOMPLETE" if findings or self.issues else "COMPLETE"
        steps = []
        def emit(seq, phase, items):
            for op, system, rid, st, ev in items:
                seq[0] += 1
                steps.append({"step_no": seq[0], "phase": phase, "system_id": system,
                              "resource_id": rid, "operation": op, "state": st,
                              "evidence_id": ev or ""})
        seq = [0]
        order = lambda table: lambda x: (table.index(x[0]), x[1], x[2])
        emit(seq, "FINDING", sorted(findings, key=order(FINDING_ORDER)))
        emit(seq, "REMEDIATION", sorted(remediations, key=order(REMEDIATION_ORDER)))
        if status == "COMPLETE":
            for i, (op, system, rid, st, _) in enumerate(verifications):
                key = (system, rid)
                info = resources[key]
                want = {ABSENT} if st == "ABSENT" else (
                    {RETAINED} if st == "PRESENT" else (
                    {CLEAN} if st == "REDACTED" else (
                    {ANONYMIZED} if st == "ANONYMIZED" else (
                    {DISABLED} if st == "DISABLED" else {BLOCKED}))))
                ev_id = self._cite(info, want)
                if not ev_id:
                    self.issues.append(f"{system}/{rid}: no admissible proof of the required verification state.")
                verifications[i] = (op, system, rid, st, ev_id)
        if status == "COMPLETE" and self.issues:
            status = "INCOMPLETE"
            verifications = [(op, system, rid, st, "") for op, system, rid, st, _ in verifications]
        emit(seq, "VERIFICATION", sorted(verifications, key=order(VERIFICATION_ORDER)))
        return status, steps

    def _cite(self, info, want_states):
        """Latest admissible evidence establishing a required state."""
        best = None
        for o in info.get("latest", info["obs"]):
            if o.claim or o.captured_at > self.audit_at:
                continue
            if o.state in want_states:
                if best is None or _ts(o) > _ts(best):
                    best = o
        if best is not None:
            return best.evidence_id
        return ""
