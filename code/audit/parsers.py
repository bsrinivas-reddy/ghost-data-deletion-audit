"""Parsers: every dataset file format -> list[Observation]."""
import csv, json, os, re, sqlite3, subprocess
from .model import *

# ---------------------------------------------------------------- identities
def norm_email(e):
    return e.strip().lower() if e else None

def norm_phone(p):
    if not p: return None
    d = re.sub(r"\D", "", p)
    return d or None

EMAIL_FULL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
UID_FULL = re.compile(r"user_\d+")
HASH_FULL = re.compile(r"[0-9a-f]{64}")

def _ids_from_record(rec, keys_email, keys_uid, keys_phone, keys_hash):
    emails, uids, phones, hashes = set(), set(), set(), set()
    # value-classified sweep over every scalar field: identity fields are
    # named inconsistently across files (lookup_value, subject_key,
    # correlation_key, matched_value, owner_key, subject_reference...), so
    # classify by value shape, not by key name
    for key, v in rec.items():
        if key in ("agent", "actor", "assignee", "operator") or key.startswith(("agent_", "actor_", "assignee_", "operator_")):
            continue
        if not isinstance(v, str) or not v:
            continue
        if EMAIL_FULL.fullmatch(v): emails.add(v.lower())
        elif UID_FULL.fullmatch(v): uids.add(v)
        elif HASH_FULL.fullmatch(v): hashes.add(v)
        if key in ("message_text", "message_excerpt", "body", "content", "notes"):
            emails.update(e.lower() for e in EMAIL_FULL.findall(v))
    for k in keys_email:
        v = rec.get(k)
        if v:
            n = norm_email(str(v))
            if n: emails.add(n)
    for k in keys_uid:
        v = rec.get(k)
        if v and re.fullmatch(r"user_\d+", str(v)): uids.add(str(v))
    for k in keys_phone:
        v = rec.get(k)
        if v:
            n = norm_phone(str(v))
            if n: phones.add(n)
    for k in keys_hash:
        v = rec.get(k)
        if v and re.fullmatch(r"[0-9a-f]{64}", str(v)): hashes.add(str(v))
    return emails, uids, phones, hashes

EMAIL_KEYS = ("email", "requester_email", "owner_email", "customer_email",
              "subject_email", "to_address", "recipient")
UID_KEYS = ("user_id", "customer_reference", "subject_reference")
PHONE_KEYS = ("phone", "requester_phone", "owner_phone")
HASH_KEYS = ("email_hash",)

def ids_from(rec):
    return _ids_from_record(rec, EMAIL_KEYS, UID_KEYS, PHONE_KEYS, HASH_KEYS)

def ids_from_deep(rec):
    """Top-level plus nested objects (e.g. search document payloads)."""
    em, ui, ph, ha = (set(x) for x in ids_from(rec))
    def walk(v):
        if isinstance(v, dict):
            e2, u2, p2, h2 = ids_from(v)
            em.update(e2); ui.update(u2); ph.update(p2); ha.update(h2)
            for key, x in v.items():
                if key not in ("agent", "actor", "assignee", "operator") and not key.startswith(("agent_", "actor_", "assignee_", "operator_")):
                    walk(x)
        elif isinstance(v, list):
            for x in v: walk(x)
    for key, v in rec.items():
        if key not in ("agent", "actor", "assignee", "operator") and not key.startswith(("agent_", "actor_", "assignee_", "operator_")):
            walk(v)
    return frozenset(em), frozenset(ui), frozenset(ph), frozenset(ha)

REF_SYSTEM = [
    ("account_", "account_service"), ("tombstone_", "identity_service"),
    ("search_", "search_service"), ("cache_", "cache_service"),
    ("support_", "support_platform"), ("analytics_", "analytics_platform"),
    ("telemetry_", "telemetry_platform"), ("data_flow_", "integration_service"),
    ("backup_", "backup_service"), ("audit_record_", "security_service"),
    ("export_", "export_service"), ("marketing_", "marketing_service"),
    ("object_", "support_platform"), ("legal_hold_", "legal_service"),
    ("email_log_", "notification_service"), ("secondary_", "account_service")]

