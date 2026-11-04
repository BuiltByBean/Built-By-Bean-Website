"""Org: one store for every business's people, read and saved through two doors.

Michael, 2026-11-04: Team becomes Org, one tab per business, built from
EntertainHQ's admin Organization page (Responsibilities, Org chart, People,
Departments) plus who owns what. His picks, one by one:

- The board holds every business's org. EntertainHQ's own page reads and saves
  the same rows over the hub (pm/org_routes.py, /api/hub/org*), exactly as its
  tax calendar reads the board's returns, so there are never two copies.
- Its rows come over once, keyed by EntertainHQ's own ids (`app_ref`), and only
  into an org nobody has edited on the board (`import_org`).
- Shares are the board's (`BusinessOwner`, typed from the paperwork); an app
  shows them and never writes them.
- Logins are each app's own. An app reports its list on every call and the
  board shows who holds one; the board's own logins are the Logins tab.
- A save names the version it read. If the row moved since, it is refused with
  "changed since you opened it", whichever door it came through, so the board
  and an app can never write over an edit they did not see.

`payload` is the one shape both doors answer with, and every write answers it
again, so a page draws itself from one reading (EntertainHQ's roles.js does
the same).
"""
import json
from datetime import datetime, timezone

from models import (db, Business, BusinessOwner, OrgDepartment, OrgPerson,
                    OrgResponsibility, OrgState, User)

NAME_MAX = 120
TITLE_MAX = 120
RESP_MAX = 200
DETAILS_MAX = 4000
DEPT_MAX = 80
STALE = "Somebody changed that since you opened it. It has been read again; make the change once more."


