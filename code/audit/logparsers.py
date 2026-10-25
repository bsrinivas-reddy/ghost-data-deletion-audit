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
    "export_metadata_read_completed": ("export_service", CAT_EXPORT),
    "restore_authorization_completed": ("backup_service", CAT_BACKUP),
    "analytics_profile_read": ("analytics_platform", CAT_ANALYTICS),
    "message_read": ("support_platform", CAT_SUPPORT_MSG),
    "retained_order_loaded": ("support_platform", CAT_SUPPORT_MSG),
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
    "export_metadata_read_started", "retained_order_query_started",
}

def _state_from_attrs(cat, a):
    """Infer state from a completed-lookup attribute set."""
    if "http_status" in a and not (re.fullmatch(r"2[0-9]{2}", str(a["http_status"])) or str(a["http_status"]) == "404"):
        return "UNKNOWN"
    if cat == CAT_SECURITY:
        return RETAINED if a.get("rows") not in ("0", None) or a.get("event_code") else ABSENT
    if "rows" in a and a["rows"] == "0": return ABSENT
    if a.get("http_status") == "404": return ABSENT
    if a.get("result", "").lower() in ("miss", "not_found", "zero"): return ABSENT
    if a.get("marker_found") == "false": return PRESENT
    if a.get("decision") is not None:
        return BLOCKED if a["decision"] == "deny" else RISK
    if cat == CAT_SUPPORT_MSG and (state_for_record(cat, a) == IDENTIFIABLE
                                   or a.get("matched_value") not in (None, "", "null")):
        return IDENTIFIABLE
    if a.get("message_text") is not None:
        return CLEAN if "[REDACTED]" in a["message_text"] else IDENTIFIABLE
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
        if k in ("agent", "actor", "assignee", "operator") or k.startswith(("agent_", "actor_", "assignee_", "operator_")):
            continue
        if v in (None, "", "null"): continue
        if EMAIL_RE.fullmatch(v): em.add(v.lower())
        elif UID_RE.fullmatch(v): ui.add(v)
        elif re.fullmatch(r"[0-9a-f]{64}", v): ha.add(v)
    for k in ("message_text", "message_excerpt", "body", "content"):
        em.update(e.lower() for e in EMAIL_RE.findall(a.get(k, "")))
    for k in ("requester_phone", "phone", "matched_value"):
        if a.get(k) not in (None, "", "null"):
            d = re.sub(r"\D", "", a[k])
            if d: ph.add(d)
    return frozenset(em), frozenset(ui), frozenset(ph), frozenset(ha)

JSON_LINE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}T[\d:.]+Z?)\s+(\{.*\})\s*$")
TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T[\d:.]+Z?)")
MSG_RE = re.compile(r'message="((?:[^"\\]|\\.)*)"\s*$')
BRACKET_RE = re.compile(
    r"^(\S+)\s+\[(\w+)\]\s+\[([^\]]+)\]\s+\[([^\]]+)\]\s+([a-z_]+):\s*(.*)$")
SYSLOG_RE = re.compile(
    r"^(\S+)\s+<\d+>\d+\s+\S+\s+(\S+)\s+(\S+)\s+-\s+-\s+(.*)$")
TRACE_TOKEN_RE = re.compile(r"\b(tr-[0-9a-z-]+|rb-[0-9a-z-]+)\b")

def _iter_kv_lines(path):
    """Yield (ts, attrs, line) per line, normalizing every log syntax seen in
    the dataset into a common attribute dict:
    - plain `level=.. service=.. k=v` lines (incl. JSON payloads)
    - cloud-runtime `requestId=.. function=.. message="k=\"v\" ..."` lines
    - bracket `[LEVEL] [service] [trace] event: k="v"` lines
    - pipe `ts | LEVEL | service | trace | event | k="v"` lines
    - syslog `ts <15>1 node service trace - - k="v"` lines
    """
    import json as _json
    with open(path) as f:
        for line in f:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            jm = JSON_LINE_RE.match(line)
            if jm:
                try:
                    obj = _json.loads(jm.group(2))
                except ValueError:
                    continue
                obj = {k: (str(v) if v is not None else "null") for k, v in obj.items()}
                yield jm.group(1), obj, line
                continue
            tm = TS_RE.match(line)
            ts = tm.group(1) if tm else None
            a = {}
            if " | " in line:
                parts = [p.strip() for p in line.split(" | ")]
                if len(parts) >= 6:
                    a = kvs(" ".join(parts[5:]))
                    a.setdefault("event", parts[4])
                    a.setdefault("trace_id", parts[3])
                    a.setdefault("service", parts[2])
            elif BRACKET_RE.match(line):
                m = BRACKET_RE.match(line)
                _, _lvl, service, trace, event, rest = m.groups()
                a = kvs(rest)
                a.setdefault("event", event)
                a.setdefault("trace_id", trace)
                a.setdefault("service", service)
            elif SYSLOG_RE.match(line):
                m = SYSLOG_RE.match(line)
                _, service, trace, rest = m.groups()
                a = kvs(rest)
                a.setdefault("trace_id", trace)
                a.setdefault("service", service)
            else:
                mm = MSG_RE.search(line)
                if mm:
                    inner = mm.group(1).replace('\\"', '"')
                    a = kvs(inner)
                    outer = kvs(line[:mm.start()])
                    for k, v in outer.items():
                        a.setdefault(k, v)
                    if "function" in a:
                        a.setdefault("service", a["function"])
                else:
                    a = kvs(line)
            if "requestId" in a:
                a.setdefault("trace_id", a["requestId"])
            if "trace_id" not in a:
                tr = TRACE_TOKEN_RE.search(line)
                if tr:
                    a["trace_id"] = tr.group(1)
            yield ts, a, line

def parse_readback_log(path, file_id, captured_at):
    """resource_lookup_trace / syslog / service-event style logs.

    Pairs *_started lines (which carry lookup_key identity) with *_completed
    lines (which carry resource_id + outcome) via trace_id.
    """
    obs = []
    pending = {}  # (service, trace_id) -> start attributes
    if True:
        for ts, a, line in _iter_kv_lines(path):
            ts = ts or captured_at
            ev = a.get("event", "")
            trace = a.get("trace_id", "")
            if ev in LOOKUP_START and trace:
                pending[(a.get("service", ""), trace)] = a
                continue
            if ev in LOOKUP_DONE:
                system, cat = LOOKUP_DONE[ev]
                start = pending.pop((a.get("service", system), trace), {})
                if start.get("resource_id") and a.get("resource_id") and start["resource_id"] != a["resource_id"]:
                    start = {}
                merged = dict(start); merged.update(a)
                rid = a.get("resource_id")
                if not rid:
                    continue
                st = _state_from_attrs(cat, merged)
                em, ui, ph, ha = _ids_from_attrs(merged)
                obs.append(Observation(file_id, "evidence", captured_at, ts,
                                       system, rid, cat, st, em, ui, ph, ha,
                                       detail=line.strip()[:200], attributes=merged))
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
                                       detail=line.strip()[:200], attributes=a))
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
