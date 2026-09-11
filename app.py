import os
import sqlite3
import datetime
import math
import io
import csv
import smtplib
import threading
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import (
    Flask, render_template, request, redirect, url_for, flash, Response, jsonify
)

# -- Firebase Admin SDK -------------------------------------------------------
try:
    import firebase_admin
    from firebase_admin import credentials, firestore, auth as firebase_auth

    _SERVICE_ACCOUNT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'serviceAccountKey.json')
    if not firebase_admin._apps:
        if os.path.exists(_SERVICE_ACCOUNT):
            _cred = credentials.Certificate(_SERVICE_ACCOUNT)
            firebase_admin.initialize_app(_cred)
            _fs_db = firestore.client()
            print("[AURA Firebase] OK - Connected to Firebase (Firestore + Auth)")
        else:
            firebase_admin.initialize_app()
            _fs_db = None
            print("[AURA Firebase] WARNING - serviceAccountKey.json not found. Firestore disabled.")
    FIREBASE_ENABLED = True
except Exception as _fb_err:
    FIREBASE_ENABLED = False
    _fs_db = None
    print("[AURA Firebase] INFO - firebase-admin not active: " + str(_fb_err))
# -----------------------------------------------------------------------------


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, 'aura.db')

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=os.path.join(BASE_DIR, 'static')
)
app.secret_key = 'aura-super-secret-key-2026'

# ==============================================================================
# Database Initialization & Helpers
# ==============================================================================

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # 1. Students Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS students (
            student_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            semester TEXT NOT NULL,
            email TEXT NOT NULL
        )
    ''')

    # 2. Attendance Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students (student_id) ON DELETE CASCADE
        )
    ''')

    # 3. Marks Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS marks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            semester TEXT NOT NULL,
            subject TEXT NOT NULL,
            internal_marks REAL NOT NULL,
            external_marks REAL NOT NULL,
            total_marks REAL NOT NULL,
            grade TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students (student_id) ON DELETE CASCADE
        )
    ''')

    # 4. Settings Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    ''')

    default_settings = {
        'threshold': '75',
        'warning_email': 'enabled',
        'term_name': 'Autumn Semester 2026',
        'smtp_server': 'smtp.gmail.com',
        'smtp_port': '587',
        'smtp_email': '',
        'smtp_password': ''
    }
    for k, v in default_settings.items():
        cursor.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (k, v))

    conn.commit()

    # Seed if empty
    cursor.execute('SELECT COUNT(*) FROM students')
    if cursor.fetchone()[0] == 0:
        seed_data(conn)

    conn.close()

def get_setting(key, default=''):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM settings WHERE key = ?', (key,))
    row = cursor.fetchone()
    conn.close()
    return row['value'] if row else default

def set_setting(key, value):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', (key, str(value)))
    conn.commit()
    conn.close()

