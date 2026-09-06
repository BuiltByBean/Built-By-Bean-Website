"""Read each business's own website for the things only it publishes.

A directory gives you a switchboard number. A business's own site gives you
the address people actually answer, the mobile on the contact page, and the
name of whoever runs it. That last one is what a cold call needs: asking for
a person by name is a different conversation from asking whoever picks up.

What it takes, in order of how much it can be trusted:

  emails    mailto: links first, then addresses in the text. An address at
            the business's own domain beats a free mailbox.
  people    a name derived from a personal mailbox (john.smith@acme.com is
            John Smith, and that is close to certain), then names sitting
            next to a job title in the page's own words.
  phones    tel: links first, then US-shaped numbers in the text.
  headcount only where the business states it in its own words, "a team of
            twelve", and only then. Nothing is estimated.

Precision over recall throughout. A wrong name on a call sheet is worse than
a blank one, because somebody will read it out.

    python enrich_sites.py            # every lead with a site, not yet read
    python enrich_sites.py --recheck  # all of them again
"""
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

UA = {"User-Agent": "BuiltByBean-Leads/1.0 (michael@builtbybean.com)"}

# Pages worth asking for beyond the homepage, best first.
LIKELY = ("/contact", "/contact-us", "/contactus", "/about", "/about-us",
          "/our-team", "/team", "/staff", "/meet-the-team", "/leadership",
          "/our-staff", "/who-we-are")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
JUNK_EMAIL = re.compile(
    r"(sentry|wixpress|example\.|\.png|\.jpg|\.jpeg|\.gif|\.webp|\.svg|@2x|"
    r"yourdomain|domain\.com|email\.com|sample|test@|noreply|no-reply|"
    r"donotreply|godaddy|squarespace|wordpress|shopify|cloudflare|"
    r"@sentry\.|@example)", re.I)

PHONE_RE = re.compile(r"(?:\+?1[\s.\-]?)?\(?([2-9]\d{2})\)?[\s.\-]?(\d{3})[\s.\-]?(\d{4})(?!\d)")

# Titles worth carrying onto a call sheet, longest first so "Vice President"
# wins over "President".
TITLES = [
    "Chief Executive Officer", "Chief Operating Officer", "Chief Financial Officer",
    "Vice President", "Managing Partner", "Managing Director", "General Manager",
    "Office Manager", "Practice Manager", "Store Manager", "Sales Manager",
    "Operations Manager", "Marketing Manager", "Branch Manager", "Owner/Operator",
    "Co-Owner", "Co-Founder", "President", "Founder", "Principal", "Partner",
    "Proprietor", "Owner", "Director", "Manager", "Superintendent", "Broker",
    "Agent", "Realtor", "Attorney", "Pastor", "Administrator", "Supervisor",
    "Estimator", "Foreman", "Dispatcher", "Controller", "Bookkeeper",
]
TITLE_RE = re.compile("(" + "|".join(re.escape(t) for t in TITLES) + ")", re.I)

# A person's name: two or three capitalised words, optionally a middle
# initial. Deliberately narrow.
NAME_RE = re.compile(r"\b([A-Z][a-z'\-]{1,15}(?: [A-Z]\.?)? [A-Z][a-z'\-]{1,20})\b")

# Forenames people are actually given. The surname can be anything, but the
# first word has to be a name, or "Featured There" and "Founding Member"
# become contacts. See the note at the top of the file.
FORENAMES = set("""
james robert john michael david william richard joseph thomas charles
christopher daniel matthew anthony mark donald steven paul andrew joshua
kenneth kevin brian george timothy ronald jason edward jeffrey ryan jacob
gary nicholas eric jonathan stephen larry justin scott brandon benjamin
samuel gregory alexander patrick frank raymond jack dennis jerry tyler
aaron jose adam nathan henry zachary douglas peter kyle noah ethan jeremy
walter christian keith roger terry austin sean gerald carl harold dylan
arthur lawrence jordan jesse bryan billy bruce gabriel joe logan alan juan
albert willie elijah wayne randy vincent mason roy ralph bobby russell
bradley philip eugene shawn louis jeffery jimmy craig cody johnny luke
ricky martin marcus danny dale curtis lee travis clarence chris tony jared
mike glenn allen dean cameron jonathon derek warren barry alexis lonnie
rodney bill jim tom dan bob ron rick steve dave mike ricardo
mary patricia jennifer linda elizabeth barbara susan jessica sarah karen
lisa nancy betty margaret sandra ashley kimberly emily donna michelle
carol amanda dorothy melissa deborah stephanie rebecca sharon laura cynthia
kathleen amy angela shirley anna brenda pamela emma nicole helen samantha
katherine christine debra rachel carolyn janet catherine maria heather
diane ruth julie olivia joyce virginia victoria kelly lauren christina joan
evelyn judith megan andrea cheryl hannah jacqueline martha gloria teresa
ann sara madison frances kathryn janice jean abigail alice julia judy
sophia grace denise amber doris marilyn danielle beverly isabella theresa
diana natalie brittany charlotte marie kayla alexis lori tammy tracy holly
crystal robin jane brandi misty kandace kandice regina wanda tina dana
leslie erin stacy monica jill cassandra sherry connie april tonya renee
kristen lindsay whitney courtney kristin allison vicki bonnie shannon
marla marsha marcia darlene charlene arlene earlene maxine geraldine
bernice lorraine yolanda gwendolyn rosalind clarice bobbie billie jodie
jodi jaime jamie kerry kelli kellie staci stacie traci tracie terri terrie
sherri sheri cheri jeri gerri toni roni dee della nadine claudine
kathi cathy kathie kate katie kim kimberley tammi tami pam pammy peg peggy
sue susie suzy liz lizzie beth bethany becky becki jen jenny jenna
abby gail gayle joann joanne jolene marlene charlie chuck hank hal
gus otis clyde earl floyd wilbur delbert dewayne dwayne duane lyle merle
orville virgil vernon marvin melvin alvin calvin elmer homer roscoe
buster junior sonny cotton rusty dusty shorty jd tj cj rj bj
""".split())

