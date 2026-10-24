"""Log-family parsers -> list[Observation]."""
import re
from .model import *
from .parsers import category_for, state_for_record

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
UID_RE = re.compile(r"\buser_\d+\b")
KV_RE = re.compile(r'(\w+)=(".*?"|\S+)')

def kvs(line):
    out = {}
    for k, v in KV_RE.findall(line):
        out[k] = v.strip('"')
    return out

def ids_in_text(text):
    return (frozenset(e.lower() for e in EMAIL_RE.findall(text)),
            frozenset(UID_RE.findall(text)), frozenset(), frozenset())

LOOKUP_DONE = {
    "profile_lookup_completed": ("account_service", CAT_PROFILE),
    "index_query_completed": ("search_service", CAT_SEARCH),
    "support_ticket_read_completed": ("support_platform", CAT_SUPPORT_MSG),
    "analytics_profile_read_completed": ("analytics_platform", CAT_ANALYTICS),
    "connector_config_read_completed": ("integration_service", CAT_DATAFLOW),
    "restore_policy_read_completed": ("backup_service", CAT_BACKUP),
    "restore_candidate_evaluated": ("backup_service", CAT_BACKUP),
    "contact_lookup_completed": ("analytics_platform", CAT_ANALYTICS),
    "connector_heartbeat": ("integration_service", CAT_DATAFLOW),
    "analytics_identity_scan": ("analytics_platform", CAT_ANALYTICS),
    "message_pii_scan": ("support_platform", CAT_SUPPORT_MSG),
    "export_download_check_completed": ("export_service", CAT_EXPORT),
    "audit_record_read_completed": ("security_service", CAT_SECURITY),
    "export_status_read_completed": ("export_service", CAT_EXPORT),
    "contact_query_completed": ("support_platform", CAT_SUPPORT_ATT),
}
LOOKUP_START = {
    "profile_lookup_started", "index_query_started", "support_ticket_read_started",
    "analytics_profile_read_started", "connector_config_read_started",
    "restore_policy_read_started", "audit_record_read_started",
    "export_status_read_started", "contact_query_started",
    "attachment_scan_started", "restore_policy_check_started",
    "analytics_profile_scan_started", "export_download_check_started",
    "audit_record_query_started", "contact_lookup_started",
}

def _state_from_attrs(cat, a):
    """Infer state from a completed-lookup attribute set."""
    if cat == CAT_SECURITY:
        return RETAINED if a.get("rows") not in ("0", None) or a.get("event_code") else ABSENT
    if "rows" in a and a["rows"] == "0": return ABSENT
    if a.get("http_status") == "404": return ABSENT
    if a.get("result", "").lower() in ("miss", "not_found", "zero"): return ABSENT
    if a.get("marker_found") == "false": return PRESENT
    if a.get("restore_allowed") is not None:
        return RISK if a["restore_allowed"] == "true" else BLOCKED
    if a.get("eligible") is not None or a.get("deletion_block") is not None:
        if a.get("deletion_block") == "true" or a.get("eligible") == "false":
            return BLOCKED
        return RISK
    if a.get("enabled") is not None:
        return ACTIVE if a["enabled"] == "true" else DISABLED
    if cat == CAT_ANALYTICS:
        if any(a.get(k) not in (None, "null", "") for k in
               ("customer_reference", "email", "phone", "email_hash", "matched_value")):
            return IDENTIFIABLE
        if a.get("rows") not in (None, "0") and "correlation_key" in a:
            return IDENTIFIABLE
        return ANONYMIZED
    if cat in (CAT_SUPPORT_MSG, CAT_SUPPORT_ATT):
        if any(a.get(k) not in (None, "null", "") for k in
               ("requester_name", "requester_email", "requester_phone", "matched_value")):
            return IDENTIFIABLE
        return CLEAN
    if cat == CAT_EXPORT:
        if a.get("download_available") == "false" or a.get("available") == "false":
            return ABSENT
        return PRESENT
    return PRESENT

def _ids_from_attrs(a):
    em, ui, ph, ha = set(), set(), set(), set()
    for k, v in a.items():
        if v in (None, "", "null"): continue
        if EMAIL_RE.fullmatch(v): em.add(v.lower())
        elif UID_RE.fullmatch(v): ui.add(v)
        elif re.fullmatch(r"[0-9a-f]{64}", v): ha.add(v)
    for k in ("requester_phone", "phone", "matched_value"):
        if a.get(k) not in (None, "", "null"):
            d = re.sub(r"\D", "", a[k])
            if d: ph.add(d)
    return frozenset(em), frozenset(ui), frozenset(ph), frozenset(ha)

