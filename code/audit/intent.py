"""Deletion-authorization intent classification (multilingual, rule-based).

Non-deletion markers win over deletion markers: several non-deletion texts
mention deletion only to decline it. Anything unclassified is returned as
UNKNOWN so the run can flag it for review instead of guessing.
"""
DELETION_MARKERS = [
    "delet", "erase", "erasure", "close my account", "close this account",
    "close the account", "would like it closed", "like it closed",
    "remove my account", "remove the profile", "remove my profile",
    "remove records", "remove that search result", "remove the personal details",
    "account closure", "suppression", "exclusão", "exclusao",
    "eliminación", "eliminacion", "削除", "삭제",
    "personal details", "already been removed", "is gone", "are gone",
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
    t = request_text.lower()
    for m in NON_DELETION_MARKERS:
        if m in t:
            return "NOT_DELETION"
    for m in DELETION_MARKERS:
        if m in t:
            return "DELETION"
    return "UNKNOWN"
