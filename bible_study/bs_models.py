from datetime import datetime, timezone
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

from models import db


class BibleStudyUser(UserMixin, db.Model):
    __tablename__ = "bs_users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    display_name = db.Column(db.String(120), nullable=True)
    email = db.Column(db.String(200), nullable=True)
    password_hash = db.Column(db.String(256), nullable=False, default="")
    role = db.Column(db.String(20), nullable=False, default="user")
    is_admin = db.Column(db.Boolean, default=False, nullable=False)
    invite_token = db.Column(db.String(64), nullable=True, unique=True)
    has_set_password = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

    notes = db.relationship("BSNote", back_populates="user", cascade="all, delete-orphan")
    tags = db.relationship("BSTag", back_populates="user", cascade="all, delete-orphan")
    questions = db.relationship("BSQuestion", back_populates="user", cascade="all, delete-orphan")
    prayers = db.relationship("BSJournalEntry", back_populates="user", cascade="all, delete-orphan")
    topics = db.relationship("BSTopic", back_populates="user", cascade="all, delete-orphan")

    def get_id(self):
        return f"bs_{self.id}"

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)


class BSNote(db.Model):
    __tablename__ = "bs_notes"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("bs_users.id", ondelete="CASCADE"), nullable=False)
    book = db.Column(db.String(50), nullable=False)
    chapter = db.Column(db.Integer, nullable=True)
    verse_start = db.Column(db.Integer, nullable=True)
    verse_end = db.Column(db.Integer, nullable=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user = db.relationship("BibleStudyUser", back_populates="notes")
    __table_args__ = (db.Index("idx_bs_notes_user_book_ch", "user_id", "book", "chapter"),)


class BSTag(db.Model):
    __tablename__ = "bs_tags"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("bs_users.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(7), nullable=False, default="#6366f1")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user = db.relationship("BibleStudyUser", back_populates="tags")
    verses = db.relationship("BSTagVerse", back_populates="tag", cascade="all, delete-orphan")
    tag_notes = db.relationship("BSTagNote", back_populates="tag", cascade="all, delete-orphan")
    __table_args__ = (db.UniqueConstraint("user_id", "name", name="uq_bs_tag_user_name"),)


class BSTagVerse(db.Model):
    __tablename__ = "bs_tag_verses"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("bs_users.id", ondelete="CASCADE"), nullable=False)
    tag_id = db.Column(db.Integer, db.ForeignKey("bs_tags.id", ondelete="CASCADE"), nullable=False)
    book = db.Column(db.String(50), nullable=False)
    chapter = db.Column(db.Integer, nullable=True)
    verse_start = db.Column(db.Integer, nullable=True)
    verse_end = db.Column(db.Integer, nullable=True)
    note = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    tag = db.relationship("BSTag", back_populates="verses")
    __table_args__ = (db.Index("idx_bs_tagverse_user_book_ch", "user_id", "book", "chapter"),)


class BSTagNote(db.Model):
    __tablename__ = "bs_tag_notes"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("bs_users.id", ondelete="CASCADE"), nullable=False)
    tag_id = db.Column(db.Integer, db.ForeignKey("bs_tags.id", ondelete="CASCADE"), nullable=False)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    tag = db.relationship("BSTag", back_populates="tag_notes")
    __table_args__ = (db.Index("idx_bs_tagnote_tag", "tag_id"),)


class BSQuestion(db.Model):
    __tablename__ = "bs_questions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("bs_users.id", ondelete="CASCADE"), nullable=False)
    book = db.Column(db.String(50), nullable=True)
    chapter = db.Column(db.Integer, nullable=True)
    verse_start = db.Column(db.Integer, nullable=True)
    verse_end = db.Column(db.Integer, nullable=True)
    body = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=True)
    is_answered = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user = db.relationship("BibleStudyUser", back_populates="questions")
    __table_args__ = (db.Index("idx_bs_questions_user_book_ch", "user_id", "book", "chapter"),)


class BSJournalType(db.Model):
    __tablename__ = "bs_journal_types"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("bs_users.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    color = db.Column(db.String(7), nullable=False, default="#6366f1")
    entries = db.relationship("BSJournalEntry", back_populates="journal_type", cascade="all, delete-orphan")


class BSJournalEntry(db.Model):
    __tablename__ = "bs_journal_entries"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("bs_users.id", ondelete="CASCADE"), nullable=False)
    type_id = db.Column(db.Integer, db.ForeignKey("bs_journal_types.id", ondelete="SET NULL"), nullable=True)
    title = db.Column(db.String(200), nullable=True)
    body = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    user = db.relationship("BibleStudyUser", back_populates="prayers")
    journal_type = db.relationship("BSJournalType", back_populates="entries")


class BSTopic(db.Model):
    __tablename__ = "bs_topics"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("bs_users.id", ondelete="CASCADE"), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False, default="")
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
    user = db.relationship("BibleStudyUser", back_populates="topics")
