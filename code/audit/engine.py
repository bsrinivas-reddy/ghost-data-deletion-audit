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
        self.captures = []       # authoritative collection captures:
                                 # (captured_at, file_id, system, collection, rids:set)
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
            for (system, coll), rids in c.items():
                self.captures.append((cap, fid, system, coll, set(rids)))
        # clamp: a record cannot carry an observation time after its capture
        fixed = []
        for o in self.obs:
            if o.obs_time > o.captured_at:
                o = replace(o, obs_time=o.captured_at)
            fixed.append(o)
        self.obs = fixed
        self.claims = activity.parse_activity(os.path.join(ds, "system_activity.csv"))
        self.ident = identity.Identities(ds)

    def _media_obs(self, fid, meta, extracted_dir):
        """Observations from generic media-extraction sidecars.

        code/extract_media.py regenerates these from the actual media files
        (OCR/VLM backends). Sidecar JSON carries the source file_id, so the
        engine cites the original evidence, not the extraction cache.
        """
        if not extracted_dir:
            extracted_dir = os.path.join(os.path.dirname(__file__), "..", "extracted")
        sidecar = os.path.join(extracted_dir, f"{fid}.json")
        if not os.path.exists(sidecar):
            return []
        with open(sidecar) as f:
            data = json.load(f)
        out = []
        for r in data.get("records", []):
            cat = r["category"]
            out.append(Observation(
                fid, "evidence", meta["captured_at"], r.get("observed_at", meta["captured_at"]),
                r["system_id"], r["resource_id"], cat, r["state"],
                frozenset(e.lower() for e in r.get("emails", [])),
                frozenset(r.get("user_ids", [])), frozenset(r.get("phones", [])),
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
        self.uid = world.ident.resolve_email(case["email"])
        self.idset = world.ident.identifier_set(case["email"], self.uid)

    def _bound(self, obs):
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
            return "NOT_APPLICABLE", []
        w = self.w
        # candidate observations bound to this identity, at/before audit_at
        # discovery gates on the record's own time; citation (later) gates on
        # the evidence file's capture time. A record that existed at audit_at
        # is usable for footprint/state even when its file arrived later.
        bound_ev = [o for o in w.obs if o.obs_time <= self.audit_at and self._bound(o)]
        bound_cl = [o for o in w.claims if o.obs_time <= self.audit_at and self._bound(o)]
        # phase 2: once a resource belongs to the case, every observation of
        # that resource informs its state (404 lookups, anonymized reads and
        # clean listings carry no identifiers by definition).
        member = {(o.system_id, o.resource_id) for o in bound_ev + bound_cl}
        bound_ev = bound_ev + [o for o in w.obs
                               if o.obs_time <= self.audit_at and not self._bound(o)
                               and (o.system_id, o.resource_id) in member]
        # footprint: resources touched by the current request lifecycle, i.e.
        # with at least one observation in [requested_at, audit_at]; older
        # resources already compliant in their latest pre-request observation
        # belong to a prior closed cycle and are out of scope.
        by_res = {}
        for o in bound_ev + bound_cl:
            by_res.setdefault((o.system_id, o.resource_id), []).append(o)
        footprint = {}
        for key, obs in by_res.items():
            obs.sort(key=_ts)
            in_window = [o for o in obs if o.obs_time >= self.requested_at]
            if not in_window:
                stated = [o for o in obs if o.state != BIND]
                if not stated:
                    continue  # only an old identity link: prior lifecycle
                pre = stated[-1]
                compliant = COMPLIANT.get(pre.category, ({ABSENT},))[0]
                if pre.state in compliant or pre.state == ABSENT:
                    continue  # closed before this request
            footprint[key] = obs
        # state at audit_at per resource: latest non-claim observation
        resources = {}
        for key, obs in footprint.items():
            ev = [o for o in obs if not o.claim and o.state != BIND]
            state_obs = ev[-1] if ev else None
            resources[key] = {
                "obs": obs,
                "state_obs": state_obs,
                "state": state_obs.state if state_obs else None,
                "category": (state_obs.category if state_obs else obs[-1].category),
            }
        findings, remediations = [], []
        verifications = []
        for (system, rid), info in resources.items():
            cat = info["category"]
            if cat not in COMPLIANT:
                continue
            compliant_states, ver_op, rem_op, find_op = COMPLIANT[cat]
            st = info["state"]
            violated = st is not None and st not in compliant_states
            if violated and find_op:
                ev_id = self._cite(info, want_states={st})
                findings.append((find_op, system, rid, FIND_STATE[find_op], ev_id))
                remediations.append((rem_op, system, rid, REM_STATE[rem_op], ""))
            verifications.append((ver_op, system, rid, VERIFY_STATE[ver_op], None))
        status = "COMPLETE" if not findings else "INCOMPLETE"
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
                verifications[i] = (op, system, rid, st, self._cite(info, want))
        emit(seq, "VERIFICATION", sorted(verifications, key=order(VERIFICATION_ORDER)))
        return status, steps

    def _cite(self, info, want_states):
        """Latest at/before-audit evidence establishing one of want_states."""
        best = None
        for o in info["obs"]:
            if o.claim or o.captured_at > self.audit_at:
                continue
            if o.state in want_states:
                if best is None or _ts(o) > _ts(best):
                    best = o
        if best is not None:
            return best.evidence_id
        # absence via authoritative collection capture
        if ABSENT in want_states:
            (system, rid) = info["obs"][0].system_id, info["obs"][0].resource_id
            coll = None
            for o in info["obs"]:
                if o.collection:
                    coll = o.collection.split("/", 1)[1]
                    break
            if coll is None:
                coll = {"account_service": "customer_profiles",
                        "search_service": "customer_search_documents",
                        "analytics_platform": "customer_analytics_profiles",
                        "support_platform": "support_records",
                        "export_service": "customer_exports",
                        "integration_service": "connector_subscriptions",
                        "backup_service": "backup_restore_entries",
                        "security_service": "security_audit_records"}.get(system)
            cands = []
            for cap, fid, csys, ccoll, rids in self.w.captures:
                if csys == system and ccoll == coll and cap <= self.audit_at and rid not in rids:
                    cands.append((cap, fid))
            if cands:
                cands.sort()
                return cands[-1][1]
        return ""
