"""Email templates: a saved email with blanks filled in per person (issue #41).

Michael, 2026-11-06: "email packages ... I can say I'm sending out a catalog /
introduction email to a company to work with ... the link will be generated to
the catalog as it sits ... just have the fields you need me to fill in that
would be different per email". He named them Email templates.

Defaults in code, edits in the database: DEFAULTS is each template as written
here, and an `EmailTemplate` row exists once he has changed one on the board,
so a template he has never touched still follows this file.

The blanks are {first_name}, {company}, {personal_line}, {catalog_link} and
{link_until}. A blank that is empty takes its paragraph with it, so leaving
the personal line out leaves no gap.

The intro's facts, checked 2026-11-06: Higginbotham has "more than 4,500 team
members" in "150-plus offices across 19 states" (Insurance Journal, 2026-09-07)
and is "one of the nation's largest independent insurance brokerages". Michael
has been a senior data analyst there for six years and is still there; Built
By Bean, LLC began taking clients in 2026. Change a figure here when it
changes, never on a guess.
"""
import re
from datetime import datetime, timezone

from markupsafe import escape

FIELDS = ("first_name", "company", "personal_line", "catalog_link", "link_until")

DEFAULTS = {
    "intro": {
        "name": "Intro email",
        "subject": "Custom software for {company}",
        "body": (
            "Hi {first_name},\n\n"
            "My name is Michael Bean. For the last six years I've been a senior data analyst at "
            "Higginbotham, one of the nation's largest independent insurance brokerages, with more "
            "than 4,500 people in over 150 offices across 19 states.\n\n"
            "{personal_line}\n\n"
            "In 2026 I started Built By Bean, LLC to build web apps and websites for businesses like "
            "{company}. Each one is built around how that business already works, and the ones I've "
            "built are running real companies today, from an entertainment staffing firm to a Fort "
            "Worth plumber.\n\n"
            "I put together a private catalog of that work for you:\n"
            "{catalog_link}\n\n"
            "It's yours until {link_until}. If anything in it looks useful for {company}, reply here "
            "and we can find a time to talk.\n\n"
            "Michael Bean\n"
            "Built By Bean, LLC\n"
            "(903) 491-2095"
        ),
    },
}

_BLANK = re.compile(r"\{(" + "|".join(FIELDS) + r")\}")


def get(slug):
    """{"slug", "name", "subject", "body", "edited"}: his edit, else the default."""
    from models import EmailTemplate
    base = DEFAULTS.get(slug)
    row = EmailTemplate.query.filter_by(slug=slug).first()
    if row is None and base is None:
        return None
    if row is None:
        return {"slug": slug, **base, "edited": False}
    return {"slug": slug, "name": row.name or (base or {}).get("name", slug), "subject": row.subject,
            "body": row.body, "edited": True}


def all_templates():
    from models import EmailTemplate
    slugs = list(DEFAULTS) + [r.slug for r in EmailTemplate.query.order_by(EmailTemplate.id)
                              if r.slug not in DEFAULTS]
    return [get(s) for s in slugs]


def save(slug, subject, body, name=None):
    from models import EmailTemplate, db
    row = EmailTemplate.query.filter_by(slug=slug).first()
    if row is None:
        row = EmailTemplate(slug=slug, name=name or DEFAULTS.get(slug, {}).get("name", slug))
        db.session.add(row)
    row.subject = subject.strip()[:300]
    row.body = body.replace("\r\n", "\n").strip()
    if name:
        row.name = name.strip()[:120]
    row.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return row


def reset(slug):
    from models import EmailTemplate, db
    EmailTemplate.query.filter_by(slug=slug).delete()
    db.session.commit()


def _fill(text, values):
    return _BLANK.sub(lambda m: values.get(m.group(1), ""), text or "")


def render(template, values):
    """(subject, text, html) for one person. `values` holds the blanks; the
    catalog link is put in as a button in the HTML and as the address in the
    text. A paragraph whose only content was an empty blank is dropped."""
    values = {k: (v or "").strip() for k, v in values.items()}
    subject = " ".join(_fill(template["subject"], values).split())
    paras = []
    for para in re.split(r"\n{2,}", (template["body"] or "").replace("\r\n", "\n")):
        blanks = _BLANK.findall(para)
        if blanks and not _BLANK.sub("", para).strip() and not any(values.get(b) for b in blanks):
            continue
        paras.append(para)
    text = "\n\n".join(_fill(p, values) for p in paras).strip() + "\n"
    link = values.get("catalog_link", "")
    html_paras = []
    for p in paras:
        if "{catalog_link}" in p:
            before = _fill(p.replace("{catalog_link}", ""), values).strip()
            if before:
                html_paras.append(f"<p>{escape(before)}</p>")
            if link:
                html_paras.append(
                    f'<p><a href="{escape(link)}" style="display:inline-block;padding:12px 22px;'
                    'border-radius:10px;background:#a855f7;color:#ffffff;text-decoration:none;'
                    'font-weight:600">See the work</a></p>')
            continue
        html_paras.append("<p>" + "<br>".join(str(escape(line)) for line in _fill(p, values).split("\n")) + "</p>")
    html = "".join(html_paras)
    return subject, text, html
