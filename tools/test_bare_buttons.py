# -*- coding: utf-8 -*-
"""Text alone is never a button, anywhere on the board.

Michael, 2026-11-06, after the catalog showcase shipped "All products" and
"See it" as bare words acting as buttons: "you only fix in isolation and build
in isolation". The showcase got its own guard (tools/test_catalog.py,
BORDERED); this is the same guard over every template under templates/pm, so
the next bare press is caught here rather than by him (issue #30).

Every <a> and <button> in templates/pm, and every confirm_button(btn_class=...)
call, must have a border or a fill: a `border` or `ring` utility, a resting
`bg-*`, or a kit class that draws one in CSS (btn-brand, glass-card, pm-chip).
`:class` and `{% set %}` variables in the same file are read too, so a press
whose look lives in a variable or a bound class is judged by what it draws.

Some presses are rightly not boxed. Each kind is on ALLOWED below with why,
and each is recognised by something the markup has to say, never by a guess:

  - a sidebar link (sidebar-link): the rail's own kit, lit when current
  - a switch or toggle (role="switch", aria-pressed): its box is drawn inside
  - an expander (its content carries icon('expand')): a row or card header
    whose chevron says it opens
  - an option in a picker (role="option")
  - anything marked data-press="<kind>" for the kinds in DATA_KINDS, each
    checked for the shape that kind must have

Run: python tools/test_bare_buttons.py
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PM = ROOT / "templates" / "pm"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# A press is boxed when one of these draws it. `border` alone (not border-b,
# which is a row's separator), `ring`, a resting bg-* (not hover:bg-, which is
# no box until the pointer is already on it), or a kit class with its border
# or fill in CSS. `btn` is the print summary's own bordered button
# (pm/mvp/summary.html defines it; it is a standalone page with no shell).
BOXED = re.compile(
    r"(?<![\w:/-])(border|border-2|ring|ring-1|ring-2|btn|btn-brand|btn-go|glass-card|pm-chip)(?![\w-])"
    r"|(?<![\w:/-])bg-(?!transparent\b|none\b)[a-z]")

# data-press kinds, each with the shape it must have. A kind is a claim about
# what the element is; the check is that the markup bears the claim out.
DATA_KINDS = {
    # A whole row or card of a list that opens its record: the list or card it
    # sits in is the box. Must be a block or a flex box, never inline words.
    "row": lambda tag, cls, inner: re.search(r"(?<![\w:-])(block|flex|w-full)(?![\w-])", cls),
    # A link inside a sentence of prose (a guide, a "Replaces ..." line). Only
    # an anchor: a <button> is never prose.
    "prose": lambda tag, cls, inner: tag.startswith("<a"),
    # A record's own value as a link: a name in a table cell or a dd, an email,
    # a phone number, an address. The data is the link; it is not an action.
    "value": lambda tag, cls, inner: tag.startswith("<a"),
    # A picture that opens what it shows, like an app icon on a home screen.
    "picture": lambda tag, cls, inner: "<img" in inner or "icon_file" in inner,
    # A row of a search result or a pick list inside an open panel, which is
    # the box.
    "option": lambda tag, cls, inner: True,
    # The drag edge of a card that is itself bordered.
    "grip": lambda tag, cls, inner: "data-grip" in tag,
    # A tick box drawn inside the press: an empty bordered square, or the
    # done glyph once ticked.
    "check": lambda tag, cls, inner: "border" in inner and "icon('done'" in inner,
    # The x inside a bordered chip: part of the chip, named for a screen reader.
    "chip-part": lambda tag, cls, inner: "aria-label" in tag,
}

ALLOWED = (
    ("sidebar link", lambda tag, cls, inner: "sidebar-link" in cls.split()),
    ("switch", lambda tag, cls, inner: 'role="switch"' in tag),
    ("toggle", lambda tag, cls, inner: "aria-pressed" in tag),
    ("expander", lambda tag, cls, inner: "icon('expand'" in inner),
    ("option", lambda tag, cls, inner: 'role="option"' in tag),
)


def _blank(m):
    """Keep every offset: a comment becomes spaces, its newlines kept."""
    return "".join(ch if ch == "\n" else " " for ch in m.group(0))


def strip_comments(src):
    src = re.sub(r"\{#.*?#\}", _blank, src, flags=re.S)
    return re.sub(r"<!--.*?-->", _blank, src, flags=re.S)


def tags(src):
    """Every <a> and <button>: (offset, opening tag, what is inside it).

    The opening tag is read quote-aware and Jinja-aware, because Alpine
    expressions carry `>` (x-show="n > 1") and would end a naive [^>]* early."""
    for m in re.finditer(r"<(a|button)\b", src):
        name = m.group(1)
        i, quote = m.end(), None
        while i < len(src):
            ch = src[i]
            if quote:
                if ch == quote:
                    quote = None
            elif src.startswith("{{", i) or src.startswith("{%", i):
                end = src.find("}}" if src[i + 1] == "{" else "%}", i)
                i = end + 2
                continue
            elif ch in "\"'":
                quote = ch
            elif ch == ">":
                break
            i += 1
        close = src.find(f"</{name}>", i)
        yield m.start(), src[m.start():i + 1], src[i + 1:close] if close != -1 else ""


def classes(tag, sets):
    """What the element draws with: class, :class, and any {% set %} variable
    either one names, as the variable's whole expression text."""
    parts = re.findall(r'(?<![\w-])(?::class|x-bind:class|class)=(?:"([^"]*)"|\'([^\']*)\')', tag)
    text = " ".join(a or b for a, b in parts)
    return re.sub(r"\{\{-?\s*(\w+)[^}]*\}\}", lambda m: sets.get(m.group(1), m.group(0)), text)


