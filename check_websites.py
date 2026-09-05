"""Find out whether a lead actually has a website, rather than assuming.

The board used to leave the website blank and call that "no website". Nobody
had looked: a site was recorded only when a map or a directory happened to
list one, and those cover a rural county thinly. An absence of data is not a
finding, so the page stopped saying it.

This is the looking. For each business it builds the handful of domains that
business would plausibly own, resolves them, fetches the ones that exist and
reads the page to decide whether it really belongs to them. A hit is proof.
A miss is not proof of absence, so the column it fills is `website_checked_at`
and the number the board shows is "no site found", which is what was actually
established.

Run it after import_leads.py:

    python check_websites.py                # everything unchecked
    python check_websites.py --recheck      # everything, again
"""
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

UA = {"User-Agent": "BuiltByBean-Leads/1.0 (michael@builtbybean.com)"}

# Words that are in half the names in the county and identify nobody.
NOISE = {
    "the", "and", "of", "a", "an", "co", "company", "inc", "incorporated",
    "llc", "l", "c", "ltd", "limited", "lp", "llp", "pllc", "pc", "pa",
    "corp", "corporation", "enterprises", "enterprise", "group", "holdings",
    "services", "service", "solutions", "texas", "tx", "usa", "dba",
}

# A registrar's holding page is a domain that exists and a business that has
# no website, which is the answer this is trying not to get wrong.
PARKED = re.compile(
    r"(domain (is )?(for sale|may be for sale|parking)|buy this domain|"
    r"this domain is parked|godaddy\.com/domainsearch|sedoparking|"
    r"hugedomains|afternic|dan\.com|namecheap parking|"
    r"future home of something quite cool|default web site page|"
    r"apache2 (ubuntu|debian) default page|welcome to nginx|"
    r"site not published|coming soon)", re.I)

TLDS = ("com", "net", "org")


def tokens(name):
    bare = re.sub(r"[^a-z0-9 ]+", " ", (name or "").lower())
    return [t for t in bare.split() if t and t not in NOISE]


def candidates(name):
    """The domains this business would plausibly own, best guess first."""
    words = tokens(name)
    if not words:
        return []
    stems, seen = [], set()

    def add(stem):
        if stem and 3 <= len(stem) <= 40 and stem not in seen:
            seen.add(stem)
            stems.append(stem)

    add("".join(words))
    if len(words) >= 2:
        add("".join(words[:2]))
        add("-".join(words))
    if len(words) >= 3:
        add("".join(words[:3]))
    if len(words) == 1:
        add(words[0])

    out = []
    for stem in stems[:4]:
        for tld in TLDS if len(stems) <= 2 else ("com",):
            out.append(f"{stem}.{tld}")
    return out[:8]


def resolves(domain):
    try:
        socket.getaddrinfo(domain, None)
        return True
    except Exception:
        return False


def fetch(url, timeout=8):
    context = ssl.create_default_context()
    # A small business's certificate is often wrong or expired. That says
    # nothing about whether the site is theirs, which is all this asks.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=timeout, context=context) as r:
            if r.status >= 400:
                return None, None
            body = r.read(300000).decode("utf-8", "ignore")
            return r.geturl(), body
    except Exception:
        return None, None


def theirs(html, name, city):
    """Does this page belong to that business, or did the name just happen to
    be a domain somebody owns."""
    if not html or PARKED.search(html[:6000]):
        return False
    text = re.sub(r"<[^>]+>", " ", html).lower()
    if len(text.strip()) < 200:
        return False
    words = [w for w in tokens(name) if len(w) > 3]
    hits = sum(1 for w in words if w in text)
    town = (city or "").strip().lower()
    # Their own name in their own words, or the name plus the town they are in.
    if hits >= 2:
        return True
    return bool(hits >= 1 and town and len(town) > 3 and town in text)


def look(name, city):
    for domain in candidates(name):
        if not resolves(domain):
            continue
        for scheme in ("https", "http"):
            final, html = fetch(f"{scheme}://{domain}")
            if html and theirs(html, name, city):
                return final or f"{scheme}://{domain}"
            if html:
                break
    return ""


def run(recheck=False, workers=32, limit=None):
    from app import create_app
    from models import db, Lead

    app = create_app()
    with app.app_context():
        query = Lead.query if recheck else Lead.query.filter(Lead.website_checked_at.is_(None))
        leads = query.all()
        if limit:
            leads = leads[:limit]
        # One that a source already handed us is checked and found.
        known = [l for l in leads if (l.website or "").strip()]
        hunt = [l for l in leads if not (l.website or "").strip()]
        print(f"{len(leads)} to check: {len(known)} already have one on file, "
              f"{len(hunt)} to go looking for")

        now = datetime.now(timezone.utc)
        for lead in known:
            lead.website_checked_at = now
        db.session.commit()

        found = 0
        jobs = [(l.id, l.name, l.city) for l in hunt]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = pool.map(lambda j: (j[0], look(j[1], j[2])), jobs)
            for done, (lead_id, site) in enumerate(results, 1):
                lead = db.session.get(Lead, lead_id)
                if site:
                    lead.website = site[:300]
                    found += 1
                lead.website_checked_at = datetime.now(timezone.utc)
                if done % 200 == 0:
                    db.session.commit()
                    print(f"   {done}/{len(jobs)} looked at, {found} sites found")
        db.session.commit()

        total = Lead.query.count()
        checked = Lead.query.filter(Lead.website_checked_at.isnot(None)).count()
        with_site = Lead.query.filter(Lead.website.isnot(None), Lead.website != "").count()
        print(f"\n{found} found by looking. Of {total} businesses, {checked} have been "
              f"checked: {with_site} have a site, {checked - with_site} none found.")


if __name__ == "__main__":
    args = sys.argv[1:]
    cap = None
    if "--limit" in args:
        cap = int(args[args.index("--limit") + 1])
    run(recheck="--recheck" in args, limit=cap)
