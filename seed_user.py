"""Create the initial admin user."""
from app import create_app
from models import db, User

app = create_app()

with app.app_context():
    db.create_all()

    if not User.query.filter_by(username="mbean").first():
        user = User(
            username="mbean",
            first_name="Matthew",
            last_name="Bean",
            email="mbean@builtbybean.com",
            role="admin",
        )
        user.set_password("admin")
        db.session.add(user)
        db.session.commit()
        print("Admin user 'mbean' created (password: admin)")
    else:
        print("User 'mbean' already exists")
