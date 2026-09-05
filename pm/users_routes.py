"""The people who may open this board.

Four titles, one decorator. An officer (CEO, CTO or CMO) runs the board
and its people; a member does the work and never sees this section. The guard sits on the
route, per the house rule, not in the template that hides the link.

An account is never deleted: it is switched off. The time somebody logged
and the timer rows that point at them are theirs, and a row that vanishes
under a foreign key is a worse day than a name that has gone quiet.

Passwords are never chosen here. A new account or a reset gets a
temporary one, shown to the officer exactly once and never stored in the
clear, and the person is made to replace it on their first sign-in.
"""
import secrets
from datetime import datetime, timezone
from functools import wraps

from flask import (Blueprint, render_template, request, redirect, url_for,
                   flash, abort, session)
from flask_login import login_required, current_user

from models import db, User

users_bp = Blueprint("users", __name__, url_prefix="/admin/users")

# Letters and digits that cannot be misread over a phone: no 0/O, no 1/l/I.
ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789"


def officer_required(view):
    @wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not getattr(current_user, "is_officer", False):
            flash("Officers only.", "warning")
            return redirect(url_for("pm.dashboard"))
        return view(*args, **kwargs)
    return wrapped


def temporary_password():
    parts = ["".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(3)]
    return "-".join(parts)


def _active_officers():
    return User.query.filter(User.is_active.is_(True),
                             User.role.in_(User.OFFICER_ROLES + User.LEGACY_OFFICER_ROLES)).count()


def _clean(form):
    role = (form.get("role") or "").strip().lower()
    return {
        "username": (form.get("username") or "").strip()[:80],
        "first_name": (form.get("first_name") or "").strip()[:100],
        "last_name": (form.get("last_name") or "").strip()[:100],
        "email": (form.get("email") or "").strip().lower()[:200],
        "role": role if role in dict(User.ROLES) else "member",
    }


def _taken(field, value, exclude_id=None):
    query = User.query.filter(getattr(User, field).ilike(value))
    if exclude_id:
        query = query.filter(User.id != exclude_id)
    return query.first() is not None


@users_bp.route("/")
@officer_required
def index():
    people = User.query.order_by(User.is_active.desc(), User.role, User.username).all()
    # Set by create and reset, read here once, gone. Never a flash: the
    # generic flash strip would print it too.
    reveal = session.pop("user_reveal", None)
    return render_template("pm/users/index.html", people=people, reveal=reveal,
                           officers=_active_officers())


@users_bp.route("/new", methods=["GET", "POST"])
@officer_required
def create():
    if request.method == "GET":
        return render_template("pm/users/form.html", person=None, values={}, roles=User.ROLES)
    values = _clean(request.form)
    problem = None
    if not values["username"] or not values["email"]:
        problem = "A username and an email are both needed."
    elif "@" not in values["email"]:
        problem = "That email does not look like one."
    elif _taken("username", values["username"]):
        problem = "That username is already taken."
    elif _taken("email", values["email"]):
        problem = "That email already has an account."
    if problem:
        flash(problem, "warning")
        return render_template("pm/users/form.html", person=None, values=values, roles=User.ROLES)

    password = temporary_password()
    person = User(**values, must_change_password=True, is_active=True)
    person.set_password(password)
    db.session.add(person)
    db.session.commit()
    session["user_reveal"] = {"username": person.username, "password": password, "why": "new"}
    return redirect(url_for("users.index"))


@users_bp.route("/<int:id>/edit", methods=["GET", "POST"])
@officer_required
def edit(id):
    person = db.session.get(User, id) or abort(404)
    if request.method == "GET":
        values = {"username": person.username, "first_name": person.first_name or "",
                  "last_name": person.last_name or "", "email": person.email,
                  "role": person.role if person.role in dict(User.ROLES)
                          else ("ceo" if person.is_officer else "member")}
        return render_template("pm/users/form.html", person=person, values=values, roles=User.ROLES)
    values = _clean(request.form)
    problem = None
    if not values["username"] or not values["email"]:
        problem = "A username and an email are both needed."
    elif _taken("username", values["username"], person.id):
        problem = "That username is already taken."
    elif _taken("email", values["email"], person.id):
        problem = "That email already has an account."
    elif values["role"] not in User.OFFICER_ROLES and person.is_officer:
        # Taking a title away: never your own, and never the last officer's.
        if person.id == current_user.id:
            problem = "You cannot take the title off your own account."
        elif person.is_active and _active_officers() <= 1:
            problem = "That is the last officer. Give somebody else a title first."
    if problem:
        flash(problem, "warning")
        return render_template("pm/users/form.html", person=person, values=values, roles=User.ROLES)
    for key, value in values.items():
        setattr(person, key, value)
    db.session.commit()
    flash(f"{person.full_name} saved.", "success")
    return redirect(url_for("users.index"))


@users_bp.route("/<int:id>/reset", methods=["POST"])
@officer_required
def reset(id):
    person = db.session.get(User, id) or abort(404)
    password = temporary_password()
    person.set_password(password)
    person.must_change_password = True
    db.session.commit()
    session["user_reveal"] = {"username": person.username, "password": password, "why": "reset"}
    return redirect(url_for("users.index"))


@users_bp.route("/<int:id>/switch", methods=["POST"])
@officer_required
def switch(id):
    person = db.session.get(User, id) or abort(404)
    if person.id == current_user.id:
        flash("You cannot switch off your own account.", "warning")
        return redirect(url_for("users.index"))
    if person.is_active and person.is_officer and _active_officers() <= 1:
        flash("That is the last officer. Give somebody else a title first.", "warning")
        return redirect(url_for("users.index"))
    person.is_active = not person.is_active
    db.session.commit()
    flash(f"{person.full_name} switched {'on' if person.is_active else 'off'}.", "success")
    return redirect(url_for("users.index"))
