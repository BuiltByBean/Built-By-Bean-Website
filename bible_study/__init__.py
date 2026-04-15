import re
import json
import secrets
import threading
from functools import wraps
from datetime import datetime, timezone

from flask import (
    Blueprint, render_template, request, redirect, url_for,
    flash, jsonify, abort, make_response, current_app,
)
from flask_login import (
    login_user, logout_user, login_required, current_user,
)
from flask_mail import Message

from models import db
from bible_study.bs_models import (
    BibleStudyUser, BSNote, BSTag, BSTagVerse, BSTagNote,
    BSQuestion, BSJournalType, BSJournalEntry, BSTopic,
)
from bible_study.bible_data import (
    BIBLE_BOOKS, BOOK_MAP, NT_BOOKS, ESV_COPYRIGHT,
    fetch_chapter, fetch_verse_text, fetch_ref_text, format_ref,
)
from bible_study.bs_forms import BSLoginForm, BSRegisterForm

# ---------------------------------------------------------------------------
# Blueprint
# ---------------------------------------------------------------------------
bible_study_bp = Blueprint(
    "bible_study", __name__,
    url_prefix="/Bible-Study",
    template_folder="../templates/bible_study",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


def _send_invite_email(app, email, invite_url, name):
    """Send invite email in a background thread so it doesn't block."""
    def send():
        with app.app_context():
            try:
                mail = current_app.extensions["mail"]
                msg = Message(
                    subject="You're invited to Bible Study Notes",
                    recipients=[email],
                    html=f"""
                    <div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px">
                        <h2 style="color:#6366f1">Bible Study Notes</h2>
                        <p>Hi{(' ' + name) if name else ''},</p>
                        <p>You've been invited to join Bible Study Notes — a personal Bible study companion for reading, notes, tags, and more.</p>
                        <p><a href="{invite_url}" style="display:inline-block;background:#6366f1;color:white;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold">Set Up Your Account</a></p>
                        <p style="color:#94a3b8;font-size:12px;margin-top:20px">If the button doesn't work, copy this link: {invite_url}</p>
                    </div>
                    """
                )
                mail.send(msg)
            except Exception as e:
                app.logger.error(f"Failed to send invite email to {email}: {e}")
    threading.Thread(target=send, daemon=True).start()


# ---------------------------------------------------------------------------
# Inline migrations — add columns to existing tables safely
# ---------------------------------------------------------------------------
def _migrate(app):
    """Add new columns to existing tables. Each ALTER is wrapped in try/except
    so it silently passes if the column already exists."""
    migrations = [
        "ALTER TABLE bs_users ADD COLUMN is_admin BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE bs_users ADD COLUMN display_name VARCHAR(120)",
        "ALTER TABLE bs_users ADD COLUMN email VARCHAR(200)",
        "ALTER TABLE bs_users ADD COLUMN role VARCHAR(20) NOT NULL DEFAULT 'user'",
        "ALTER TABLE bs_users ADD COLUMN invite_token VARCHAR(64) UNIQUE",
        "ALTER TABLE bs_users ADD COLUMN has_set_password BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE bs_questions ADD COLUMN answer TEXT",
        "ALTER TABLE bs_journal_entries ADD COLUMN title VARCHAR(200)",
        "ALTER TABLE bs_tag_verses ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE bs_notes ALTER COLUMN chapter DROP NOT NULL",
        "ALTER TABLE bs_notes ALTER COLUMN verse_start DROP NOT NULL",
        "ALTER TABLE bs_notes ALTER COLUMN verse_end DROP NOT NULL",
    ]
    for sql in migrations:
        try:
            db.session.execute(db.text(sql))
            db.session.commit()
        except Exception:
            db.session.rollback()


# ---------------------------------------------------------------------------
# init_bible_study — called from main app's create_app
# ---------------------------------------------------------------------------
def init_bible_study(app):
    """Create tables, run migrations, seed admin user."""
    with app.app_context():
        db.create_all()
        _migrate(app)
        # Seed admin user
        u = BibleStudyUser.query.filter(BibleStudyUser.username.ilike("mbean21")).first()
        if not u:
            u = BibleStudyUser(
                username="mbean21", is_admin=True, role="admin",
                display_name="Michael Bean",
            )
            u.set_password("Scout0213!")
            db.session.add(u)
            db.session.commit()
        else:
            changed = False
            if not u.is_admin:
                u.is_admin = True
                changed = True
            if u.role != "admin":
                u.role = "admin"
                changed = True
            if changed:
                db.session.commit()


# ---------------------------------------------------------------------------
# Context processor — make helpers available in all blueprint templates
# ---------------------------------------------------------------------------
@bible_study_bp.context_processor
def inject_helpers():
    return {"format_ref": format_ref, "ESV_COPYRIGHT": ESV_COPYRIGHT}


# ══════════════════════════════════════════════════════════════════════════════
# Auth routes
# ══════════════════════════════════════════════════════════════════════════════

@bible_study_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("bible_study.index"))
    form = BSLoginForm()
    if form.validate_on_submit():
        user = BibleStudyUser.query.filter(
            BibleStudyUser.username.ilike(form.username.data)
        ).first()
        if user and user.check_password(form.password.data):
            login_user(user, remember=True)
            return redirect(request.args.get("next") or url_for("bible_study.index"))
        flash("Invalid username or password.", "error")
    return render_template("bible_study/auth/login.html", form=form)