def system_for_ref(rid):
    for pfx, sysname in REF_SYSTEM:
        if rid.startswith(pfx):
            return sysname
    return ""

def bind_obs_for_refs(rec, file_id, captured_at, t, em, ui, ph, ha):
    """Identity-only observations for resources referenced by this record
    (e.g. a search document's source_resource_id). Never state proof."""
    out = []
    for ref in refs_from(rec):
        system = system_for_ref(ref)
        if not system:
            continue
        out.append(Observation(file_id, "evidence", captured_at, t, system, ref,
                               category_for(system, ""), BIND, em, ui, ph, ha,
                               detail="cross-reference"))
    return out

REF_RE = re.compile(
    r"^(account|analytics|support|search|backup|data_flow|export|tombstone|"
    r"audit_record|object|cache|marketing|telemetry|secondary|email_log|"
    r"legal_hold)_\d+$")

def refs_from(rec):
    """Cross-resource references such as a search doc's source_resource_id."""
    out = set()
    def walk(v):
        if isinstance(v, dict):
            for k, x in v.items():
                if k in ("agent", "actor", "assignee", "operator") or k.startswith(("agent_", "actor_", "assignee_", "operator_")):
                    continue
                if (isinstance(x, str) and k != "resource_id"
                        and k.endswith("resource_id") and REF_RE.match(x)):
                    out.add(x)
                else:
                    walk(x)
        elif isinstance(v, list):
            for x in v: walk(x)
    walk(rec)
    return out

# ------------------------------------------------- collection interpretation
# (system, collection) -> category
COLLECTION_CATEGORY = {
    ("account_service", "customer_profiles"): CAT_PROFILE,
    ("identity_service", "deleted_customer_references"): CAT_TOMBSTONE,
    ("search_service", "customer_search_documents"): CAT_SEARCH,
    ("search_service", "search_documents"): CAT_SEARCH,
    ("support_platform", "support_records"): CAT_SUPPORT_MSG,
    ("support_platform", "support_conversations"): CAT_SUPPORT_MSG,
    ("support_platform", "customer_support_tickets"): CAT_SUPPORT_MSG,
    ("support_platform", "support_attachments"): CAT_SUPPORT_ATT,
    ("support_platform", "ticket_attachments"): CAT_SUPPORT_ATT,
    ("analytics_platform", "customer_analytics_reports"): CAT_ANALYTICS,
    ("analytics_platform", "customer_analytics_profiles"): CAT_ANALYTICS,
    ("telemetry_platform", "product_telemetry"): CAT_TELEMETRY,
    ("integration_service", "connector_subscriptions"): CAT_DATAFLOW,
    ("integration_service", "connector_configurations"): CAT_DATAFLOW,
    ("backup_service", "backup_restore_entries"): CAT_BACKUP,
    ("backup_service", "backup_catalog"): CAT_BACKUP,
    ("security_service", "security_audit_events"): CAT_SECURITY,
    ("security_service", "security_audit_records"): CAT_SECURITY,
    ("export_service", "customer_exports"): CAT_EXPORT,
    ("export_service", "customer_export_jobs"): CAT_EXPORT,
    ("marketing_service", "marketing_profiles"): CAT_MARKETING,
    ("marketing_platform", "marketing_profiles"): CAT_MARKETING,
    ("notification_service", "email_delivery_logs"): CAT_EMAILLOG,
    ("cache_service", "cache_entries"): CAT_CACHE,
    ("legal_service", "legal_hold_records"): CAT_LEGAL,
    ("legal_service", "retained_order_records"): CAT_LEGAL,
}

