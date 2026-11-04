"""The icon vocabulary: one drawing per concept, the same in every project.

Michael, 2026-11-04: "give me an icon overhaul. and heck that is another
thing that should likely go into handbooks is icons that I like to use for
concepts." So a concept (notifications, clients, delete) has ONE drawing,
read from where he already uses the same one in more than one repo, and:

  render          what the board's `icon('concept')` macro draws. Every
                  sidebar link and every icon on the board's pages comes
                  through here, so a change in the Handbook is a change
                  everywhere at once.
  concepts        the whole vocabulary as plain dicts, for the Handbook's
                  Icons tab, the door (get_icons) and the build prompt.
  prompt_lines    one line per concept, which every MVP build prompt carries.
  clean_svg       what the door accepts as a drawing: geometry only, in the
                  vocabulary's one viewBox. Everything else is thrown away,
                  because this markup is drawn on every page of the board.
  duplicate_of    the catalogue rule "One icon, one meaning" as a check: a
                  drawing already standing for another concept is refused.

Defaults in code (icon_defaults.py), edits in the database (IconConcept). A
concept with no row draws its default; the door writes a row the first time
it changes one (row_for). A retired concept leaves the Handbook and the
prompt, and the board keeps drawing its default until its call sites move,
because a sidebar with blank holes in it is worse than an old drawing.

One stroke style: Heroicons outline, viewBox 0 0 24 24, stroke 1.5, round
caps and joins. Under 18px the macro draws the same paths at stroke 2, so a
line is never thinner than a pixel (Heroicons' own outline set is drawn for
24px). That is the only thing the size changes.
"""
import re
import time
import xml.etree.ElementTree as ET

from markupsafe import Markup, escape

from icon_defaults import DEFAULTS

VIEWBOX = "0 0 24 24"
STROKE = "1.5"
SMALL_STROKE = "2"
LIBRARY = "Heroicons outline"
GROUPS = (("nav", "Places"), ("action", "Actions"), ("status", "States"), ("thing", "Things"))
FIELDS = ("name", "group", "svg", "library", "icon_name", "aliases", "used_in_md", "never_md")

# What a drawing may be made of, and the attributes each shape may carry.
# Everything a stroke style is (width, caps, colour) belongs to the
# vocabulary, so it is dropped here rather than stored per concept.
_SHAPES = {
    "path": ("d",),
    "circle": ("cx", "cy", "r"),
    "ellipse": ("cx", "cy", "rx", "ry"),
    "rect": ("x", "y", "width", "height", "rx", "ry"),
    "line": ("x1", "y1", "x2", "y2"),
    "polyline": ("points",),
    "polygon": ("points",),
}
_GEOMETRY = re.compile(r"^[0-9A-Za-z.,\s\-]{1,6000}$")
_SMALL = re.compile(r"(?:^|\s)(?:w|size)-(?:2|2\.5|3|3\.5|4)(?:\s|$)")

_CACHE = {"at": 0.0, "rows": None}
TTL = 60


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def clean_svg(raw):
    """(inner markup, error) for a drawing a session sent.

    Takes a whole <svg> or just its shapes. Refuses another viewBox, because
    a vocabulary in two coordinate systems draws at two sizes; refuses any
    element that is not a shape and any geometry with characters a path
    never needs. The answer is re-written from what was parsed, never the
    text that came in.
    """
    text = (raw or "").strip()
    if not text:
        return None, "svg is empty"
    if not text.startswith("<svg"):
        text = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{VIEWBOX}">{text}</svg>'
    try:
        root = ET.fromstring(text)
    except ET.ParseError as e:
        return None, f"svg does not parse: {e}"
    if _local(root.tag) != "svg":
        return None, "the drawing must be an <svg> or its shapes"
    box = " ".join((root.get("viewBox") or VIEWBOX).replace(",", " ").split())
    if box != VIEWBOX:
        return None, f"the vocabulary draws in viewBox {VIEWBOX}; this one is {box}"
    out = []
    for el in root.iter():
        if el is root:
            continue
        tag = _local(el.tag)
        if tag in ("g", "title", "desc"):
            continue
        if tag not in _SHAPES:
            return None, f"<{tag}> is not a shape; a drawing is paths and simple shapes only"
        attrs = []
        for name in _SHAPES[tag]:
            value = el.get(name)
            if value is None:
                continue
            value = " ".join(value.split())
            if not _GEOMETRY.match(value):
                return None, f"{tag} {name} carries characters a drawing never needs"
            attrs.append(f'{name}="{value}"')
        if not attrs:
            continue
        if (el.get("fill") or "").lower() == "currentcolor":
            attrs.append('fill="currentColor"')
        out.append(f"<{tag} {' '.join(attrs)}/>")
    if not out:
        return None, "the drawing has no shapes"
    return "".join(out), None


def drawing_key(inner):
    """The drawing with its spacing and number spelling taken out, so the
    same icon pasted from two sources compares equal."""
    key = re.sub(r"\s+", " ", inner or "").strip()
    key = re.sub(r"(?<=[a-zA-Z])\s+|\s+(?=[a-zA-Z])", "", key)
    key = re.sub(r"(?<![0-9])0\.", ".", key)
    return key


def _default_rows():
    rows = {}
    for i, d in enumerate(DEFAULTS):
        row = {k: d.get(k, "") for k in FIELDS}
        row.update(slug=d["slug"], library=d.get("library") or LIBRARY,
                   group=d.get("group") or "thing", sort_order=(i + 1) * 10,
                   is_active=True, stored=False)
        rows[d["slug"]] = row
    return rows


