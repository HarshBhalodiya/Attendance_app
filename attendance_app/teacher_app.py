import os
from flask import Flask, render_template, redirect, url_for, flash, request, Response, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, datetime
import csv
import io
import smtplib
from email.message import EmailMessage

from models import db, User, Student, Subject, Attendance

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ─── App config ───────────────────────────────────────────────────────────────

app = Flask(__name__, template_folder='templates/teacher')
app.config['SECRET_KEY']                     = os.environ.get('SECRET_KEY', 'teacher-secret-key')
app.config['SESSION_COOKIE_NAME']            = 'teacher_session'
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
    if user_id.startswith('teacher-'):
        return User.query.get(int(user_id.split('-')[1]))
    return None

# ─── AI helpers ───────────────────────────────────────────────────────────────

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

    return f"""You are a school attendance advisor. Analyse this student's attendance.

Student: {student.name} | Roll No: {student.roll_no}
Overall: {pct}% ({present} present, {absent} absent out of {total})

Subject breakdown:
{chr(10).join(subject_lines) if subject_lines else '  No data'}

Recent absences: {', '.join(recent_abs) if recent_abs else 'None'}

Provide exactly 3 numbered points:
1. Risk assessment (Critical/Warning/Good) with one sentence
2. Pattern analysis — any pattern in absences?
3. One specific suggestion for the teacher"""


def build_class_prompt(teacher_id=None):
    students = Student.query.filter_by(teacher_id=teacher_id).all() if teacher_id else Student.query.all()
    if not students:
        return "No students yet."
    lines = [f"  - {s.name}: {s.attendance_percentage()}%" for s in students]
    avg   = round(sum(s.attendance_percentage() for s in students) / len(students), 1)
    at_risk = sum(1 for s in students if s.attendance_percentage() < 75)

    return f"""Analyse this class attendance.
Total: {len(students)} students | Average: {avg}% | At risk: {at_risk}
{chr(10).join(lines)}

Provide exactly 3 numbered points:
1. Overall class health (1-2 sentences)
2. Top 2-3 students needing attention
3. One actionable recommendation for this week"""

# ─── Dashboard ────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def dashboard():
    students       = Student.query.filter_by(teacher_id=current_user.id).order_by(Student.roll_no).all()
    subjects       = Subject.query.filter_by(teacher_id=current_user.id).all()
    total_students = len(students)
    at_risk        = [s for s in students if Attendance.query.filter_by(student_id=s.id).count() > 0 and s.attendance_percentage() < 75]
    good           = [s for s in students if s.attendance_percentage() >= 75]
    alert          = total_students > 0 and (len(at_risk) / total_students) > 0.3
    subject_ids    = [s.id for s in subjects]
    recent = (Attendance.query.filter(Attendance.subject_id.in_(subject_ids))
          .order_by(Attendance.marked_at.desc()).limit(5).all()) if subject_ids else []

    return render_template('dashboard.html',
                           students=students, subjects=subjects,
                           total_students=total_students,
                           at_risk=at_risk, good=good,
                           recent=recent, alert=alert)

