"""Create or reset an admin user.

Usage:
    python reset_admin.py <username> <password> [email] [first_name] [last_name]

Runs against whatever DATABASE_URL is set. Use `railway run python reset_admin.py ...`
from this repo's root to point it at the Railway Postgres.

If a user with the given username already exists (case-insensitive), its password
is reset. Otherwise a new admin user is created. If the email collides with an
existing row, that existing row is updated instead (username is changed to match).
"""
import sys

from app import create_app
from models import db, User


def main() -> int:
    if len(sys.argv) < 3:
        print("Usage: python reset_admin.py <username> <password> [email] [first_name] [last_name]")
        return 1

    username = sys.argv[1]
    password = sys.argv[2]
    email = sys.argv[3] if len(sys.argv) > 3 else f"{username.lower()}@builtbybean.com"
    first_name = sys.argv[4] if len(sys.argv) > 4 else "Matthew"
    last_name = sys.argv[5] if len(sys.argv) > 5 else "Bean"

    app = create_app()
    with app.app_context():
        user = User.query.filter(User.username.ilike(username)).first()
        if user is None:
            user = User.query.filter(User.email.ilike(email)).first()

        if user is None:
            user = User(
                username=username,
                first_name=first_name,
                last_name=last_name,
                email=email,
                role="admin",
            )
            db.session.add(user)
            action = "created"
        else:
            user.username = username
            user.role = "admin"
            action = "updated"

        user.set_password(password)
        if hasattr(user, "must_change_password"):
            user.must_change_password = False

        db.session.commit()
        print(f"{action} user id={user.id} username={user.username} email={user.email} role={user.role}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
