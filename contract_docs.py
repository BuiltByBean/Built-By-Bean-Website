"""The two shorter contracts: selling an add-on, and amending what is signed.

Neither is a Statement of Work. A SOW scopes and prices a build; these two
attach to one that already exists. So both incorporate the SOW by reference
rather than restating its terms, which keeps them to two pages and keeps one
set of intellectual property, liability and governing-law clauses in the world
instead of three drifting copies.

Drawn with contract_style, so they look like the SOW and the engagement letter
and like the website, and so a layout fix lands in all four.
"""
from fpdf import FPDF

import contract_style

# Where a signature field sits on its line, in millimetres. Matches the SOW so
# every document this board sends places its fields identically.
SIGN_FIELD_X, SIGN_FIELD_W, SIGN_FIELD_H = 61.0, 86.0, 6.0
SIGN_LABELS = ["Signature", "Printed Name", "Title", "Date"]


# ── What can be sold ─────────────────────────────────────
#
# Written for the client, not for me. The playbooks hold the operational truth
# about each of these and are full of things a client should never read; this
# is the half of it they are buying, plus the half they have to do themselves,
# which is the part that decides whether it lands on time.

PRODUCTS = {
    "texting": {
        "name": "Text messaging",
        "summary": (
            "Your application sends text messages to your customers from a phone number "
            "registered to your business - appointment confirmations, arrival notices, "
            "invoice and receipt links. Customers opt in themselves, and a reply of STOP "
            "removes them permanently."
        ),
        "includes": [
            "A phone number registered to your business with the mobile carriers",
            "Consent collection built into your existing forms, worded to carrier standards",
            "Automatic messages tied to the events you choose",
            "STOP and HELP handled automatically, with opt-outs recorded against the customer",
            "Delivery status visible for every message sent",
        ],
        "client_provides": [
            "Your legal business name exactly as filed, and your EIN or Tax ID",
            "Business address, business phone, and an email address on your own domain",
            "A named point of contact with an email and mobile number",
            "A decision on whether you will ever send promotional messages, or only "
            "messages about work a customer has already requested",
        ],
        "lead_time": (
            "Carrier registration is a legal identity check run by the mobile carriers, not "
            "by Built by Bean LLC. It typically takes one to three weeks from the date all "
            "of the information above is received, and can be rejected for reasons outside "
            "either party's control, in which case it is resubmitted at no additional charge."
        ),
        "third_party": (
            "Message and phone number fees are charged by the messaging provider directly to "
            "the Client's own account and are not included in the fee below."
        ),
    },
    "signadoc": {
        "name": "Electronic signatures",
        "summary": (
            "Send documents out for signature from inside your application. The recipient "
            "opens a link, signs in a browser without creating an account, and both sides "
            "get a completed PDF with a tamper-evident record of who signed what and when."
        ),
        "includes": [
            "Send any document for signature from inside your application",
            "Signature, date and name fields placed on the document before it goes out",
            "A one-click link for the signer, with no account to create",
            "Documents requiring more than one signature, signed in the order you choose",
            "A sealed PDF and a full audit trail once everyone has signed",
            "Signed documents stored against the customer they belong to",
        ],
        "client_provides": [
            "The documents or templates you want to send",
            "Who signs each one, and in what order",
            "The address signing requests should appear to come from",
        ],
        "lead_time": (
            "No third-party approval is required. Delivery is scheduled by agreement once "
            "this agreement is signed."
        ),
        "third_party": "",
    },
    "payments": {
        "name": "Card payments",
        "summary": (
            "Take card payments through your application, into your own payment account. "
            "Money settles directly to your bank; Built by Bean LLC never holds or handles "
            "your funds at any point."
        ),
        "includes": [
            "A pay button on your invoices and, where you want one, on your booking flow",
            "Payments recorded against the right job automatically",
            "Refunds handled from inside your application",
            "Failed and disputed payments surfaced rather than silently ignored",
        ],
        "client_provides": [
            "A payment account created by you, in your business's name - it cannot be "
            "created on your behalf",
            "Your EIN, business address, and the bank account payouts should reach",
            "Completion of the payment provider's identity check, which only you can do",
        ],
        "lead_time": (
            "Available as soon as your payment account passes its identity check, which is "
            "usually same-day but can take several days."
        ),
        "third_party": (
            "Card processing fees are charged by the payment provider directly to the "
            "Client's own account and are not included in the fee below. Built by Bean LLC "
            "receives no part of them."
        ),
    },
    "email": {
        "name": "Email from your own domain",
        "summary": (
            "Your application sends email as your business rather than from a generic "
            "address - confirmations, invoices, reminders - so it arrives looking like it "
            "came from you and is far less likely to be filtered as spam."
        ),
        "includes": [
            "Sending set up on your own domain, verified with the mail providers",
            "Your templates styled to match your business",
            "Delivery, bounce and spam status visible for every message",
        ],
        "client_provides": [
            "Access to wherever your domain's DNS is managed, or somebody who can add "
            "three records to it",
            "The address email should come from, and where replies should go",
        ],
        "lead_time": (
            "Domain verification is a DNS change and usually completes within a day of the "
            "records being added, though it depends on who manages your DNS."
        ),
        "third_party": "",
    },
    "other": {
        "name": "",
        "summary": "",
        "includes": [],
        "client_provides": [],
        "lead_time": "",
        "third_party": "",
    },
}

