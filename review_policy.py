"""Local advisory checks, not Google's moderation engine or a publication score."""
import re

POLICY_URL = "https://support.google.com/contributionpolicy/answer/7400114?hl=en"
QUALITY_URL = "https://support.google.com/maps/answer/10357321?hl=en"
APPEAL_URL = "https://support.google.com/contributionpolicy/answer/12648169?hl=en"


def review_warnings(text, repeated=False):
    """Return fixed messages only; never rewrite, upload or echo personal details."""
    warnings = []
    if re.search(r"\b(?:https?://|www\.)\S+", text, re.I):
        warnings.append({"code": "website", "message":
            "Website link detected. Google's review policy prohibits website/social links in reviews; keep the review about your own experience."})
    if re.search(r"[\w.+%\-]+@[\w.\-]+\.[a-z]{2,}", text, re.I):
        warnings.append({"code": "email", "message":
            "Email address detected. Remove contact details from a public review; do not expose personal information."})
    numbers = re.findall(r"(?<!\w)\+?\d[\d ()\-]*\d(?!\w)", text)
    if any(10 <= sum(character.isdigit() for character in number) <= 15 for number in numbers):
        warnings.append({"code": "possible_phone", "message":
            "Possible phone number or long identifier detected. Check it manually: phone numbers and private identifiers should not be included in reviews."})
    if repeated and text.strip():
        warnings.append({"code": "repeated_text", "message":
            "The same wording exists in local submitted or uncertain history. Check the existing review; do not duplicate or repost an uncertain submission."})
    return warnings