@bible_study_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("bible_study.index"))
    form = BSRegisterForm()
    if form.validate_on_submit():
        if BibleStudyUser.query.filter(
            BibleStudyUser.username.ilike(form.username.data)
        ).first():
            flash("Username already taken.", "error")
        else:
            u = BibleStudyUser(username=form.username.data)
            u.set_password(form.password.data)
            db.session.add(u)
            db.session.commit()
            login_user(u, remember=True)
            return redirect(url_for("bible_study.index"))
    return render_template("bible_study/auth/login.html", form=form, register_mode=True)


@bible_study_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("bible_study.login"))


@bible_study_bp.route("/invite/<token>", methods=["GET", "POST"])
def claim_invite(token):
    u = BibleStudyUser.query.filter_by(invite_token=token).first()
    if not u:
        flash("Invalid or expired invite link.", "error")
        return redirect(url_for("bible_study.login"))
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password", "")
        display_name = (request.form.get("display_name") or "").strip()
        if not username or len(password) < 6:
            flash("Username required and password must be 6+ characters.", "error")
            return render_template("bible_study/auth/invite.html", user=u, token=token)
        existing = BibleStudyUser.query.filter(
            BibleStudyUser.username.ilike(username)
        ).first()
        if existing and existing.id != u.id:
            flash("Username already taken.", "error")
            return render_template("bible_study/auth/invite.html", user=u, token=token)
        u.username = username
        u.display_name = display_name or username
        u.set_password(password)
        u.invite_token = None
        u.has_set_password = True
        db.session.commit()
        login_user(u, remember=True)
        return redirect(url_for("bible_study.index"))
    return render_template("bible_study/auth/invite.html", user=u, token=token)


# ══════════════════════════════════════════════════════════════════════════════
# Page routes
# ══════════════════════════════════════════════════════════════════════════════

@bible_study_bp.route("/")
@login_required
def index():
    last = request.cookies.get("last_passage", "John/1")
    parts = last.split("/", 1)
    book = parts[0] if parts[0] in BOOK_MAP else "John"
    chapter = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
    return redirect(url_for("bible_study.reader", book=book, chapter=chapter))


@bible_study_bp.route("/read/<book>/<int:chapter>")
@login_required
def reader(book, chapter):
    if book not in BOOK_MAP or chapter < 1 or chapter > BOOK_MAP[book]["chapters"]:
        flash("Invalid book or chapter.", "error")
        return redirect(url_for("bible_study.reader", book="John", chapter=1))
    resp = make_response(render_template(
        "bible_study/reader/index.html", book=book, chapter=chapter,
        bible_books_json=json.dumps(BIBLE_BOOKS),
    ))
    resp.set_cookie("last_passage", f"{book}/{chapter}", max_age=60 * 60 * 24 * 365)
    return resp