def send_low_attendance_email(student_email, student_name, student_id, percentage, classes_needed, threshold=75):
    smtp_server = get_setting('smtp_server', 'smtp.gmail.com')
    try:
        smtp_port = int(get_setting('smtp_port', '587'))
    except Exception:
        smtp_port = 587
    sender_email = get_setting('smtp_email', '').strip()
    sender_password = get_setting('smtp_password', '').strip().replace(' ', '')

    if not sender_email or not sender_password:
        msg = "SMTP sender email or App Password is not configured in Settings."
        print(f"[AURA EMAIL NOTICE] Cannot send email to {student_email}: {msg}")
        return False, msg

    if not student_email or '@' not in student_email:
        msg = f"Invalid recipient email: '{student_email}'"
        print(f"[AURA EMAIL NOTICE] {msg}")
        return False, msg

    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = f"🚨 URGENT: Low Attendance Alert for {student_name} ({percentage}%) - AURA"
        msg['From'] = f"AURA Academic Portal <{sender_email}>"
        msg['To'] = student_email

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #0b0f19; color: #f8fafc; margin: 0; padding: 20px; }}
                .card {{ max-width: 600px; margin: 0 auto; background: #111827; border: 1px solid rgba(255, 255, 255, 0.12); border-radius: 18px; overflow: hidden; box-shadow: 0 15px 35px rgba(0,0,0,0.6); }}
                .header {{ background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%); padding: 32px 24px; text-align: center; border-bottom: 2px solid #ef4444; }}
                .header h1 {{ margin: 0; color: #ffffff; font-size: 24px; letter-spacing: 1px; }}
                .badge {{ display: inline-block; background: rgba(239, 68, 68, 0.2); color: #f87171; border: 1px solid rgba(239, 68, 68, 0.4); padding: 6px 16px; border-radius: 9999px; font-weight: bold; font-size: 12.5px; margin-top: 10px; }}
                .body-content {{ padding: 28px 24px; color: #cbd5e1; font-size: 15px; line-height: 1.6; }}
                .warning-box {{ background: rgba(239, 68, 68, 0.1); border-left: 4px solid #ef4444; border-radius: 8px; padding: 14px 18px; margin: 18px 0; color: #fca5a5; }}
                .stats-table {{ width: 100%; margin: 20px 0; border-collapse: separate; border-spacing: 12px; }}
                .stat-card {{ background: #1e293b; padding: 16px; border-radius: 12px; text-align: center; border: 1px solid rgba(255,255,255,0.06); width: 50%; }}
                .stat-card h2 {{ margin: 0; font-size: 30px; color: #f87171; }}
                .stat-card p {{ margin: 4px 0 0; font-size: 12px; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.5px; }}
                .footer {{ background: #0f172a; padding: 18px; text-align: center; font-size: 12px; color: #64748b; border-top: 1px solid rgba(255,255,255,0.06); }}
            </style>
        </head>
        <body>
            <div class="card">
                <div class="header">
                    <h1>🏛️ AURA Institute of Technology</h1>
                    <div class="badge">⚠️ OFFICIAL ATTENDANCE WARNING NOTICE</div>
                </div>
                <div class="body-content">
                    <p>Dear <strong>{student_name}</strong> (Student ID: <strong style="color:#38bdf8;">{student_id}</strong>),</p>
                    
                    <div class="warning-box">
                        <strong>Policy Alert:</strong> Your registered attendance has dropped to <strong>{percentage}%</strong>, which is strictly below the mandatory university threshold of <strong>{threshold}%</strong>.
                    </div>

                    <table class="stats-table">
                        <tr>
                            <td class="stat-card">
                                <h2>{percentage}%</h2>
                                <p>Current Attendance</p>
                            </td>
                            <td class="stat-card">
                                <h2>+{classes_needed}</h2>
                                <p>Consecutive Classes Needed</p>
                            </td>
                        </tr>
                    </table>

                    <p>Maintaining at least <strong>{threshold}%</strong> attendance is compulsory to remain eligible for end-semester university examinations. You are required to attend the next consecutive <strong>{classes_needed}</strong> classes without absence to restore your academic standing.</p>
                    
                    <p>If you have medical or emergency circumstances, please submit documentation to the Office of Academic Affairs immediately.</p>
                    
                    <p style="margin-top: 24px;">Sincerely,<br><strong>Office of Academic Affairs & Attendance Registry</strong><br>AURA Automated System</p>
                </div>
                <div class="footer">
                    Automated notification from AURA Portal. Please do not reply directly to this automated email.
                </div>
            </div>
        </body>
        </html>
        """

        msg.attach(MIMEText(html_content, 'html'))

        server = smtplib.SMTP(smtp_server, smtp_port, timeout=12)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        print(f"[AURA EMAIL] Successfully sent low attendance alert to {student_email} ({student_name})")
        return True, f"Email delivered to {student_email}"
    except Exception as e:
        print(f"[AURA EMAIL ERROR] Failed delivering to {student_email}: {e}")
        return False, str(e)

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            status TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students (student_id) ON DELETE CASCADE
        )
    ''')

    # 3. Marks Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS marks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id TEXT NOT NULL,
            semester TEXT NOT NULL,
            subject TEXT NOT NULL,
            internal_marks REAL NOT NULL,
            external_marks REAL NOT NULL,
            total_marks REAL NOT NULL,
            grade TEXT NOT NULL,
            FOREIGN KEY (student_id) REFERENCES students (student_id) ON DELETE CASCADE
        )
    ''')

    conn.commit()

    # Seed if empty
    cursor.execute('SELECT COUNT(*) FROM students')
    if cursor.fetchone()[0] == 0:
        seed_data(conn)

    conn.close()

def seed_data(conn):
    cursor = conn.cursor()

    sample_students = [
        ('AURA101', 'Aarav Sharma', 'Computer Science', '5', 'aarav.sharma@aura.edu'),
        ('AURA102', 'Diya Patel', 'Information Technology', '5', 'diya.patel@aura.edu'),
        ('AURA103', 'Rohan Mehta', 'Computer Science', '5', 'rohan.mehta@aura.edu'),
        ('AURA104', 'Ananya Iyer', 'Electronics', '5', 'ananya.iyer@aura.edu'),
        ('AURA105', 'Vikram Singh', 'Mechanical', '5', 'vikram.singh@aura.edu'),
        ('AURA106', 'Pooja Verma', 'Computer Science', '5', 'pooja.verma@aura.edu'),
        ('AURA107', 'Siddharth Rao', 'Information Technology', '5', 'siddharth.rao@aura.edu'),
        ('AURA108', 'Sneha Kulkarni', 'Electronics', '5', 'sneha.kulkarni@aura.edu'),
    ]

    cursor.executemany(
        'INSERT OR IGNORE INTO students (student_id, name, department, semester, email) VALUES (?, ?, ?, ?, ?)',
        sample_students
    )

    # Attendance generator (recent 10 days)
    today = datetime.date.today()
    attendance_patterns = {
        'AURA101': ['Present', 'Present', 'Present', 'Present', 'Present', 'Present', 'Present', 'Present', 'Present', 'Present'], # 100%
        'AURA102': ['Present', 'Present', 'Present', 'Present', 'Present', 'Present', 'Present', 'Absent', 'Present', 'Present'],  # 90%
        'AURA103': ['Absent', 'Present', 'Absent', 'Present', 'Absent', 'Present', 'Absent', 'Present', 'Absent', 'Absent'],      # 40% (Warning)
        'AURA104': ['Present', 'Present', 'Present', 'Present', 'Present', 'Present', 'Absent', 'Present', 'Present', 'Present'],  # 90%
        'AURA105': ['Absent', 'Absent', 'Present', 'Present', 'Absent', 'Present', 'Absent', 'Present', 'Absent', 'Present'],      # 50% (Warning)
        'AURA106': ['Present', 'Present', 'Present', 'Present', 'Present', 'Present', 'Present', 'Present', 'Present', 'Present'], # 100%
        'AURA107': ['Present', 'Present', 'Present', 'Absent', 'Present', 'Present', 'Present', 'Present', 'Present', 'Present'],  # 90%
        'AURA108': ['Absent', 'Present', 'Present', 'Absent', 'Present', 'Absent', 'Present', 'Absent', 'Present', 'Absent'],      # 50% (Warning)
    }

    attendance_records = []
    for sid, statuses in attendance_patterns.items():
        for i, status in enumerate(statuses):
            d = today - datetime.timedelta(days=(10 - i))
            date_str = d.strftime('%Y-%m-%d')
            time_str = f"09:{15 + (i % 15):02d} AM"
            attendance_records.append((sid, date_str, time_str, status))

    cursor.executemany(
        'INSERT INTO attendance (student_id, date, time, status) VALUES (?, ?, ?, ?)',
        attendance_records
    )

    # Sample Marks
    sample_marks = [
        ('AURA101', '5', 'Data Structures & Algorithms', 28.0, 65.0, 93.0, 'O'),
        ('AURA101', '5', 'Database Management Systems', 27.0, 61.0, 88.0, 'A+'),
        ('AURA102', '5', 'Cloud Computing Architecture', 26.0, 58.0, 84.0, 'A'),
        ('AURA102', '5', 'Software Engineering', 25.0, 62.0, 87.0, 'A+'),
        ('AURA103', '5', 'Operating Systems', 18.0, 36.0, 54.0, 'D'),
        ('AURA103', '5', 'Computer Networks', 15.0, 32.0, 47.0, 'F'),
        ('AURA104', '5', 'Microprocessors & Microcontrollers', 29.0, 66.0, 95.0, 'O'),
        ('AURA104', '5', 'Signal Processing', 26.0, 59.0, 85.0, 'A+'),
        ('AURA105', '5', 'Thermodynamics & Heat Transfer', 19.0, 42.0, 61.0, 'C'),
        ('AURA106', '5', 'Artificial Intelligence & ML', 30.0, 67.0, 97.0, 'O'),
        ('AURA107', '5', 'Full Stack Web Engineering', 28.0, 64.0, 92.0, 'O'),
        ('AURA108', '5', 'Digital Communication Systems', 20.0, 45.0, 65.0, 'B'),
    ]

    cursor.executemany(
        'INSERT INTO marks (student_id, semester, subject, internal_marks, external_marks, total_marks, grade) VALUES (?, ?, ?, ?, ?, ?, ?)',
        sample_marks
    )

    conn.commit()

# ==============================================================================
# Helper Computations
# ==============================================================================

def calculate_grade(total):
    if total >= 90:
        return 'O'
    elif total >= 80:
        return 'A+'
    elif total >= 70:
        return 'A'
    elif total >= 60:
        return 'B'
    elif total >= 50:
        return 'C'
    elif total >= 40:
        return 'D'
    else:
        return 'F'

def get_student_attendance_stats(conn, student_id):
    cursor = conn.cursor()
    cursor.execute('SELECT status FROM attendance WHERE student_id = ?', (student_id,))
    records = cursor.fetchall()
    total = len(records)
    if total == 0:
        return {
            'total': 0,
            'present': 0,
            'absent': 0,
            'percentage': 100.0,
            'status': 'Good',
            'classes_needed': 0
        }

    present = sum(1 for r in records if r['status'] == 'Present')
    absent = total - present
    pct = round((present / total) * 100, 1)

    if pct >= 85:
        status = 'Good'
    elif pct >= 75:
        status = 'Normal'
    else:
        status = 'Warning'

    # Needed classes to reach 75%: (present + X) / (total + X) >= 0.75 => X >= 3*total - 4*present
    if pct < 75.0:
        x = 3 * total - 4 * present
        classes_needed = max(0, int(math.ceil(x)))
    else:
        classes_needed = 0

    return {
        'total': total,
        'present': present,
        'absent': absent,
        'percentage': pct,
        'status': status,
        'classes_needed': classes_needed
    }

# ==============================================================================
# Routes & Controllers
# ==============================================================================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/dashboard')
def dashboard():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM students')
    total_students = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM attendance')
    total_attendance = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM attendance WHERE status = 'Present'")
    total_present = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM attendance WHERE status = 'Absent'")
    total_absent = cursor.fetchone()[0]

    if total_attendance > 0:
        attendance_percentage = round((total_present / total_attendance) * 100, 1)
    else:
        attendance_percentage = 0.0

    # Count below 75%
    cursor.execute('SELECT student_id FROM students')
    student_ids = [row['student_id'] for row in cursor.fetchall()]
    below_75 = 0
    for sid in student_ids:
        stats = get_student_attendance_stats(conn, sid)
        if stats['percentage'] < 75.0 and stats['total'] > 0:
            below_75 += 1

    conn.close()

    return render_template(
        'dashboard.html',
        total_students=total_students,
        total_attendance=total_attendance,
        total_present=total_present,
        total_absent=total_absent,
        attendance_percentage=attendance_percentage,
        below_75=below_75
    )

@app.route('/students')
def students():
    search = request.args.get('search', '').strip()
    conn = get_db()
    cursor = conn.cursor()

    if search:
        query = '''
            SELECT * FROM students 
            WHERE student_id LIKE ? OR name LIKE ? OR department LIKE ?
            ORDER BY student_id ASC
        '''
        cursor.execute(query, (f'%{search}%', f'%{search}%', f'%{search}%'))
    else:
        cursor.execute('SELECT * FROM students ORDER BY student_id ASC')

    raw_students = cursor.fetchall()
    student_list = []

    for s in raw_students:
        stats = get_student_attendance_stats(conn, s['student_id'])
        student_list.append({
            'student_id': s['student_id'],
            'name': s['name'],
            'department': s['department'],
            'semester': s['semester'],
            'email': s['email'],
            'percentage': stats['percentage'],
            'status': stats['status'],
            'classes_needed': stats['classes_needed']
        })

    conn.close()
    return render_template('students.html', students=student_list, search_query=search)

@app.route('/add')
def add_student_page():
    return render_template('add_student.html')

@app.route('/submit', methods=['POST'])
def submit_student():
    student_id = request.form.get('student_id', '').strip()
    name = request.form.get('name', '').strip()
    department = request.form.get('department', '').strip()
    semester = request.form.get('semester', '').strip()
    email = request.form.get('email', '').strip()

    if not student_id or not name:
        flash('Student ID and Name are required.', 'error')
        return redirect(url_for('add_student_page'))

    conn = get_db()
    cursor = conn.cursor()

    try:
        cursor.execute(
            'INSERT INTO students (student_id, name, department, semester, email) VALUES (?, ?, ?, ?, ?)',
            (student_id, name, department, semester, email)
        )
        conn.commit()
        flash(f'Student {name} ({student_id}) successfully registered!', 'success')
    except sqlite3.IntegrityError:
        flash(f'Student ID "{student_id}" is already registered.', 'error')
    finally:
        conn.close()

    return redirect(url_for('students'))

@app.route('/edit/<student_id>', methods=['GET', 'POST'])
def edit_student(student_id):
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        department = request.form.get('department', '').strip()
        semester = request.form.get('semester', '').strip()
        email = request.form.get('email', '').strip()

        cursor.execute('''
            UPDATE students 
            SET name = ?, department = ?, semester = ?, email = ?
            WHERE student_id = ?
        ''', (name, department, semester, email, student_id))
        conn.commit()
        conn.close()
        flash(f'Student details for {student_id} updated successfully!', 'success')
        return redirect(url_for('students'))

    cursor.execute('SELECT * FROM students WHERE student_id = ?', (student_id,))
    student = cursor.fetchone()
    conn.close()

    if not student:
        flash(f'Student {student_id} not found.', 'error')
        return redirect(url_for('students'))

    return render_template('edit.html', student=student)

@app.route('/update/<student_id>', methods=['POST'])
def update_student(student_id):
    return edit_student(student_id)

@app.route('/delete/<student_id>')
def delete_student(student_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM students WHERE student_id = ?', (student_id,))
    cursor.execute('DELETE FROM attendance WHERE student_id = ?', (student_id,))
    cursor.execute('DELETE FROM marks WHERE student_id = ?', (student_id,))
    conn.commit()
    conn.close()

    flash(f'Student {student_id} and all related logs were deleted.', 'success')
    return redirect(url_for('students'))

@app.route('/student/<student_id>')
def student_details(student_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM students WHERE student_id = ?', (student_id,))
    student_row = cursor.fetchone()

    if not student_row:
        conn.close()
        flash(f'Student {student_id} not found.', 'error')
        return redirect(url_for('students'))

    stats = get_student_attendance_stats(conn, student_id)

    # Attendance logs
    cursor.execute('SELECT * FROM attendance WHERE student_id = ? ORDER BY date DESC, time DESC', (student_id,))
    attendance_records = cursor.fetchall()

    # Marks records
    cursor.execute('SELECT * FROM marks WHERE student_id = ? ORDER BY semester, subject', (student_id,))
    marks_records = cursor.fetchall()

    # Average marks
    if marks_records:
        avg_marks = round(sum(m['total_marks'] for m in marks_records) / len(marks_records), 1)
    else:
        avg_marks = 0.0

    student_data = {
        'student_id': student_row['student_id'],
        'name': student_row['name'],
        'department': student_row['department'],
        'semester': student_row['semester'],
        'email': student_row['email'],
        'percentage': stats['percentage'],
        'avg_marks': avg_marks
    }

    conn.close()
    return render_template(
        'student_details.html',
        student=student_data,
        attendance_records=attendance_records,
        marks_records=marks_records
    )

# ==============================================================================
# Attendance Routes
# ==============================================================================

@app.route('/take_attendance')
def take_attendance():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM students ORDER BY student_id ASC')
    raw_students = cursor.fetchall()

    students_with_stats = []
    for s in raw_students:
        stats = get_student_attendance_stats(conn, s['student_id'])
        students_with_stats.append((
            s['student_id'],
            s['name'],
            s['department'],
            s['semester'],
            s['email'],
            stats['percentage']
        ))

    conn.close()
    current_date = datetime.date.today().strftime('%B %d, %Y')
    return render_template('take_attendance.html', students=students_with_stats, current_date=current_date)

@app.route('/save_attendance/<student_id>/<status>')
def save_attendance(student_id, status):
    status_clean = 'Present' if status.lower() == 'present' else 'Absent'
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    time_str = datetime.datetime.now().strftime('%I:%M %p')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        'INSERT INTO attendance (student_id, date, time, status) VALUES (?, ?, ?, ?)',
        (student_id, today_str, time_str, status_clean)
    )
    conn.commit()

    # Automatic Email Check
    auto_email = get_setting('warning_email', 'enabled')
    try:
        threshold_val = float(get_setting('threshold', '75'))
    except Exception:
        threshold_val = 75.0

    stats = get_student_attendance_stats(conn, student_id)
    cursor.execute('SELECT name, email FROM students WHERE student_id = ?', (student_id,))
    student = cursor.fetchone()
    conn.close()

    if auto_email == 'enabled' and student and stats['percentage'] < threshold_val and stats['total'] > 0:
        # Send email alert in background thread
        threading.Thread(
            target=send_low_attendance_email,
            args=(student['email'], student['name'], student_id, stats['percentage'], stats['classes_needed'], threshold_val)
        ).start()

    flash(f'Marked {student_id} as {status_clean} for today ({today_str}).', 'success')
    return redirect(request.referrer or url_for('take_attendance'))

@app.route('/mark_all_attendance/<status>')
def mark_all_attendance(status):
    status_clean = 'Present' if status.lower() == 'present' else 'Absent'
    today_str = datetime.date.today().strftime('%Y-%m-%d')
    time_str = datetime.datetime.now().strftime('%I:%M %p')

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT student_id, name, email FROM students')
    students = cursor.fetchall()

    for s in students:
        cursor.execute(
            'INSERT INTO attendance (student_id, date, time, status) VALUES (?, ?, ?, ?)',
            (s['student_id'], today_str, time_str, status_clean)
        )
    conn.commit()

    auto_email = get_setting('warning_email', 'enabled')
    try:
        threshold_val = float(get_setting('threshold', '75'))
    except Exception:
        threshold_val = 75.0

    if auto_email == 'enabled' and status_clean == 'Absent':
        for s in students:
            stats = get_student_attendance_stats(conn, s['student_id'])
            if stats['percentage'] < threshold_val and stats['total'] > 0:
                threading.Thread(
                    target=send_low_attendance_email,
                    args=(s['email'], s['name'], s['student_id'], stats['percentage'], stats['classes_needed'], threshold_val)
                ).start()

    conn.close()

    flash(f'All {len(students)} students marked as {status_clean} for today!', 'success')
    return redirect(url_for('take_attendance'))

@app.route('/mark_attendance/<student_id>', methods=['GET', 'POST'])
def mark_attendance(student_id):
    if request.method == 'POST':
        status = request.form.get('status', 'Present')
        return redirect(url_for('save_attendance', student_id=student_id, status=status))

    return render_template('mark_attendance.html', student_id=student_id)

@app.route('/attendance_list')
def attendance_list():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT a.id, a.student_id, a.date, a.time, a.status, s.name 
        FROM attendance a
        LEFT JOIN students s ON a.student_id = s.student_id
        ORDER BY a.id DESC
    ''')
    records = cursor.fetchall()
    conn.close()
    return render_template('attendance.html', attendance=records, student_filter=None)

@app.route('/attendance/<student_id>')
def student_attendance(student_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM students WHERE student_id = ?', (student_id,))
    student = cursor.fetchone()

    cursor.execute('''
        SELECT a.id, a.student_id, a.date, a.time, a.status, s.name 
        FROM attendance a
        LEFT JOIN students s ON a.student_id = s.student_id
        WHERE a.student_id = ?
        ORDER BY a.date DESC, a.id DESC
    ''', (student_id,))
    records = cursor.fetchall()
    conn.close()
    return render_template('attendance.html', attendance=records, student_filter=student)

@app.route('/delete_attendance/<int:rec_id>')
def delete_attendance(rec_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM attendance WHERE id = ?', (rec_id,))
    conn.commit()
    conn.close()
    flash('Attendance log deleted.', 'success')
    return redirect(request.referrer or url_for('attendance_list'))

# ==============================================================================
# Marks & Performance Routes
# ==============================================================================

@app.route('/add_marks', methods=['GET', 'POST'])
def add_marks():
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        student_id = request.form.get('student_id', '').strip()
        semester = request.form.get('semester', '').strip()
        subject = request.form.get('subject', '').strip()
        internal_marks = float(request.form.get('internal_marks', 0))
        external_marks = float(request.form.get('external_marks', 0))
        total_marks = internal_marks + external_marks
        grade = calculate_grade(total_marks)

        cursor.execute('''
            INSERT INTO marks (student_id, semester, subject, internal_marks, external_marks, total_marks, grade)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (student_id, semester, subject, internal_marks, external_marks, total_marks, grade))
        conn.commit()
        conn.close()

        flash(f'Marks recorded for {student_id} in {subject} (Grade: {grade})!', 'success')
        return redirect(url_for('view_marks'))

    cursor.execute('SELECT student_id, name, department FROM students ORDER BY student_id')
    students = cursor.fetchall()
    conn.close()
    return render_template('add_marks.html', students=students)

@app.route('/marks')
def view_marks():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT m.id, m.student_id, m.semester, m.subject, m.internal_marks, m.external_marks, m.total_marks, m.grade, s.name
        FROM marks m
        LEFT JOIN students s ON m.student_id = s.student_id
        ORDER BY m.id DESC
    ''')
    marks_list = cursor.fetchall()
    conn.close()
    return render_template('marks.html', marks=marks_list)

@app.route('/edit_marks/<int:mark_id>', methods=['GET', 'POST'])
def edit_marks(mark_id):
    conn = get_db()
    cursor = conn.cursor()

    if request.method == 'POST':
        semester = request.form.get('semester', '').strip()
        subject = request.form.get('subject', '').strip()
        internal_marks = float(request.form.get('internal_marks', 0))
        external_marks = float(request.form.get('external_marks', 0))
        total_marks = internal_marks + external_marks
        grade = calculate_grade(total_marks)

        cursor.execute('''
            UPDATE marks 
            SET semester = ?, subject = ?, internal_marks = ?, external_marks = ?, total_marks = ?, grade = ?
            WHERE id = ?
        ''', (semester, subject, internal_marks, external_marks, total_marks, grade, mark_id))
        conn.commit()
        conn.close()
        flash('Subject marks updated successfully!', 'success')
        return redirect(url_for('view_marks'))

    cursor.execute('SELECT * FROM marks WHERE id = ?', (mark_id,))
    mark = cursor.fetchone()
    conn.close()

    if not mark:
        flash('Marks entry not found.', 'error')
        return redirect(url_for('view_marks'))

    return render_template('edit_marks.html', mark=mark)

@app.route('/delete_marks/<int:mark_id>')
def delete_marks(mark_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM marks WHERE id = ?', (mark_id,))
    conn.commit()
    conn.close()
    flash('Marks entry deleted.', 'success')
    return redirect(url_for('view_marks'))

@app.route('/performance')
def performance():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT * FROM students ORDER BY student_id ASC')
    students = cursor.fetchall()
    perf_list = []

    for s in students:
        stats = get_student_attendance_stats(conn, s['student_id'])
        cursor.execute('SELECT total_marks FROM marks WHERE student_id = ?', (s['student_id'],))
        marks = [m['total_marks'] for m in cursor.fetchall()]

        if marks:
            avg_marks = round(sum(marks) / len(marks), 1)
        else:
            avg_marks = 0.0

        overall_grade = calculate_grade(avg_marks)

        # Performance rating
        if avg_marks >= 80 and stats['percentage'] >= 75:
            rating = 'Excellent'
        elif avg_marks >= 60 and stats['percentage'] >= 70:
            rating = 'Good'
        else:
            rating = 'Needs Improvement'

        perf_list.append({
            'student_id': s['student_id'],
            'name': s['name'],
            'attendance': stats['percentage'],
            'average': avg_marks,
            'grade': overall_grade,
            'performance': rating
        })

    conn.close()
    return render_template('performance.html', performance=perf_list)

@app.route('/notifications')
def notifications():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM students ORDER BY student_id ASC')
    students = cursor.fetchall()

    warning_list = []
    for s in students:
        stats = get_student_attendance_stats(conn, s['student_id'])
        if stats['percentage'] < 75.0 and stats['total'] > 0:
            warning_list.append({
                'student_id': s['student_id'],
                'name': s['name'],
                'department': s['department'],
                'semester': s['semester'],
                'email': s['email'],
                'attendance': stats['percentage'],
                'classes_needed': stats['classes_needed']
            })

    conn.close()
    return render_template('notifications.html', notifications=warning_list)

@app.route('/send_warning_emails', methods=['POST'])
def send_warning_emails():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM students')
    students = cursor.fetchall()

    try:
        threshold_val = float(get_setting('threshold', '75'))
    except Exception:
        threshold_val = 75.0

    sent_count = 0
    errors = []

    for s in students:
        stats = get_student_attendance_stats(conn, s['student_id'])
        if stats['percentage'] < threshold_val and stats['total'] > 0:
            success, msg = send_low_attendance_email(
                student_email=s['email'],
                student_name=s['name'],
                student_id=s['student_id'],
                percentage=stats['percentage'],
                classes_needed=stats['classes_needed'],
                threshold=threshold_val
            )
            if success:
                sent_count += 1
            else:
                errors.append(f"{s['name']} ({s['email']}): {msg}")

    conn.close()

    if sent_count > 0:
        flash(f'✅ Automated Email Dispatch: Successfully delivered {sent_count} low attendance warning email(s) directly to student inboxes!', 'success')
    elif errors:
        flash(f'⚠️ Could not send email(s). Please configure your SMTP Email & Gmail App Password in Settings. Error: {errors[0]}', 'error')
    else:
        flash('All registered students currently meet or exceed the attendance threshold!', 'info')

    return redirect(url_for('notifications'))

# ==============================================================================
# Reports & Profile Routes
# ==============================================================================

@app.route('/reports')
def reports():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute('SELECT COUNT(*) FROM students')
    total_students = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM attendance')
    total_attendance = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM attendance WHERE status = 'Present'")
    total_present = cursor.fetchone()[0]

    cursor.execute('SELECT COUNT(*) FROM marks')
    total_marks = cursor.fetchone()[0]

    if total_attendance > 0:
        attendance_percentage = round((total_present / total_attendance) * 100, 1)
    else:
        attendance_percentage = 0.0

    # Department Statistics
    cursor.execute('SELECT DISTINCT department FROM students')
    departments = [r['department'] for r in cursor.fetchall()]

    dept_stats = {}
    for d in departments:
        cursor.execute('SELECT student_id FROM students WHERE department = ?', (d,))
        sids = [r['student_id'] for r in cursor.fetchall()]
        dept_student_count = len(sids)

        dept_attendances = []
        at_risk = 0
        for sid in sids:
            st = get_student_attendance_stats(conn, sid)
            if st['total'] > 0:
                dept_attendances.append(st['percentage'])
                if st['percentage'] < 75.0:
                    at_risk += 1

        avg_att = round(sum(dept_attendances) / len(dept_attendances), 1) if dept_attendances else 0.0

        dept_stats[d] = {
            'student_count': dept_student_count,
            'avg_attendance': avg_att,
            'at_risk': at_risk
        }

    dept_labels = list(dept_stats.keys())
    dept_counts = [data['student_count'] for data in dept_stats.values()]

    # Grade distribution
    cursor.execute('SELECT grade, COUNT(*) as cnt FROM marks GROUP BY grade')
    grade_rows = cursor.fetchall()
    grade_map = {'O': 0, 'A+': 0, 'A': 0, 'B': 0, 'C': 0, 'D': 0, 'F': 0}
    for r in grade_rows:
        if r['grade'] in grade_map:
            grade_map[r['grade']] = r['cnt']

    grade_labels = list(grade_map.keys())
    grade_counts = list(grade_map.values())

    conn.close()
    return render_template(
        'reports.html',
        total_students=total_students,
        total_attendance=total_attendance,
        attendance_percentage=attendance_percentage,
        total_marks=total_marks,
        dept_stats=dept_stats,
        dept_labels=dept_labels,
        dept_counts=dept_counts,
        grade_labels=grade_labels,
        grade_counts=grade_counts
    )

@app.route('/profile')
def profile():
    return render_template('profile.html')

@app.route('/settings')
def settings():
    settings_data = {
        'threshold': get_setting('threshold', '75'),
        'warning_email': get_setting('warning_email', 'enabled'),
        'term_name': get_setting('term_name', 'Autumn Semester 2026'),
        'smtp_server': get_setting('smtp_server', 'smtp.gmail.com'),
        'smtp_port': get_setting('smtp_port', '587'),
        'smtp_email': get_setting('smtp_email', ''),
        'smtp_password': get_setting('smtp_password', '')
    }
    return render_template('settings.html', settings=settings_data)

@app.route('/save_settings', methods=['POST'])
def save_settings():
    threshold = request.form.get('threshold', '75').strip()
    warning_email = request.form.get('warning_email', 'enabled').strip()
    term_name = request.form.get('term_name', 'Autumn Semester 2026').strip()
    smtp_server = request.form.get('smtp_server', 'smtp.gmail.com').strip()
    smtp_port = request.form.get('smtp_port', '587').strip()
    smtp_email = request.form.get('smtp_email', '').strip()
    smtp_password = request.form.get('smtp_password', '').strip()

    set_setting('threshold', threshold)
    set_setting('warning_email', warning_email)
    set_setting('term_name', term_name)
    set_setting('smtp_server', smtp_server)
    set_setting('smtp_port', smtp_port)
    set_setting('smtp_email', smtp_email)
    set_setting('smtp_password', smtp_password)

    flash('✅ System preferences and Email / SMTP configuration saved successfully!', 'success')
    return redirect(url_for('settings'))

@app.route('/send_test_email', methods=['POST'])
def send_test_email():
    target_email = request.form.get('test_email', '').strip()
    if not target_email or '@' not in target_email:
        flash('Please enter a valid personal email address to send the test alert.', 'error')
        return redirect(url_for('settings'))

    try:
        threshold_val = float(get_setting('threshold', '75'))
    except Exception:
        threshold_val = 75.0

    success, msg = send_low_attendance_email(
        student_email=target_email,
        student_name="Test Student Notification",
        student_id="AURA-TEST-01",
        percentage=68.5,
        classes_needed=4,
        threshold=threshold_val
    )

    if success:
        flash(f'✅ Test Low Attendance Email delivered successfully to {target_email}! Check your inbox.', 'success')
    else:
        flash(f'❌ Email delivery failed: {msg}. Please verify your Gmail address and 16-character App Password.', 'error')

    return redirect(url_for('settings'))

@app.route('/seed_sample_data')
def seed_sample_data():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM marks')
    cursor.execute('DELETE FROM attendance')
    cursor.execute('DELETE FROM students')
    conn.commit()
    seed_data(conn)
    conn.close()

    flash('Realistic sample student records, attendance logs, and marks populated successfully!', 'success')
    return redirect(url_for('dashboard'))

# ==============================================================================
# CSV Exports
# ==============================================================================

@app.route('/export/students_csv')
def export_students_csv():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM students ORDER BY student_id ASC')
    students = cursor.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Student ID', 'Full Name', 'Department', 'Semester', 'Email', 'Attendance %', 'Status'])

    for s in students:
        stats = get_student_attendance_stats(conn, s['student_id'])
        writer.writerow([
            s['student_id'],
            s['name'],
            s['department'],
            s['semester'],
            s['email'],
            f"{stats['percentage']}%",
            stats['status']
        ])

    conn.close()
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=aura_students_report.csv"}
    )

@app.route('/export/attendance_csv')
def export_attendance_csv():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT a.id, a.student_id, s.name, a.date, a.time, a.status
        FROM attendance a
        LEFT JOIN students s ON a.student_id = s.student_id
        ORDER BY a.id DESC
    ''')
    records = cursor.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Record ID', 'Student ID', 'Student Name', 'Date', 'Time', 'Status'])

    for r in records:
        writer.writerow([r['id'], r['student_id'], r['name'] or '', r['date'], r['time'], r['status']])

    conn.close()
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=aura_attendance_logs.csv"}
    )

@app.route('/export/marks_csv')
def export_marks_csv():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT m.id, m.student_id, s.name, m.semester, m.subject, m.internal_marks, m.external_marks, m.total_marks, m.grade
        FROM marks m
        LEFT JOIN students s ON m.student_id = s.student_id
        ORDER BY m.id DESC
    ''')
    records = cursor.fetchall()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Student ID', 'Student Name', 'Semester', 'Subject', 'Internal', 'External', 'Total', 'Grade'])

    for r in records:
        writer.writerow([
            r['id'], r['student_id'], r['name'] or '', r['semester'], r['subject'],
            r['internal_marks'], r['external_marks'], r['total_marks'], r['grade']
        ])

    conn.close()
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": "attachment; filename=aura_marks_report.csv"}
    )

# ==============================================================================
# JSON REST APIs for Frontend Integration & Email Dispatch
# ==============================================================================

@app.after_request
def add_cors_headers(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type,Authorization'
    response.headers['Access-Control-Allow-Methods'] = 'GET,POST,OPTIONS'
    return response

@app.route('/api/smtp_settings', methods=['GET', 'POST', 'OPTIONS'])
def api_smtp_settings():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'})
    if request.method == 'POST':
        data = request.json or request.form
        threshold = str(data.get('threshold', '75')).strip()
        term_name = str(data.get('term_name', 'Autumn Semester 2026')).strip()
        smtp_email = str(data.get('smtp_email', '')).strip()
        smtp_password = str(data.get('smtp_password', '')).strip().replace(' ', '')
        
        set_setting('threshold', threshold)
        set_setting('term_name', term_name)
        if smtp_email:
            set_setting('smtp_email', smtp_email)
        if smtp_password:
            set_setting('smtp_password', smtp_password)
        return jsonify({'success': True, 'message': 'SMTP configuration saved successfully.'})
    
    # GET
    return jsonify({
        'threshold': get_setting('threshold', '75'),
        'term_name': get_setting('term_name', 'Autumn Semester 2026'),
        'smtp_email': get_setting('smtp_email', ''),
        'has_password': bool(get_setting('smtp_password', ''))
    })

@app.route('/api/send_warning_emails', methods=['POST', 'OPTIONS'])
def api_send_warning_emails():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'})
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM students')
    students = cursor.fetchall()

    try:
        threshold_val = float(get_setting('threshold', '75'))
    except Exception:
        threshold_val = 75.0

    sender_email = get_setting('smtp_email', '').strip()
    sender_password = get_setting('smtp_password', '').strip()

    if not sender_email or not sender_password:
        conn.close()
        return jsonify({
            'success': False,
            'message': 'Gmail SMTP is not configured. Please open Settings tab and enter your Gmail & 16-character App Password.'
        }), 400

    sent_list = []
    error_list = []

    for s in students:
        stats = get_student_attendance_stats(conn, s['student_id'])
        if stats['percentage'] < threshold_val and stats['total'] > 0:
            success, msg = send_low_attendance_email(
                student_email=s['email'],
                student_name=s['name'],
                student_id=s['student_id'],
                percentage=stats['percentage'],
                classes_needed=stats['classes_needed'],
                threshold=threshold_val
            )
            if success:
                sent_list.append(f"{s['name']} ({s['email']})")
            else:
                error_list.append(f"{s['name']} ({s['email']}): {msg}")

    conn.close()

    if sent_list:
        return jsonify({
            'success': True,
            'count': len(sent_list),
            'sent_to': sent_list,
            'errors': error_list,
            'message': f"Delivered {len(sent_list)} warning email(s) to student inboxes: {', '.join(sent_list)}"
        })
    elif error_list:
        return jsonify({
            'success': False,
            'errors': error_list,
            'message': f"Email delivery failed: {error_list[0]}"
        }), 500
    else:
        return jsonify({
            'success': True,
            'count': 0,
            'message': 'All students currently meet or exceed the minimum attendance threshold!'
        })

@app.route('/api/send_test_email', methods=['POST', 'OPTIONS'])
def api_send_test_email():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'})
    
    data = request.json or request.form
    target_email = (data.get('email') or data.get('test_email') or '').strip()
    
    if not target_email or '@' not in target_email:
        return jsonify({'success': False, 'message': 'Please enter a valid email address.'}), 400

    try:
        threshold_val = float(get_setting('threshold', '75'))
    except Exception:
        threshold_val = 75.0

    success, msg = send_low_attendance_email(
        student_email=target_email,
        student_name="Student",
        student_id="AURA-TEST-01",
        percentage=68.5,
        classes_needed=4,
        threshold=threshold_val
    )

    if success:
        return jsonify({'success': True, 'message': f"Test Warning Notice delivered successfully to {target_email}! Check your inbox (and spam folder)."})
    else:
        return jsonify({'success': False, 'message': f"Delivery failed: {msg}"}), 500

# ==============================================================================
# Main Entry Point
# ==============================================================================

if __name__ == '__main__':
    init_db()
    print("AURA server starting on http://127.0.0.1:5000")
    app.run(host='127.0.0.1', port=5000, debug=True)

