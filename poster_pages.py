"""Read-only Google Maps assertions shared by poster resolution and saved checks."""
import re
import time
from urllib.parse import parse_qs, urlsplit

from review_store import ReviewError, business_location, normalize_name


def business_details(page, email, timeout=15000):
    from poster import ReviewWorker
    page.locator('h1, [role="heading"][aria-level="1"]').first.wait_for(state="visible", timeout=timeout)
    ReviewWorker._check_google_page(page)
    heading = page.locator("h1.DUwDvf")
    if not heading.count():
        heading = page.get_by_role("heading", level=1).filter(has_not_text=re.compile(r"^Results$", re.I))
    name = ReviewWorker._one_visible(heading).inner_text().strip()
    if not name or len(name) > 200:
        raise ReviewError("Open a specific business link with a readable business name.")
    deadline = time.monotonic() + timeout / 1000
    while True:
        try:
            actual_email = ReviewWorker._account(page)
            break
        except ReviewError:
            if time.monotonic() >= deadline:
                raise
            page.wait_for_timeout(150)
    if actual_email != email:
        raise ReviewError("Google is signed into a different account. Nothing was submitted.", 409)
    address = ""
    addresses = page.locator('[data-item-id="address"]')
    visible = [addresses.nth(i) for i in range(min(addresses.count(), 100)) if addresses.nth(i).is_visible()]
    if len(visible) == 1:
        label = visible[0].get_attribute("aria-label") or ""
        if label.lower().startswith("address:"):
            address = label.split(":", 1)[1].strip()
        elif visible[0].locator(".Io6YTe").count() == 1:
            address = visible[0].locator(".Io6YTe").inner_text().strip()
    location = business_location(page.url, address)
    return {"name": name, "email": actual_email, "url": page.url, "address": location["business_address"],
            "latitude": location["business_latitude"], "longitude": location["business_longitude"]}


def validate_widget(form, original, review):
    location = urlsplit(form.evaluate("() => location.href"))
    if location.path != "/maps/api/js/ReviewsService.LoadWriteWidget":
        return
    parent = urlsplit(original.url)
    account = lambda url: parse_qs(url.query).get("authuser", ["0"])[0]
    if ((location.scheme, location.netloc) != (parent.scheme, parent.netloc)
            or account(location) != account(parent) or not parse_qs(location.query).get("placeid")):
        raise ReviewError("The review iframe belongs to another account or origin.", 409)
    heading = form.locator('h1, h2, [role="heading"]')
    names = [heading.nth(i).inner_text() for i in range(min(heading.count(), 100)) if heading.nth(i).is_visible()]
    if sum(normalize_name(name) == normalize_name(review["expected_name"]) for name in names) != 1:
        raise ReviewError("The review iframe business does not match the draft.", 409)


def saved_review(page, review, timeout=10000):
    from poster import business_key
    info = business_details(page, review["account_email"], min(timeout, 15000))
    if (normalize_name(info["name"]) != normalize_name(review["expected_name"])
            or business_key(info["url"], info["name"]) != review["business_key"]):
        raise ReviewError("The saved-review business does not match.", 409)
    deadline = time.monotonic() + timeout / 1000
    while True:
        proof = page.evaluate("""() => {
          const visible = n => n && n.getClientRects().length && getComputedStyle(n).visibility !== 'hidden';
          const headings = [...document.querySelectorAll('h2,[role="heading"]')]
            .filter(n => visible(n) && n.textContent.trim() === 'Your review');
          if (headings.length !== 1) return null;
          const card = headings[0].parentElement?.nextElementSibling;
          if (!visible(card) || !card.matches('[data-review-id]')) return null;
          const text = [...card.querySelectorAll('.wiI7pd')].filter(visible);
          const stars = [...card.querySelectorAll('[role="img"][aria-label]')]
            .filter(n => visible(n) && /^[1-5] stars?$/.test(n.getAttribute('aria-label')));
          let sibling = card.nextElementSibling, editable = false;
          for (let i = 0; sibling && i < 3; i++, sibling = sibling.nextElementSibling) {
            if ([...sibling.querySelectorAll('h1,h2,[role="heading"],[data-review-id]')].some(visible)) break;
            editable ||= [...sibling.querySelectorAll('button,[role="button"]')].some(n =>
              visible(n) && (n.getAttribute('aria-label') || n.textContent).trim() === 'Edit your review');
          }
          if (!editable || text.length !== 1 || stars.length !== 1) return null;
          return {id:card.getAttribute('data-review-id'), text:text[0].textContent,
                  stars:Number(stars[0].getAttribute('aria-label')[0])};
        }""")
        if (proof and isinstance(proof.get("id"), str) and 0 < len(proof["id"]) <= 500
                and proof["text"].replace("\r\n", "\n") == review["text"].replace("\r\n", "\n")
                and proof["stars"] == review["stars"]):
            current = business_details(page, review["account_email"], min(timeout, 15000))
            if (normalize_name(current["name"]) != normalize_name(review["expected_name"])
                    or business_key(current["url"], current["name"]) != review["business_key"]):
                raise ReviewError("The account or business changed while checking the saved review.", 409)
            return proof["id"]
        if time.monotonic() >= deadline:
            raise ReviewError("A matching saved review was not found. Nothing was reposted.", 409)
        page.wait_for_timeout(200)