def judge(tag, cls, inner):
    """None when the press is fine, else why it is not."""
    if BOXED.search(cls):
        return None
    kind = re.search(r'data-press="([\w-]+)"', tag)
    if kind:
        check = DATA_KINDS.get(kind.group(1))
        if not check:
            return f'data-press="{kind.group(1)}" is not a kind on the allow-list'
        return None if check(tag, cls, inner) else f'does not have the shape of a "{kind.group(1)}"'
    for _, ok in ALLOWED:
        if ok(tag, cls, inner):
            return None
    return "no border, no fill, and not a kind on the allow-list"


def scan(src):
    """Every bare press in one template's text: [(line, why, tag)]."""
    src = strip_comments(src)
    sets = dict(re.findall(r"\{%-?\s*set\s+(\w+)\s*=\s*(.*?)-?%\}", src, flags=re.S))
    found = []
    for off, tag, inner in tags(src):
        why = judge(tag, classes(tag, sets), inner)
        if why:
            found.append((src.count("\n", 0, off) + 1, why, re.sub(r"\s+", " ", tag)[:140]))
    # A confirm_button draws its resting button from btn_class.
    # The macro's own definition is not a call, and a btn_class built as
    # 'shape ' ~ TONES['danger'] is judged with the variable read in.
    for m in re.finditer(r"(?<!macro )confirm_button\((.*?)\)\s*-?(?:\}\}|%\})", src, flags=re.S):
        bc = re.search(r"btn_class\s*=\s*'([^']*)'(?:\s*~\s*(\w+))?", m.group(1))
        drawn = bc.group(1) + " " + sets.get(bc.group(2) or "", "") if bc else ""
        if bc and not BOXED.search(drawn):
            found.append((src.count("\n", 0, m.start()) + 1, "confirm_button btn_class has no border or fill",
                          bc.group(1)[:140]))
    return found


failures = 0


def check(label, ok, detail=None):
    global failures
    print(("  ok   " if ok else "  FAIL ") + label)
    if not ok:
        failures += 1
        for line in (detail or []):
            print("         " + str(line))


print("EVERY PRESS ON THE BOARD IS BOXED:")
files = sorted(PM.rglob("*.html"))
check("the scan reads the board's templates", len(files) > 100, [len(files)])
bare = []
counted = 0
for path in files:
    src = path.read_text(encoding="utf-8")
    counted += sum(1 for _ in tags(strip_comments(src)))
    for line, why, tag in scan(src):
        bare.append(f"{path.relative_to(ROOT).as_posix()}:{line}  {why}\n           {tag}")
check(f"no bare link or button in templates/pm ({counted} read)", not bare, bare)

print("\nTHE GUARD CATCHES WHAT IT IS FOR:")
planted = {
    "a bare link": '<a href="/admin/x" class="text-brand-300 hover:text-brand-200">See it</a>',
    "a bare Cancel": '<a href="/x" class="px-6 py-2.5 text-sm text-surface-300 hover:text-white">Cancel</a>',
    "a bare button": '<button type="button" class="text-xs text-brand-500">Select All</button>',
    "a hover-only fill": '<button class="p-2 rounded-lg hover:bg-white/5">{{ icon(\'close\') }}</button>',
    "a side border only": '<a href="/x" class="border-b border-white/10 px-3">Open</a>',
    "a kind nobody allowed": '<a href="/x" data-press="link" class="text-brand-300">Go</a>',
    "a button claiming to be prose": '<button data-press="prose" class="text-brand-300">Go</button>',
    "a bare confirm_button": "{% call confirm_button(question='Sure?', btn_class='p-2 text-red-400') %}x{% endcall %}",
    "a bare variable": "{% set b = 'text-sm text-brand-300' %}<a href=\"/x\" class=\"{{ b }}\">Go</a>",
    "an arrow in an Alpine expression": '<button x-show="n > 1" class="text-xs">Go</button>',
}
for label, src in planted.items():
    check(f"{label} fails", len(scan(src)) == 1, [src])
passing = {
    "a bordered button": '<button class="min-h-[44px] px-3 rounded-xl border border-white/10">Cancel</button>',
    "a filled submit": '<button type="submit" class="px-6 btn-brand rounded-xl">Save</button>',
    "a bound fill": '<button :class="on ? \'bg-brand-500/20\' : \'bg-surface-800\'" class="px-3">All</button>',
    "a bordered variable": "{% set b = 'rounded-xl border border-white/10' %}<a href=\"/x\" class=\"{{ b }}\">Go</a>",
    "an expander": "<button :aria-expanded=\"o\" class=\"w-full text-left\">Row {{ icon('expand', 'w-4 h-4') }}</button>",
    "a prose link": '<p>Replaces <a href="/x" data-press="prose" class="text-brand-400">the old one</a>.</p>',
    "a row": '<a href="/x" data-press="row" class="flex items-center gap-3 hover:bg-white/5">Row</a>',
    "a link inside a comment": "{# a form cannot hold an <a> #}",
}
for label, src in passing.items():
    check(f"{label} passes", not scan(src), scan(src))

print()
if failures:
    print(f"{failures} FAILED")
    sys.exit(1)
print("All passed.")