RECORD_TYPE_CATEGORY = {
    "USER_PROFILE": CAT_PROFILE, "SECONDARY_IDENTIFIER": CAT_SECONDARY,
    "SEARCH_INDEX_ENTRY": CAT_SEARCH, "CACHE_ENTRY": CAT_CACHE,
    "SUPPORT_MESSAGE": CAT_SUPPORT_MSG, "SUPPORT_ATTACHMENT": CAT_SUPPORT_ATT,
    "ANALYTICS_PROFILE": CAT_ANALYTICS, "PRODUCT_TELEMETRY": CAT_TELEMETRY,
    "USER_EXPORT": CAT_EXPORT, "MARKETING_PROFILE": CAT_MARKETING,
    "EMAIL_DELIVERY_LOG": CAT_EMAILLOG, "SECURITY_AUDIT_LOG": CAT_SECURITY,
    "LEGAL_HOLD_RECORD": CAT_LEGAL, "BACKUP_ARCHIVE": CAT_BACKUP,
    "ACCOUNT_TOMBSTONE": CAT_TOMBSTONE, "DATA_FLOW": CAT_DATAFLOW,
}

def category_for(system, collection="", record_type=""):
    if record_type and record_type in RECORD_TYPE_CATEGORY:
        return RECORD_TYPE_CATEGORY[record_type]
    if (system, collection) in COLLECTION_CATEGORY:
        return COLLECTION_CATEGORY[(system, collection)]
    if record_type:  # unknown record type: keep it visible, do not guess
        return record_type
    return "UNKNOWN"

def state_for_record(category, rec):
    """State of a present record from its fields."""
    def has(*keys):
        return any(rec.get(k) not in (None, "", "null") for k in keys)
    if category in (CAT_PROFILE, CAT_SEARCH, CAT_CACHE, CAT_EXPORT,
                    CAT_MARKETING, CAT_SUPPORT_ATT, CAT_SECONDARY):
        return PRESENT
    if category in (CAT_ANALYTICS, CAT_TELEMETRY):
        if has("user_id", "customer_reference", "email", "phone", "email_hash"):
            return IDENTIFIABLE
        return ANONYMIZED
    if category == CAT_SUPPORT_MSG:
        content = " ".join(str(rec.get(k) or "") for k in ("message_text", "message_excerpt", "body", "content"))
        if has("requester_name", "requester_email", "requester_phone") or EMAIL_FULL.search(content) or re.search(r"\+\d[\d ()-]{6,}\d", content):
            return IDENTIFIABLE
        return CLEAN
    if category == CAT_TOMBSTONE:
        if has("name", "full_name", "email", "phone", "email_hash"):
            return IDENTIFIABLE
        return CLEAN
    if category == CAT_EMAILLOG:
        if has("email", "to_address", "recipient"):
            return IDENTIFIABLE
        return CLEAN
    if category == CAT_DATAFLOW:
        en = rec.get("enabled")
        if str(en).lower() in ("1", "true"): return ACTIVE
        if str(en).lower() in ("0", "false"): return DISABLED
        return "UNKNOWN"
    if category == CAT_BACKUP:
        ra = rec.get("restore_allowed")
        if str(ra).lower() in ("1", "true"): return RISK
        if str(ra).lower() in ("0", "false"): return BLOCKED
        return "UNKNOWN"
    if category in (CAT_SECURITY, CAT_LEGAL):
        return RETAINED
    return PRESENT

# ------------------------------------------------------------------- manifest
def load_manifest(ds):
    out = {}
    with open(os.path.join(ds, "evidence_files.csv")) as f:
        for r in csv.DictReader(f):
            out[r["file_id"]] = r
    return out

