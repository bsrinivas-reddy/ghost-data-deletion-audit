"""Deletion-authorization intent classification (multilingual, rule-based).

Non-deletion markers win over deletion markers: several non-deletion texts
mention deletion only to decline it. Anything unclassified is returned as
UNKNOWN so the run can flag it for review instead of guessing.
"""
import re

DELETION_MARKERS = [
    "delet", "erase", "erasure", "close my account", "close this account",
    "close the account", "would like it closed", "like it closed",
    "remove my account", "remove the profile", "remove my profile",
    "remove records", "remove that search result", "remove the personal details",
    "account closure", "suppression", "exclusão", "exclusao",
    "eliminación", "eliminacion", "削除", "삭제",
    "already been removed", "is gone", "are gone",
    "be gone", "cannot identify me", "permanently removed",
]
NON_DELETION_MARKERS = [
    "not a request to erase", "don't delete", "do not delete",
    "not asking for deletion", "do not close", "keep the account",
    "keep my account", "leave the account active", "leave my profile",
    "still need the account", "still use it", "continue using the service",
    "without removing any of my records", "marketing lists only",
    "promotional emails", "download my account", "copy of the information",
    "copy of last year's invoices", "what personal information",
    "resetting the login", "change the email address",
    "replace it with the new one", "correct it", "misspelled",
    "out of date", "information request", "portable format",
    "i still want receipts", "i am not asking",
]

def classify(request_text):
    t = request_text.lower().replace("’", "'")
    clauses = re.split(r"[.!?;]+|\bbut\b|\bhowever\b", t)
    negative_patterns = [
        r"\b(?:do not|don't|not asking (?:you )?to|never)\s+(?:delete|erase|close|remove)",
        r"\bnot (?:a )?request (?:for|to) (?:deletion|erase|delete)",
        r"\bno\s+(?:borres|elimine|elimines|borrar|eliminar)",
        r"\bn(?:e|')?\s*(?:supprimez|effacez).{0,20}\bpas\b",
        r"(?:삭제하지|削除しない)",
    ]
    negative = any(re.search(p, c) for p in negative_patterns for c in clauses)
    positive_clauses = []
    for c in clauses:
        if any(re.search(p, c) for p in negative_patterns):
            continue
        if any(m in c for m in DELETION_MARKERS):
            positive_clauses.append(c)
    if negative:
        return "UNKNOWN" if positive_clauses else "NOT_DELETION"
    for m in NON_DELETION_MARKERS:
        if m in t:
            return "NOT_DELETION"
    for m in DELETION_MARKERS:
        if m in t:
            return "DELETION"
    return "UNKNOWN"