def _load():
    rows = _default_rows()
    try:
        from models import IconConcept
        for r in IconConcept.query.all():
            base = rows.get(r.slug, {})
            row = {k: (getattr(r, k) or "") for k in FIELDS}
            row.update(slug=r.slug, sort_order=base.get("sort_order", 10000 + (r.sort_order or 0)),
                       is_active=bool(r.is_active), stored=True,
                       default_svg=base.get("svg", ""))
            rows[r.slug] = row
    except Exception:
        # No app context or no table (a fresh database, a test): the
        # defaults are a whole vocabulary on their own.
        pass
    return rows


def _rows():
    now = time.monotonic()
    if _CACHE["rows"] is None or now - _CACHE["at"] > TTL:
        _CACHE["rows"] = _load()
        _CACHE["at"] = now
    return _CACHE["rows"]


def invalidate():
    _CACHE["rows"] = None


def concepts(include_retired=False):
    """Every concept, in the vocabulary's order: places, actions, states, things."""
    order = {k: i for i, (k, _) in enumerate(GROUPS)}
    rows = [r for r in _rows().values() if include_retired or r["is_active"]]
    return sorted(rows, key=lambda r: (order.get(r["group"], 9), r["sort_order"], r["name"]))


def get(slug):
    return _rows().get(slug)


def known(slug):
    return slug in _rows()


def _drawing(slug):
    row = _rows().get(slug)
    if row is None:
        return None
    if not row["is_active"] and row.get("default_svg"):
        return row["default_svg"]
    return row["svg"]


def render(slug, cls="w-5 h-5", label=None, attrs="", small=None):
    """The <svg> for a concept. `label` makes it an image with a name; with
    none it is decoration (aria-hidden), which is right inside a link or a
    button that already says what it is. `attrs` is markup the call site
    owns (x-show, :class), dropped on the element verbatim. `small` says the
    icon is drawn under 18px by something other than its classes (a
    stylesheet rule, a width attribute); otherwise the classes say."""
    inner = _drawing(slug)
    if inner is None:
        # Drawn as nothing, loudly in the log and in tools/test_icons.py,
        # which fails on any icon() naming a concept the vocabulary lacks.
        import logging
        logging.getLogger(__name__).warning("icon(%r): no such concept", slug)
        inner = ""
    if small is None:
        small = bool(_SMALL.search(f" {cls} "))
    stroke = SMALL_STROKE if small else STROKE
    name = (f'role="img" aria-label="{escape(label)}"' if label else 'aria-hidden="true"')
    return Markup(
        f'<svg class="{escape(cls)} shrink-0" viewBox="{VIEWBOX}" fill="none" stroke="currentColor" '
        f'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round" '
        f'focusable="false" data-icon="{escape(slug)}" {name} {attrs}>{inner}</svg>')


def shapes(slugs):
    """{concept: its shapes} for a script that draws icons itself (the
    business map sets each tile's shapes with x-html)."""
    return {s: (_drawing(s) or "") for s in slugs}


def duplicate_of(inner, slug):
    """The name of another live concept already drawn this way, or None."""
    key = drawing_key(inner)
    for row in _rows().values():
        if row["slug"] != slug and row["is_active"] and drawing_key(row["svg"]) == key:
            return row["name"]
    return None


def row_for(slug):
    """The IconConcept for a concept, written from its default the first
    time the door touches it. None for a concept nobody has defined."""
    from models import db, IconConcept
    row = IconConcept.query.filter_by(slug=slug).first()
    if row is not None:
        return row
    base = _default_rows().get(slug)
    if base is None:
        return None
    row = IconConcept(slug=slug, sort_order=base["sort_order"],
                      **{k: base[k] for k in FIELDS})
    db.session.add(row)
    db.session.flush()
    return row


def entry_text(row):
    """One concept as a session reads it through the door."""
    out = [f"{row['name']} [{row['slug']}] - {row['library']} {row['icon_name']}".rstrip()]
    if row.get("aliases"):
        out.append(f"  Also called: {row['aliases']}")
    if row.get("used_in_md"):
        out.append(f"  Where he uses it: {row['used_in_md']}")
    if row.get("never_md"):
        out.append(f"  Never confuse with: {row['never_md']}")
    out.append(f'  <svg viewBox="{VIEWBOX}" fill="none" stroke="currentColor" stroke-width="{STROKE}" '
               f'stroke-linecap="round" stroke-linejoin="round">{row["svg"]}</svg>')
    return "\n".join(out)


def prompt_lines():
    """The vocabulary as a build prompt carries it: one line per concept."""
    rows = concepts()
    if not rows:
        return []
    out = ["THE ICONS",
           f"  One drawing per concept, the same in every project: {LIBRARY}, viewBox {VIEWBOX}, "
           f"stroke {STROKE}, round caps and joins, currentColor. Put them in ONE icon macro "
           "(icon('concept')) and never draw an icon inline. Never use one drawing for two "
           "concepts. get_icons gives each drawing's SVG; a concept not listed here is added "
           "with suggest_update kind icon before it is used.",
           ""]
    for r in rows:
        line = f"  - {r['name']} [{r['slug']}]: {r['icon_name'] or 'custom'}"
        if r.get("aliases"):
            line += f"; also {r['aliases']}"
        if r.get("never_md"):
            line += f". Not {r['never_md'].splitlines()[0].rstrip('.')}"
        out.append(line + ".")
    out.append("")
    return out