@bible_study_bp.route("/tags")
@login_required
def tags_page():
    tags = BSTag.query.filter_by(user_id=current_user.id).order_by(BSTag.name).all()
    tag_counts = {t.id: BSTagVerse.query.filter_by(tag_id=t.id).count() for t in tags}
    return render_template("bible_study/tags/library.html", tags=tags, tag_counts=tag_counts)


@bible_study_bp.route("/tags/<int:tag_id>")
@login_required
def tag_detail(tag_id):
    tag = BSTag.query.filter_by(id=tag_id, user_id=current_user.id).first_or_404()
    verses = BSTagVerse.query.filter_by(tag_id=tag.id).order_by(
        BSTagVerse.sort_order, BSTagVerse.created_at
    ).all()
    notes = BSTagNote.query.filter_by(tag_id=tag.id).order_by(BSTagNote.created_at).all()
    verse_texts = {}
    for v in verses[:50]:
        if v.chapter and v.verse_start and v.verse_end:
            verse_texts[v.id] = fetch_verse_text(v.book, v.chapter, v.verse_start, v.verse_end)
    return render_template(
        "bible_study/tags/detail.html", tag=tag, verses=verses, notes=notes,
        verse_texts=verse_texts, copyright=ESV_COPYRIGHT,
    )


@bible_study_bp.route("/notes")
@login_required
def notes_page():
    return render_template("bible_study/notes/index.html")


@bible_study_bp.route("/questions")
@login_required
def questions_page():
    return render_template("bible_study/questions/index.html")


@bible_study_bp.route("/journal")
@login_required
def journal_page():
    return render_template("bible_study/journal/index.html")


@bible_study_bp.route("/topics")
@login_required
def topics_page():
    return render_template("bible_study/topics/index.html")


@bible_study_bp.route("/topics/<int:topic_id>")
@login_required
def topic_detail(topic_id):
    topic = BSTopic.query.filter_by(
        id=topic_id, user_id=current_user.id
    ).first_or_404()
    return render_template("bible_study/topics/detail.html", topic=topic)


@bible_study_bp.route("/admin/users")
@admin_required
def admin_users():
    users = BibleStudyUser.query.order_by(BibleStudyUser.created_at).all()
    return render_template("bible_study/admin/users.html", users=users)


# ══════════════════════════════════════════════════════════════════════════════
# JSON API routes
# ══════════════════════════════════════════════════════════════════════════════

# -- Passage ---------------------------------------------------------------

@bible_study_bp.route("/api/passage")
@login_required
def api_passage():
    book = request.args.get("book", "")
    chapter = request.args.get("chapter", 1, type=int)
    data = fetch_chapter(book, chapter)
    noted, tagged, questioned = set(), {}, set()
    for n in BSNote.query.filter_by(
        user_id=current_user.id, book=book, chapter=chapter
    ).all():
        if n.verse_start and n.verse_end:
            for v in range(n.verse_start, n.verse_end + 1):
                noted.add(v)
    for tv in BSTagVerse.query.filter_by(
        user_id=current_user.id, book=book, chapter=chapter
    ).all():
        if tv.verse_start and tv.verse_end:
            t = db.session.get(BSTag, tv.tag_id)
            for v in range(tv.verse_start, tv.verse_end + 1):
                tagged.setdefault(v, []).append(t.color if t else "#6366f1")
    for q in BSQuestion.query.filter_by(
        user_id=current_user.id, book=book, chapter=chapter
    ).all():
        if q.verse_start and q.verse_end:
            for v in range(q.verse_start, q.verse_end + 1):
                questioned.add(v)
    data["noted_verses"] = list(noted)
    data["tagged_verses"] = tagged
    data["questioned_verses"] = list(questioned)
    return jsonify(data)


# -- Verse text ------------------------------------------------------------

@bible_study_bp.route("/api/verse-text")
@login_required
def api_verse_text():
    ref = request.args.get("ref", "")
    if not ref:
        return jsonify({"text": "", "error": "ref required"})
    text = fetch_ref_text(ref)
    return jsonify({"text": text, "copyright": ESV_COPYRIGHT})