PRODUCT_CHOICES = [(k, v["name"] or "Something else") for k, v in PRODUCTS.items()]


# ── Shared chrome ────────────────────────────────────────


def _document(kind_label):
    """A blank document wearing the house style, with running heads."""

    class Doc(FPDF):
        def header(self):
            if self.page_no() == 1:
                return
            self.set_font(self.contract_family, "B", 7)
            self.set_text_color(*contract_style.MUTED)
            self.cell(75, 4, "BUILT BY BEAN LLC")
            self.set_font(self.contract_family, "", 7)
            self.set_text_color(*contract_style.ACCENT)
            self.cell(0, 4, kind_label, align="R", new_x="LMARGIN", new_y="NEXT")
            self.set_draw_color(*contract_style.PAPER_EDGE)
            self.set_line_width(0.3)
            self.line(30, self.get_y() + 1, 180, self.get_y() + 1)
            self.ln(5)

        def footer(self):
            self.set_y(-15)
            self.set_font(self.contract_family, "", 7)
            self.set_text_color(*contract_style.MUTED)
            self.cell(0, 5, f"Confidential - Built by Bean LLC    Page {self.page_no()}",
                      align="C")

    pdf = Doc()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.set_margins(30, 25, 30)
    style = contract_style.ContractPDF(pdf)
    pdf.contract_family = style.family
    return pdf, style


def _facts(style, rows):
    """The who and when block under the title."""
    pdf = style.pdf
    for label, value in rows:
        pdf.set_font(style.family, "B", 10)
        pdf.set_text_color(*contract_style.INK)
        pdf.cell(24, 6, label)
        pdf.set_font(style.family, "", 10)
        pdf.set_text_color(*contract_style.BODY)
        pdf.cell(0, 6, contract_style.sanitize(value), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)


