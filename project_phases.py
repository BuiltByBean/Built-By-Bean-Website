"""Move projects along on their own.

A phase is not a thing to remember to update. Every transition after the build
starts is already written down somewhere else — the delivery date came off the
statement of work, the go-live date is set when it goes live, and the free
maintenance window is a number of days from that. So the board reads those and
moves itself.

Two rules keep it from being annoying:

**Forward only.** The phase order in PHASE_CHOICES is the order of this list,
and nothing here ever moves a project back up it. A phase you advanced by hand
is never undone by a date.

**A hand-set phase holds.** mvp_date is what the contract *promised*, not what
happened. A build running two weeks late would otherwise be marched to
Delivered by its own contract date, and marched straight back every time you
corrected it. Changing a phase by hand sets phase_locked, and this leaves that
project alone until you say resume.

Contracted -> MVP is deliberately not automated: nothing in the data says
"started", and guessing from the first logged hour would move projects on the
day you did ten minutes of scoping.
"""

from datetime import date

from forms import PHASE_CHOICES
from models import db, Project

# The order is the list's order. index() is the comparison, so a phase missing
# from here would raise rather than silently sort as "earliest".
PHASE_ORDER = [key for key, _ in PHASE_CHOICES]
PHASE_LABELS = dict(PHASE_CHOICES)

# Phases nothing advances out of automatically, because no date implies them.
MANUAL_ONLY = ("contracted", "mvp")

# A project nobody is working on should not be marching through phases in the
# background; the board would fill with movement that means nothing.
SKIP_STATUSES = ("archived",)


def rank(phase):
    """Where a phase sits in the order, or -1 for anything unrecognised."""
    try:
        return PHASE_ORDER.index(phase or "")
    except ValueError:
        return -1


def due_phase(project, today=None):
    """The phase this project's own dates say it is in, or None.

    None means the dates have nothing to say — which is the normal answer for
    everything before delivery, and why the first two phases are yours to set.
    """
    today = today or date.today()

    # go_live_date, not maintenance_anchor: the anchor falls back to mvp_date
    # so that projects predating go-live keep a billing window, and using it
    # here would jump a delivered project straight past Delivered on the day
    # it was handed over, which is the gap these phases exist to show.
    if project.go_live_date:
        end = project.free_maintenance_end
        if end and today >= end:
            return "in_production"
        if today >= project.go_live_date:
            return "free_maintenance"

    if project.mvp_date and today >= project.mvp_date:
        return "delivered"

    return None


def pending_moves(projects=None, today=None):
    """What sync would change, without changing it.

    Split out so the interface can say "this is about to move" and so the
    behaviour can be tested without writing to anything.
    """
    today = today or date.today()
    if projects is None:
        projects = Project.query.all()

    moves = []
    for project in projects:
        if project.phase_locked or project.status in SKIP_STATUSES:
            continue
        due = due_phase(project, today)
        if due and rank(due) > rank(project.phase):
            moves.append((project, project.phase, due))
    return moves


def sync_project_phases(projects=None, today=None):
    """Advance every project its dates have moved past. Returns what changed."""
    moves = pending_moves(projects, today)
    for project, _old, new in moves:
        project.phase = new
    if moves:
        db.session.commit()
    return moves


def explain(project, today=None):
    """Why this project is where it is, in one sentence for the interface."""
    today = today or date.today()

    if project.phase_locked:
        return "Held where you put it. Dates will not move it."
    if project.phase in MANUAL_ONLY and not due_phase(project, today):
        if project.phase == "contracted":
            return "Move it to MVP when you start building."
        if project.mvp_date:
            return f"Moves to Delivered on {project.mvp_date:%b %d, %Y}."
        return "Set a delivery date and it will move itself."

    if project.phase == "delivered":
        if project.go_live_date:
            return f"Moves to Free maintenance on {project.go_live_date:%b %d, %Y}."
        return "Set a go-live date to start the free maintenance window."
    if project.phase == "free_maintenance":
        end = project.free_maintenance_end
        if end:
            left = (end - today).days
            when = f"{end:%b %d, %Y}"
            return (f"Free maintenance ends {when} — {left} days left."
                    if left > 0 else f"Free maintenance ended {when}.")
        return "Free maintenance is running."
    if project.phase == "in_production":
        return "Live, and maintenance is billable."
    return ""
