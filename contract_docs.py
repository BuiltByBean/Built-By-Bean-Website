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
    # Invoicing and taking the money were sold separately and read to a client
    # as one thing - "bill people and get paid" - so two thousand-dollar line
    # items for it felt like being charged twice. One product, one price.
    "billing": {
        "name": "Invoicing and payments",
        "summary": (
            "Invoices built from the work already recorded, and a way for your customers "
            "to pay them by card. Money settles directly into your own account; Built by "
            "Bean LLC never holds or handles your funds at any point."
        ),
        "includes": [
            "Invoices generated from the jobs, hours and materials already in your system",
            "Numbered, sent as PDFs, and filed against the customer they belong to",
            "A pay button on them and, where you want one, on your booking flow",
            "Payments recorded against the right invoice automatically",
            "Refunds handled from inside your application",
            "Failed and disputed payments surfaced rather than silently ignored",
        ],
        "client_provides": [
            "A payment account created by you, in your business's name - it cannot be "
            "created on your behalf",
            "Your EIN, business address, and the bank account payouts should reach",
            "Completion of the payment provider's identity check, which only you can do",
            "Your invoice numbering, payment terms, and anything that has to appear on "
            "the document",
        ],
        "lead_time": (
            "Invoicing is ready as soon as the work it bills is being recorded. Payments "
            "follow once your payment account passes its identity check, usually same-day "
            "but sometimes several days."
        ),
        "third_party": (
            "Card processing fees are charged by the payment provider directly to the "
            "Client's own account and are not included in the fee below. Built by Bean LLC "
            "receives no part of them. Stripe is used unless the Client asks for a "
            "different provider, which may change the timeline."
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


# ── Hosting and infrastructure ───────────────────────────
#
# Written once and used twice: Section 7 of the Statement of Work says this, and
# the standalone Hosting & Infrastructure Agreement says this. Two copies of a
# pricing clause is two clauses that disagree the first time one is edited.

HOSTING_INCLUDES = [
    "Application hosting on managed infrastructure, kept running and reachable",
    "Data storage and the database the application runs on",
    "SSL certificates, issued and renewed before they expire",
    "Domain and DNS management for the addresses the application answers on",
    "Routine infrastructure upkeep: platform updates, dependency and security patching",
    "Backups of application data, and restoration from them if it is ever needed",
]

HOSTING_EXCLUDES = [
    "New features, changes to existing ones, and any other development work",
    "Third-party services billed to the Client's own accounts, such as payment "
    "processing, messaging, or email delivery",
    "Content, images, and data the Client is responsible for supplying",
]

# The fee moves when the infrastructure under it moves, and it is not worth a
# month of unbillable notice every time a provider raises a price. Michael sets
# it; the Client is told in writing, with the reason, in a document they keep.
HOSTING_PRICE_CHANGE = (
    "The fee may be updated at any time. Built by Bean LLC may revise it as needed to "
    "reflect changes in infrastructure requirements, application usage, or third-party "
    "provider pricing, and is not required to give advance notice before doing so. When "
    "the fee changes, an updated agreement stating the new fee and explaining the reason "
    "for the change is sent to the Client, and the new fee applies from the first billing "
    "cycle that begins after that agreement is issued."
)

# What happens when it stops being paid. A hosting agreement without this is a
# promise to keep paying a vendor on somebody else's behalf indefinitely.
#
# Said the plain way on purpose: the fee is what keeps their application and
# their data reachable, and a month past due is where that stops until it is
# paid. The softer version of this clause asked for written notice and a
# "reasonable opportunity", which is a negotiation with somebody who has
# already stopped paying. Read into the Statement of Work, the standalone
# agreement and every fee update, from this one place.
HOSTING_LAPSE = (
    "The Hosting & Infrastructure Fee is what keeps the application online and the "
    "Client's data stored and accessible; it is the Client's hosting and data fee. If an "
    "invoice for it remains unpaid more than thirty (30) days past its due date, Built by "
    "Bean LLC may suspend the Client's access to the application and to the data it holds, "
    "and is not obliged to keep either available until the account is brought current. "
    "Once all outstanding fees are paid, access is restored in full. The Client's data "
    "remains the Client's throughout and is retained, not deleted, while access is "
    "suspended."
)

# The reason a fee goes up, said once so every update contract says it the
# same way.
HOSTING_RAISE_REASON = (
    "an increase in the data storage and infrastructure the application requires"
)


# ── Who owns what ────────────────────────────────────────
#
# Written once and read into the Statement of Work, the engagement letter and
# the standalone protections on the shorter documents, because three copies of
# an ownership clause are three clauses that will say three different things
# the first time one of them is edited, and this is the one clause that must
# not.
#
# What it says, in the order a client reads it. The code is Built by Bean's,
# outright, and stays so after payment. Built by Bean may do anything at all
# with it, including packaging it up and selling it as a product to anybody,
# and owes the client nothing for that. What the client buys is a perpetual
# license to use the application they paid for, with no renewal and no
# recurring license fee: they do not pay monthly to keep the right to use it.
# The one recurring charge is hosting, which is a different thing and says so,
# and which suspends access when unpaid without ending the license. Their
# data is theirs. An earlier version said only that Built by Bean "retains the
# right to reuse the underlying code in other work for other clients", which
# is true and narrower than the freedom the business actually needs.
IP_TERMS = [
    "All software, source code, designs, documentation and other work product created "
    "by Built by Bean LLC, including everything built for or delivered to the Client, is "
    "and remains the sole and exclusive property of Built by Bean LLC. Nothing in this "
    "agreement, and no payment made under it, transfers ownership of any of it to the "
    "Client.",

    "Built by Bean LLC is free to use, reuse, copy, modify, combine, license, distribute, "
    "sell and otherwise deal with that work product, in whole or in part, in any way and "
    "for any purpose it chooses, including reusing it in work for other clients and "
    "packaging it, or any product derived from it, for license or sale to anyone. It owes "
    "the Client no notice, consent, credit, royalty or other payment for doing so.",

    "On receipt of full payment of the build fee, the Client is granted a perpetual, "
    "royalty-free, non-exclusive, non-transferable license to use the delivered "
    "application for the Client's own business, with no renewal, no expiry and no "
    "recurring license fee. Until full payment is received, the Client has no license and "
    "no right to use the work product.",

    "That license does not permit the Client to copy, resell, sublicense, distribute or "
    "provide the application or its code to any third party, or to offer it to others as "
    "a service.",

    "The Hosting & Infrastructure Fee is the only recurring charge. It pays for keeping "
    "the application online and the Client's data stored and backed up; it is not a "
    "license fee, and the license above does not depend on it. If it goes unpaid, access "
    "to the hosted application is suspended as set out in the hosting terms and restored "
    "in full when the account is brought current. A lapse in hosting does not end the "
    "license.",

    "Client data, meaning customer records, content, files and any material the Client "
    "provides or generates through the application, is and remains the sole property of "
    "the Client at all times. Built by Bean LLC claims no ownership of it, will not sell "
    "or license it to any third party, and will provide the Client a complete export in a "
    "machine-readable format on written request.",

    "Built by Bean LLC may show completed work in its portfolio unless the Client asks "
    "otherwise in writing before the project starts.",
]


# ── Shared chrome ────────────────────────────────────────


def _document(kind_label, accent=None):
    """A blank document wearing the house style, with running heads.

    `accent` is the one thing a document may change about the look. It is the
    house violet everywhere except a co-branded one, which wears the colour of
    the thing it is about - and it has to reach the running head as well as the
    body, or page two stops matching page one.
    """

    class Doc(FPDF):
        def header(self):
            if self.page_no() == 1:
                return
            self.set_font(self.contract_family, "B", 7)
            self.set_text_color(*contract_style.MUTED)
            self.cell(75, 4, "BUILT BY BEAN LLC")
            self.set_font(self.contract_family, "", 7)
            self.set_text_color(*self.contract_accent)
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
    style = contract_style.ContractPDF(pdf, accent=accent)
    pdf.contract_family = style.family
    pdf.contract_accent = style.accent
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


# Two clauses that say nothing about who is paying whom, and one that says
# where an argument is settled. Lifted out of the list below so a document
# written the other way round - the revenue share, where Built by Bean LLC is
# the one that pays - can carry the same words without carrying the rest.
THIRD_PARTY_TERMS = [
    "Built by Bean LLC is not responsible for outages, data loss, or service interruptions "
    "caused by third-party providers, including hosting platforms, cloud storage, domain "
    "registrars, DNS providers, email delivery services, payment processors, and mobile "
    "carriers. Those services operate under their own terms and service levels.",

    "Built by Bean LLC does not guarantee 100% uptime or availability of any deployed "
    "application. Reasonable efforts will be made, and factors outside Built by Bean LLC's "
    "control - including provider failures, network outages, cyberattacks and force "
    "majeure events - may affect availability.",
]

GOVERNING_LAW = (
    "This agreement is governed by the laws of the State of Texas, and any dispute arising "
    "under it will be resolved in the courts of the State of Texas."
)


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

    *THIRD_PARTY_TERMS,

    "The Client is responsible for maintaining its own backups of any content, data or "
    "credentials it provides. Built by Bean LLC is not responsible for loss of "
    "Client-provided materials.",

    "The Client is responsible for ensuring that any content, images, trademarks or "
    "materials it provides do not infringe third-party rights, and indemnifies Built by "
    "Bean LLC against any claim arising from Client-provided materials.",

    # Ownership: the seven sentences above, spliced in here so the shorter
    # documents carry exactly what the Statement of Work carries.
    *IP_TERMS,

    "Built by Bean LLC has no obligation to perform work beyond what is described in this "
    "agreement unless separately contracted in writing.",

    "All fees are in USD. Late payments are subject to a $50 per day late fee for each day "
    "payment remains outstanding past the invoice due date.",

    GOVERNING_LAW,

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


# ── Hosting and infrastructure agreement ─────────────────


def build_hosting(*, client_name, application, fee, cycle, start_date, date_str,
                  includes=None, excludes=None, reference="", notes="",
                  countersign=False, script_font=None,
                  previous_fee=None, effective="", reason=""):
    """The recurring agreement for keeping a delivered application online.

    Section 7 of a Statement of Work already says a hosting fee is payable, but
    a SOW is signed once, when the build is scoped, and prices a project. This
    is the thing that recurs: it names the application, states the fee and the
    cycle, and carries the clause that lets the fee move when the infrastructure
    under it moves.

    `reference` is optional and it is the difference between this attaching to a
    Statement of Work and standing entirely on its own. An application taken
    over from somebody else has no SOW to point at, so with no reference the
    protections are stated outright rather than inherited from a document that
    does not exist.

    `previous_fee` turns this into a fee update: the same agreement, stating
    that the old fee is cancelled and the new one applies from `effective`,
    with the reason. One builder for both, so an update can never carry
    different words from the agreement it replaces.
    """
    pdf, style = _document("Hosting Agreement")
    pdf.add_page()

    cycle = (cycle or "monthly").lower()
    per = {"monthly": "month", "quarterly": "quarter", "annually": "year"}.get(cycle, "month")
    is_update = previous_fee not in (None, "")

    style.eyebrow("Built by Bean LLC")
    style.rule(gap=1)
    pdf.ln(6)
    style.title("Hosting & Infrastructure Agreement",
                f"{application} - {client_name}" + (" - fee update" if is_update else ""))
    facts = [("Client:", client_name), ("Date:", date_str),
             ("Application:", application),
             ("Starts:", start_date or "on signature")]
    if is_update:
        facts.append(("Replaces:", f"the ${previous_fee}/{per} fee"))
    _facts(style, facts)

    style.section_heading("1. What this covers")
    style.body(
        f"A delivered application does not stay online by itself. It runs on paid "
        f"infrastructure, answers on a domain, holds data that has to be stored and backed "
        f"up, and needs the platform underneath it kept patched and current. This "
        f"agreement covers all of that for {application}, billed separately from any "
        f"development work.")
    style.bullets(includes or HOSTING_INCLUDES)

    style.section_heading("2. What this does not cover")
    style.body(
        "This is upkeep of what has already been built. Building anything new, or "
        "changing what exists, is development work and is quoted and billed separately.")
    style.bullets(excludes or HOSTING_EXCLUDES)

    style.section_heading("3. Fee")
    style.table([
        ("Hosting & Infrastructure Fee", f"${fee}/{per}"),
        ("Billing Cycle", cycle.title()),
        ("Invoicing", "Net 30 days from invoice date"),
    ])
    style.body(
        "The fee is payable for as long as the application is hosted, and begins on the "
        "start date above.")
    if is_update:
        style.body(
            f"This agreement replaces the previous Hosting & Infrastructure Fee of "
            f"${previous_fee}/{per}, which is cancelled. The fee above applies from "
            f"{effective or 'the first billing cycle that begins after this agreement is issued'}. "
            f"The change reflects {reason or HOSTING_RAISE_REASON}. Everything else "
            f"agreed for the hosting of {application} continues unchanged.")

    style.section_heading("4. Changes to the fee")
    style.body(HOSTING_PRICE_CHANGE)

    style.section_heading("5. Term, and stopping")
    style.body(
        "This agreement continues until either party ends it in writing. The Client may "
        "end it at any time, effective at the end of the billing cycle then in progress; "
        "fees already paid for that cycle are not refunded. Built by Bean LLC will give at "
        "least thirty (30) days written notice before ending it, so the Client has time to "
        "move the application elsewhere.")
    style.body(HOSTING_LAPSE)

    if notes:
        style.section_heading("6. Notes")
        style.body(notes)

    if reference:
        _incorporated_terms(style, reference)
    else:
        # Nothing to inherit from. An application taken on from another
        # developer has no Statement of Work behind it, and a terms section
        # that only pointed at one would protect nobody.
        style.section_heading("Terms")
        style.body("The following apply to the services described here:")
        style.bullets(STANDALONE_PROTECTIONS, size=8.5)

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


# ── Revenue share, and why it is not a partnership ───────
#
# The deal this is for: Michael and somebody who knows an industry take a
# product to market together, and they split what it earns. He calls it a
# partnership and that is the right word for the relationship. It is the wrong
# word for the paper.
#
# Texas creates a general partnership out of conduct, not out of intent
# (TBOC 152.051), and a share of profits is one of the factors that makes one.
# A general partner is jointly liable for the other's debts, owes fiduciary
# duties, and can bind the business by signing something. None of that is what
# is being agreed here, so Section 2 negates every factor a court weighs:
# no capital, no losses, no control, no common property, no authority to bind,
# and an express statement that the word "partner" is a commercial description.
# The board calls the document type a partnership, because that is what he is
# doing; the document calls itself a Revenue Share Agreement, because that is
# what a court should read it as.
#
# Everything below is a default that the form can overwrite. The terms of one
# of these WILL change over time, and the way that stays honest is that the
# document is regenerated from a form rather than edited in a word processor
# until two copies disagree.

# How the share is measured. Two bases, deliberately: a share of what is left
# after the Venture's costs, or a commission on what comes in. They are worth
# many thousands of dollars apart on the same revenue, and a contract that is
# vague about which one it means is a contract that gets argued about.
SHARE_BASES = {
    "net_profit": {
        "label": "% of Net Profit",
        "noun": "Net Profit",
        "summary": (
            "Built by Bean LLC will pay the Partner {pct}% of the Net Profit of the "
            "Venture, calculated and paid as set out below. The share is a percentage "
            "of Net Profit. It is not a percentage of gross revenue and it is not a "
            "commission on sales."
        ),
    },
    "gross": {
        "label": "% of gross revenue (a commission)",
        "noun": "Gross Receipts",
        "summary": (
            "Built by Bean LLC will pay the Partner a commission of {pct}% of the Gross "
            "Receipts of the Venture, calculated and paid as set out below. The "
            "commission is calculated on money collected, before the costs of building, "
            "running and selling the Venture, and none of those costs are deducted "
            "before it is worked out."
        ),
    },
}
SHARE_BASIS_CHOICES = [(k, v["label"]) for k, v in SHARE_BASES.items()]

# What the share is calculated on. "All of it" is the ordinary deal. The other
# is the one where somebody is paid for what they bring in rather than for
# everything the product earns, and it is the difference between a share and a
# finder's fee.
SHARE_SCOPES = {
    "all": {
        "label": "Everything the Venture earns",
        "clause": ", from every customer and every channel",
    },
    "introduced": {
        "label": "Only customers the Partner introduces",
        "clause": (
            ", and only from customers the Partner introduced and which Built by Bean "
            "LLC accepted in writing as the Partner's introduction at the time"
        ),
    },
}
SHARE_SCOPE_CHOICES = [(k, v["label"]) for k, v in SHARE_SCOPES.items()]

PAY_PERIODS = {
    "monthly": {"label": "Monthly", "noun": "calendar month", "adj": "month"},
    "quarterly": {"label": "Quarterly", "noun": "calendar quarter", "adj": "quarter"},
}
PAY_PERIOD_CHOICES = [(k, v["label"]) for k, v in PAY_PERIODS.items()]

# What comes off before the split. Written as the Venture's own costs, not as
# Built by Bean's business: the whole point of a net profit share is that the
# number is real, and a deduction list that quietly swallows general overhead
# makes a 35% share of nothing.
PARTNERSHIP_DEDUCTIONS = [
    "Refunds, chargebacks, credits, and reversed or failed payments",
    "Payment processing, platform and marketplace fees",
    "Sales, use and other transaction taxes collected on behalf of a taxing authority",
    "Hosting, infrastructure, data storage, domains and third-party services the "
    "Venture runs on",
    "Software licenses, tooling and subscriptions bought for the Venture",
    "Advertising and marketing spent on the Venture",
    "Commissions, affiliate and referral payments made to anyone other than the Partner",
    "Any other direct, documented out-of-pocket cost of building, running or selling "
    "the Venture",
]

PARTNERSHIP_OUR_DUTIES = [
    "Build, maintain and improve the Venture's software",
    "Host and operate it, and own the infrastructure, domains and accounts it runs on",
    "Set pricing, packaging, the roadmap, and the terms customers are sold on",
    "Invoice customers, collect the money, and hold the accounts it is paid into",
    "Provide customer support and handle technical issues",
    "Keep the books, calculate the share, and pay it on time with a statement",
]

PARTNERSHIP_THEIR_DUTIES = [
    "Introduce the Venture to venues, clients and operators, and sell it",
    "Represent the Venture in the industry and at events, accurately and as Built by "
    "Bean LLC describes it",
    "Bring industry knowledge to what gets built: what customers need, and what they "
    "will pay for",
    "Run demonstrations and onboarding conversations with prospective customers",
    "Pass every lead, enquiry and expression of interest to Built by Bean LLC promptly, "
    "so it can be handled and recorded",
    "Keep confidential everything learned about the Venture, its customers and its "
    "finances",
]

# The clauses that negate a legal partnership, one for each factor a Texas
# court weighs. Kept whole and in this order: they are only as good as the
# completeness of the list, and dropping one is how the word "partner" on the
# front page starts doing work nobody intended.
PARTNERSHIP_NOT = [
    "This agreement does not create a partnership, joint venture, general or limited "
    "partnership, agency, franchise, employment or fiduciary relationship of any kind. "
    "The parties are independent contractors. This is a contract to share revenue and "
    "nothing more, and the word \"partner\" is used in it as a commercial description "
    "that creates none of the duties, powers or liabilities of a legal partner.",

    "The Partner contributes no capital to the Venture, holds no property in common "
    "with Built by Bean LLC, has no right to control or direct the business of the "
    "Venture, and bears none of its losses, debts or liabilities. The share is a "
    "contractual payment. It is not a distribution of partnership profits and not a "
    "return on an ownership interest.",

    "Nothing in this agreement gives the Partner any equity, membership interest, "
    "share, unit, option, warrant, profits interest, or any right to acquire any of "
    "them, in Built by Bean LLC or in the Venture.",

    "Neither party may bind the other. Neither may enter into a contract, incur an "
    "expense or liability, make a promise about price, delivery, features or support, "
    "or otherwise hold itself out as authorised to act for the other. A commitment "
    "made without that authority is the sole responsibility of the party who made it, "
    "and that party indemnifies the other against it in full.",

    "The Partner is not an employee. There is no salary, no benefits, no paid leave, "
    "no workers compensation and no unemployment insurance, and nothing is withheld "
    "from the amounts paid.",
]

# Ownership, written for this document rather than read from IP_TERMS.
#
# IP_TERMS is the answer to "who owns what the client paid me to build", and it
# is framed around a delivered application, a build fee and a license to use it.
# None of those exist here: nobody is buying anything, the counterparty is being
# paid rather than paying, and what has to be nailed down is that a share of the
# money is not a share of the thing. Two clauses that disagree about ownership
# is the one drift this repo cannot afford, so this is a separate clause that
# says so outright rather than an edit to the one the client documents read.
PARTNERSHIP_OWNERSHIP = [
    "The Venture, and everything in it, is and remains the sole and exclusive property "
    "of Built by Bean LLC. That includes all software and source code, designs, user "
    "interfaces, documentation, content, the name, the brand, the domain names, the "
    "accounts, the customer and prospect lists, and all data the Venture generates. "
    "Nothing in this agreement, and no work done or introduction made under it, "
    "transfers any part of it to the Partner.",

    "Built by Bean LLC may use, reuse, copy, modify, combine, rebrand, license, "
    "distribute, sell and otherwise deal with the Venture and any part of it, in any "
    "way and for any purpose it chooses, including reusing the code in work for other "
    "clients and packaging it, or any product derived from it, for license or sale to "
    "anyone. It owes the Partner no notice, consent, credit, royalty or other payment "
    "for doing so, beyond the share this agreement provides on Gross Receipts actually "
    "received.",

    "Everything the Partner creates, contributes, suggests or develops for the Venture, "
    "including ideas, feedback, specifications, designs, copy, images, processes, "
    "customer lists and introductions, is assigned to Built by Bean LLC as it is "
    "created and belongs to Built by Bean LLC outright. The Partner will sign whatever "
    "is reasonably needed to record that assignment, and waives any moral rights in the "
    "work.",

    "A sale, merger, financing, licensing of the whole, or other transfer of the "
    "Venture or of Built by Bean LLC, in whole or in part, is not a Gross Receipt, and "
    "no share is payable on the proceeds of it. The Partner has no interest in, and no "
    "claim on, the value of the Venture itself.",

    "During the term, Built by Bean LLC grants the Partner a limited, revocable, "
    "non-exclusive license to use the Venture's name and marks solely to promote the "
    "Venture, in the form and manner Built by Bean LLC directs. That license ends on "
    "the day this agreement ends, and the Partner stops using them that day.",

    "The Partner grants Built by Bean LLC a non-exclusive license to use the Partner's "
    "name, likeness, title and professional biography to market the Venture during the "
    "term, and afterwards only in materials already published.",
]

# The general terms, written for a document where Built by Bean LLC is the one
# paying. STANDALONE_PROTECTIONS is written for the other direction and carries
# a $50 per day late fee and a liability cap measured on fees the Client paid;
# dropped in here, the first would run against Michael and the second would
# read as zero. The clauses that genuinely do not care who pays are shared
# constants rather than copies.
PARTNERSHIP_PROTECTIONS = [
    "Each party performs on a best-effort basis. To the maximum extent permitted by "
    "law, neither party is liable to the other for indirect, incidental, consequential "
    "or punitive damages, including loss of revenue, profit, data or business "
    "opportunity, arising from or related to this agreement.",

    "Built by Bean LLC's total aggregate liability arising out of or relating to this "
    "agreement will not exceed the total amount it paid the Partner under this "
    "agreement in the twelve (12) months preceding the event giving rise to the claim.",

    *THIRD_PARTY_TERMS,

    "Each party is responsible for ensuring that any content, images, trademarks or "
    "materials it provides do not infringe third-party rights, and indemnifies the "
    "other against any claim arising from materials it provided.",

    "All amounts are in USD.",

    "This agreement is the entire agreement between the parties about the Venture and "
    "the share, and replaces any earlier discussion, proposal or understanding about "
    "it. It does not replace or affect any Statement of Work, hosting agreement, "
    "add-on agreement or other agreement between the parties for work Built by Bean "
    "LLC performs for the Partner, all of which continue in force on their own terms.",

    "It may be changed only in writing signed by both parties. An email, a text "
    "message or a conversation does not change it.",

    "Built by Bean LLC may assign this agreement, in whole or in part, including to a "
    "buyer of the Venture or of its business. The Partner may not assign it, or any "
    "right or obligation under it, and any attempt to do so is void.",

    "Notices are in writing, given by email to the addresses the parties use for the "
    "Venture or by hand or courier to the addresses on the signature page.",

    "If any provision is found unenforceable, the rest continues in force, and that "
    "provision is reduced to what is enforceable rather than struck out.",

    "A failure to enforce any provision is not a waiver of it, and a waiver on one "
    "occasion is not a waiver on another.",

    "In any dispute arising under this agreement, the prevailing party is entitled to "
    "recover its reasonable attorney's fees and costs.",

    GOVERNING_LAW,

    "This agreement may be signed in counterparts and by electronic signature, each of "
    "which is an original.",
]


def build_partnership(*, partner_name, venture, share_pct, basis="net_profit",
                      scope="all", deductions=None, our_time_rate="",
                      our_duties=None, their_duties=None,
                      period="monthly", pay_days="30", notice_days="30",
                      tail_months="0", restraint_months="12",
                      special_terms="", date_str="", title="Revenue Share Agreement",
                      accent=None, mark_path=None,
                      countersign=False, script_font=None):
    """The agreement behind taking a product to market with somebody.

    Co-branded on purpose: this document is about a thing that has its own name
    and its own audience, and it is signed by somebody who is being asked to go
    and sell it. `accent` and `mark_path` are the only look this board lets a
    document change, and both default to the house style.
    """
    spec = SHARE_BASES.get(basis) or SHARE_BASES["net_profit"]
    scoping = SHARE_SCOPES.get(scope) or SHARE_SCOPES["all"]
    cadence = PAY_PERIODS.get(period) or PAY_PERIODS["monthly"]
    pct = str(share_pct).strip().rstrip("%") or "0"
    days = str(pay_days).strip() or "30"
    notice = str(notice_days).strip() or "30"
    restraint = str(restraint_months).strip() or "12"
    tail = str(tail_months).strip() or "0"
    net = basis == "net_profit"

    pdf, style = _document(title, accent=accent)
    pdf.add_page()

    # The mark sits above the eyebrow rather than beside it, because a logo
    # whose aspect ratio nobody controls cannot share a line with type.
    style.mark(mark_path)
    style.eyebrow("Built by Bean LLC", partner=venture)
    style.rule(gap=1)
    pdf.ln(6)
    style.title(title, f"{venture} - Built by Bean LLC and {partner_name}")
    _facts(style, [
        ("Venture:", venture),
        ("Between:", f"Built by Bean LLC and {partner_name}"),
        ("Date:", date_str),
        ("Share:", f"{pct}% of {spec['noun']}"),
    ])

    style.section_heading("1. What this covers")
    style.lead(
        f"Built by Bean LLC owns and operates {venture} (the \"Venture\"). "
        f"{partner_name} (the \"Partner\") works with Built by Bean LLC to take it to "
        f"market, and in return receives a share of what it earns. This agreement sets "
        f"out what each party does, how the share is calculated, when it is paid, and "
        f"what each party may and may not do with what it learns.")

    style.section_heading("2. What this is, and what it is not")
    style.body(
        "This is a revenue share between two independent businesses. It is worth being "
        "exact about that, because the consequences of the alternative fall on both "
        "parties:")
    style.bullets(PARTNERSHIP_NOT)

    style.section_heading("3. Who does what")
    style.body("Built by Bean LLC will:")
    style.bullets(our_duties or PARTNERSHIP_OUR_DUTIES)
    style.body("The Partner will:")
    style.bullets(their_duties or PARTNERSHIP_THEIR_DUTIES)
    style.body(
        "Each party bears its own costs of doing its part. Neither is reimbursed for "
        "travel, time, equipment, marketing or anything else unless Built by Bean LLC "
        "agrees to it in writing in advance. The Partner sets their own hours and "
        "methods and is not supervised, directed or scheduled by Built by Bean LLC.")
    style.body(
        "Built by Bean LLC is free to build, sell, license and operate any other "
        "product, including one that competes with the Venture, and owes the Partner "
        "nothing in respect of it.")

    style.section_heading("4. The share")
    style.body(spec["summary"].format(pct=pct), colour=contract_style.INK)
    style.body(
        "\"Gross Receipts\" means all amounts actually received and cleared by Built by "
        "Bean LLC from the sale, license, subscription or other commercial exploitation "
        f"of the Venture{scoping['clause']}. An amount that has been invoiced, promised, "
        "pledged, committed or contracted for is not a Gross Receipt until the money "
        "has been received and has cleared.")

    if net:
        style.body(
            f"\"Net Profit\" for a period means the Gross Receipts received in that "
            f"period, less the following to the extent they relate to the Venture:")
        deducts = list(deductions or PARTNERSHIP_DEDUCTIONS)
        rate = str(our_time_rate).strip().lstrip("$")
        if rate:
            deducts.append(
                f"Built by Bean LLC's development and support time spent on the Venture, "
                f"at ${rate} per hour, recorded as it is worked")
        style.bullets(deducts)
        style.body(
            "Built by Bean LLC's general business overhead is not deducted before the "
            "share is calculated"
            + ("." if rate else
               ", and neither is its own time. The share is calculated on the Venture's "
               "own costs only.")
            + " A cost that serves the Venture and something else is apportioned "
              "honestly, and the statement says how.")
    else:
        style.body(
            "Gross Receipts are reduced by refunds, chargebacks, credits and reversed or "
            "failed payments, and exclude sales, use and other transaction taxes "
            "collected on behalf of a taxing authority. Nothing else is deducted before "
            "the commission is calculated: the costs of building, hosting, running, "
            "supporting and marketing the Venture are borne by Built by Bean LLC out of "
            "its own share.")

    style.section_heading("5. When the Partner is paid")
    style.callout([
        "The Partner is paid out of money that has arrived.",
        "Built by Bean LLC does not pay the Partner before it has been paid itself, and "
        "does not advance any part of the share against revenue that has not been "
        "received. Nothing is earned on an invoice, a promise, a pledge or a signed "
        "order until the money is in the account and has cleared.",
    ])
    style.bullets([
        f"The share is calculated for each {cadence['noun']} and paid within {days} days "
        f"of the end of it, on amounts received and cleared during that {cadence['adj']}.",

        f"A {cadence['adj']} in which nothing was received and cleared produces no "
        f"payment, and nothing is carried forward as a debt.",

        "No advance, draw, retainer, guarantee or minimum is payable, and no part of the "
        "share is payable before the money it is calculated on has been received.",

        "If an amount the share has already been paid on is later refunded, charged back "
        "or reversed, the Partner's share of it is deducted from the next payment due. "
        "If no further payment becomes due within ninety (90) days, the Partner repays "
        "it within thirty (30) days of being asked.",

        "Built by Bean LLC may set off against any payment due under this agreement any "
        "amount the Partner owes it.",

        "Payment is made by ACH or another method Built by Bean LLC chooses, to an "
        "account the Partner names in writing. Nothing is withheld for taxes: the "
        "Partner is responsible for all taxes on amounts paid, and a Form 1099 is issued "
        "where the law requires one.",
    ])

    style.section_heading("6. Statements, records and questions")
    style.bullets([
        "Each payment is accompanied by a statement showing the Gross Receipts for the "
        "period, what was deducted, and how the share was calculated.",

        "The Partner may question a statement in writing within sixty (60) days of "
        "receiving it. A statement not questioned in that time is final and binding and "
        "is not reopened later.",

        "Once in any twelve (12) months, on fifteen (15) days written notice, the Partner "
        "may have an independent accountant bound to confidentiality review the records "
        "behind the statements for the preceding twelve months, at the Partner's own "
        "expense, during business hours and without disrupting the business. If that "
        "review finds an underpayment of more than five percent (5%) for the period "
        "reviewed, Built by Bean LLC pays the cost of the review as well as the "
        "shortfall.",

        "Built by Bean LLC keeps the books and controls the bank accounts, the payment "
        "processor, the hosting accounts and the administration of the Venture. Nothing "
        "in this agreement gives the Partner access to any of them, or any right to "
        "direct how money is held or spent.",
    ])

    style.section_heading("7. Who owns what")
    style.body(
        "A share of the money is not a share of the thing that earns it. This section "
        "says so in terms:")
    style.bullets(PARTNERSHIP_OWNERSHIP)

    style.section_heading("8. Confidentiality, and staying out of each other's way")
    style.body(
        "Built by Bean LLC will give the Partner confidential information about the "
        "Venture, including its customers, its pricing, its finances and how it is "
        "built, which the Partner would not otherwise have. The commitments in this "
        "section are given in exchange for that information and are ancillary to it.")
    style.bullets([
        "\"Confidential Information\" means anything either party learns from the other "
        "that is not public, including customer and prospect lists, pricing, financial "
        "information, source code, product plans, and the terms of this agreement. Each "
        "party keeps it confidential, uses it only for the Venture, and does not "
        "disclose it to anyone else. This continues for three (3) years after this "
        "agreement ends, and for as long as the law protects it in the case of a trade "
        "secret.",

        f"During the term and for {restraint} months after it ends, the Partner will not "
        f"build, market, sell, promote or hold an interest in a product or service that "
        f"competes with the Venture in the markets the Venture is offered in, and will "
        f"not help anyone else do so.",

        f"During the term and for {restraint} months after it ends, the Partner will not "
        f"approach any customer, former customer or identified prospect of the Venture "
        f"to supply them a competing product or service, and will not divert, or attempt "
        f"to divert, revenue away from the Venture.",

        "During the term and for twelve (12) months after it ends, neither party will "
        "solicit or hire the other's employees or contractors.",

        "Neither party will disparage the other, or the Venture, publicly or to a "
        "customer.",

        "The parties agree these restrictions are reasonable in time, scope and "
        "geography, that a breach would cause harm money could not adequately repair, "
        "and that the party harmed may seek an injunction without posting a bond in "
        "addition to any other remedy. If a court finds any of them broader than the law "
        "allows, it is reduced to what is allowed rather than struck out.",
    ])

    style.section_heading("9. Term, and ending it")
    ending = [
        "This agreement starts on the date of the last signature below and continues "
        "until it is ended under this section.",

        f"Either party may end it for any reason on {notice} days written notice.",

        "Built by Bean LLC may end it immediately, in writing, if the Partner breaches "
        "this agreement and does not fix the breach within ten (10) days of being told, "
        "misrepresents their authority, acts dishonestly, discloses Confidential "
        "Information, or does something that damages the Venture or its reputation.",
    ]
    if tail in ("", "0"):
        ending.append(
            "On the day this agreement ends, the Partner's right to a share ends with "
            "it. Built by Bean LLC pays the share on Gross Receipts received and cleared "
            "up to that day, on the normal schedule, and nothing further is payable on "
            "money received after it.")
    else:
        ending.append(
            f"On the day this agreement ends, Built by Bean LLC pays the share on Gross "
            f"Receipts received and cleared up to that day, on the normal schedule, and "
            f"continues to pay it on Gross Receipts received during the {tail} months "
            f"after it. Nothing is payable on money received after that, and the "
            f"Partner's right to any share then ends.")
    ending += [
        "The Partner stops representing the Venture on the day it ends, returns or "
        "destroys everything confidential, and stops using the Venture's name and marks.",

        "The Venture continues to belong to and be operated by Built by Bean LLC, which "
        "may continue it, change it, sell it or discontinue it. The Partner has no claim "
        "on it and no right to any part of it.",

        "This agreement is personal to the Partner. It ends on the Partner's death or "
        "long-term incapacity, is not assignable by the Partner, does not pass to an "
        "estate, heir or assign, and cannot be pledged or used as security. Amounts "
        "already earned and unpaid at that point are paid to the Partner or their "
        "estate.",

        "The sections on ownership, confidentiality and the restrictions above, together "
        "with limitation of liability and governing law, survive the end of this "
        "agreement, as does any amount earned and unpaid.",
    ]
    style.bullets(ending)

    style.section_heading("10. No guarantee of revenue")
    style.bullets([
        "Built by Bean LLC does not guarantee that the Venture will earn any revenue, "
        "any profit, or anything at all. There is no minimum, no floor and no promise of "
        "a result. A period in which the share is zero is not a breach of this "
        "agreement.",

        "Every decision about the Venture is Built by Bean LLC's alone, in its sole "
        "discretion: what is built and when, what it costs, who it is sold to, how it is "
        "marketed, which customers are accepted or refused, and whether the Venture "
        "continues, pauses or stops. Nothing in this agreement obliges Built by Bean LLC "
        "to develop, market, sell, continue or maximise the revenue or profit of the "
        "Venture, and no such obligation is implied.",

        "The Partner has relied on no promise, projection, forecast or statement about "
        "what the Venture might earn, and none has been made.",
    ])

    n = 11
    if special_terms:
        style.section_heading(f"{n}. Terms specific to this agreement")
        style.body(special_terms)
        style.body(
            "Where this section and anything above it conflict, this section governs, "
            "and only on the point it covers.")
        n += 1

    style.section_heading(f"{n}. General terms")
    style.bullets(PARTNERSHIP_PROTECTIONS, size=8.5)

    own, client = _signatures(style, partner_name, date_str, countersign, script_font)
    return bytes(pdf.output()), own, client, pdf.w, pdf.h
