import os
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, datetime

from models import db, Student, Subject, Attendance

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─── App config ───────────────────────────────────────────────────────────────

app = Flask(__name__, template_folder='templates/student')
app.config['SECRET_KEY']                     = os.environ.get('SECRET_KEY', 'student-secret-key')
app.config['SESSION_COOKIE_NAME']            = 'student_session'
app.config['SQLALCHEMY_DATABASE_URI']        = 'sqlite:///attendance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# ─── Flask-Login ──────────────────────────────────────────────────────────────

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view             = 'login'
login_manager.login_message          = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'

@login_manager.user_loader
def load_user(user_id):
    if user_id.startswith('student-'):
        return Student.query.get(int(user_id.split('-')[1]))
    return None

# ─── AI helper ────────────────────────────────────────────────────────────────

def call_claude(prompt):
    try:
        import anthropic
        client  = anthropic.Anthropic(api_key=os.environ.get('ANTHROPIC_API_KEY'))
        message = client.messages.create(
            model='claude-3-5-sonnet-20241022',
            max_tokens=600,
            messages=[{'role': 'user', 'content': prompt}]
        )
        return message.content[0].text
    except Exception as e:
        return f"AI insight unavailable: {str(e)}"


def build_student_prompt(student):
    records = Attendance.query.filter_by(student_id=student.id).all()
    total   = len(records)
    present = sum(1 for r in records if r.status == 'present')
    absent  = total - present
    pct     = round((present / total * 100), 1) if total else 0

    subject_map = {}
    for r in records:
        subj = r.subject.name
        if subj not in subject_map:
            subject_map[subj] = {'present': 0, 'absent': 0}
        subject_map[subj][r.status] += 1

    subject_lines = []
    for subj, counts in subject_map.items():
        t = counts['present'] + counts['absent']
        p = round(counts['present'] / t * 100, 1) if t else 0
        subject_lines.append(f"  - {subj}: {p}% ({counts['absent']} absences)")

    absent_dates = [str(r.date) for r in records if r.status == 'absent']
    recent_abs   = absent_dates[-5:] if absent_dates else []

    return f"""You are a friendly school advisor talking directly to a student.

Student: {student.name} | Roll No: {student.roll_no}
Overall: {pct}% ({present} present, {absent} absent out of {total})

Subject breakdown:
{chr(10).join(subject_lines) if subject_lines else '  No data'}

Recent absences: {', '.join(recent_abs) if recent_abs else 'None'}

Provide exactly 3 numbered points (speak directly to the student):
1. Your attendance status (Critical/Warning/Good) with one friendly sentence
2. Any pattern you notice in your absences
3. One practical tip to help you improve your attendance"""

# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        student  = Student.query.filter_by(username=username).first()

        if student:
            if not student.is_active:
                flash('Account not active. Please ask your teacher to set a password for you.', 'warning')
            elif student.password and check_password_hash(student.password, password):
                login_user(student, remember=request.form.get('remember'))
                flash(f'Welcome, {student.name}!', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Incorrect username or password.', 'danger')
        else:
            flash('Incorrect username or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ─── Student dashboard ────────────────────────────────────────────────────────

@app.route('/dashboard')
@login_required
def dashboard():
    student  = current_user
    # Only show subjects from student's own teacher
    subjects = Subject.query.filter_by(teacher_id=student.teacher_id).all() if student.teacher_id else Subject.query.all()

    all_records = Attendance.query.filter_by(student_id=student.id).all()
    total       = len(all_records)
    present     = sum(1 for r in all_records if r.status == 'present')
    absent      = total - present
    pct         = round((present / total * 100), 1) if total else 0

    subject_stats = []
    for subj in subjects:
        recs = Attendance.query.filter_by(
            student_id=student.id, subject_id=subj.id).all()
        t  = len(recs)
        p  = sum(1 for r in recs if r.status == 'present')
        a  = t - p
        sp = round((p / t * 100), 1) if t else 0
        if t > 0:
            subject_stats.append({
                'name': subj.name, 'total': t,
                'present': p, 'absent': a,
                'pct': sp, 'at_risk': sp < 75
            })

    absences = (Attendance.query
                .filter_by(student_id=student.id, status='absent')
                .order_by(Attendance.date.desc())
                .limit(10).all())

    return render_template('dashboard.html',
                           student=student,
                           total=total, present=present,
                           absent=absent, pct=pct,
                           subject_stats=subject_stats,
                           absences=absences)

# ─── AI Insight ───────────────────────────────────────────────────────────────

@app.route('/insight')
@login_required
def insight():
    student = current_user

    if student.ai_cache_valid():
        insight_text = student.ai_cache
        from_cache   = True
    else:
        insight_text         = call_claude(build_student_prompt(student))
        student.ai_cache     = insight_text
        student.ai_cached_at = datetime.utcnow()
        db.session.commit()
        from_cache = False

    records = Attendance.query.filter_by(student_id=student.id).all()
    total   = len(records)
    present = sum(1 for r in records if r.status == 'present')
    absent  = total - present
    pct     = round((present / total * 100), 1) if total else 0

    return render_template('insight.html',
                           student=student, insight=insight_text,
                           from_cache=from_cache, total=total,
                           present=present, absent=absent, pct=pct)


@app.route('/insight/refresh', methods=['POST'])
@login_required
def refresh_insight():
    student              = current_user
    student.ai_cache     = call_claude(build_student_prompt(student))
    student.ai_cached_at = datetime.utcnow()
    db.session.commit()
    flash('AI insight refreshed.', 'success')
    return redirect(url_for('insight'))

# ─── Change password ──────────────────────────────────────────────────────────

@app.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current  = request.form.get('current_password', '')
        new_pass = request.form.get('new_password', '')
        confirm  = request.form.get('confirm_password', '')

        if not current_user.password or not check_password_hash(current_user.password, current):
            flash('Current password is incorrect.', 'danger')
        elif new_pass != confirm:
            flash('New passwords do not match.', 'danger')
        elif len(new_pass) < 6:
            flash('Password must be at least 6 characters.', 'danger')
        else:
            current_user.password = generate_password_hash(new_pass)
            db.session.commit()
            flash('Password changed successfully!', 'success')
            return redirect(url_for('dashboard'))

    return render_template('change_password.html')

# ─── Error handler ────────────────────────────────────────────────────────────

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

# ─── Init & run ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("✓ Student app ready.")
        print("✓ Open http://127.0.0.1:5001")
    app.run(debug=True, port=5001)
