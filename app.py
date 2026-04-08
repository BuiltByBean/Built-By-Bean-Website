import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-secret-key")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/contact", methods=["POST"])
def contact():
    data = request.get_json()
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    project_type = data.get("project_type", "").strip()
    message = data.get("message", "").strip()

    if not name or not email or not message:
        return jsonify({"error": "Please fill in all required fields."}), 400

    try:
        send_email(name, email, project_type, message)
        return jsonify({"success": True, "message": "Message sent! I'll get back to you soon."})
    except Exception as e:
        print(f"Email error: {e}")
        return jsonify({"error": "Something went wrong. Please email me directly at mbean@builtbybeans.com"}), 500


def send_email(name, email, project_type, message):
    mail_server = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    mail_port = int(os.getenv("MAIL_PORT", 587))
    mail_username = os.getenv("MAIL_USERNAME")
    mail_password = os.getenv("MAIL_PASSWORD")
    contact_email = os.getenv("CONTACT_EMAIL", "mbean@builtbybeans.com")

    msg = MIMEMultipart()
    msg["From"] = mail_username
    msg["To"] = contact_email
    msg["Subject"] = f"New Inquiry from {name} — {project_type or 'General'}"
    msg["Reply-To"] = email

    body = f"""New contact form submission from builtbybeans.com

Name: {name}
Email: {email}
Project Type: {project_type or 'Not specified'}

Message:
{message}
"""
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP(mail_server, mail_port) as server:
        server.starttls()
        server.login(mail_username, mail_password)
        server.send_message(msg)


if __name__ == "__main__":
    app.run(debug=True, port=5000)