def parse_readback_log(path, file_id, captured_at):
    """resource_lookup_trace / syslog / service-event style logs.

    Pairs *_started lines (which carry lookup_key identity) with *_completed
    lines (which carry resource_id + outcome) via trace_id.
    """
    obs = []
    pending = {}  # trace_id -> attrs of started line
    with open(path) as f:
        for line in f:
            m = re.match(r"(\d{4}-\d{2}-\d{2}T[\d:.]+Z?)", line)
            ts = m.group(1) if m else captured_at
            a = kvs(line)
            ev = a.get("event", "")
            trace = a.get("trace_id", "")
            if ev in LOOKUP_START and trace:
                pending[trace] = a
                continue
            if ev in LOOKUP_DONE:
                system, cat = LOOKUP_DONE[ev]
                start = pending.pop(trace, {})
                merged = dict(start); merged.update(a)
                rid = a.get("resource_id")
                if not rid:
                    continue
                st = _state_from_attrs(cat, merged)
                em, ui, ph, ha = _ids_from_attrs(merged)
                obs.append(Observation(file_id, "evidence", captured_at, ts,
                                       system, rid, cat, st, em, ui, ph, ha,
                                       detail=line.strip()[:200]))
                continue
            if ev in ("attachment_pii_scan", "deletion_marker_check",
                      "restore_policy_violation"):
                system = a.get("service", "")
                if "support" in system: cat = CAT_SUPPORT_ATT
                elif "backup" in system: cat = CAT_BACKUP
                else: cat = CAT_SUPPORT_ATT
                rid = a.get("resource_id")
                if not rid: continue
                st = _state_from_attrs(cat, a)
                em, ui, ph, ha = _ids_from_attrs(a)
                obs.append(Observation(file_id, "evidence", captured_at, ts,
                                       system, rid, cat, st, em, ui, ph, ha,
                                       detail=line.strip()[:200]))
    return obs

RECORD_LOOKUP_RE = re.compile(
    r"^(\S+)\s+INFO\s+service=(\S+)\s+event=record_lookup\s+seq=(\d+)\s+"
    r'system="?([^"\s]+)"?\s+resource_id="?([^"\s]+)"?\s+record_type="?([^"\s]+)"?\s+'
    r'result="?([^"\s]+)"?\s+subject_reference="?([^"\s]+)"?')

def parse_record_lookup_log(path, file_id, captured_at):
    """search_index_diagnostic / notification_delivery style logs."""
    obs = []
    with open(path) as f:
        for line in f:
            m = RECORD_LOOKUP_RE.match(line.strip())
            if not m:
                continue
            ts, svc, seq, system, rid, rtype, result, subj = m.groups()
            cat = category_for(system, "", rtype)
            result_u = result.upper()
            st = {"FOUND": None, "NOT_FOUND": ABSENT, "IDENTIFIABLE": IDENTIFIABLE,
                  "ANONYMIZED": ANONYMIZED, "REDACTED": CLEAN, "ACTIVE": ACTIVE,
                  "DISABLED": DISABLED, "BLOCKED": BLOCKED}.get(result_u)
            if st is None:
                st = state_for_record(cat, {}) if result_u == "FOUND" else PRESENT
                if result_u == "FOUND":
                    st = RETAINED if cat in RETAIN_CATS else (
                        ACTIVE if cat == CAT_DATAFLOW else
                        RISK if cat == CAT_BACKUP else
                        state_for_record(cat, {"email": subj, "requester_email": subj}))
            ids = []
            em = subj.lower() if EMAIL_RE.fullmatch(subj) else None
            ui = subj if UID_RE.fullmatch(subj) else None
            obs.append(Observation(file_id, "evidence", captured_at, ts,
                                   system, rid, cat, st,
                                   frozenset([em]) if em else frozenset(),
                                   frozenset([ui]) if ui else frozenset(),
                                   frozenset(), frozenset(),
                                   detail=line.strip()[:200]))
    return obs

HANDOVER_RE = re.compile(
    r"^-\s+(\S+)\s+\|\s+(\S+)\s+\|\s+(\S+)\s+\|\s+([A-Z_]+)\s+\|\s+([A-Z_]+)\s+\|\s+(.+)$")

def parse_handover_txt(path, file_id, captured_at):
    obs = []
    with open(path) as f:
        for line in f:
            m = HANDOVER_RE.match(line.strip())
            if not m:
                continue
            ts, system, rid, rtype, state, ident = m.groups()
            cat = category_for(system, "", rtype)
            st = {"NOT_FOUND": ABSENT, "FOUND": PRESENT, "IDENTIFIABLE": IDENTIFIABLE,
                  "ANONYMIZED": ANONYMIZED, "REDACTED": CLEAN, "ACTIVE": ACTIVE,
                  "DISABLED": DISABLED, "BLOCKED": BLOCKED}.get(state, PRESENT)
            if state == "FOUND" and cat in (CAT_ANALYTICS, CAT_SUPPORT_MSG):
                st = IDENTIFIABLE
            if state == "FOUND" and cat in RETAIN_CATS:
                st = RETAINED
            if state == "FOUND" and cat == CAT_DATAFLOW:
                st = ACTIVE
            if state == "FOUND" and cat == CAT_BACKUP:
                st = RISK
            em = ident.lower() if EMAIL_RE.fullmatch(ident.strip()) else None
            ui = ident.strip() if UID_RE.fullmatch(ident.strip()) else None
            obs.append(Observation(file_id, "evidence", captured_at, ts,
                                   system, rid, cat, st,
                                   frozenset([em]) if em else frozenset(),
                                   frozenset([ui]) if ui else frozenset(),
                                   frozenset(), frozenset(),
                                   detail=line.strip()[:200]))
    return obs

def parse_log_file(path, file_id, captured_at):
    with open(path) as f:
        head = "".join([f.readline() for _ in range(5)])
    if "event=record_lookup" in head:
        return parse_record_lookup_log(path, file_id, captured_at)
    return parse_readback_log(path, file_id, captured_at)