# -- Notes -----------------------------------------------------------------

@bible_study_bp.route("/api/notes", methods=["GET"])
@login_required
def api_notes_get():
    book = request.args.get("book", "")
    chapter = request.args.get("chapter", None, type=int)
    vs = request.args.get("verse_start", None, type=int)
    ve = request.args.get("verse_end", None, type=int)
    q = BSNote.query.filter_by(user_id=current_user.id)
    if book:
        q = q.filter_by(book=book)
    if chapter is not None:
        q = q.filter_by(chapter=chapter)
    if vs is not None and ve is not None:
        q = q.filter(BSNote.verse_start <= ve, BSNote.verse_end >= vs)
    return jsonify([{
        "id": n.id, "book": n.book, "chapter": n.chapter,
        "verse_start": n.verse_start, "verse_end": n.verse_end,
        "body": n.body,
        "reference": format_ref(n.book, n.chapter, n.verse_start, n.verse_end),
        "created_at": n.created_at.isoformat() if n.created_at else "",
    } for n in q.order_by(BSNote.created_at.asc()).all()])


@bible_study_bp.route("/api/notes/all", methods=["GET"])
@login_required
def api_notes_all():
    notes = BSNote.query.filter_by(user_id=current_user.id).order_by(
        BSNote.book, BSNote.chapter, BSNote.verse_start, BSNote.created_at
    ).all()
    return jsonify([{
        "id": n.id, "book": n.book, "chapter": n.chapter,
        "verse_start": n.verse_start, "verse_end": n.verse_end,
        "body": n.body,
        "reference": format_ref(n.book, n.chapter, n.verse_start, n.verse_end),
        "created_at": n.created_at.isoformat() if n.created_at else "",
    } for n in notes])


@bible_study_bp.route("/api/notes", methods=["POST"])
@login_required
def api_notes_create():
    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"error": "body required"}), 400
    n = BSNote(
        user_id=current_user.id, book=data.get("book", ""),
        chapter=data.get("chapter"), verse_start=data.get("verse_start"),
        verse_end=data.get("verse_end"), body=body,
    )
    db.session.add(n)
    db.session.commit()
    return jsonify({"id": n.id}), 201


# -- Tags ------------------------------------------------------------------

@bible_study_bp.route("/api/tags", methods=["GET"])
@login_required
def api_tags_get():
    return jsonify([
        {"id": t.id, "name": t.name, "color": t.color}
        for t in BSTag.query.filter_by(user_id=current_user.id).order_by(BSTag.name).all()
    ])


@bible_study_bp.route("/api/tags", methods=["POST"])
@login_required
def api_tags_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    if BSTag.query.filter_by(user_id=current_user.id, name=name).first():
        return jsonify({"error": "tag already exists"}), 409
    t = BSTag(user_id=current_user.id, name=name, color=data.get("color", "#6366f1"))
    db.session.add(t)
    db.session.commit()
    return jsonify({"id": t.id, "name": t.name, "color": t.color}), 201


@bible_study_bp.route("/api/tags/<int:tag_id>", methods=["PUT"])
@login_required
def api_tags_update(tag_id):
    t = BSTag.query.filter_by(id=tag_id, user_id=current_user.id).first_or_404()
    data = request.get_json(silent=True) or {}
    if "name" in data:
        t.name = data["name"]
    if "color" in data:
        t.color = data["color"]
    db.session.commit()
    return jsonify({"ok": True})


@bible_study_bp.route("/api/tags/<int:tag_id>", methods=["DELETE"])
@login_required
def api_tags_delete(tag_id):
    t = BSTag.query.filter_by(id=tag_id, user_id=current_user.id).first_or_404()
    db.session.delete(t)
    db.session.commit()
    return jsonify({"ok": True})


# -- Tag Verses ------------------------------------------------------------

