"""Which papers each company must hold, which it holds, and which are missing.

Michael, 2026-11-06: "I need to be able to cleanly have a place where I store
my business like IRS documents ... my Texas sales license ... I need these
things to be pointed out to me when there is no upload." The papers
themselves are `BusinessDocument` rows on each business's page; this module
is the one answer to "what should be there", read by the business page, by
Needs attention and by the hub door a company's own app reads
(`/api/hub/documents`), so the three can never disagree.

What a company must hold is decided by what it IS, from what the board
already knows about it, never typed as a list per company:

  formation     Certificate of Formation. Every company the state has on
                file (a formation date, an SOS file number or a Texas
                taxpayer number): it is the proof the LLC exists.
  ein           The IRS letter giving its EIN (a CP 575, or a 147C when the
                first is lost). Same companies: banks, Stripe and every
                1099 ask for it, and the IRS will not send the CP 575 twice.
  sales_permit  The Texas sales and use tax permit. A company that collects
                Texas sales tax (a sales tax WebFile number, a registration
                or first-sale date, or a location on its permit). The state
                says it must be displayed at the place of business.
  operating     The company agreement. A company with more than one owner
                on its Books (EntertainHQ has three): it is what says each
                member's share, and the partnership return's K-1s lean on it.
                A single-member LLC is not required to have one in Texas.
  assumed_name  A DBA's one paper: the Assumed Name Certificate its company
                filed to trade under that name. A DBA has no formation, EIN
                or permit of its own; its company holds those.

Employees would add more (a Texas Workforce Commission account, the IRS
payroll deposits), but the board knows of no employee at any company, so
nothing asks for them yet. When payroll starts, add a requirement here keyed
on whatever records it.

A requirement Michael says does not apply is set aside with "Not needed",
written as a `DeadlineDone` row keyed `paper:<business id>:<kind>` (the same
press-proved record the deadline list uses), and undone the same way. A
company the state has nothing on yet (an idea, "In the works") must hold
nothing: asking an idea for its EIN letter is noise.
"""
import time

from models import BusinessDocument, DeadlineDone, db

# The sidebar badge is built on every page and this walks every business's
# papers, locations and owners. Cached per worker for a minute, cleared by
# every upload, removal and Not needed here (forget), and never used by the
# Needs attention page or the business page, which read it fresh.
_CACHE = {"at": 0.0, "value": None}
_TTL = 60

# Label for each requirement, then why it is asked for, said once here so the
# business page and the attention row say it the same way.
WHY = {
    "formation": "Texas's record that the company exists",
    "ein": "The IRS letter with its EIN, asked for by banks, Stripe and every 1099",
    "sales_permit": "Its permit to collect Texas sales tax, to display where it trades",
    "operating": "The members' agreement that says each owner's share",
    "assumed_name": "The certificate its company filed to trade under this name",
}


def kind_label(kind):
    return dict(BusinessDocument.KINDS).get(kind, "Other")


def _formed(b):
    return bool(b.formed_on or (b.sos_file_number or "").strip()
                or (b.texas_taxpayer_number or "").strip())


def _sells_in_texas(b):
    return bool((b.sales_tax_webfile or "").strip() or b.sales_tax_registered_on
                or b.sales_tax_first_sale or list(b.locations or []))


def required_kinds(b):
    """The kinds this business must hold, in the order the page lists them."""
    if b.parent_id:
        return ["assumed_name"]
    if not _formed(b):
        return []
    kinds = ["formation", "ein"]
    if _sells_in_texas(b):
        kinds.append("sales_permit")
    if len(list(getattr(b, "owners", []) or [])) > 1:
        kinds.append("operating")
    return kinds


def waive_key(business_id, kind):
    return f"paper:{business_id}:{kind}"


def _waived(business_ids):
    """{(business_id, kind)} Michael set aside, read in one query."""
    keys = DeadlineDone.query.filter(DeadlineDone.key.like("paper:%")).all()
    out = set()
    for row in keys:
        try:
            _p, bid, kind = row.key.split(":", 2)
            if int(bid) in business_ids:
                out.add((int(bid), kind))
        except ValueError:
            continue
    return out


def status(b, waived=None):
    """Every requirement of one business: [{kind, label, why, state, docs}].

    state is "held" (a paper of that kind is on file), "waived" (Not needed)
    or "missing". A held kind lists its papers, newest first.
    """
    if waived is None:
        waived = _waived({b.id})
    docs = list(b.documents or [])
    rows = []
    for kind in required_kinds(b):
        held = sorted((d for d in docs if d.kind == kind), key=lambda d: d.id, reverse=True)
        state = "held" if held else ("waived" if (b.id, kind) in waived else "missing")
        rows.append({"kind": kind, "label": kind_label(kind), "why": WHY.get(kind, ""),
                     "state": state, "docs": held})
    return rows


def forget():
    _CACHE.update(at=0.0, value=None)


def missing_count(force=False):
    """How many rows missing_rows() draws: the badge's share."""
    now = time.time()
    if not force and _CACHE["value"] is not None and now - _CACHE["at"] < _TTL:
        return _CACHE["value"]
    value = len(missing_rows())
    _CACHE.update(at=now, value=value)
    return value


def missing_rows():
    """Needs attention: one row per business missing a paper it must hold,
    naming each missing paper, so three papers one upload session will clear
    read as one thing to do rather than three rows.

    Every active business, DBAs included (a DBA's Assumed Name Certificate),
    in name order. A couple of queries and the relationships, no network, so
    it is safe on every page the sidebar badge is built on.
    """
    from models import Business
    try:
        businesses = (Business.query.filter_by(is_active=True)
                      .order_by(Business.name, Business.id).all())
        waived = _waived({b.id for b in businesses})
        rows = []
        for b in businesses:
            missing = [r for r in status(b, waived) if r["state"] == "missing"]
            if missing:
                rows.append({"business": b, "missing": missing})
        return rows
    except Exception:  # noqa: BLE001 - a table that does not exist yet must not take the board down
        db.session.rollback()
        return []


def set_waived(business_id, kind, on, who=""):
    """Not needed (on) or needed after all (off). Returns whether it changed."""
    key = waive_key(business_id, kind)
    row = DeadlineDone.query.filter_by(key=key).first()
    if on and row is None:
        db.session.add(DeadlineDone(key=key, done_by=(who or "")[:80]))
        return True
    if not on and row is not None:
        db.session.delete(row)
        return True
    return False
