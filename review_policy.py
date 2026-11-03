"""Local review checks and self-attestation, not Google's moderation engine."""
import re

from review_store import ReviewError

POLICY_URL = "https://support.google.com/contributionpolicy/answer/7400114?hl=en"
QUALITY_URL = "https://support.google.com/maps/answer/10357321?hl=en"
APPEAL_URL = "https://support.google.com/contributionpolicy/answer/12648169?hl=en"


def review_warnings(text, repeated=False, cross_account=False):
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
    if cross_account:
        warnings.append({"code": "cross_account_business", "message":
            "This business has a submitted or uncertain review under another local account. Check the existing submission; do not use multiple accounts to duplicate reviews or manipulate ratings."})
    return warnings


def policy_submission_check(data, text, repeated=False, cross_account=False):
    """Validate final consent and clear contact links without changing the draft.

    Returns None or raises ReviewError with fixed, non-sensitive field messages.
    Ambiguous phone numbers, repeated wording and other-account history remain
    advisory; an acknowledgement is not verification of a genuine experience.
    """
    if not isinstance(data, dict) or data.get("policy_confirmed") is not True:
        message = (
            "Confirm this is your own firsthand experience with the correct branch and account, "
            "with no incentives, conflict of interest, or duplicate/multiple-account manipulation. "
            "Review private information, advertising, off-topic content and harassment before posting. "
            "This is your confirmation, not Google's approval."
        )
        raise ReviewError(message, fields={"policy_confirmed": message})
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ReviewError("Check the prepared review text.",
                          fields={"text": "Enter a review of 1 to 4,000 characters."})
    warnings = review_warnings(text, repeated=repeated, cross_account=cross_account)
    if any(warning["code"] in {"website", "email"} for warning in warnings):
        message = "Remove website links and email addresses, then prepare the review again. Your text has not been changed."
        raise ReviewError(message, fields={"text": message})
