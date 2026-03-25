import os
from flask import Flask, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from models import db, Admin, User, Student, Subject, Attendance

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__, template_folder='templates/admin')
app.config['SECRET_KEY']                     = os.environ.get('SECRET_KEY', 'admin-secret')
app.config['SESSION_COOKIE_NAME']            = 'admin_session'
app.config['SQLALCHEMY_DATABASE_URI']        = 'sqlite:///attendance.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db.init_app(app)

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view             = 'login'
login_manager.login_message_category = 'warning'

@login_manager.user_loader
def load_user(user_id):
    if user_id.startswith('admin-'):
        return Admin.query.get(int(user_id.split('-')[1]))
    return None

# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def dashboard():
    teachers       = User.query.all()
    total_students = Student.query.count()
    total_teachers = len(teachers)
    total_records  = Attendance.query.count()
    all_students   = Student.query.all()
    verified_students = [s for s in all_students if Attendance.query.filter_by(student_id=s.id).count() > 0]
    at_risk_count  = sum(1 for s in verified_students if s.attendance_percentage() < 75)
    avg_pct = round(sum(s.attendance_percentage() for s in verified_students) / len(verified_students), 1) if verified_students else 0

    teacher_stats = []
    for t in teachers:
        studs = Student.query.filter_by(teacher_id=t.id).all()
        teacher_stats.append({
            'teacher':       t,
            'student_count': len(studs),
            'at_risk':       sum(1 for s in studs if Attendance.query.filter_by(student_id=s.id).count() > 0 and s.attendance_percentage() < 75),
            'avg_pct':       round(sum(s.attendance_percentage() for s in studs if Attendance.query.filter_by(student_id=s.id).count() > 0) / max(1, sum(1 for s in studs if Attendance.query.filter_by(student_id=s.id).count() > 0)), 1) if any(Attendance.query.filter_by(student_id=s.id).count() > 0 for s in studs) else 0
        })

    return render_template('dashboard.html',
                           total_teachers=total_teachers,
                           total_students=total_students,
                           total_records=total_records,
                           at_risk_count=at_risk_count,
                           avg_pct=avg_pct,
                           teacher_stats=teacher_stats)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        admin    = Admin.query.filter_by(username=username).first()
        if admin and check_password_hash(admin.password, password):
            login_user(admin)
            flash(f'Welcome, {admin.username}!', 'success')
            return redirect(url_for('dashboard'))
        flash('Incorrect username or password.', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('login'))

# ─── Manage Teachers ──────────────────────────────────────────────────────────

