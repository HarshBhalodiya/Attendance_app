from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class Admin(UserMixin, db.Model):
    __tablename__ = 'admin'
    id       = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    def get_id(self): return f"admin-{self.id}"
    @property
    def role(self): return 'admin'

class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id         = db.Column(db.Integer, primary_key=True)
    username   = db.Column(db.String(80), unique=True, nullable=False)
    password   = db.Column(db.String(200), nullable=False)
    name       = db.Column(db.String(100), nullable=True)
    is_active_ = db.Column(db.Boolean, default=True)
    students   = db.relationship('Student', backref='teacher', lazy=True)
    subjects   = db.relationship('Subject', backref='teacher', lazy=True)
    def get_id(self): return f"teacher-{self.id}"
    @property
    def role(self): return 'teacher'
    @property
    def is_active(self): return self.is_active_

class Student(UserMixin, db.Model):
    __tablename__ = 'student'
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(100), nullable=False)
    roll_no      = db.Column(db.String(20), unique=True, nullable=False)
    email        = db.Column(db.String(120), unique=True, nullable=True)
    username     = db.Column(db.String(80), unique=True, nullable=True)
    password     = db.Column(db.String(200), nullable=True)
    teacher_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    ai_cache     = db.Column(db.Text, nullable=True)
    ai_cached_at = db.Column(db.DateTime, nullable=True)
    attendances  = db.relationship('Attendance', backref='student', lazy=True)
    def get_id(self): return f"student-{self.id}"
    @property
    def role(self): return 'student'
    @property
    def is_active(self): return self.password is not None and self.password != ''
    def attendance_percentage(self, subject_id=None):
        query = Attendance.query.filter_by(student_id=self.id)
        if subject_id: query = query.filter_by(subject_id=subject_id)
        records = query.all()
        if not records: return 0.0
        return round(sum(1 for r in records if r.status == 'present') / len(records) * 100, 1)
    def ai_cache_valid(self):
        if not self.ai_cache or not self.ai_cached_at: return False
        return (datetime.utcnow() - self.ai_cached_at).total_seconds() < 86400

class Subject(db.Model):
    __tablename__ = 'subject'
    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(100), nullable=False)
    teacher_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    attendances = db.relationship('Attendance', backref='subject', lazy=True)

class Attendance(db.Model):
    __tablename__ = 'attendance'
    id         = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id'), nullable=False)
    subject_id = db.Column(db.Integer, db.ForeignKey('subject.id'), nullable=False)
    date       = db.Column(db.Date, nullable=False, default=datetime.utcnow().date)
    status     = db.Column(db.String(10), nullable=False)
    marked_at  = db.Column(db.DateTime, default=datetime.utcnow)
    marked_by  = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    __table_args__ = (db.UniqueConstraint('student_id', 'subject_id', 'date', name='unique_attendance'),)