@bible_study_bp.route("/api/tag-verses", methods=["GET"])
@login_required
def api_tagverses_get():
    book = request.args.get("book", "")
    chapter = request.args.get("chapter", None, type=int)
    vs = request.args.get("verse_start", None, type=int)
    ve = request.args.get("verse_end", None, type=int)
    tag_id = request.args.get("tag_id", 0, type=int)
    q = BSTagVerse.query.filter_by(user_id=current_user.id)
    if tag_id:
        q = q.filter_by(tag_id=tag_id)
    if book:
        q = q.filter_by(book=book)
        if chapter is not None:
            q = q.filter_by(chapter=chapter)
            if vs is not None and ve is not None:
                q = q.filter(BSTagVerse.verse_start <= ve, BSTagVerse.verse_end >= vs)
    result = []
    for tv in q.order_by(BSTagVerse.created_at).all():
        tag = db.session.get(BSTag, tv.tag_id)
        result.append({
            "id": tv.id, "tag_id": tv.tag_id,
            "tag_name": tag.name if tag else "",
            "tag_color": tag.color if tag else "#ccc",
            "book": tv.book, "chapter": tv.chapter,
            "verse_start": tv.verse_start, "verse_end": tv.verse_end,
            "note": tv.note or "",
            "created_at": tv.created_at.isoformat() if tv.created_at else "",
        })
    return jsonify(result)


@bible_study_bp.route("/api/tag-verses", methods=["POST"])
@login_required
def api_tagverses_create():
    data = request.get_json(silent=True) or {}
    tag_id = data.get("tag_id")
    if not tag_id:
        return jsonify({"error": "tag_id required"}), 400
    max_order = db.session.query(
        db.func.coalesce(db.func.max(BSTagVerse.sort_order), -1)
    ).filter_by(tag_id=tag_id).scalar()
    tv = BSTagVerse(
        user_id=current_user.id, tag_id=tag_id, book=data.get("book", ""),
        chapter=data.get("chapter"), verse_start=data.get("verse_start"),
        verse_end=data.get("verse_end"), note=data.get("note"),
        sort_order=max_order + 1,
    )
    db.session.add(tv)
    db.session.commit()
    return jsonify({"id": tv.id}), 201


@bible_study_bp.route("/api/tag-verses/<int:tv_id>", methods=["DELETE"])
@login_required
def api_tagverses_delete(tv_id):
    tv = BSTagVerse.query.filter_by(id=tv_id, user_id=current_user.id).first_or_404()
    db.session.delete(tv)
    db.session.commit()
    return jsonify({"ok": True})


@bible_study_bp.route("/api/tag-verses/reorder", methods=["POST"])
@login_required
def api_tagverses_reorder():
    data = request.get_json(silent=True) or {}
    for i, tv_id in enumerate(data.get("ids", [])):
        tv = BSTagVerse.query.filter_by(id=tv_id, user_id=current_user.id).first()
        if tv:
            tv.sort_order = i
    db.session.commit()
    return jsonify({"ok": True})


# -- Tag Notes -------------------------------------------------------------

@bible_study_bp.route("/api/tag-notes", methods=["POST"])
@login_required
def api_tagnotes_create():
    data = request.get_json(silent=True) or {}
    tag_id = data.get("tag_id")
    body = (data.get("body") or "").strip()
    if not tag_id or not body:
        return jsonify({"error": "tag_id and body required"}), 400
    tn = BSTagNote(user_id=current_user.id, tag_id=tag_id, body=body)
    db.session.add(tn)
    db.session.commit()
    return jsonify({"id": tn.id}), 201


# -- Questions -------------------------------------------------------------

@bible_study_bp.route("/api/questions", methods=["GET"])
@login_required
def api_questions_get():
    book = request.args.get("book", None)
    chapter = request.args.get("chapter", None, type=int)
    vs = request.args.get("verse_start", None, type=int)
    ve = request.args.get("verse_end", None, type=int)
    answered = request.args.get("answered", None)
    q = BSQuestion.query.filter_by(user_id=current_user.id)
    if book:
        q = q.filter_by(book=book)
        if chapter is not None:
            q = q.filter_by(chapter=chapter)
            if vs is not None and ve is not None:
                q = q.filter(BSQuestion.verse_start <= ve, BSQuestion.verse_end >= vs)
    if answered == "true":
        q = q.filter_by(is_answered=True)
    elif answered == "false":
        q = q.filter_by(is_answered=False)
    return jsonify([{
        "id": r.id, "book": r.book, "chapter": r.chapter,
        "verse_start": r.verse_start, "verse_end": r.verse_end,
        "body": r.body, "answer": r.answer or "", "is_answered": r.is_answered,
        "reference": format_ref(r.book, r.chapter, r.verse_start, r.verse_end) if r.book else None,
        "created_at": r.created_at.isoformat() if r.created_at else "",
    } for r in q.order_by(BSQuestion.created_at.desc()).all()])