@app.route('/teachers', methods=['GET', 'POST'])
@login_required
def teachers():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        name     = request.form.get('name', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            flash('Username and password required.', 'danger')
        elif len(password) < 6:
            flash('Password must be at least 6 characters.', 'danger')
        elif User.query.filter_by(username=username).first():
            flash(f'Username "{username}" already taken.', 'danger')
        else:
            db.session.add(User(username=username, name=name,
                                password=generate_password_hash(password)))
            db.session.commit()
            flash(f'Teacher "{username}" created successfully.', 'success')
        return redirect(url_for('teachers'))

    all_teachers = User.query.all()
    teacher_data = []
    for t in all_teachers:
        studs = Student.query.filter_by(teacher_id=t.id).all()
        teacher_data.append({
            'teacher':       t,
            'student_count': len(studs),
            'avg_pct':       round(sum(s.attendance_percentage() for s in studs) / len(studs), 1) if studs else 0
        })
    return render_template('teachers.html', teacher_data=teacher_data)

@app.route('/teachers/<int:teacher_id>/toggle', methods=['POST'])
@login_required
def toggle_teacher(teacher_id):
    teacher          = User.query.get_or_404(teacher_id)
    teacher.is_active_ = not teacher.is_active_
    db.session.commit()
    status = 'activated' if teacher.is_active_ else 'deactivated'
    flash(f'Teacher "{teacher.username}" {status}.', 'info')
    return redirect(url_for('teachers'))

@app.route('/teachers/<int:teacher_id>/reset-password', methods=['POST'])
@login_required
def reset_teacher_password(teacher_id):
    teacher          = User.query.get_or_404(teacher_id)
    new_pass         = request.form.get('new_password', '')
    if len(new_pass) < 6:
        flash('Password must be at least 6 characters.', 'danger')
        return redirect(url_for('teachers'))
    teacher.password = generate_password_hash(new_pass)
    db.session.commit()
    flash(f'Password reset for "{teacher.username}".', 'success')
    return redirect(url_for('teachers'))

@app.route('/teachers/<int:teacher_id>/delete', methods=['POST'])
@login_required
def delete_teacher(teacher_id):
    teacher  = User.query.get_or_404(teacher_id)
    students = Student.query.filter_by(teacher_id=teacher_id).all()
    for s in students:
        Attendance.query.filter_by(student_id=s.id).delete()
        db.session.delete(s)
    Subject.query.filter_by(teacher_id=teacher_id).delete()
    db.session.delete(teacher)
    db.session.commit()
    flash(f'Teacher "{teacher.username}" and all their data deleted.', 'info')
    return redirect(url_for('teachers'))

@app.route('/teachers/<int:teacher_id>')
@login_required
def teacher_detail(teacher_id):
    teacher  = User.query.get_or_404(teacher_id)
    students = Student.query.filter_by(teacher_id=teacher_id).all()
    subjects = Subject.query.filter_by(teacher_id=teacher_id).all()
    student_data = []
    for s in students:
        pct = s.attendance_percentage()
        student_data.append({'student': s, 'pct': pct, 'at_risk': pct < 75})
    student_data.sort(key=lambda x: x['pct'])
    return render_template('teacher_detail.html', teacher=teacher,
                           student_data=student_data, subjects=subjects)

# ─── School-wide report ───────────────────────────────────────────────────────

@app.route('/report')
@login_required
def report():
    all_students = Student.query.all()
    student_labels = [s.name for s in all_students]
    student_pcts   = [s.attendance_percentage() for s in all_students]
    student_colors = ['#22c55e' if p >= 75 else '#ef4444' for p in student_pcts]
    all_records    = Attendance.query.all()
    total_all      = len(all_records)
    present_all    = sum(1 for r in all_records if r.status == 'present')
    absent_all     = total_all - present_all
    verified_students = [s for s in all_students if Attendance.query.filter_by(student_id=s.id).count() > 0]
    verified_pcts = [s.attendance_percentage() for s in verified_students]
    avg_pct        = round(sum(verified_pcts) / len(verified_pcts), 1) if verified_pcts else 0
    at_risk_count  = sum(1 for p in verified_pcts if p < 75)
    return render_template('report.html',
                           student_labels=student_labels,
                           student_pcts=student_pcts,
                           student_colors=student_colors,
                           present_all=present_all,
                           absent_all=absent_all,
                           total_all=total_all,
                           avg_pct=avg_pct,
                           at_risk_count=at_risk_count,
                           total_students=len(all_students))

@app.errorhandler(404)
def not_found(e):
    return render_template('404.html'), 404

# ─── Create first admin ───────────────────────────────────────────────────────

def create_admin(username, password):
    """Run this once to create the first admin account."""
    with app.app_context():
        db.create_all()
        if Admin.query.filter_by(username=username).first():
            print(f"Admin '{username}' already exists.")
            return
        db.session.add(Admin(username=username,
                             password=generate_password_hash(password)))
        db.session.commit()
        print(f"✓ Admin '{username}' created successfully.")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Create default admin if none exists
        if not Admin.query.first():
            db.session.add(Admin(username='admin',
                                 password=generate_password_hash('admin123')))
            db.session.commit()
            print("✓ Default admin created — username: admin | password: admin123")
            print("  Change this password after first login!")
        print("✓ Admin app → http://127.0.0.1:5002")
    app.run(debug=True, port=5002)