# Words that mean the capitalised pair is a business, not a person.
NOT_A_PERSON = re.compile(
    r"\b(llc|inc|company|corp|service|services|solutions|group|center|centre|"
    r"clinic|hospital|church|school|store|shop|repair|supply|insurance|realty|"
    r"county|texas|paris|street|road|avenue|drive|suite|monday|tuesday|"
    r"wednesday|thursday|friday|saturday|sunday|january|february|march|april|"
    r"june|july|august|september|october|november|december|privacy|policy|"
    r"terms|contact|about|home|our|the|we|you|your|all rights|read more|"
    r"learn more|get started|customer|reviews?|google|facebook|website|"
    # The words businesses end in. A forename plus one of these is a trading
    # name, not a person: Christian Ministries, Russell Cellular.
    r"ministries|ministry|cellular|department|distributing|distributors|"
    r"industries|industrial|equipment|rentals|rental|systems|technologies|"
    r"technology|associates|partners|brands|holdings|motors|foods|farms|"
    r"ranch|chapel|temple|tabernacle|fellowship|outreach|assembly|"
    r"enterprises|properties|investments|construction|plumbing|electric|"
    r"heating|cooling|roofing|flooring|landscaping|trucking|transport|"
    r"logistics|storage|wireless|communications|financial|mortgage|"
    r"agency|studios|salon|barbers|bakery|grill|cafe|diner|pizza|"
    r"chevrolet|ford|toyota|honda|dodge|nissan)\b", re.I)

HEADCOUNT_RE = re.compile(
    r"(?:team of|staff of|employs|employing|workforce of|family of)\s+"
    r"(?:over\s+|more than\s+|nearly\s+|about\s+|some\s+)?([0-9]{1,4})\b"
    r"|\b([0-9]{1,4})\+?\s+(?:employees|team members|staff members|"
    r"technicians|associates)\b", re.I)

REVENUE_RE = re.compile(
    r"(?:annual (?:revenue|sales)|revenue of|sales of)\s*(?:over|more than|about)?\s*"
    r"\$\s?([0-9][0-9,.]*)\s*(million|billion|m|b)?\b", re.I)


def strip_tags(html):
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def fetch(url, timeout=9):
    context = ssl.create_default_context()
    # A small business's certificate is often wrong. It says nothing about
    # whether the page is theirs.
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(
                urllib.request.Request(url, headers=UA), timeout=timeout, context=context) as r:
            if r.status >= 400:
                return ""
            kind = (r.headers.get("Content-Type") or "").lower()
            if "html" not in kind and kind:
                return ""
            return r.read(500000).decode("utf-8", "ignore")
    except Exception:
        return ""


def inner_pages(html, base):
    """Contact and team pages this site actually links to, plus the usual
    guesses. Its own links first: a site that calls it /connect is not going
    to be found by guessing."""
    host = urllib.parse.urlparse(base).netloc.lower()
    found, seen = [], set()
    for href in re.findall(r'href=["\']([^"\']+)["\']', html or "", re.I):
        low = href.lower()
        if not any(w in low for w in ("contact", "about", "team", "staff",
                                      "leadership", "who-we-are", "meet")):
            continue
        full = urllib.parse.urljoin(base, href)
        parsed = urllib.parse.urlparse(full)
        if parsed.netloc.lower() != host or parsed.scheme not in ("http", "https"):
            continue
        clean = parsed._replace(fragment="", query="").geturl()
        if clean not in seen:
            seen.add(clean)
            found.append(clean)
    for guess in LIKELY:
        full = base.rstrip("/") + guess
        if full not in seen:
            seen.add(full)
            found.append(full)
    return found[:5]