@bible_study_bp.route("/api/questions", methods=["POST"])
@login_required
def api_questions_create():
    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"error": "body required"}), 400
    q = BSQuestion(
        user_id=current_user.id, book=data.get("book") or None,
        chapter=data.get("chapter"), verse_start=data.get("verse_start"),
        verse_end=data.get("verse_end"), body=body,
    )
    db.session.add(q)
    db.session.commit()
    return jsonify({"id": q.id}), 201


@bible_study_bp.route("/api/questions/<int:qid>", methods=["PUT"])
@login_required
def api_questions_update(qid):
    q = BSQuestion.query.filter_by(id=qid, user_id=current_user.id).first_or_404()
    data = request.get_json(silent=True) or {}
    if "is_answered" in data:
        q.is_answered = bool(data["is_answered"])
    if "body" in data:
        q.body = data["body"]
    if "answer" in data:
        q.answer = data["answer"] or None
    db.session.commit()
    return jsonify({"ok": True})


@bible_study_bp.route("/api/questions/<int:qid>", methods=["DELETE"])
@login_required
def api_questions_delete(qid):
    q = BSQuestion.query.filter_by(id=qid, user_id=current_user.id).first_or_404()
    db.session.delete(q)
    db.session.commit()
    return jsonify({"ok": True})


# -- Journal ---------------------------------------------------------------

@bible_study_bp.route("/api/journal/types", methods=["GET"])
@login_required
def api_journal_types():
    types = BSJournalType.query.filter_by(user_id=current_user.id).order_by(
        BSJournalType.name
    ).all()
    return jsonify([{"id": t.id, "name": t.name, "color": t.color} for t in types])


@bible_study_bp.route("/api/journal/types", methods=["POST"])
@login_required
def api_journal_types_create():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    t = BSJournalType(
        user_id=current_user.id, name=name, color=data.get("color", "#6366f1"),
    )
    db.session.add(t)
    db.session.commit()
    return jsonify({"id": t.id, "name": t.name, "color": t.color}), 201


@bible_study_bp.route("/api/journal/types/<int:tid>", methods=["DELETE"])
@login_required
def api_journal_types_delete(tid):
    t = BSJournalType.query.filter_by(id=tid, user_id=current_user.id).first_or_404()
    db.session.delete(t)
    db.session.commit()
    return jsonify({"ok": True})


@bible_study_bp.route("/api/journal/types/<int:tid>", methods=["PUT"])
@login_required
def api_journal_types_update(tid):
    t = BSJournalType.query.filter_by(id=tid, user_id=current_user.id).first_or_404()
    data = request.get_json(silent=True) or {}
    if "name" in data:
        t.name = data["name"]
    if "color" in data:
        t.color = data["color"]
    db.session.commit()
    return jsonify({"ok": True})


@bible_study_bp.route("/api/journal", methods=["GET"])
@login_required
def api_journal_get():
    entries = BSJournalEntry.query.filter_by(user_id=current_user.id).order_by(
        BSJournalEntry.created_at.desc()
    ).all()
    return jsonify([{
        "id": e.id, "title": e.title or "", "body": e.body,
        "type_id": e.type_id,
        "type_name": e.journal_type.name if e.journal_type else None,
        "type_color": e.journal_type.color if e.journal_type else None,
        "created_at": e.created_at.isoformat() if e.created_at else "",
        "date": e.created_at.strftime("%B %d, %Y") if e.created_at else "",
    } for e in entries])