# ------------------------------------------------------------------ SQL files
SQL_TABLE_MAP = {  # table -> (system, collection)
    "customer_profiles": ("account_service", "customer_profiles"),
    "customer_profiles_primary": ("account_service", "customer_profiles"),
    "customer_profiles_failover_replica": ("account_service", "customer_profiles"),
    "customer_search_documents": ("search_service", "customer_search_documents"),
    "search_documents_primary": ("search_service", "customer_search_documents"),
    "customer_analytics_profiles": ("analytics_platform", "customer_analytics_profiles"),
    "support_records": ("support_platform", "support_records"),
    "customer_exports": ("export_service", "customer_exports"),
    "connector_subscriptions": ("integration_service", "connector_subscriptions"),
    "backup_restore_entries": ("backup_service", "backup_restore_entries"),
    "security_audit_records": ("security_service", "security_audit_records"),
}

def parse_sql_file(path, file_id, captured_at):
    con = sqlite3.connect(":memory:")
    with open(path) as f:
        con.executescript(f.read())
    obs = []
    tables = [r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")]
    collections = {}
    scope = dict(con.execute("SELECT origin_system, captured_at FROM snapshot_scope")) if "snapshot_scope" in tables else None
    for t in tables:
        if t == "snapshot_scope":
            continue
        if t.startswith("customer_data_"):  # generic topology tables
            store = t.removeprefix("customer_data_")
            for rid, system, coll, rec_json in con.execute(
                    f'SELECT resource_id, origin_system, collection_name, record_json FROM "{t}"'):
                rec = json.loads(rec_json)
                if coll == "operational_record_history":
                    history, _ = _parse_json_data({"records": [rec]}, file_id, captured_at)
                    obs.extend(history)
                    continue
                cat = category_for(system, coll)
                st = state_for_record(cat, rec)
                em, ui, ph, ha = ids_from_deep(rec)
                obs.append(Observation(file_id, "evidence", captured_at, captured_at,
                                       system, rid, cat, st, frozenset(em), frozenset(ui),
                                       frozenset(ph), frozenset(ha),
                                       collection=f"{system}/{coll}", authoritative=True,
                                       store_id=store, attributes=rec))
                obs.extend(bind_obs_for_refs(rec, file_id, captured_at, captured_at,
                                             em, ui, ph, ha))
                collections.setdefault((system, coll, store, captured_at), set()).add(rid)
            continue
        if t not in SQL_TABLE_MAP:
            continue
        system, coll = SQL_TABLE_MAP[t]
        if scope is not None and system not in scope:
            continue
        observed_at = scope[system] if scope is not None else captured_at
        store = "failover_replica" if "failover_replica" in t else "primary"
        collections.setdefault((system, coll, store, observed_at), set())
        cols = [c[1] for c in con.execute(f'PRAGMA table_info("{t}")')]
        for row in con.execute(f'SELECT * FROM "{t}"'):
            rec = dict(zip(cols, row))
            rid = rec.get("resource_id")
            if not rid:
                continue
            cat = category_for(system, coll)
            st = state_for_record(cat, rec)
            em, ui, ph, ha = ids_from_deep(rec)
            obs.append(Observation(file_id, "evidence", captured_at, observed_at,
                                   system, rid, cat, st, frozenset(em), frozenset(ui),
                                   frozenset(ph), frozenset(ha),
                                   collection=f"{system}/{coll}", authoritative=True,
                                   store_id=store, attributes=rec))
            obs.extend(bind_obs_for_refs(rec, file_id, captured_at, captured_at,
                                         em, ui, ph, ha))
            collections.setdefault((system, coll, store, observed_at), set()).add(rid)
    con.close()
    return obs, collections

# ----------------------------------------------------------------- JSON files
def parse_json_file(path, file_id, captured_at):
    with open(path) as f:
        d = json.load(f)
    return _parse_json_data(d, file_id, captured_at)

def _parse_json_data(d, file_id, captured_at):
    obs, collections = [], {}
    def coll_key(system, coll):
        collections.setdefault((system, coll), set())
        return collections[(system, coll)]

    if "service_exports" in d:  # service_resource_export_*
        se = d["service_exports"]
        for lookup in se.get("account_service", {}).get("profile_lookups", []):
            rid = lookup["resource_id"]; prof = lookup.get("profile")
            t = lookup.get("observed_at", captured_at)
            if prof is None:
                obs.append(Observation(file_id, "evidence", captured_at, t,
                    "account_service", rid, CAT_PROFILE, ABSENT if str(lookup.get("status_code")) == "404" else "UNKNOWN"))
            else:
                em, ui, ph, ha = ids_from_deep(prof)
                obs.append(Observation(file_id, "evidence", captured_at, t,
                    "account_service", rid, CAT_PROFILE, PRESENT,
                    frozenset(em), frozenset(ui), frozenset(ph), frozenset(ha), attributes=prof))
        for prof in se.get("analytics_platform", {}).get("profiles", []):
            t = prof.get("observed_at", captured_at)
            em, ui, ph, ha = ids_from_deep(prof)
            st = state_for_record(CAT_ANALYTICS, prof)
            obs.append(Observation(file_id, "evidence", captured_at, t,
                "analytics_platform", prof["resource_id"], CAT_ANALYTICS, st,
                frozenset(em), frozenset(ui), frozenset(ph), frozenset(ha), attributes=prof))
        for e in se.get("backup_service", {}).get("restore_entries", []):
            t = e.get("observed_at", captured_at)
            em, ui, ph, ha = ids_from_deep(e)
            st = state_for_record(CAT_BACKUP, e)
            obs.append(Observation(file_id, "evidence", captured_at, t,
                "backup_service", e["resource_id"], CAT_BACKUP, st,
                frozenset(em), frozenset(ui), frozenset(ph), frozenset(ha), attributes=e))
        for e in se.get("export_service", {}).get("exports", []):
            t = e.get("observed_at", captured_at)
            em, ui, ph, ha = ids_from_deep(e)
            present = e.get("download_available", True)
            st = PRESENT if present else ABSENT
            obs.append(Observation(file_id, "evidence", captured_at, t,
                "export_service", e["resource_id"], CAT_EXPORT, st,
                frozenset(em), frozenset(ui), frozenset(ph), frozenset(ha), attributes=e))
        for e in se.get("integration_service", {}).get("connectors", []):
            t = e.get("observed_at", captured_at)
            em, ui, ph, ha = ids_from_deep(e)
            st = state_for_record(CAT_DATAFLOW, e)
            obs.append(Observation(file_id, "evidence", captured_at, t,
                "integration_service", e["resource_id"], CAT_DATAFLOW, st,
                frozenset(em), frozenset(ui), frozenset(ph), frozenset(ha)))
        for e in se.get("search_service", {}).get("index_queries", []):
            t = e.get("observed_at", captured_at)
            em, ui, ph, ha = ids_from_deep(e)
            res = str(e.get("result", "")).lower()
            hits = e.get("hits", {})
            total = hits.get("total") if isinstance(hits, dict) else None
            if isinstance(total, dict):
                total = total.get("value")
            documents = hits.get("documents", hits.get("hits", [])) if isinstance(hits, dict) else []
            if documents or isinstance(total, (int, float)) and total > 0 or res in ("hit", "found"):
                st = PRESENT
            elif total == 0 or res in ("miss", "not_found", "absent"):
                st = ABSENT
            else:
                st = "UNKNOWN"
            obs.append(Observation(file_id, "evidence", captured_at, t,
                "search_service", e["resource_id"], CAT_SEARCH, st,
                frozenset(em), frozenset(ui), frozenset(ph), frozenset(ha)))
        for e in se.get("security_service", {}).get("audit_records", []):
            t = e.get("observed_at", captured_at)
            em, ui, ph, ha = ids_from_deep(e)
            obs.append(Observation(file_id, "evidence", captured_at, t,
                "security_service", e["resource_id"], CAT_SECURITY, RETAINED,
                frozenset(em), frozenset(ui), frozenset(ph), frozenset(ha), attributes=e))
        for e in se.get("support_platform", {}).get("tickets", []):
            t = e.get("observed_at", captured_at)
            em, ui, ph, ha = ids_from_deep(e)
            st = state_for_record(CAT_SUPPORT_MSG, e)
            obs.append(Observation(file_id, "evidence", captured_at, t,
                "support_platform", e["resource_id"], CAT_SUPPORT_MSG, st,
                frozenset(em), frozenset(ui), frozenset(ph), frozenset(ha), attributes=e))
        return obs, collections

    if "snapshots" in d:  # customer_data_snapshot_bundle_*
        for snap in d["snapshots"]:
            system = snap["data_store"]; coll = snap["collection"]
            t = snap.get("captured_at", captured_at)
            present_ids = set()
            for rec in snap.get("records", []):
                rid = rec.get("resource_id")
                if not rid: continue
                if coll == "operational_record_history":
                    history, _ = _parse_json_data({"records": [rec]}, file_id, captured_at)
                    obs.extend(history)
                    continue
                cat = category_for(system, coll)
                st = state_for_record(cat, rec)
                em, ui, ph, ha = ids_from_deep(rec)
                obs.append(Observation(file_id, "evidence", captured_at, t,
                    system, rid, cat, st, frozenset(em), frozenset(ui),
                    frozenset(ph), frozenset(ha),
                    collection=f"{system}/{coll}", authoritative=True, attributes=rec))
                obs.extend(bind_obs_for_refs(rec, file_id, captured_at, t,
                                             em, ui, ph, ha))
                present_ids.add(rid)
            if coll != "operational_record_history":
                collections[(system, coll, "service", t)] = present_ids
        return obs, collections

    records = d.get("records")
    if isinstance(records, list):
        for rec in records:
            t = rec.get("recorded_at") or rec.get("captured_at") or captured_at
            rid = rec.get("resource_id")
            if not rid: continue
            system = rec.get("system") or rec.get("source_system") or ""
            rtype = rec.get("record_type", "")
            if not system:
                # analytics_report / export_jobs style: infer from content
                if "metrics" in rec or "audience_cohort" in rec:
                    system = "analytics_platform"
                elif "file_name" in rec or "included_sections" in rec:
                    system = "export_service"
            coll = ""
            cat = category_for(system, coll, rtype)
            if cat == "UNKNOWN":
                if system == "analytics_platform": cat = CAT_ANALYTICS
                elif system == "export_service": cat = CAT_EXPORT
            result = str(rec.get("result", "")).upper()
            if result in ("NOT_FOUND", "ABSENT"):
                st = ABSENT
            elif result in ("IDENTIFIABLE",):
                st = IDENTIFIABLE
            elif result in ("ANONYMIZED",):
                st = ANONYMIZED
            elif result in ("REDACTED",):
                st = CLEAN
            elif result in ("ACTIVE",):
                st = ACTIVE
            elif result in ("DISABLED",):
                st = DISABLED
            elif result in ("BLOCKED",):
                st = BLOCKED
            elif result in ("FOUND", "PRESENT"):
                st = state_for_record(cat, rec) if cat in (
                    CAT_ANALYTICS, CAT_SUPPORT_MSG, CAT_TOMBSTONE) else (
                    RETAINED if cat in RETAIN_CATS else
                    ACTIVE if cat == CAT_DATAFLOW else
                    RISK if cat == CAT_BACKUP else PRESENT)
            else:
                st = state_for_record(cat, rec)
            if system == "security_service": st = RETAINED if st != ABSENT else ABSENT
            em, ui, ph, ha = ids_from_deep(rec)
            obs.append(Observation(file_id, "evidence", captured_at, t,
                system, rid, cat, st, frozenset(em), frozenset(ui),
                frozenset(ph), frozenset(ha), attributes=rec))
        return obs, collections
    return obs, collections