def _signatures(style, client_name, date_str, countersign, script_font=None):
    """Both parties, kept on one page, with fields when it is signed online.

    Returns (own_anchors, client_anchors) - empty for whichever party is
    pre-filled, which is Built by Bean on a printed copy.
    """
    pdf = style.pdf
    # Heading, intro and two blocks together. Two parties signing an agreement
    # on different pages is how a page goes missing from a scan.
    if pdf.get_y() + 130 > pdf.h - pdf.b_margin:
        pdf.add_page()
    pdf.ln(4)
    style.rule()
    pdf.ln(6)
    pdf.set_font(style.family, "B", 10)
    pdf.set_text_color(*contract_style.INK)
    pdf.cell(0, 7, "SIGNATURES", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2)
    style.body("By signing below, both parties agree to the terms set out above.")

    def block(party, prefill=None, anchors=None):
        pdf.set_font(style.family, "B", 10)
        pdf.set_text_color(*contract_style.INK)
        pdf.cell(0, 7, contract_style.sanitize(party), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(2)
        for label in SIGN_LABELS:
            pdf.set_font(style.family, "", 10)
            pdf.set_text_color(*contract_style.INK)
            if prefill and label in prefill:
                pdf.cell(30, 8, f"{label}:")
                if label == "Signature" and script_font:
                    pdf.set_font(script_font, "", 20)
                pdf.set_text_color(*contract_style.BODY)
                pdf.cell(100, 8, contract_style.sanitize(prefill[label]),
                         new_x="LMARGIN", new_y="NEXT")
            else:
                if anchors is not None:
                    anchors.append({"label": label, "page": pdf.page_no(),
                                    "y": pdf.get_y(), "x": SIGN_FIELD_X,
                                    "w": SIGN_FIELD_W, "h": SIGN_FIELD_H})
                pdf.cell(30, 8, f"{label}:")
                pdf.cell(100, 8, "_" * 50, new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)
        pdf.ln(6)

    own_anchors, client_anchors = [], []
    if countersign:
        block("Built by Bean LLC", anchors=own_anchors)
    else:
        block("Built by Bean LLC", prefill={
            "Signature": "Michael Bean", "Printed Name": "Michael Bean",
            "Title": "Owner, Built by Bean LLC", "Date": date_str})
    block(client_name, anchors=client_anchors)
    return own_anchors, client_anchors


# The protections, in one place, so no document can be missing them.
#
# Written to stand on their own. A document that only inherited these from a
# Statement of Work would inherit nothing on the day there is no SOW - an
# add-on sold to somebody who never had one, or an addendum to a contract
# papered years ago on somebody else's template - and that is exactly the
# document you would want them on.
STANDALONE_PROTECTIONS = [
    "Built by Bean LLC provides services on a best-effort basis. To the maximum extent "
    "permitted by law, Built by Bean LLC is not liable for any indirect, incidental, "
    "consequential or punitive damages, including loss of revenue, data, or business "
    "opportunity, arising from or related to the services provided.",

    "Built by Bean LLC's total aggregate liability arising out of or relating to this "
    "agreement will not exceed the total fees paid by the Client under this agreement in "
    "the twelve (12) months preceding the event giving rise to the claim.",

    "Built by Bean LLC is not responsible for outages, data loss, or service interruptions "
    "caused by third-party providers, including hosting platforms, cloud storage, domain "
    "registrars, DNS providers, email delivery services, payment processors, and mobile "
    "carriers. Those services operate under their own terms and service levels.",

    "Built by Bean LLC does not guarantee 100% uptime or availability of any deployed "
    "application. Reasonable efforts will be made, and factors outside Built by Bean LLC's "
    "control - including provider failures, network outages, cyberattacks and force "
    "majeure events - may affect availability.",

    "The Client is responsible for maintaining its own backups of any content, data or "
    "credentials it provides. Built by Bean LLC is not responsible for loss of "
    "Client-provided materials.",

    "The Client is responsible for ensuring that any content, images, trademarks or "
    "materials it provides do not infringe third-party rights, and indemnifies Built by "
    "Bean LLC against any claim arising from Client-provided materials.",

    "All software, source code and designs created by Built by Bean LLC remain the "
    "exclusive property of Built by Bean LLC. On full payment the Client holds a "
    "perpetual, non-exclusive, non-transferable license to use them for its own business. "
    "The Client's own data remains the Client's at all times.",

    "Built by Bean LLC has no obligation to perform work beyond what is described in this "
    "agreement unless separately contracted in writing.",

    "All fees are in USD. Late payments are subject to a $50 per day late fee for each day "
    "payment remains outstanding past the invoice due date.",

    "This agreement is governed by the laws of the State of Texas, and any dispute arising "
    "under it will be resolved in the courts of the State of Texas.",

    "This agreement, once signed by both parties, is binding for the scope and terms "
    "described in it.",
]


def _incorporated_terms(style, reference):
    """The terms this document carries, whether or not a SOW sits behind it.

    Two halves. The first inherits the Statement of Work, so its clauses are
    not restated in full and cannot drift from it. The second states the
    protections outright, "whether or not" that agreement is in force, because
    a document that only inherits them protects nobody on the day the thing it
    inherits from is missing, unclear, or somebody else's template.
    """
    style.section_heading("Terms")
    style.body(
        f"This agreement is entered into under, and forms part of, {reference}. All terms "
        "of that agreement - including intellectual property and licensing, limitation of "
        "liability, confidentiality, and governing law - apply to the work described here. "
        "Where this agreement and that one conflict, this one governs for the work "
        "described here only.")
    style.body(
        "In addition, and whether or not any agreement referred to above is in force, the "
        "following apply to the work described here:")
    style.bullets(STANDALONE_PROTECTIONS, size=8.5)
    style.bullets([
        "Work described here is in addition to any delivered scope and does not extend any "
        "free maintenance window.",
        "Third-party service fees, where noted, are charged to the Client directly by the "
        "provider and are not collected by Built by Bean LLC.",
    ], size=8.5)


# ── Add-on agreement ─────────────────────────────────────


def build_addon(*, client_name, product_key, product_name, summary, includes,
                client_provides, lead_time, third_party, one_time_fee,
                monthly_fee, date_str, reference, notes="", countersign=False,
                script_font=None):
    """A short agreement for one product sold on top of an existing build."""
    pdf, style = _document("Add-On Agreement")
    pdf.add_page()

    style.eyebrow("Built by Bean LLC")
    style.rule(gap=1)
    pdf.ln(6)
    style.title("Add-On Agreement", f"{product_name} - {client_name}")
    _facts(style, [("Client:", client_name), ("Date:", date_str),
                   ("Product:", product_name)])

    style.section_heading("1. What this covers")
    style.body(summary)
    if includes:
        style.body("Included:")
        style.bullets(includes)

    if client_provides:
        style.section_heading("2. What you provide")
        style.body(
            "This part cannot be done for you, and the timeline below starts when all of "
            "it has been received.")
        style.bullets(client_provides)

    style.section_heading("3. Fee")
    rows = []
    if one_time_fee:
        rows.append(("One-time fee", f"${one_time_fee}"))
    if monthly_fee:
        rows.append(("Ongoing", f"${monthly_fee}/month"))
    if not rows:
        rows.append(("Fee", "Included at no additional charge"))
    style.table(rows)
    if third_party:
        style.body(third_party)

    if lead_time:
        style.section_heading("4. Timeline")
        style.body(lead_time)

    if notes:
        style.section_heading("5. Notes")
        style.body(notes)

    _incorporated_terms(style, reference)
    own, client = _signatures(style, client_name, date_str, countersign, script_font)
    return bytes(pdf.output()), own, client, pdf.w, pdf.h


# ── Addendum ─────────────────────────────────────────────


def build_addendum(*, client_name, original_title, original_date, description,
                   fee_change, date_str, effective, countersign=False,
                   script_font=None):
    """An amendment to a contract that is already signed."""
    pdf, style = _document("Addendum")
    pdf.add_page()

    style.eyebrow("Built by Bean LLC")
    style.rule(gap=1)
    pdf.ln(6)
    style.title("Contract Addendum", f"{original_title} - {client_name}")
    _facts(style, [("Client:", client_name), ("Date:", date_str),
                   ("Amends:", original_title),
                   ("Dated:", original_date or "as signed")])

    # Ahead of everything, because somebody reading an amendment needs to know
    # what it attaches to before they read what it changes.
    style.body(
        f"This Addendum amends the {original_title}"
        + (f" dated {original_date}" if original_date else "")
        + f" between Built by Bean LLC and {client_name} (the \"Original Agreement\"). "
        "It takes effect on " + (effective or "the date of the last signature below") + ".",
        colour=contract_style.INK)

    style.section_heading("1. What changes")
    style.body(description)

    if fee_change:
        style.section_heading("2. Fee")
        style.body(fee_change)

    style.section_heading("3. Everything else stands")
    style.body(
        "Except as expressly changed above, every term of the Original Agreement remains in "
        "full force and effect and is unchanged. Nothing in this Addendum waives any right "
        "under the Original Agreement, and nothing in it restarts, duplicates or resets any "
        "payment schedule, term or notice period.")
    style.body(
        "Where this Addendum and the Original Agreement conflict, this Addendum governs, "
        "and only on the point it changes.")

    # Stated rather than inherited. An addendum to an agreement papered years
    # ago on somebody else's template inherits whatever that template said,
    # which may be nothing at all.
    style.section_heading("4. Terms")
    style.body(
        "The following apply to this Addendum whether or not the Original Agreement "
        "provides for them:")
    style.bullets(STANDALONE_PROTECTIONS, size=8.5)

    own, client = _signatures(style, client_name, date_str, countersign, script_font)
    return bytes(pdf.output()), own, client, pdf.w, pdf.h
