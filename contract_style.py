"""One look, and one set of drawing helpers, for every document a client sees.

The engagement letter and the statement of work each carried their own copy of
these helpers, and the copies had drifted. The letter's header drew the company
name and the tagline at the same Y and printed one on top of the other; the
SOW's header was fine. The letter had no page-break guard on section headings;
the SOW did. The letter's header only appeared on page one because it was
called by hand instead of from FPDF's own `header` hook.

None of that is a hard problem. It is two copies of the same code, which is why
this file exists: there is now one copy, and a fix lands in both documents.

Palette is the website's, translated for paper. The site is near-black with a
violet primary; a contract is ink on white with the same violet doing the work
the gold used to. Type is Inter, the site's face, instanced from Google's
variable font into the two static weights fpdf needs.
"""
import os

# --- palette -------------------------------------------------------------
# Taken from static/css/style.css and darkened where a screen colour would be
# too light on paper. --primary is #c084fc on the site; #a855f7 (its
# --primary-dark) is what survives print.
INK = (24, 24, 27)          # headings and the client's own name
BODY = (82, 82, 91)         # running text
MUTED = (113, 113, 122)     # labels, footer, anything supporting
ACCENT = (168, 85, 247)     # the site's violet, used for rules and the eyebrow
RULE = (214, 214, 220)      # hairlines inside tables
PAPER_EDGE = (235, 235, 238)

# --- type ----------------------------------------------------------------
FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "fonts")
_REGULAR = os.path.join(FONT_DIR, "Inter-Regular.ttf")
_BOLD = os.path.join(FONT_DIR, "Inter-Bold.ttf")

# Named once so a document never hard-codes "Helvetica" and quietly diverges
# from the rest when the font files are present.
FAMILY = "Inter"
FALLBACK = "Helvetica"


def register_fonts(pdf):
    """Load Inter if it is on disk, and report which family to use.

    Falls back to Helvetica rather than raising. A contract that renders in the
    wrong face is a document; a contract that does not render is an outage, and
    this runs while somebody is waiting to send one.
    """
    if os.path.exists(_REGULAR) and os.path.exists(_BOLD):
        try:
            pdf.add_font(FAMILY, "", _REGULAR)
            pdf.add_font(FAMILY, "B", _BOLD)
            return FAMILY
        except Exception:
            pass
    return FALLBACK


def sanitize(text):
    """Flatten the typography Word and the web insert into what a PDF core
    font can draw. Kept here so both documents strip the same characters."""
    if text is None:
        return ""
    for bad, good in (("—", "-"), ("–", "-"), ("‘", "'"),
                      ("’", "'"), ("“", '"'), ("”", '"'),
                      ("…", "..."), (" ", " "), ("•", "-")):
        text = text.replace(bad, good)
    return text