# ─── Auth ─────────────────────────────────────────────────────────────────────

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        confirm  = request.form.get('confirm_password', '')
        if not username or not password:
            flash('Username and password are required.', 'danger')
            return redirect(url_for('register'))
        if password != confirm:
            flash('Passwords do not match.', 'danger')
            return redirect(url_for('register'))
        if len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
            return redirect(url_for('register'))
        if User.query.filter_by(username=username).first():
            flash('Username already taken.', 'danger')
            return redirect(url_for('register'))
        db.session.add(User(username=username,
                            password=generate_password_hash(password)))
        db.session.commit()
        flash('Teacher account created! You can now log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        user     = User.query.filter_by(username=username).first()
        if user and user.is_active and check_password_hash(user.password, password):
            login_user(user, remember=request.form.get('remember'))
            flash(f'Welcome back, {user.username}!', 'success')
            return redirect(url_for('dashboard'))
        elif user and not user.is_active:
            flash('Your account has been deactivated. Contact the admin.', 'danger')
        else:
            flash('Incorrect username or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ─── Students ─────────────────────────────────────────────────────────────────

@app.route('/students', methods=['GET', 'POST'])
@login_required
def students():
    if request.method == 'POST':
        name     = request.form.get('name', '').strip()
        roll_no  = request.form.get('roll_no', '').strip()
        email    = request.form.get('email', '').strip() or None
        username = request.form.get('username', '').strip() or None
        password = request.form.get('password', '') or None

        if not name or not roll_no:
            flash('Name and roll number are required.', 'danger')
        elif Student.query.filter_by(roll_no=roll_no).first():
            flash(f'Roll number "{roll_no}" already exists.', 'danger')
        elif username and Student.query.filter_by(username=username).first():
            flash(f'Username "{username}" already taken.', 'danger')
        else:
            hashed = generate_password_hash(password) if password else None
            db.session.add(Student(name=name, roll_no=roll_no,
                                   email=email, username=username,
                                   password=hashed, teacher_id=current_user.id))
            db.session.commit()
            flash(f'Student "{name}" added successfully.', 'success')
            
        csv_file = request.files.get('csv_file')
        if csv_file and csv_file.filename.endswith('.csv'):
            stream = io.StringIO(csv_file.stream.read().decode("UTF8"), newline=None)
            csv_input = csv.reader(stream)
            next(csv_input, None) # skip header
            added = 0
            for row in csv_input:
                if len(row) >= 2:
                    name, roll_no = row[0].strip(), row[1].strip()
                    email = row[2].strip() if len(row) > 2 else None
                    if name and roll_no and not Student.query.filter_by(roll_no=roll_no).first():
                        db.session.add(Student(name=name, roll_no=roll_no, email=email, teacher_id=current_user.id))
                        added += 1
            if added > 0:
                db.session.commit()
                flash(f'{added} students imported successfully.', 'success')

        return redirect(url_for('students'))

    all_students = Student.query.filter_by(teacher_id=current_user.id).order_by(Student.roll_no).all()
    return render_template('students.html', students=all_students)


@app.route('/students/<int:student_id>')
@login_required
def student_detail(student_id):
    student    = Student.query.filter_by(id=student_id, teacher_id=current_user.id).first_or_404()
    subjects   = Subject.query.filter_by(teacher_id=current_user.id).all()
    subject_id = request.args.get('subject_id', type=int)
    date_from  = request.args.get('date_from')
    date_to    = request.args.get('date_to')

    query = Attendance.query.filter_by(student_id=student_id)
    my_subject_ids = [s.id for s in subjects]
    if my_subject_ids:
        query = query.filter(Attendance.subject_id.in_(my_subject_ids))
    else:
        query = query.filter(Attendance.subject_id == -1)

    if subject_id:
        query = query.filter_by(subject_id=subject_id)
    if date_from:
        query = query.filter(Attendance.date >= date.fromisoformat(date_from))
    if date_to:
        query = query.filter(Attendance.date <= date.fromisoformat(date_to))

    records = query.order_by(Attendance.date.desc()).all()
    total   = len(records)
    present = sum(1 for r in records if r.status == 'present')
    absent  = total - present
    pct     = round((present / total * 100), 1) if total else 0

    return render_template('student_detail.html',
                           student=student, records=records, subjects=subjects,
                           selected_subject=subject_id, date_from=date_from,
                           date_to=date_to, total=total, present=present,
                           absent=absent, pct=pct)


@app.route('/students/delete/<int:student_id>', methods=['POST'])
@login_required
def delete_student(student_id):
    student = Student.query.filter_by(id=student_id, teacher_id=current_user.id).first_or_404()
    Attendance.query.filter_by(student_id=student_id).delete()
    db.session.delete(student)
    db.session.commit()
    flash(f'Student "{student.name}" deleted.', 'info')
    return redirect(url_for('students'))

# ─── Subjects ─────────────────────────────────────────────────────────────────

@app.route('/subjects', methods=['GET', 'POST'])
@login_required
def subjects():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Subject name cannot be empty.', 'danger')
        else:
            db.session.add(Subject(name=name, teacher_id=current_user.id))
            db.session.commit()
            flash(f'Subject "{name}" added.', 'success')
        return redirect(url_for('subjects'))
    all_subjects = Subject.query.filter_by(teacher_id=current_user.id).all()
    return render_template('subjects.html', subjects=all_subjects)


@app.route('/subjects/delete/<int:subject_id>', methods=['POST'])
@login_required
def delete_subject(subject_id):
    subject = Subject.query.filter_by(id=subject_id, teacher_id=current_user.id).first_or_404()
    Attendance.query.filter_by(subject_id=subject_id).delete()
    db.session.delete(subject)
    db.session.commit()
    flash(f'Subject "{subject.name}" deleted.', 'info')
    return redirect(url_for('subjects'))

# ─── Mark attendance ──────────────────────────────────────────────────────────

def check_and_send_alert(student, old_pct):
    new_pct = student.attendance_percentage()
    if new_pct < 75 and old_pct >= 75:
        if student.email:
            try:
                msg = EmailMessage()
                msg.set_content(f"Dear {student.name},\nYour attendance has dropped below the 75% threshold (currently {new_pct}%). Please attend classes regularly.")
                msg['Subject'] = "Attendance Warning"
                msg['From'] = "admin@attendance.local"
                msg['To'] = student.email
                # Use a local test SMTP server or catch error to prevent app crash
                print(f"[Demo] Sending email to {student.email}...")
                s = smtplib.SMTP('localhost', 1025)
                s.send_message(msg)
                s.quit()
            except Exception as e:
                print(f"Could not connect to SMTP server. Alert logic executed. ({e})")

@app.route('/mark', methods=['GET', 'POST'])
@login_required
def mark_attendance():
    students = Student.query.filter_by(teacher_id=current_user.id).order_by(Student.roll_no).all()
    subjects = Subject.query.filter_by(teacher_id=current_user.id).all()

    if request.method == 'POST':
        subject_id = request.form.get('subject_id', type=int)
        date_str   = request.form.get('date')
        if not subject_id or not date_str:
            flash('Please select a subject and date.', 'danger')
            return redirect(url_for('mark_attendance'))

        subject_check = Subject.query.filter_by(id=subject_id, teacher_id=current_user.id).first()
        if not subject_check:
            flash('Unauthorized subject.', 'danger')
            return redirect(url_for('mark_attendance'))

        att_date = date.fromisoformat(date_str)
        saved    = 0
        old_pcts = {}
        for student in students:
            old_pcts[student] = student.attendance_percentage()
            status   = request.form.get(f'status_{student.id}', 'absent')
            existing = Attendance.query.filter_by(
                student_id=student.id, subject_id=subject_id, date=att_date
            ).first()
            if existing:
                existing.status = status
                existing.marked_at = datetime.utcnow()
                existing.marked_by = current_user.id
            else:
                db.session.add(Attendance(
                    student_id=student.id, subject_id=subject_id,
                    date=att_date, status=status,
                    marked_by=current_user.id
                ))
            saved += 1
        db.session.commit()
        
        for student, old_pct in old_pcts.items():
            check_and_send_alert(student, old_pct)
            
        flash(f'Attendance saved for {saved} students on {att_date}.', 'success')
        return redirect(url_for('dashboard'))

    return render_template('mark_attendance.html',
                           students=students, subjects=subjects,
                           today=date.today().isoformat())

# ─── View records ─────────────────────────────────────────────────────────────

@app.route('/view')
@login_required
def view_records():
    subject_id = request.args.get('subject_id', type=int)
    date_from  = request.args.get('date_from')
    date_to    = request.args.get('date_to')
    subjects   = Subject.query.filter_by(teacher_id=current_user.id).all()
    students   = Student.query.filter_by(teacher_id=current_user.id).order_by(Student.roll_no).all()
    
    # Restrict shown attendance to teacher's subjects
    my_subject_ids = [s.id for s in subjects]
    if subject_id and subject_id not in my_subject_ids:
        subject_id = -1 # effectively show nothing or handle error

    summary = []
    for s in students:
        query = Attendance.query.filter_by(student_id=s.id)
        if my_subject_ids:
            query = query.filter(Attendance.subject_id.in_(my_subject_ids))
        else:
            query = query.filter(Attendance.subject_id == -1)
            
        if subject_id and subject_id != -1:
            query = query.filter_by(subject_id=subject_id)
        if date_from:
            query = query.filter(Attendance.date >= date.fromisoformat(date_from))
        if date_to:
            query = query.filter(Attendance.date <= date.fromisoformat(date_to))
        records = query.all()
        total   = len(records)
        present = sum(1 for r in records if r.status == 'present')
        absent  = total - present
        pct     = round((present / total * 100), 1) if total else 0
        summary.append({'student': s, 'total': total, 'present': present,
                        'absent': absent, 'pct': pct,
                        'at_risk': pct < 75 and total > 0})

    summary.sort(key=lambda x: x['pct'])
    return render_template('view_records.html',
                           summary=summary, subjects=subjects,
                           selected_subject=subject_id,
                           date_from=date_from or '', date_to=date_to or '')

# ─── Report ───────────────────────────────────────────────────────────────────

@app.route('/report')
@login_required
def report():
    students = Student.query.filter_by(teacher_id=current_user.id).order_by(Student.roll_no).all()
    subjects = Subject.query.filter_by(teacher_id=current_user.id).all()
    my_subject_ids = [s.id for s in subjects]

    student_labels, student_pcts, student_colors = [], [], []
    for s in students:
        pct = s.attendance_percentage()
        student_labels.append(s.name)
        student_pcts.append(pct)
        student_colors.append('#22c55e' if pct >= 75 else '#ef4444')

    all_records = Attendance.query.filter(Attendance.subject_id.in_(my_subject_ids)).all() if my_subject_ids else []
    total_all   = len(all_records)
    present_all = sum(1 for r in all_records if r.status == 'present')
    absent_all  = total_all - present_all

    subject_stats = []
    for subj in subjects:
        recs    = Attendance.query.filter_by(subject_id=subj.id).all()
        total   = len(recs)
        present = sum(1 for r in recs if r.status == 'present')
        pct     = round((present / total * 100), 1) if total else 0
        subject_stats.append({'name': subj.name, 'total': total,
                              'present': present, 'absent': total - present,
                              'pct': pct, 'at_risk': pct < 75 and total > 0})
    subject_stats.sort(key=lambda x: x['pct'])

    at_risk_count = sum(1 for s in students if Attendance.query.filter_by(student_id=s.id).count() > 0 and s.attendance_percentage() < 75)
    avg_pct = round(sum(student_pcts) / len(student_pcts), 1) if student_pcts else 0

    return render_template('report.html',
                           students=students,
                           student_labels=student_labels,
                           student_pcts=student_pcts,
                           student_colors=student_colors,
                           present_all=present_all, absent_all=absent_all,
                           total_all=total_all, subject_stats=subject_stats,
                           at_risk_count=at_risk_count, avg_pct=avg_pct,
                           total_students=len(students))

# ─── AI Insights ──────────────────────────────────────────────────────────────

@app.route('/insights/<int:student_id>')
@login_required
def insights(student_id):
    student = Student.query.filter_by(id=student_id, teacher_id=current_user.id).first_or_404()

    if student.ai_cache_valid():
        insight_text = student.ai_cache
        from_cache   = True
    else:
        insight_text         = call_claude(build_student_prompt(student))
        student.ai_cache     = insight_text
        student.ai_cached_at = datetime.utcnow()
        db.session.commit()
        from_cache = False

    subjects = Subject.query.filter_by(teacher_id=current_user.id).all()
    my_subject_ids = [s.id for s in subjects]
    
    query = Attendance.query.filter_by(student_id=student_id)
    if my_subject_ids:
        query = query.filter(Attendance.subject_id.in_(my_subject_ids))
    else:
        query = query.filter(Attendance.subject_id == -1)
        
    records = query.all()
    total   = len(records)
    present = sum(1 for r in records if r.status == 'present')
    absent  = total - present
    pct     = round((present / total * 100), 1) if total else 0

    return render_template('insights.html',
                           student=student, insight=insight_text,
                           from_cache=from_cache, total=total,
                           present=present, absent=absent, pct=pct)


@app.route('/insights/<int:student_id>/refresh', methods=['POST'])
@login_required
def refresh_insight(student_id):
    student              = Student.query.filter_by(id=student_id, teacher_id=current_user.id).first_or_404()
    student.ai_cache     = call_claude(build_student_prompt(student))
    student.ai_cached_at = datetime.utcnow()
    db.session.commit()
    flash('AI insight refreshed.', 'success')
    return redirect(url_for('insights', student_id=student_id))


@app.route('/insights/class')
@login_required
def class_insight():
    if not Student.query.filter_by(teacher_id=current_user.id).first():
        return jsonify({'insight': 'No students yet.'})
    return jsonify({'insight': call_claude(build_class_prompt(teacher_id=current_user.id))})

# ─── CSV Export ───────────────────────────────────────────────────────────────

@app.route('/export')
@login_required
def export_csv():
    subject_id = request.args.get('subject_id', type=int)
    date_from  = request.args.get('date_from')
    date_to    = request.args.get('date_to')
    students   = Student.query.filter_by(teacher_id=current_user.id).order_by(Student.roll_no).all()
    subjects   = Subject.query.filter_by(teacher_id=current_user.id).all()
    my_subject_ids = [s.id for s in subjects]

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Roll No', 'Name', 'Email', 'Total', 'Present',
                     'Absent', 'Attendance %', 'Status'])

    for s in students:
        query = Attendance.query.filter_by(student_id=s.id)
        if my_subject_ids:
            query = query.filter(Attendance.subject_id.in_(my_subject_ids))
        else:
            query = query.filter(Attendance.subject_id == -1)
            
        if subject_id:
            query = query.filter_by(subject_id=subject_id)
        if date_from:
            query = query.filter(Attendance.date >= date.fromisoformat(date_from))
        if date_to:
            query = query.filter(Attendance.date <= date.fromisoformat(date_to))
        records = query.all()
        total   = len(records)
        present = sum(1 for r in records if r.status == 'present')
        absent  = total - present
        pct     = round((present / total * 100), 1) if total else 0
        writer.writerow([s.roll_no, s.name, s.email or '', total,
                         present, absent, pct,
                         'At Risk' if pct < 75 and total > 0 else 'Good'])

    output.seek(0)
    return Response(output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=attendance_report.csv'})

# ─── Edit / Delete Record ─────────────────────────────────────────────────────

@app.route('/attendance/toggle/<int:record_id>', methods=['POST'])
@login_required
def toggle_attendance(record_id):
    record = Attendance.query.get_or_404(record_id)
    if record.subject.teacher_id != current_user.id:
        flash('Unauthorized.', 'danger')
        return redirect(request.referrer or url_for('dashboard'))
    record.status = 'absent' if record.status == 'present' else 'present'
    record.marked_at = datetime.utcnow()
    record.marked_by = current_user.id
    db.session.commit()
    flash('Attendance updated.', 'success')
    return redirect(request.referrer or url_for('dashboard'))

@app.route('/attendance/delete/<int:record_id>', methods=['POST'])
@login_required
def delete_attendance(record_id):
    record = Attendance.query.get_or_404(record_id)
    if record.subject.teacher_id != current_user.id:
        flash('Unauthorized.', 'danger')
        return redirect(request.referrer or url_for('dashboard'))
    db.session.delete(record)
    db.session.commit()
    flash('Attendance record deleted.', 'info')
    return redirect(request.referrer or url_for('dashboard'))

# ─── Edit Student (added fix) ─────────────────────────────────────────────────

@app.route('/students/<int:student_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_student(student_id):
    student = Student.query.filter_by(id=student_id, teacher_id=current_user.id).first_or_404()
    if request.method == 'POST':
        student.name  = request.form.get('name', student.name).strip()
        student.email = request.form.get('email', '').strip() or None
        new_username  = request.form.get('username', '').strip() or None
        new_password  = request.form.get('password', '') or None
        if new_username and new_username != student.username:
            if Student.query.filter_by(username=new_username).first():
                flash(f'Username "{new_username}" already taken.', 'danger')
                return redirect(url_for('edit_student', student_id=student_id))
            student.username = new_username
        if new_password:
            if len(new_password) < 6:
                flash('Password must be at least 6 characters.', 'danger')
                return redirect(url_for('edit_student', student_id=student_id))
            student.password = generate_password_hash(new_password)
        db.session.commit()
        flash(f'Student "{student.name}" updated.', 'success')
        return redirect(url_for('students'))
    return render_template('edit_student.html', student=student)

# ─── Profile (added fix) ──────────────────────────────────────────────────────

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    if request.method == 'POST':
        name         = request.form.get('name', '').strip()
        current_pass = request.form.get('current_password', '')
        new_pass     = request.form.get('new_password', '')
        confirm      = request.form.get('confirm_password', '')
        if name:
            current_user.name = name
        if new_pass:
            if not check_password_hash(current_user.password, current_pass):
                flash('Current password is incorrect.', 'danger')
                return redirect(url_for('profile'))
            if new_pass != confirm:
                flash('New passwords do not match.', 'danger')
                return redirect(url_for('profile'))
            if len(new_pass) < 6:
                flash('Password must be at least 6 characters.', 'danger')
                return redirect(url_for('profile'))
            current_user.password = generate_password_hash(new_pass)
        db.session.commit()
        flash('Profile updated successfully.', 'success')
        return redirect(url_for('profile'))
    return render_template('profile.html')


# ─── Error handlers ───────────────────────────────────────────────────────────

@app.errorhandler(404)
def page_not_found(e):
    return render_template('404.html'), 404

# ─── Init & run ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        print("✓ Teacher app ready.")
        print("✓ Open http://127.0.0.1:5000")
    app.run(debug=True, port=5000)