@bible_study_bp.route("/api/journal", methods=["POST"])
@login_required
def api_journal_create():
    data = request.get_json(silent=True) or {}
    body = (data.get("body") or "").strip()
    if not body:
        return jsonify({"error": "body required"}), 400
    e = BSJournalEntry(
        user_id=current_user.id, body=body,
        title=(data.get("title") or "").strip() or None,
        type_id=data.get("type_id") or None,
    )
    db.session.add(e)
    db.session.commit()
    return jsonify({"id": e.id}), 201


@bible_study_bp.route("/api/journal/<int:eid>", methods=["PUT"])
@login_required
def api_journal_update(eid):
    e = BSJournalEntry.query.filter_by(
        id=eid, user_id=current_user.id
    ).first_or_404()
    data = request.get_json(silent=True) or {}
    if "title" in data:
        e.title = (data["title"] or "").strip() or None
    if "body" in data:
        e.body = data["body"]
    if "type_id" in data:
        e.type_id = data["type_id"] or None
    db.session.commit()
    return jsonify({"ok": True})


@bible_study_bp.route("/api/journal/<int:eid>", methods=["DELETE"])
@login_required
def api_journal_delete(eid):
    e = BSJournalEntry.query.filter_by(
        id=eid, user_id=current_user.id
    ).first_or_404()
    db.session.delete(e)
    db.session.commit()
    return jsonify({"ok": True})


# -- Topics ----------------------------------------------------------------

@bible_study_bp.route("/api/topics", methods=["GET"])
@login_required
def api_topics_get():
    topics = BSTopic.query.filter_by(user_id=current_user.id).order_by(
        BSTopic.updated_at.desc()
    ).all()
    return jsonify([{
        "id": t.id, "title": t.title,
        "snippet": re.sub(r"<[^>]+>", "", t.body)[:120],
        "created_at": t.created_at.isoformat() if t.created_at else "",
        "updated_at": t.updated_at.isoformat() if t.updated_at else "",
    } for t in topics])


@bible_study_bp.route("/api/topics", methods=["POST"])
@login_required
def api_topics_create():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if not title:
        return jsonify({"error": "title required"}), 400
    t = BSTopic(user_id=current_user.id, title=title, body=data.get("body", ""))
    db.session.add(t)
    db.session.commit()
    return jsonify({"id": t.id}), 201


@bible_study_bp.route("/api/topics/<int:tid>", methods=["PUT"])
@login_required
def api_topics_update(tid):
    t = BSTopic.query.filter_by(id=tid, user_id=current_user.id).first_or_404()
    data = request.get_json(silent=True) or {}
    if "title" in data:
        t.title = data["title"]
    if "body" in data:
        t.body = data["body"]
    t.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return jsonify({"ok": True})


@bible_study_bp.route("/api/topics/<int:tid>", methods=["DELETE"])
@login_required
def api_topics_delete(tid):
    t = BSTopic.query.filter_by(id=tid, user_id=current_user.id).first_or_404()
    db.session.delete(t)
    db.session.commit()
    return jsonify({"ok": True})


# -- Admin -----------------------------------------------------------------

