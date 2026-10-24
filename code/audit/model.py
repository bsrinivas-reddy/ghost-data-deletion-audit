"""Unified observation model for the deletion-audit engine.

Every parser (SQL snapshots, JSON exports, logs, text handovers, media
extractions, and the global activity stream) normalizes what it sees into
Observation records. The engine reasons only over Observations.
"""
from dataclasses import dataclass, field

# Record states (what the evidence shows about one resource at one time)
PRESENT = "PRESENT"            # record exists (carries personal data by nature)
IDENTIFIABLE = "IDENTIFIABLE"  # record exists and still carries direct identifiers
CLEAN = "CLEAN"                # record exists, direct identifiers removed (redacted)
ANONYMIZED = "ANONYMIZED"      # record irreversibly unlinked from the user
ACTIVE = "ACTIVE"              # data flow enabled / restore path open
DISABLED = "DISABLED"          # data flow stopped
RISK = "RISK"                  # backup restore allowed
BLOCKED = "BLOCKED"            # backup restore blocked
ABSENT = "ABSENT"              # authoritative proof the record is gone
RETAINED = "RETAINED"          # record present and required by policy (audit/legal)
BIND = "BIND"                  # identity cross-reference only; never a state proof

# Data categories (mirror deletion_rules.csv data_category values, plus
# DATA_FLOW for sync/connector processes which the rules treat via
# "no active sync, import, or restore path can recreate the data")
CAT_PROFILE = "USER_PROFILE"
CAT_SECONDARY = "SECONDARY_IDENTIFIER"
CAT_SEARCH = "SEARCH_INDEX_ENTRY"
CAT_CACHE = "CACHE_ENTRY"
CAT_SUPPORT_MSG = "SUPPORT_MESSAGE"
CAT_SUPPORT_ATT = "SUPPORT_ATTACHMENT"
CAT_ANALYTICS = "ANALYTICS_PROFILE"
CAT_TELEMETRY = "PRODUCT_TELEMETRY"
CAT_EXPORT = "USER_EXPORT"
CAT_MARKETING = "MARKETING_PROFILE"
CAT_EMAILLOG = "EMAIL_DELIVERY_LOG"
CAT_SECURITY = "SECURITY_AUDIT_LOG"
CAT_LEGAL = "LEGAL_HOLD_RECORD"
CAT_BACKUP = "BACKUP_ARCHIVE"
CAT_TOMBSTONE = "ACCOUNT_TOMBSTONE"
CAT_DATAFLOW = "DATA_FLOW"

# Required end-state per category once deletion is authorized.
# Maps category -> (verification operation, compliant states, remediation op)
DELETE_CATS = {CAT_PROFILE, CAT_SECONDARY, CAT_SEARCH, CAT_CACHE,
               CAT_SUPPORT_ATT, CAT_EXPORT, CAT_MARKETING}
REDACT_CATS = {CAT_SUPPORT_MSG, CAT_EMAILLOG, CAT_TOMBSTONE}
ANONYMIZE_CATS = {CAT_ANALYTICS, CAT_TELEMETRY}
RETAIN_CATS = {CAT_SECURITY, CAT_LEGAL}

@dataclass
class Observation:
    evidence_id: str          # evidence_NN (file) or activity_NN (claim)
    source_kind: str          # 'evidence' | 'activity' | 'media'
    captured_at: str          # file-level capture time (ISO) / activity time
    obs_time: str             # record-level time when known, else captured_at
    system_id: str
    resource_id: str
    category: str
    state: str
    emails: frozenset = frozenset()
    user_ids: frozenset = frozenset()
    phones: frozenset = frozenset()
    hashes: frozenset = frozenset()
    collection: str = ""      # collection key for authoritative snapshots
    authoritative: bool = False  # collection-level capture: absence is provable
    claim: bool = False       # True for system_activity claims (never state proof)
    detail: str = ""

    def identifiers(self):
        return self.emails | self.user_ids | self.phones | self.hashes