def emails_from(html, host):
    out = []
    for match in re.findall(r'mailto:([^"\'>?\s]+)', html or "", re.I):
        out.append(match)
    out.extend(EMAIL_RE.findall(strip_tags(html or "")))
    clean, seen = [], set()
    for raw in out:
        mail = raw.strip().strip(".,;:").lower()
        if not EMAIL_RE.fullmatch(mail) or JUNK_EMAIL.search(mail) or len(mail) > 90:
            continue
        if mail in seen:
            continue
        seen.add(mail)
        clean.append(mail)
    # Their own domain first: info@theirsite.com beats a gmail in a footer.
    stem = host.replace("www.", "").split(".")[0] if host else ""
    clean.sort(key=lambda m: 0 if stem and stem in m.split("@")[-1] else 1)
    return clean


def phones_from(html):
    out = []
    for raw in re.findall(r'tel:([+0-9()\s.\-]{7,})', html or "", re.I):
        out.append(raw)
    out.extend(" ".join(m) for m in PHONE_RE.findall(strip_tags(html or "")))
    clean, seen = [], set()
    for raw in out:
        digits = re.sub(r"\D", "", raw)
        if len(digits) == 11 and digits.startswith("1"):
            digits = digits[1:]
        if len(digits) != 10 or digits in seen or digits[0] in "01":
            continue
        seen.add(digits)
        clean.append(digits)
    return clean


def name_from_email(mail):
    """john.smith@acme.com is John Smith. A mailbox named after a person is
    about as reliable as this gets, and info@ is not one."""
    local = mail.split("@")[0]
    if local.lower() in {
            "info", "contact", "office", "sales", "admin", "hello", "mail",
            "support", "service", "help", "team", "enquiries", "inquiries",
            "billing", "accounts", "accounting", "orders", "shop", "booking",
            "reservations", "frontdesk", "reception", "hr", "jobs", "careers",
            "webmaster", "postmaster", "manager", "owner", "general"}:
        return ""
    parts = [p for p in re.split(r"[._\-]+", local) if p.isalpha() and len(p) > 1]
    if len(parts) < 2 or len(parts) > 3:
        return ""
    if any(len(p) > 18 for p in parts):
        return ""
    # prmc.gme@ and credit_department@ are shaped exactly like
    # firstname.lastname@, so a mailbox has to pass the same forename test
    # as a name read off a page.
    if parts[0].lower() not in FORENAMES:
        return ""
    if NOT_A_PERSON.search(" ".join(parts)):
        return ""
    return " ".join(p.capitalize() for p in parts)


def people_from(html):
    """Names sitting beside a job title in the page's own words.

    Each title takes the NEAREST name, not every name within a window. A
    staff page reads "Dale Pruitt, Owner, Marla Quinn, Office Manager", and
    a symmetric window hands Marla the title above her: two people, both
    wrong. Distance decides, and a name before its title beats one after,
    because that is how a staff list is written.
    """
    text = strip_tags(html or "")
    # Titles first, because stripping the tags puts a name and the title
    # under it into one line: "Marla Quinn Office Manager Ray Hobbs General
    # Manager". A capitalised pair that overlaps a title is half a title,
    # and "Quinn Office" is not a person.
    titles = [(m.start(), m.end(), m.group(1)) for m in TITLE_RE.finditer(text)]

    # The titles are MASKED before names are looked for, not filtered after.
    # A non-overlapping scan reads "Owner Marla" as a name, and having eaten
    # it, never offers "Marla Quinn"; blanking the title first stops a name
    # forming across one at all. Same length, so every offset still lines up.
    masked = list(text)
    for start, end, _ in titles:
        masked[start:end] = " " * (end - start)
    masked = "".join(masked)

    names = [(m.start(), m.end(), m.group(1)) for m in NAME_RE.finditer(masked)
             if not NOT_A_PERSON.search(m.group(1))
             and m.group(1).split()[0].lower() in FORENAMES]
    if not names:
        return []

    pairs = []
    for hit_start, hit_end, hit_title in titles:
        best, best_gap = None, 61
        for start, end, name in names:
            if end <= hit_start:
                gap = hit_start - end            # name then title
            elif start >= hit_end:
                gap = (start - hit_end) + 12     # title then name, less likely
            else:
                continue
            if gap < best_gap:
                best, best_gap = (name, hit_title.title()), gap
        if best:
            pairs.append((best_gap, best[0], best[1]))

    pairs.sort()
    seen, out = set(), []
    for _, name, title in pairs:
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({"name": name, "role": title})
    return out[:6]