@bible_study_bp.route("/api/admin/users", methods=["POST"])
@admin_required
def api_admin_create_user():
    """Create user and send invite email. Only email is required."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    if not email:
        return jsonify({"error": "Email is required"}), 400
    if BibleStudyUser.query.filter(BibleStudyUser.email.ilike(email)).first():
        return jsonify({"error": "Email already in use"}), 409
    token = secrets.token_urlsafe(32)
    username = email.split("@")[0].lower()
    base = username
    counter = 1
    while BibleStudyUser.query.filter(BibleStudyUser.username.ilike(username)).first():
        username = f"{base}{counter}"
        counter += 1
    role = data.get("role", "user")
    u = BibleStudyUser(
        username=username, email=email, role=role,
        display_name=data.get("display_name", ""),
        is_admin=role == "admin",
        invite_token=token, has_set_password=False,
    )
    u.set_password(secrets.token_urlsafe(16))
    db.session.add(u)
    db.session.commit()
    invite_url = f"{request.host_url.rstrip('/')}/Bible-Study/invite/{token}"
    _send_invite_email(
        current_app._get_current_object(), email, invite_url,
        data.get("display_name", ""),
    )
    return jsonify({"id": u.id, "invite_url": invite_url}), 201


@bible_study_bp.route("/api/admin/users/<int:uid>", methods=["PUT"])
@admin_required
def api_admin_update_user(uid):
    u = db.session.get(BibleStudyUser, uid)
    if not u:
        abort(404)
    data = request.get_json(silent=True) or {}
    if "display_name" in data:
        u.display_name = data["display_name"]
    if "email" in data:
        u.email = data["email"]
    if "role" in data:
        u.role = data["role"]
        u.is_admin = data["role"] == "admin"
    db.session.commit()
    return jsonify({"ok": True})


@bible_study_bp.route("/api/admin/users/<int:uid>/reset-password", methods=["POST"])
@admin_required
def api_admin_reset_password(uid):
    u = db.session.get(BibleStudyUser, uid)
    if not u:
        abort(404)
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    if not password or len(password) < 6:
        return jsonify({"error": "Password must be 6+ characters"}), 400
    u.set_password(password)
    db.session.commit()
    return jsonify({"ok": True})


@bible_study_bp.route("/api/admin/users/<int:uid>/delete", methods=["POST"])
@admin_required
def api_admin_delete_user(uid):
    if uid == current_user.id:
        return jsonify({"error": "Cannot delete yourself"}), 400
    u = db.session.get(BibleStudyUser, uid)
    if not u:
        abort(404)
    db.session.delete(u)
    db.session.commit()
    return jsonify({"ok": True})


# -- Search ----------------------------------------------------------------

@bible_study_bp.route("/api/search")
@login_required
def api_search():
    term = (request.args.get("q") or "").strip()
    if len(term) < 2:
        return jsonify([])
    is_pg = "postgresql" in current_app.config["SQLALCHEMY_DATABASE_URI"]
    results = []

    def like_fn(col):
        return col.ilike(f"%{term}%") if is_pg else col.like(f"%{term}%")

    # Notes
    for n in BSNote.query.filter(
        BSNote.user_id == current_user.id, like_fn(BSNote.body)
    ).order_by(BSNote.created_at.desc()).limit(20).all():
        results.append({
            "type": "note",
            "reference": format_ref(n.book, n.chapter, n.verse_start, n.verse_end),
            "snippet": re.sub(r"<[^>]+>", "", n.body)[:150],
            "book": n.book, "chapter": n.chapter,
            "date": n.created_at.isoformat() if n.created_at else "",
        })

    # Questions
    for q in BSQuestion.query.filter(
        BSQuestion.user_id == current_user.id, like_fn(BSQuestion.body)
    ).order_by(BSQuestion.created_at.desc()).limit(15).all():
        results.append({
            "type": "question",
            "reference": (
                format_ref(q.book, q.chapter, q.verse_start, q.verse_end)
                if q.book else "Standalone"
            ),
            "snippet": q.body[:150], "book": q.book, "chapter": q.chapter,
            "date": q.created_at.isoformat() if q.created_at else "",
        })

    # Journal entries (fixed: original had PrayerEntry bug)
    for p in BSJournalEntry.query.filter(
        BSJournalEntry.user_id == current_user.id, like_fn(BSJournalEntry.body)
    ).order_by(BSJournalEntry.created_at.desc()).limit(10).all():
        results.append({
            "type": "journal",
            "reference": p.created_at.strftime("%B %d, %Y") if p.created_at else "",
            "snippet": p.body[:150],
            "date": p.created_at.isoformat() if p.created_at else "",
        })

    # Topics
    for t in BSTopic.query.filter(
        BSTopic.user_id == current_user.id,
        (like_fn(BSTopic.title) | like_fn(BSTopic.body)),
    ).order_by(BSTopic.updated_at.desc()).limit(10).all():
        results.append({
            "type": "topic", "reference": t.title, "id": t.id,
            "snippet": re.sub(r"<[^>]+>", "", t.body)[:150],
            "date": t.updated_at.isoformat() if t.updated_at else "",
        })

    results.sort(key=lambda r: r.get("date", ""), reverse=True)
    return jsonify(results[:40])