class Refused(Exception):
    """A save that cannot be made, with the words to show and a status."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _clean(value, limit):
    return " ".join(str(value or "").split())[:limit]


def _text(value, limit):
    return str(value or "").replace("\r\n", "\n").strip()[:limit]


def _id(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def state(business):
    row = db.session.get(OrgState, business.id)
    if row is None:
        row = OrgState(business_id=business.id, app_logins_json="[]")
        db.session.add(row)
    return row


def app_logins(business):
    row = db.session.get(OrgState, business.id)
    try:
        return json.loads(row.app_logins_json or "[]") if row else []
    except ValueError:
        return []


def record_logins(business, logins):
    """What the app says about its own logins. Only well formed entries are
    kept, and an app that sends nothing leaves the last list as it was."""
    if not isinstance(logins, list):
        return
    kept = []
    for item in logins[:200]:
        if not isinstance(item, dict):
            continue
        email = _clean(item.get("email"), 200).lower()
        if "@" not in email:
            continue
        kept.append({"email": email, "name": _clean(item.get("name"), NAME_MAX)})
    row = state(business)
    row.app_logins_json = json.dumps(kept)
    row.reported_at = _now()


def org_businesses():
    """Every business with an org: the companies, never a DBA (Michael,
    2026-11-04: "orgs should only be on primary businesses not dba. So built
    by bean and entertainhq are the only ones that have actual orgs"). A
    DBA's people are its company's, so a DBA added later gets no tab either."""
    return (Business.query.filter(Business.parent_id.is_(None), Business.is_active.is_(True))
            .order_by(Business.id).all())


def org_home(business):
    """Whose org a business's people are on: its own, or its company's."""
    return business.parent if business.is_division and business.parent else business


def owners_of(business):
    return list(business.owners)


def fold_into_parent(division):
    """Carry a DBA's org onto its company's, and say what moved.

    Run when a business is made a DBA (pm/business_routes.py edit), because
    from then on its people are its company's and nothing draws a DBA's org.
    A department or person the company already has (a department by name, a
    person by email, else by name) is the same one: what was on the DBA's is
    moved onto it and the DBA's copy goes. Everything else moves as it is.
    Returns None when there was nothing to move."""
    parent = division.parent
    if parent is None:
        return None
    people = OrgPerson.query.filter_by(business_id=division.id).all()
    depts = OrgDepartment.query.filter_by(business_id=division.id).all()
    resps = OrgResponsibility.query.filter_by(business_id=division.id).all()
    if not (people or depts or resps):
        st = db.session.get(OrgState, division.id)
        if st is not None:
            db.session.delete(st)
        return None
    taken = {r for (r,) in db.session.query(OrgPerson.app_ref).filter_by(business_id=parent.id)}
    taken |= {r for (r,) in db.session.query(OrgDepartment.app_ref).filter_by(business_id=parent.id)}
    taken |= {r for (r,) in db.session.query(OrgResponsibility.app_ref).filter_by(business_id=parent.id)}
    their_depts = {(d.name or "").strip().lower(): d
                   for d in OrgDepartment.query.filter_by(business_id=parent.id).all()}
    last = max([d.sort for d in their_depts.values()] or [0])
    dept_to = {}
    for d in depts:
        same = their_depts.get((d.name or "").strip().lower())
        if same is not None:
            dept_to[d.id] = same
        else:
            d.business_id = parent.id
            last += 1
            d.sort = last
            if d.app_ref in taken:
                d.app_ref = None
            _touch(d)
    their_people = OrgPerson.query.filter_by(business_id=parent.id).all()
    by_email = {(p.email or "").lower(): p for p in their_people if p.email}
    by_name = {(p.name or "").strip().lower(): p for p in their_people}
    person_to = {}
    for p in people:
        same = by_email.get((p.email or "").lower()) if p.email else None
        same = same or by_name.get((p.name or "").strip().lower())
        if same is not None:
            person_to[p.id] = same
    for p in people:
        if p.id in person_to:
            continue
        p.business_id = parent.id
        if p.app_ref in taken:
            p.app_ref = None
        p.departments = [dept_to.get(d.id, d) for d in p.departments]
        if p.supervisor_id in person_to:
            p.supervisor_id = person_to[p.supervisor_id].id
        _touch(p)
    for p in people:
        same = person_to.get(p.id)
        if same is None:
            continue
        for d in p.departments:
            target = dept_to.get(d.id, d)
            if target not in same.departments:
                same.departments.append(target)
        for kid in OrgPerson.query.filter_by(supervisor_id=p.id).all():
            kid.supervisor_id = same.id
        _touch(same)
    db.session.flush()
    for r in resps:
        r.business_id = parent.id
        if r.app_ref in taken:
            r.app_ref = None
        if r.owner_id in person_to:
            r.owner_id = person_to[r.owner_id].id
        if r.dept_id in dept_to:
            r.dept_id = dept_to[r.dept_id].id
        r.sort = (r.sort or 0) + 100000
        _touch(r)
    db.session.flush()
    for p in people:
        if p.id in person_to:
            BusinessOwner.query.filter_by(person_id=p.id).update({"person_id": person_to[p.id].id})
            db.session.delete(p)
    for d in depts:
        if d.id in dept_to:
            db.session.delete(d)
    st = db.session.get(OrgState, division.id)
    if st is not None:
        db.session.delete(st)
    state(parent).edited_at = _now()
    db.session.flush()
    link_owners(parent)

    def n(count, one, many):
        return f"{count} {one if count == 1 else many}"
    parts = [x for x in (n(len(people), "person", "people") if people else "",
                         n(len(depts), "department", "departments") if depts else "",
                         n(len(resps), "responsibility", "responsibilities") if resps else "") if x]
    said = ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1]
    merged = len(person_to) + len(dept_to)
    return (f"{said} moved from {division.label}'s org to {parent.label}'s"
            + (f", {merged} of them onto ones it already had." if merged else "."))


def _board_logins():
    return {(u.email or "").lower(): u for u in User.query.all() if u.email}


def payload(business):
    people = list(business.org_people)
    depts = list(business.org_departments)
    resps = list(business.org_responsibilities)
    owners = owners_of(business)
    board = _board_logins()
    on_app = {l["email"] for l in app_logins(business)}
    by_person = {o.person_id: o for o in owners if o.person_id}
    by_name = {(o.name or "").strip().lower(): o for o in owners}
    reports, owns, in_dept, resp_in = {}, {}, {}, {}
    for p in people:
        if p.supervisor_id:
            reports[p.supervisor_id] = reports.get(p.supervisor_id, 0) + 1
        for d in p.departments:
            in_dept[d.id] = in_dept.get(d.id, 0) + 1
    for r in resps:
        if r.owner_id:
            owns[r.owner_id] = owns.get(r.owner_id, 0) + 1
        if r.dept_id:
            resp_in[r.dept_id] = resp_in.get(r.dept_id, 0) + 1
    st = db.session.get(OrgState, business.id)

    def person(p):
        email = (p.email or "").lower()
        login = board.get(email) if email else None
        owner = by_person.get(p.id) or by_name.get((p.name or "").strip().lower())
        return {
            "id": p.id, "name": p.name, "title": p.title or "", "email": p.email or "",
            "phone": p.phone or "", "supervisor": p.supervisor_id,
            "depts": [d.id for d in p.departments], "initials": p.initials,
            "reports": reports.get(p.id, 0), "owns": owns.get(p.id, 0),
            "share_percent": owner.share_percent if owner else None,
            "board_login": ({"username": login.username, "title": login.role_label,
                             "active": bool(login.is_active)} if login else None),
            "app_login": bool(email and email in on_app),
            "app_ref": p.app_ref or "", "version": p.version,
        }

    return {
        "business": {"id": business.id, "name": business.name, "label": business.label,
                     },
        "people": [person(p) for p in people],
        "departments": [{"id": d.id, "name": d.name, "tone": d.tone, "sort": d.sort,
                         "people": in_dept.get(d.id, 0), "responsibilities": resp_in.get(d.id, 0),
                         "version": d.version} for d in depts],
        "responsibilities": [{"id": r.id, "title": r.title, "details": r.details or "",
                              "owner": r.owner_id, "dept": r.dept_id, "sort": r.sort,
                              "by": r.created_by or "", "version": r.version,
                              "updated": r.updated_at.isoformat() if r.updated_at else None}
                             for r in resps],
        "owners": [{"name": o.name, "share_percent": o.share_percent, "person": o.person_id}
                   for o in owners],
        "app_logins": app_logins(business),
        "reported_at": st.reported_at.isoformat() if st and st.reported_at else None,
        "imported_at": st.imported_at.isoformat() if st and st.imported_at else None,
        "tones": list(OrgDepartment.TONES),
    }


# ── Saving ──────────────────────────────────────────────────


def _row(model, business, rid):
    row = db.session.get(model, rid) if rid else None
    if row is None or row.business_id != business.id:
        raise Refused("That is not on this org.", 404)
    return row


def _fresh(row, version):
    """A save names the version it read. One that does not, or names an old
    one, is refused: the other door may have moved the row since."""
    try:
        version = int(version)
    except (TypeError, ValueError):
        raise Refused("A change has to say which version it was made against.", 400)
    if version != row.version:
        raise Refused(STALE, 409)


def _touch(row):
    row.version = (row.version or 1) + 1
    if hasattr(row, "updated_at"):
        row.updated_at = _now()


def _sups(business_id):
    """Each person's supervisor id, read from the database as it stands now,
    so a change earlier in the same save is seen."""
    db.session.flush()
    rows = db.session.query(OrgPerson.id, OrgPerson.supervisor_id).filter_by(business_id=business_id).all()
    return {pid: sup for pid, sup in rows}


def _below(person):
    """Everybody under this person, however far down."""
    sups = _sups(person.business_id)
    kids = {}
    for pid, sup in sups.items():
        if sup:
            kids.setdefault(sup, []).append(pid)
    out, todo = set(), list(kids.get(person.id, []))
    while todo:
        k = todo.pop()
        if k == person.id or k in out:
            continue
        out.add(k)
        todo.extend(kids.get(k, []))
    return out


def _above(person):
    """Everybody over this person, nearest first."""
    sups = _sups(person.business_id)
    out, seen, s = [], {person.id}, sups.get(person.id)
    while s and s not in seen:
        out.append(s)
        seen.add(s)
        s = sups.get(s)
    return out


def _set_supervisor(business, person, sup_id):
    if sup_id is None:
        person.supervisor_id = None
        return
    sup = _row(OrgPerson, business, sup_id)
    if sup.id == person.id or (person.id and sup.id in _below(person)):
        raise Refused(f"{person.name} cannot report to somebody who reports to them.")
    person.supervisor_id = sup.id


def _set_depts(business, person, ids):
    wanted = []
    for d in ids or []:
        dept = _row(OrgDepartment, business, _id(d))
        if dept not in wanted:
            wanted.append(dept)
    person.departments = wanted


def _set_share(business, person, value):
    """The share is the board's, typed here or on Books."""
    owner = BusinessOwner.query.filter_by(business_id=business.id, person_id=person.id).first()
    if owner is None:
        owner = next((o for o in business.owners if not o.person_id
                      and (o.name or "").strip().lower() == (person.name or "").strip().lower()), None)
    if value in (None, ""):
        if owner is not None:
            db.session.delete(owner)
        return
    try:
        share = float(value)
    except (TypeError, ValueError):
        raise Refused("A share is a number of percent.")
    if not 0 <= share <= 100:
        raise Refused("A share is between 0 and 100 percent.")
    if owner is None:
        owner = BusinessOwner(business_id=business.id, name=person.name)
        db.session.add(owner)
    owner.person_id = person.id
    owner.share_percent = share


def link_owners(business):
    """Each owner to the person of the same name, where nobody linked them."""
    if business.is_division:
        return
    # Queried, not read off the relationships: those are as they were loaded,
    # before this save added or took anyone off.
    db.session.flush()
    people = {(p.name or "").strip().lower(): p
              for p in OrgPerson.query.filter_by(business_id=business.id).all()}
    for o in BusinessOwner.query.filter_by(business_id=business.id).all():
        if o.person_id is None:
            p = people.get((o.name or "").strip().lower())
            if p is not None and p.id:
                o.person_id = p.id


def save(business, body, by="", allow_share=False):
    """One change to one business's org. `body` is the same shape from either
    door: {what, op, id, version, ...fields}. Returns the words that say what
    happened; raises Refused."""
    what = str(body.get("what") or "")
    op = str(body.get("op") or "")
    rid = _id(body.get("id"))
    said = _apply(business, what, op, rid, body, by, allow_share)
    state(business).edited_at = _now()
    db.session.flush()
    link_owners(business)
    db.session.commit()
    return said


def _apply(business, what, op, rid, body, by, allow_share):
    if what == "person":
        if op == "create":
            name = _clean(body.get("name"), NAME_MAX)
            if not name:
                raise Refused("Name the person.")
            p = OrgPerson(business_id=business.id, name=name, title=_clean(body.get("title"), TITLE_MAX),
                          email=_clean(body.get("email"), 200).lower(), phone=_clean(body.get("phone"), 40))
            db.session.add(p)
            db.session.flush()
            if "supervisor" in body:
                _set_supervisor(business, p, _id(body.get("supervisor")))
            return f"{name} added."
        p = _row(OrgPerson, business, rid)
        _fresh(p, body.get("version"))
        if op == "update":
            if "name" in body:
                name = _clean(body.get("name"), NAME_MAX)
                if not name:
                    raise Refused("Name the person.")
                p.name = name
            if "title" in body:
                p.title = _clean(body.get("title"), TITLE_MAX)
            if "email" in body:
                p.email = _clean(body.get("email"), 200).lower()
            if "phone" in body:
                p.phone = _clean(body.get("phone"), 40)
            if "supervisor" in body:
                _set_supervisor(business, p, _id(body.get("supervisor")))
            if "depts" in body:
                _set_depts(business, p, body.get("depts"))
            if "reports" in body:
                wanted = {_row(OrgPerson, business, _id(k)).id for k in body.get("reports") or []}
                current = [pid for pid, sup in _sups(business.id).items() if sup == p.id]
                for kid in [db.session.get(OrgPerson, k) for k in current]:
                    if kid.id not in wanted:
                        kid.supervisor_id = None
                        _touch(kid)
                for kid_id in wanted:
                    kid = db.session.get(OrgPerson, kid_id)
                    if kid.supervisor_id != p.id:
                        # Somebody above this person cannot become their report.
                        if kid.id == p.id or kid.id in _above(p):
                            raise Refused(f"{kid.name} is above {p.name}, so cannot report to them.")
                        kid.supervisor_id = p.id
                        _touch(kid)
            if allow_share and "share_percent" in body:
                _set_share(business, p, body.get("share_percent"))
            _touch(p)
            return f"{p.name} saved."
        if op == "delete":
            email = (p.email or "").lower()
            if email and email in {l["email"] for l in app_logins(business)}:
                raise Refused(f"{p.name} holds a login on {business.label}'s app; take it off there first.")
            name = p.name
            for kid in list(p.reports):
                kid.supervisor_id = p.supervisor_id
            # Said here as well as by the foreign key, because SQLite only
            # honours ON DELETE when told to.
            BusinessOwner.query.filter_by(person_id=p.id).update({"person_id": None})
            db.session.delete(p)
            return f"{name} taken off the chart."
    if what == "department":
        if op == "create":
            name = _clean(body.get("name"), DEPT_MAX)
            if not name:
                raise Refused("Name the department.")
            tone = body.get("tone") if body.get("tone") in OrgDepartment.TONES else "gold"
            last = max([d.sort for d in business.org_departments] or [0])
            db.session.add(OrgDepartment(business_id=business.id, name=name, tone=tone, sort=last + 1))
            return f"{name} added."
        d = _row(OrgDepartment, business, rid)
        _fresh(d, body.get("version"))
        if op == "update":
            if "name" in body:
                name = _clean(body.get("name"), DEPT_MAX)
                if not name:
                    raise Refused("Name the department.")
                d.name = name
            if "tone" in body and body.get("tone") in OrgDepartment.TONES:
                d.tone = body["tone"]
            if "people" in body:
                d.people = [_row(OrgPerson, business, _id(pid)) for pid in body.get("people") or []]
            _touch(d)
            return f"{d.name} saved."
        if op == "delete":
            if d.responsibilities:
                raise Refused(f"{d.name} still holds {len(d.responsibilities)} responsibilities; move them first.")
            name = d.name
            db.session.delete(d)
            return f"{name} deleted."
    if what == "responsibility":
        if op == "create":
            title = _clean(body.get("title"), RESP_MAX)
            if not title:
                raise Refused("Say what the responsibility is.")
            dept = _row(OrgDepartment, business, _id(body.get("dept"))) if _id(body.get("dept")) else None
            if dept is None:
                raise Refused("Every responsibility belongs to a department.")
            owner = _row(OrgPerson, business, _id(body.get("owner"))) if _id(body.get("owner")) else None
            last = max([r.sort for r in business.org_responsibilities] or [0])
            db.session.add(OrgResponsibility(
                business_id=business.id, title=title, details=_text(body.get("details"), DETAILS_MAX),
                owner_id=owner.id if owner else None, dept_id=dept.id, sort=last + 1,
                created_by=_clean(by, 200)))
            return f"{title} added."
        r = _row(OrgResponsibility, business, rid)
        _fresh(r, body.get("version"))
        if op in ("update", "move"):
            if "title" in body:
                title = _clean(body.get("title"), RESP_MAX)
                if not title:
                    raise Refused("Say what the responsibility is.")
                r.title = title
            if "details" in body:
                r.details = _text(body.get("details"), DETAILS_MAX)
            if "dept" in body:
                if not _id(body.get("dept")):
                    raise Refused("Every responsibility belongs to a department.")
                r.dept_id = _row(OrgDepartment, business, _id(body.get("dept"))).id
            if "owner" in body:
                r.owner_id = _row(OrgPerson, business, _id(body["owner"])).id if _id(body.get("owner")) else None
            if op == "move" and _id(body.get("before")):
                before = _row(OrgResponsibility, business, _id(body.get("before")))
                for other in business.org_responsibilities:
                    if other.sort >= before.sort and other.id != r.id:
                        other.sort += 1
                r.sort = before.sort - 1 if before.sort > 0 else 0
            _touch(r)
            return "Moved." if op == "move" else f"{r.title} saved."
        if op == "delete":
            title = r.title
            db.session.delete(r)
            return f"{title} deleted."
    raise Refused("No such change.", 404)


# ── The one-time import ─────────────────────────────────────


def can_import(business):
    """Into an empty org, or over an earlier import nobody has edited since.
    Never over an edit made on either door."""
    st = db.session.get(OrgState, business.id)
    empty = not any(m.query.filter_by(business_id=business.id).first()
                    for m in (OrgPerson, OrgDepartment, OrgResponsibility))
    if empty:
        return True
    if st is None or st.imported_at is None:
        return False
    return st.edited_at is None or st.edited_at <= st.imported_at


def import_org(business, data, origin):
    """An app's org, as its own page holds it, keyed by its ids. Rows are
    upserted on `<origin>:<id>`, so running it twice changes nothing, and rows
    of that origin the app no longer has are removed. Returns counts; raises
    Refused when the org has been edited since."""
    origin = _clean(origin, 40).lower() or "app"
    if not can_import(business):
        raise Refused(f"{business.label}'s org has been edited since it was imported, so it is not "
                      "written over. Its rows are the board's now.", 409)

    def ref(x):
        rid = x.get("id") if isinstance(x, dict) else None
        return f"{origin}:{rid}" if rid not in (None, "") else None

    people_in = [p for p in (data.get("people") or []) if isinstance(p, dict) and ref(p)]
    depts_in = [d for d in (data.get("departments") or []) if isinstance(d, dict) and ref(d)]
    resps_in = [r for r in (data.get("responsibilities") or []) if isinstance(r, dict) and ref(r)]

    def existing(model):
        return {r.app_ref: r for r in model.query.filter_by(business_id=business.id).all() if r.app_ref}

    depts = existing(OrgDepartment)
    for i, d in enumerate(depts_in):
        row = depts.get(ref(d)) or OrgDepartment(business_id=business.id, app_ref=ref(d))
        row.name = _clean(d.get("name"), DEPT_MAX) or "Department"
        row.tone = d.get("tone") if d.get("tone") in OrgDepartment.TONES else "gold"
        row.sort = _id(d.get("sort")) or i + 1
        db.session.add(row)
        depts[ref(d)] = row
    people = existing(OrgPerson)
    for p in people_in:
        row = people.get(ref(p)) or OrgPerson(business_id=business.id, app_ref=ref(p))
        row.name = _clean(p.get("name"), NAME_MAX) or "Somebody"
        row.title = _clean(p.get("title"), TITLE_MAX)
        row.email = _clean(p.get("email"), 200).lower()
        if "phone" in p:
            row.phone = _clean(p.get("phone"), 40)
        db.session.add(row)
        people[ref(p)] = row
    db.session.flush()
    for p in people_in:
        row = people[ref(p)]
        sup = p.get("supervisor") if p.get("supervisor") is not None else p.get("supervisor_id")
        row.supervisor_id = people[f"{origin}:{sup}"].id if f"{origin}:{sup}" in people and sup else None
        row.departments = [depts[f"{origin}:{d}"] for d in (p.get("depts") or []) if f"{origin}:{d}" in depts]
    resps = existing(OrgResponsibility)
    for r in resps_in:
        row = resps.get(ref(r)) or OrgResponsibility(business_id=business.id, app_ref=ref(r))
        row.title = _clean(r.get("title"), RESP_MAX) or "Responsibility"
        row.details = _text(r.get("details"), DETAILS_MAX)
        owner = r.get("owner") if r.get("owner") is not None else r.get("owner_id")
        dept = r.get("dept") if r.get("dept") is not None else r.get("dept_id")
        row.owner_id = people[f"{origin}:{owner}"].id if owner and f"{origin}:{owner}" in people else None
        row.dept_id = depts[f"{origin}:{dept}"].id if dept and f"{origin}:{dept}" in depts else None
        row.sort = int(r.get("sort") or 0)
        row.created_by = _clean(r.get("by") or r.get("created_by"), 200)
        db.session.add(row)
        resps[ref(r)] = row
    # What the app no longer has goes, but only rows that came from it.
    # Per kind: the app numbers each table on its own, so person 3 and
    # responsibility 3 are different rows with the same ref.
    keep = {OrgResponsibility: {ref(x) for x in resps_in}, OrgPerson: {ref(x) for x in people_in},
            OrgDepartment: {ref(x) for x in depts_in}}
    for model in (OrgResponsibility, OrgPerson, OrgDepartment):
        for row in model.query.filter(model.business_id == business.id,
                                      model.app_ref.like(f"{origin}:%")).all():
            if row.app_ref not in keep[model]:
                if model is OrgPerson:
                    BusinessOwner.query.filter_by(person_id=row.id).update({"person_id": None})
                db.session.delete(row)
    if "logins" in data:
        record_logins(business, data.get("logins"))
    st = state(business)
    st.imported_at = _now()
    db.session.flush()
    link_owners(business)
    db.session.commit()
    return {"people": len(people_in), "departments": len(depts_in), "responsibilities": len(resps_in)}


def tree(business):
    """The chart as nested lists: the people nobody is over, each with the
    people under them, in name order."""
    people = list(business.org_people)
    ids = {p.id for p in people}
    kids = {}
    for p in people:
        top = p.supervisor_id if p.supervisor_id in ids else None
        kids.setdefault(top, []).append(p)

    def node(p, seen):
        if p.id in seen:
            return {"person": p, "reports": []}
        seen = seen | {p.id}
        return {"person": p, "reports": [node(k, seen) for k in sorted(kids.get(p.id, []), key=lambda x: x.name.lower())]}

    return [node(p, set()) for p in sorted(kids.get(None, []), key=lambda x: x.name.lower())]