def headcount_from(text):
    for match in HEADCOUNT_RE.finditer(text):
        raw = match.group(1) or match.group(2)
        try:
            n = int(raw)
        except (TypeError, ValueError):
            continue
        if 1 <= n <= 5000:
            return n
    return None


def revenue_from(text):
    match = REVENUE_RE.search(text)
    if not match:
        return None
    try:
        amount = float(match.group(1).replace(",", ""))
    except ValueError:
        return None
    scale = (match.group(2) or "").lower()
    if scale in ("million", "m"):
        amount *= 1_000_000
    elif scale in ("billion", "b"):
        amount *= 1_000_000_000
    return amount if 1000 <= amount <= 10_000_000_000 else None


def _own_name(business, person):
    """A business is never its own contact."""
    if not business:
        return False
    words = {w for w in re.findall(r"[a-z]{3,}", business.lower())}
    return all(w in words for w in re.findall(r"[a-z]{3,}", person.lower()))


def read_site(site, business=""):
    """Everything one business publishes about how to reach it."""
    host = urllib.parse.urlparse(site).netloc.lower()
    home = fetch(site)
    if not home:
        return None
    pages = [home]
    for url in inner_pages(home, site):
        html = fetch(url)
        if html:
            pages.append(html)

    blob = " ".join(pages)
    text = strip_tags(blob)
    mails = emails_from(blob, host)
    people = []
    for mail in mails[:6]:
        person = name_from_email(mail)
        if person:
            people.append({"name": person, "role": "", "email": mail})
    for person in people_from(blob):
        if not any(p["name"].lower() == person["name"].lower() for p in people):
            people.append({"name": person["name"], "role": person["role"], "email": ""})
    people = [p for p in people if not _own_name(business, p["name"])]

    return {
        "emails": mails,
        "phones": phones_from(blob),
        "people": people[:6],
        "employees": headcount_from(text),
        "revenue": revenue_from(text),
        "pages": len(pages),
    }


def run(recheck=False, workers=20, limit=None):
    from app import create_app
    from models import db, Lead, LeadPerson

    app = create_app()
    with app.app_context():
        query = Lead.query.filter(Lead.website.isnot(None), Lead.website != "")
        if not recheck:
            query = query.filter(~Lead.sources.like("%site%"))
        leads = query.all()
        if limit:
            leads = leads[:limit]
        print(f"{len(leads)} websites to read")

        jobs = [(l.id, l.website, l.name) for l in leads]
        got = {"email": 0, "phone": 0, "people": 0, "staff": 0, "revenue": 0}
        done = 0
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for (lead_id, _, _n), found in zip(
                    jobs, pool.map(lambda j: read_site(j[1], j[2]), jobs)):
                done += 1
                if not found:
                    continue
                lead = db.session.get(Lead, lead_id)
                if lead is None:
                    continue
                if found["emails"] and not (lead.email or "").strip():
                    lead.email = found["emails"][0][:200]
                    got["email"] += 1
                if found["phones"] and not (lead.phone or "").strip():
                    lead.phone = found["phones"][0]
                    got["phone"] += 1
                if found["employees"] and lead.employees is None:
                    lead.employees = found["employees"]
                    got["staff"] += 1
                if found["revenue"] and lead.revenue is None:
                    lead.revenue = found["revenue"]
                    got["revenue"] += 1
                have = {(p.name or "").lower() for p in lead.people}
                order = len(lead.people)
                for person in found["people"]:
                    key = person["name"].lower()
                    if key in have:
                        continue
                    have.add(key)
                    db.session.add(LeadPerson(
                        lead_id=lead.id, name=person["name"][:160],
                        role=(person.get("role") or "")[:120],
                        email=(person.get("email") or "")[:200], source="site",
                        sort_order=order))
                    order += 1
                    got["people"] += 1
                marks = [m for m in (lead.sources or "").split(",") if m]
                if "site" not in marks:
                    marks.append("site")
                lead.sources = ",".join(marks)[:200]
                if done % 100 == 0:
                    db.session.commit()
                    print(f"   {done}/{len(jobs)} read | +{got['email']} emails "
                          f"+{got['phone']} phones +{got['people']} people")
        db.session.commit()

        total = Lead.query.count()
        print(f"\nfrom their own sites: {got['email']} emails, {got['phone']} phones, "
              f"{got['people']} named contacts, {got['staff']} headcounts, "
              f"{got['revenue']} revenue figures")
        print(f"of {total} businesses: "
              f"{Lead.query.filter(Lead.email != '', Lead.email.isnot(None)).count()} have an email, "
              f"{Lead.query.filter(Lead.phone != '', Lead.phone.isnot(None)).count()} a phone, "
              f"{LeadPerson.query.count()} named contacts on file")


if __name__ == "__main__":
    args = sys.argv[1:]
    cap = int(args[args.index("--limit") + 1]) if "--limit" in args else None
    run(recheck="--recheck" in args, limit=cap)
