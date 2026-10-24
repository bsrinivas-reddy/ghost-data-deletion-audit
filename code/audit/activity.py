"""system_activity.csv -> claim observations (never state proof) + bindings."""
import csv, re
from .model import *
from .logparsers import EMAIL_RE, UID_RE

SYSTEM_CATEGORY = {
    "account_service": CAT_PROFILE, "identity_service": CAT_TOMBSTONE,
    "search_service": CAT_SEARCH, "cache_service": CAT_CACHE,
    "support_platform": CAT_SUPPORT_MSG, "analytics_platform": CAT_ANALYTICS,
    "telemetry_platform": CAT_TELEMETRY, "integration_service": CAT_DATAFLOW,
    "backup_service": CAT_BACKUP, "security_service": CAT_SECURITY,
    "export_service": CAT_EXPORT, "marketing_service": CAT_MARKETING,
    "marketing_platform": CAT_MARKETING, "notification_service": CAT_EMAILLOG,
    "legal_service": CAT_LEGAL,
}
# resource-id prefix fallbacks when the owning system is ambiguous
PREFIX = [("account_", "account_service"), ("tombstone_", "identity_service"),
          ("search_", "search_service"), ("cache_", "cache_service"),
          ("support_", "support_platform"), ("analytics_", "analytics_platform"),
          ("telemetry_", "telemetry_platform"), ("data_flow_", "integration_service"),
          ("backup_", "backup_service"), ("audit_record_", "security_service"),
          ("export_", "export_service"), ("marketing_", "marketing_service"),
          ("object_", "support_platform"), ("legal_hold_", "legal_service"),
          ("email_log_", "notification_service"), ("secondary_", "account_service")]

def system_for_resource(rid, source, target):
    for cand in (target, source):
        if cand in SYSTEM_CATEGORY:
            return cand
    for p, s in PREFIX:
        if rid.startswith(p):
            return s
    return target or source or ""

LINK_RE = re.compile(r"linked\s+(\S+)\s+\(([^)]*)\)\s+to\s+(\S+)\s+and\s+(user_\d+)")

def parse_activity(path):
    obs = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rid = r["resource_id"]
            et = r["event_type"]
            details = r["details"]
            system = system_for_resource(rid, r["source_system"], r["target_system"])
            cat = SYSTEM_CATEGORY.get(system, "UNKNOWN")
            if rid.startswith("object_"):
                cat = CAT_SUPPORT_ATT
            m = LINK_RE.search(details)
            emails = set(e.lower() for e in EMAIL_RE.findall(details))
            uids = set(UID_RE.findall(details))
            # deletion/sync claims: state hint only, kept as claim
            st = PRESENT
            if et == "LINK_RESOURCE_IDENTITY":
                st = BIND
            if et in ("DELETE_RECORD",) and r["reported_result"] == "SUCCESS":
                st = ABSENT
            elif et in ("DISABLE_DATA_FLOW",) and r["reported_result"] == "SUCCESS":
                st = DISABLED
            elif et in ("BLOCK_RESTORE",) and r["reported_result"] == "SUCCESS":
                st = BLOCKED
            elif et in ("ANONYMIZE_RECORD",) and r["reported_result"] == "SUCCESS":
                st = ANONYMIZED
            elif et in ("REDACT_RECORD",) and r["reported_result"] == "SUCCESS":
                st = CLEAN
            obs.append(Observation(
                r["activity_id"], "activity", r["event_time"], r["event_time"],
                system, rid, cat, st, frozenset(emails), frozenset(uids),
                frozenset(), frozenset(), claim=True, detail=details[:200]))
    return obs
