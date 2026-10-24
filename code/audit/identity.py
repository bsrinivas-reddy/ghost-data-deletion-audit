"""Identity resolution: current snapshot + historical audit log chains."""
import csv, re
from .parsers import norm_phone

class Identities:
    def __init__(self, ds):
        self.users = {}        # uid -> dict(emails,set phones,set hashes,set name)
        self.email_to_uid = {} # any known email (lower) -> uid
        self.phone_to_uid = {}
        self.hash_to_uid = {}
        import os
        with open(os.path.join(ds, "user_identities.csv")) as f:
            for r in csv.DictReader(f):
                u = self.users.setdefault(r["user_id"], {
                    "emails": set(), "phones": set(), "hashes": set(),
                    "name": r["name"]})
                e = r["email"].strip().lower()
                u["emails"].add(e)
                p = norm_phone(r["phone"])
                if p: u["phones"].add(p)
                if r["email_hash"]: u["hashes"].add(r["email_hash"])
        with open(os.path.join(ds, "user_audit_log.csv")) as f:
            for a in csv.DictReader(f):
                u = self.users.setdefault(a["user_id"], {
                    "emails": set(), "phones": set(), "hashes": set(), "name": ""})
                fn = a["field_name"]
                for val in (a["old_value"], a["new_value"]):
                    if not val: continue
                    if fn == "email":
                        u["emails"].add(val.strip().lower())
                    elif fn == "phone":
                        p = norm_phone(val)
                        if p: u["phones"].add(p)
                    elif fn == "email_hash":
                        u["hashes"].add(val)
        for uid, u in self.users.items():
            for e in u["emails"]: self.email_to_uid[e] = uid
            for p in u["phones"]: self.phone_to_uid[p] = uid
            for h in u["hashes"]: self.hash_to_uid[h] = uid

    def resolve_email(self, email):
        return self.email_to_uid.get(email.strip().lower())

    def identifier_set(self, request_email, uid):
        emails, phones, hashes, uids = set(), set(), set(), set()
        emails.add(request_email.strip().lower())
        if uid:
            uids.add(uid)
            u = self.users.get(uid, {})
            emails |= u.get("emails", set())
            phones |= u.get("phones", set())
            hashes |= u.get("hashes", set())
        return {"emails": emails, "phones": phones, "hashes": hashes, "uids": uids}
