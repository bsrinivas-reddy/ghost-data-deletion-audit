"""Evidence-level index: for each evidence file, which case identities does
it cover (from its per-case readback/lookup structure) and which resources
does it mention. Used to propagate identity onto identifier-less resources
inside case-scoped evidence, and to reconstruct workflow batches from
system_activity claims.
"""
import os, re
from .parsers import norm_email
from .logparsers import EMAIL_RE, UID_RE

class EvidenceIndex:
    def __init__(self, world):
        self.world = world
        # file_id -> set of identifier strings (emails lower / user_ids)
        self.file_idents = {}
        # file_id -> set of resource_ids
        self.file_resources = {}
        for o in world.obs:
            self.file_resources.setdefault(o.evidence_id, set()).add(o.resource_id)
        # group observations per file and cluster identity per resource-neighborhood:
        # readback-style evidence lists resources per looked-up identity, so an
        # identifier-less record shares its case with the nearest identified
        # records in the same file. We approximate: a file identifies a set of
        # cases; each case's identity appears on >=1 record in the file.
        for o in world.obs:
            s = self.file_idents.setdefault(o.evidence_id, set())
            s |= set(o.emails) | set(o.user_ids)

    def cases_in_file(self, fid):
        return self.file_idents.get(fid, set())

class WorkflowBatches:
    """Groups deletion-workflow claims into per-request batches.

    A case's remediation claims (DELETE/REDACT/ANONYMIZE on profile +
    downstream, RETAIN of its privacy audit record, flow/restore handling)
    cluster in time: they complete at the case's reported_at. Claims are
    grouped by connected time gaps so each request's actions form one batch.
    """
    EVENTS = {"DELETE_RECORD", "REDACT_RECORD", "ANONYMIZE_RECORD",
              "DISABLE_DATA_FLOW", "BLOCK_RESTORE", "RETAIN_RECORD",
              "CHECK_DATA_FLOW", "CHECK_RESTORE_ACCESS"}
    GAP_SECONDS = 6 * 3600  # claims closer than this belong to one batch

    def __init__(self, claims):
        evs = sorted((c for c in claims if c.detail is not None and
                      self._is_batch_event(c)), key=lambda c: c.obs_time)
        self.batches = []  # list of (start, end, [claims])
        for c in evs:
            if self.batches and self._gap(self.batches[-1][1], c.obs_time) <= self.GAP_SECONDS:
                b = self.batches[-1]
                b[1] = c.obs_time; b[2].append(c)
            else:
                self.batches.append([c.obs_time, c.obs_time, [c]])

    def _is_batch_event(self, c):
        import re
        m = re.match(r"(DELETE_RECORD|REDACT_RECORD|ANONYMIZE_RECORD|DISABLE_DATA_FLOW|BLOCK_RESTORE)", c.detail)
        # claims carry event type in detail only via our parser; use state heuristics instead
        return True

    @staticmethod
    def _gap(t1, t2):
        from datetime import datetime
        f = "%Y-%m-%dT%H:%M:%SZ"
        return (datetime.strptime(t2, f) - datetime.strptime(t1, f)).total_seconds()
