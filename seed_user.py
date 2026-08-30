"""Create the initial admin user.

The password is read from SEED_ADMIN_PASSWORD rather than hardcoded — this
repo is public, so a literal here would be a published admin credential.

    SEED_ADMIN_PASSWORD='...' python seed_user.py
"""
import os
import sys

from app import create_app
from models import db, User

app = create_app()

password = os.environ.get("SEED_ADMIN_PASSWORD", "")
if not password:
    sys.exit("SEED_ADMIN_PASSWORD is not set. Refusing to create an admin with a default password.")

with app.app_context():
    db.create_all()

    if not User.query.filter_by(username="mbean").first():
        user = User(
            username="mbean",
            first_name="Michael",
            last_name="Bean",
            email="mbean@builtbybean.com",
            role="admin",
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        print("Admin user 'mbean' created (password taken from SEED_ADMIN_PASSWORD)")
    else:
        print("User 'mbean' already exists")