class ContractPDF:
    """Thin wrapper over an FPDF instance holding the house style.

    Not a subclass: the two documents already subclass FPDF for their own
    header and footer, and inheritance in two directions is how this got
    duplicated in the first place.
    """

    LEFT = 30
    RIGHT = 180

    def __init__(self, pdf):
        self.pdf = pdf
        self.family = register_fonts(pdf)

    # -- primitives -------------------------------------------------------

    def _font(self, style="", size=10):
        self.pdf.set_font(self.family, style, size)

    def rule(self, colour=ACCENT, width=0.5, gap=0):
        p = self.pdf
        p.set_draw_color(*colour)
        p.set_line_width(width)
        y = p.get_y() + gap
        p.line(self.LEFT, y, self.RIGHT, y)

    def space_needed(self, mm):
        """Start a new page rather than orphan `mm` of content at the bottom."""
        p = self.pdf
        if p.get_y() + mm > p.h - p.b_margin:
            p.add_page()
            return True
        return False

    # -- blocks -----------------------------------------------------------

    def eyebrow(self, text):
        self._font("B", 7.5)
        self.pdf.set_text_color(*ACCENT)
        self.pdf.cell(0, 4, sanitize(text).upper(), new_x="LMARGIN", new_y="NEXT")
        self.pdf.ln(1)

    def title(self, text, subtitle=""):
        p = self.pdf
        self._font("B", 21)
        p.set_text_color(*INK)
        p.cell(0, 11, sanitize(text), new_x="LMARGIN", new_y="NEXT")
        if subtitle:
            self._font("", 10.5)
            p.set_text_color(*MUTED)
            p.multi_cell(0, 5.5, sanitize(subtitle))
        p.ln(4)

    def section_heading(self, text):
        # A heading needs its first lines with it. 34mm is a heading, its rule
        # and roughly three lines of body, which is enough that a section never
        # opens alone at the foot of a page.
        self.space_needed(34)
        p = self.pdf
        p.ln(5)
        self._font("B", 10)
        p.set_text_color(*INK)
        p.cell(0, 6.5, sanitize(text).upper(), new_x="LMARGIN", new_y="NEXT")
        self.rule()
        p.ln(4.5)

    def body(self, text, size=10, colour=BODY, leading=5.4):
        p = self.pdf
        self._font("", size)
        p.set_text_color(*colour)
        # Left-aligned, not justified. Justification at this measure opens
        # rivers of white space through the paragraph, which is what made the
        # old documents look self-published.
        p.multi_cell(0, leading, sanitize(text), align="L")
        p.ln(2.6)

    def lead(self, text):
        """The opening paragraph, or anything that has to be read first."""
        self.body(text, size=10.5, colour=INK, leading=5.8)

    def callout(self, lines):
        """A bordered block for something the reader must not skim past."""
        p = self.pdf
        self._font("", 9.5)
        # Measure first so the whole block moves to the next page together.
        height = sum(len(p.multi_cell(self.RIGHT - self.LEFT - 12, 5.2, sanitize(l),
                                      dry_run=True, output="LINES")) * 5.2 + 2.4
                     for l in lines) + 9
        self.space_needed(height + 4)
        top = p.get_y()
        p.set_fill_color(250, 248, 253)
        p.set_draw_color(*ACCENT)
        p.set_line_width(0.4)
        p.rect(self.LEFT, top, self.RIGHT - self.LEFT, height, style="DF")
        p.set_xy(self.LEFT + 6, top + 4.5)
        for i, line in enumerate(lines):
            self._font("B" if i == 0 else "", 9.5)
            p.set_text_color(*(INK if i == 0 else BODY))
            p.set_x(self.LEFT + 6)
            p.multi_cell(self.RIGHT - self.LEFT - 12, 5.2, sanitize(line), align="L")
            p.ln(1.2)
        p.set_y(top + height)
        p.ln(4)

    def table(self, rows, label_w=52):
        """Label/value rows. The whole table moves together or not at all."""
        p = self.pdf
        row_h = 9.5
        self.space_needed(len(rows) * row_h + 4)
        value_w = self.RIGHT - self.LEFT - label_w
        for label, value in rows:
            self._font("B", 9)
            p.set_text_color(*INK)
            p.cell(label_w, row_h, sanitize(label))
            self._font("", 9)
            p.set_text_color(*BODY)
            p.cell(value_w, row_h, sanitize(value), new_x="LMARGIN", new_y="NEXT")
            p.set_draw_color(*RULE)
            p.set_line_width(0.2)
            p.line(self.LEFT, p.get_y(), self.RIGHT, p.get_y())
        p.ln(4)

    def bullets(self, items, size=9.5):
        """A hanging indent that survives wrapping.

        The old version printed a dash and then a full-width multi_cell, so the
        second line of a long bullet ran back to the left margin and lined up
        under the dash instead of under the text.
        """
        p = self.pdf
        indent = 5.0
        for item in items:
            self._font("", size)
            p.set_text_color(*BODY)
            lines = p.multi_cell(self.RIGHT - self.LEFT - indent, 5.2, sanitize(item),
                                 dry_run=True, output="LINES")
            self.space_needed(len(lines) * 5.2 + 2)
            y = p.get_y()
            p.set_xy(self.LEFT, y)
            p.cell(indent, 5.2, "-")
            p.set_xy(self.LEFT + indent, y)
            p.multi_cell(self.RIGHT - self.LEFT - indent, 5.2, sanitize(item), align="L")
            p.ln(1.6)
        p.ln(2)

    def signature_block(self, party, name="", title="", date="", script_font=None):
        """One party's signature lines, kept whole on a single page."""
        p = self.pdf
        self.space_needed(46)
        self._font("B", 10)
        p.set_text_color(*INK)
        p.cell(0, 6, sanitize(party), new_x="LMARGIN", new_y="NEXT")
        p.ln(2)
        for label, value in (("Signature", name), ("Printed Name", name),
                             ("Title", title), ("Date", date)):
            self._font("", 9)
            p.set_text_color(*MUTED)
            p.cell(30, 8, label + ":")
            if value:
                if label == "Signature" and script_font:
                    p.set_font(script_font, "", 16)
                else:
                    self._font("", 9.5)
                p.set_text_color(*INK)
                p.cell(0, 8, sanitize(value), new_x="LMARGIN", new_y="NEXT")
            else:
                y = p.get_y() + 6
                p.set_draw_color(*RULE)
                p.set_line_width(0.3)
                p.line(self.LEFT + 32, y, self.RIGHT - 6, y)
                p.ln(8)
        p.ln(4)
