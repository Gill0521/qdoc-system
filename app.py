import os
import re
import secrets
import random
import smtplib
from email.message import EmailMessage
from email.utils import formataddr
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import quote_plus

import bcrypt
import mysql.connector
from dotenv import load_dotenv
from flask import Flask, flash, jsonify, make_response, redirect, render_template, request, session, url_for, send_from_directory
from werkzeug.utils import secure_filename

from database import get_db_connection

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env", override=True)

app = Flask(__name__, static_folder=None)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "qdoc-change-this-secret-key")
app.config["UPLOAD_FOLDER"] = os.getenv("UPLOAD_FOLDER", "uploads")
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024
(BASE_DIR / app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
(BASE_DIR / "assets" / "uploads" / "requirements").mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf"}
REQUEST_STATUSES = ["Pending", "Approved", "Processing", "Ready for Pickup", "Completed", "Rejected"]
PAYMENT_STATUSES = ["Paid", "Unpaid"]
PENDING_REGISTRATIONS = {}


# ---------------------------------------------------------------------
# Gmail OTP helpers
# ---------------------------------------------------------------------
def generate_otp():
    return str(random.randint(100000, 999999))


def otp_expiry_time():
    minutes = int(os.getenv("OTP_EXPIRY_MINUTES", "5"))
    return datetime.now() + timedelta(minutes=minutes)


def mask_email(email):
    if not email or "@" not in email:
        return email or ""
    name, domain = email.split("@", 1)
    visible = name[:2] if len(name) >= 2 else name[:1]
    return f"{visible}***@{domain}"


def send_gmail_otp(to_email, otp_code, purpose="Q:DOC Verification Code"):
    mail_server = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    mail_port = int(os.getenv("MAIL_PORT", "587"))
    mail_username = os.getenv("MAIL_USERNAME", "")
    mail_password = os.getenv("MAIL_PASSWORD", "").replace(" ", "")
    sender_email = os.getenv("MAIL_DEFAULT_SENDER", mail_username)
    sender_name = os.getenv("MAIL_SENDER_NAME", "Q-DOC System")
    expiry_minutes = os.getenv("OTP_EXPIRY_MINUTES", "5")

    if not mail_username or not mail_password or mail_username.startswith('your_'):
        raise ValueError("Gmail SMTP is not configured. Please check MAIL_USERNAME and MAIL_PASSWORD in .env.")

    logo_path = BASE_DIR / "assets" / "images" / "Q-DOC Logo.png"
    logo_cid = "qdoc_logo"

    msg = EmailMessage()
    msg["Subject"] = purpose
    msg["From"] = formataddr((sender_name, sender_email))
    msg["To"] = to_email

    plain_text = f"""Hello,

Your Q-DOC verification code is:

{otp_code}

This code is valid for {expiry_minutes} minutes.

Do not share this code.

Thank you,
Q-DOC System
"""

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="UTF-8"><title>{purpose}</title></head>
    <body style="margin:0; padding:0; background-color:#f4f6f8; font-family:Arial, Helvetica, sans-serif;">
        <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#f4f6f8; padding:30px 0;">
            <tr><td align="center">
                <table width="650" cellpadding="0" cellspacing="0" border="0" style="background:#ffffff; border:1px solid #e5e7eb; border-radius:10px; overflow:hidden;">
                    <tr><td align="center" style="padding:35px 20px 10px 20px;">
                        <img src="cid:{logo_cid}" alt="Q-DOC Logo" style="max-width:180px; height:auto; display:block;">
                    </td></tr>
                    <tr><td align="center" style="padding:20px 40px 10px 40px;">
                        <p style="margin:0; font-size:18px; color:#1f2937;">Your 6-digit verification code is:</p>
                    </td></tr>
                    <tr><td align="center" style="padding:18px 20px 10px 20px;">
                        <div style="font-size:42px; font-weight:700; color:#111827; letter-spacing:4px;">{otp_code}</div>
                    </td></tr>
                    <tr><td align="center" style="padding:10px 20px;">
                        <p style="margin:0; font-size:16px; color:#4b5563;">Valid for {expiry_minutes} minutes.</p>
                    </td></tr>
                    <tr><td align="center" style="padding:15px 20px 35px 20px;">
                        <p style="margin:0; font-size:16px; color:#dc2626; font-weight:700;">Do not share this code.</p>
                    </td></tr>
                </table>
                <table width="650" cellpadding="0" cellspacing="0" border="0">
                    <tr><td align="center" style="padding:18px 20px 0 20px; font-size:12px; color:#6b7280;">
                        This is an automated message from Q:DOC Barangay Document Request System.
                    </td></tr>
                </table>
            </td></tr>
        </table>
    </body>
    </html>
    """

    msg.set_content(plain_text)
    msg.add_alternative(html_content, subtype="html")

    if logo_path.exists():
        with open(logo_path, "rb") as logo_file:
            logo_data = logo_file.read()
        html_part = msg.get_payload()[1]
        html_part.add_related( logo_data, maintype="image", subtype="png", cid=f"<{logo_cid}>", filename="Q-DOC.png", disposition="inline")

    with smtplib.SMTP(mail_server, mail_port) as server:
        server.starttls()
        server.login(mail_username, mail_password)
        server.send_message(msg)


def is_otp_expired(expiry_value):
    try:
        return datetime.now() > datetime.fromisoformat(expiry_value)
    except Exception:
        return True


# ---------------------------------------------------------------------
# Static routes.
# ---------------------------------------------------------------------
@app.route('/assets/<path:filename>')
def assets(filename):
    return send_from_directory(BASE_DIR / 'assets', filename)

@app.route('/uploads/<path:filename>')
def uploads(filename):
    return send_from_directory(BASE_DIR / 'uploads', filename)

@app.route('/healthz')
def healthz():
    return 'OK', 200

# ---------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------
def fetch_one(sql, params=()):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchone()
    finally:
        cur.close(); conn.close()


def fetch_all(sql, params=()):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        cur.close(); conn.close()


def execute(sql, params=(), return_id=False):
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid if return_id else True
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close(); conn.close()


def table_count(sql, params=()):
    row = fetch_one(sql, params)
    if not row:
        return 0
    return int(next(iter(row.values())) or 0)


def request_ref(req_id, req_date=None):
    year = date.today().year
    if req_date:
        try:
            if isinstance(req_date, str):
                year = datetime.fromisoformat(req_date.replace('Z', '+00:00')).year
            else:
                year = req_date.year
        except Exception:
            pass
    return f"BRGY-{year}-{int(req_id):05d}" if req_id else ''


def validate_password_strength(raw_password: str):
    if len(raw_password or '') < 8:
        raise ValueError('Password must be at least 8 characters long.')
    if not re.search(r'[A-Z]', raw_password):
        raise ValueError('Password must contain at least one uppercase letter.')
    if not re.search(r'[a-z]', raw_password):
        raise ValueError('Password must contain at least one lowercase letter.')
    if not re.search(r'[0-9]', raw_password):
        raise ValueError('Password must contain at least one number.')
    if not re.search(r'[^A-Za-z0-9]', raw_password):
        raise ValueError('Password must contain at least one special character.')
    return True

# ---------------------------------------------------------------------
# Password helpers
# ---------------------------------------------------------------------
def hash_password(raw_password: str) -> str:
    if not raw_password:
        raise ValueError('Password is required.')

    salt = bcrypt.gensalt(rounds=12)

    return bcrypt.hashpw(raw_password.encode('utf-8'), salt).decode('utf-8')


def check_password(raw_password: str, stored_hash: str) -> bool:
    if not raw_password or not stored_hash:
        return False

    normalized = stored_hash.replace('$2y$', '$2b$', 1).encode('utf-8')

    try:
        return bcrypt.checkpw(raw_password.encode('utf-8'), normalized)
    except Exception:
        return False


def password_needs_rehash(stored_hash: str) -> bool:
    if not stored_hash:
        return True

    if stored_hash.startswith('$2y$'):
        return True

    return False

# ---------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------
def get_settings():
    default_gcash_qr = 'uploads/1768004504_maya-qr.jpeg'
    default_maya_qr = 'uploads/1768004504_maya-qr.jpeg'
    default_bank_qr = 'uploads/1768004504_banktransfer-qr.png'

    defaults = {
        'id': 1,
        'brgy_name': 'Barangay Sto. Niño',
        'city_name': 'Parañaque City',
        'province_name': 'Metro Manila',
        'email': 'admin.gov@gmail.com',
        'contact_number': '09053063531',
        'maintenance_mode': 0,
        'captain_name': 'Hon. Captain Name',
        'gcash_number': '',
        'gcash_qr': default_gcash_qr,
        'maya_number': '',
        'maya_qr': default_maya_qr,
        'bank_name': '',
        'bank_account_num': '',
        'bank_account_name': '',
        'bank_qr': default_bank_qr,
        'logo_left': 'assets/images/city-logo.png',
        'logo_right': 'assets/images/brgy-logo.png',
        'allow_registration': 1,
        'official_code': 'BrgyOfficial2025',
        'admin_code': 'BrgyAdmin2025',
    }

    try:
        row = fetch_one('SELECT * FROM system_settings WHERE id=1')
        if row:
            defaults.update({k: v for k, v in row.items() if v is not None})
    except Exception:
        pass

    # If database QR fields are blank, use your current QR files from uploads folder.
    if not defaults.get('gcash_qr'):
        defaults['gcash_qr'] = default_gcash_qr

    if not defaults.get('maya_qr'):
        defaults['maya_qr'] = default_maya_qr

    if not defaults.get('bank_qr'):
        defaults['bank_qr'] = default_bank_qr

    return defaults

def get_public_base_url():
    public_url = os.getenv('PUBLIC_BASE_URL', '').strip().rstrip('/')

    if public_url:
        return public_url

    return request.host_url.rstrip('/')

def get_client_ip():
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.remote_addr or '127.0.0.1'


def log_activity(user_id, action, description):
    if not user_id:
        return
    try:
        execute(
            'INSERT INTO activity_logs (user_id, action, description, ip_address, created_at) VALUES (%s,%s,%s,%s,NOW())',
            (user_id, action, description, get_client_ip())
        )
    except Exception as exc:
        print('Activity log failed:', exc)


def send_notification(user_id, title, message, request_id=None):
    try:
        execute(
            'INSERT INTO notifications (user_id, request_id, title, message, is_read, created_at) VALUES (%s,%s,%s,%s,0,NOW())',
            (user_id, request_id, title, message)
        )
    except Exception as exc:
        print('Notification failed:', exc)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def normalize_ph_mobile_number(value):
    number = (value or '').strip().replace(' ', '').replace('-', '')

    if number.startswith('+63'):
        number = '0' + number[3:]

    if number.startswith('63') and len(number) == 12:
        number = '0' + number[2:]

    return number


def validate_ph_wallet_number(value, label='Mobile wallet number'):
    number = normalize_ph_mobile_number(value)

    if not number:
        return ''

    if not re.fullmatch(r'09\d{9}', number):
        raise ValueError(f'{label} must be a valid Philippine mobile number. Example: 09171234567.')

    return number


def validate_payment_reference(payment_method, reference_number):
    method = (payment_method or '').strip()
    reference = (reference_number or '').strip().replace(' ', '').replace('-', '')

    online_methods = ['GCash', 'Maya', 'Bank Transfer']

    if method not in online_methods:
        return ''

    if not reference:
        raise ValueError(f'Please enter your {method} reference number.')

    if not re.fullmatch(r'[A-Za-z0-9]{8,30}', reference):
        raise ValueError(
            f'Invalid {method} reference number. Please enter 8 to 30 letters/numbers only.'
        )

    if len(set(reference.lower())) <= 2:
        raise ValueError(
            f'Invalid {method} reference number. Please enter the actual transaction reference.'
        )

    existing = fetch_one(
        '''
        SELECT id FROM requests
        WHERE payment_method=%s
        AND payment_reference=%s
        LIMIT 1
        ''',
        (method, reference)
    )

    if existing:
        raise ValueError(
            f'This {method} reference number has already been used. Please check your payment details.'
        )

    return reference

def save_file(file_storage, subfolder='', base_folder=None):
    if not file_storage or not file_storage.filename:
        return ''
    if not allowed_file(file_storage.filename):
        raise ValueError('Only JPG, PNG, WEBP, GIF, or PDF files are allowed.')
    safe_name = secure_filename(file_storage.filename)
    unique_name = f"{int(datetime.now().timestamp())}_{secrets.token_hex(4)}_{safe_name}"
    root = BASE_DIR / (base_folder or app.config['UPLOAD_FOLDER'])
    target = root / subfolder if subfolder else root
    target.mkdir(parents=True, exist_ok=True)
    file_storage.save(target / unique_name)
    if base_folder:
        return f"{base_folder}/{subfolder + '/' if subfolder else ''}{unique_name}".replace('//','/')
    return f"uploads/{subfolder + '/' if subfolder else ''}{unique_name}".replace('//','/')


def normalize_upload_path(value, default='assets/images/default-id.jpg'):
    if not value:
        return default
    cleaned = str(value).replace('\\', '/').lstrip('/')
    if cleaned.startswith('static/'):
        cleaned = cleaned[len('static/'):]
    if cleaned.startswith('assets/') or cleaned.startswith('uploads/'):
        return cleaned
    return 'uploads/' + cleaned


def initials(name):
    words = [w for w in (name or '').split() if w]
    return ''.join(w[0].upper() for w in words[:2]) or 'U'


def get_service_icon(name):
    text = (name or '').lower()
    if 'clearance' in text: return 'ri-shield-check-line'
    if 'residency' in text: return 'ri-home-4-line'
    if 'indigency' in text: return 'ri-hand-heart-line'
    if 'business' in text: return 'ri-briefcase-4-line'
    if 'id' in text: return 'ri-id-card-line'
    if 'solo' in text: return 'ri-user-heart-line'
    if 'health' in text: return 'ri-heart-pulse-line'
    if 'blotter' in text: return 'ri-alarm-warning-line'
    return 'ri-file-text-line'



def status_badge_class(status):
    key = (status or '').lower().replace(' ', '-')
    return {
        'pending': 'badge-pending',
        'approved': 'badge-approved',
        'processing': 'badge-processing',
        'ready-for-pickup': 'badge-ready',
        'completed': 'badge-completed',
        'rejected': 'badge-rejected',
        'published': 'bg-success',
        'draft': 'bg-secondary',
        'active': 'status-active',
        'hidden': 'status-hidden',
    }.get(key, 'bg-secondary')


def payment_badge_class(status):
    return 'bg-success' if (status or '').lower() == 'paid' else 'bg-warning text-dark'


def payment_status_text(status):
    return status or 'Unpaid'


def request_tracking_id(req_id, req_date=None):
    return request_ref(req_id, req_date)


def current_user():
    if not session.get('user_id'):
        return None
    return fetch_one('SELECT * FROM users WHERE id=%s', (session['user_id'],))


def common_admin_context():
    user = current_user() or {}
    settings = get_settings()
    return {
        'admin_name': user.get('fullname', 'Administrator'),
        'admin_role': user.get('role', 'Admin'),
        'db_pic': normalize_upload_path(user.get('profile_picture'), ''),
        'initials': initials(user.get('fullname', 'Admin')),
        'LOGO_LEFT': normalize_upload_path(settings.get('logo_left'), 'assets/images/city-logo.png'),
        'LOGO_RIGHT': normalize_upload_path(settings.get('logo_right'), 'assets/images/brgy-logo.png'),
    }


def resident_notifications(user_id):
    notifications = fetch_all('SELECT * FROM notifications WHERE user_id=%s ORDER BY created_at DESC LIMIT 5', (user_id,))
    unread = table_count('SELECT COUNT(*) AS c FROM notifications WHERE user_id=%s AND is_read=0', (user_id,))
    return notifications, unread


def parse_tracking_id(value):
    if not value:
        return None
    m = re.search(r'(\d+)$', str(value))
    return int(m.group(1)) if m else None


def role_redirect():
    role = session.get('role')
    status = session.get('status')
    if role == 'Admin':
        return redirect('dashboard_admin.php')
    if role == 'Official':
        return redirect('dashboard_offcl.php')
    if status == 'Approved':
        return redirect('welcomepage_rsdnt.php')
    return redirect('pending_status.php')

# ---------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------
def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not session.get('user_id'):
            flash('Please login first.', 'warning')
            return redirect('login.php')
        return view(*args, **kwargs)
    return wrapper


def role_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not session.get('user_id'):
                flash('Please login first.', 'warning')
                return redirect('login.php')
            if session.get('role') not in roles:
                flash('Access denied.', 'danger')
                return role_redirect()
            return view(*args, **kwargs)
        return wrapper
    return decorator

# ---------------------------------------------------------------------
# Jinja globals
# ---------------------------------------------------------------------
@app.context_processor
def inject_settings():
    s = get_settings()
    user = current_user() if session.get('user_id') else None
    return {
        'SYS': s,
        'sys_setting': s,
        'BRGY_NAME': s['brgy_name'],
        'CITY_NAME': s['city_name'],
        'PROVINCE': s['province_name'],
        'ADDRESS': f"{s['brgy_name']}, {s['city_name']}, {s['province_name']}",
        'CONTACT_NO': s['contact_number'],
        'EMAIL_ADDR': s['email'],
        'CAPTAIN': s['captain_name'],
        'LOGO_LEFT': normalize_upload_path(s.get('logo_left'), 'assets/images/city-logo.png'),
        'LOGO_RIGHT': normalize_upload_path(s.get('logo_right'), 'assets/images/brgy-logo.png'),
        'MAINTENANCE': s.get('maintenance_mode', 0),
        'current_year': date.today().year,
        'session_user': user,
        'status_badge_class': status_badge_class,
        'payment_badge_class': payment_badge_class,
        'payment_status_text': payment_status_text,
        'request_tracking_id': request_tracking_id,
        'request_ref': request_ref,
    }

@app.template_filter('fmt_date')
def fmt_date(value, fmt='%b %d, %Y'):
    if not value:
        return ''
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except Exception:
            return value
    return value.strftime(fmt)


@app.template_filter('log_time')
def log_time(value):
    if not value:
        return ''
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except Exception:
            return value
    return value.strftime('%m/%d/%y ') + value.strftime('%I:%M %p').lstrip('0')

@app.template_filter('peso')
def peso(value):
    try:
        amount = float(value or 0)
    except Exception:
        amount = 0
    return 'Free' if amount == 0 else f'₱{amount:,.2f}'

# ---------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------
@app.route('/')
@app.route('/index.php')
def index():
    if session.get('user_id'):
        return role_redirect()
    services = fetch_all('SELECT * FROM document_settings WHERE is_available=1 ORDER BY doc_name ASC LIMIT 9')
    for row in services:
        row['icon'] = get_service_icon(row.get('doc_name'))
        req = row.get('requirements') or 'Request this document officially from the barangay.'
        row['excerpt'] = req[:80] + ('...' if len(req) > 80 else '')
        row['price_text'] = 'Free' if float(row.get('price') or 0) == 0 else f"₱{float(row.get('price')):,.2f}"
    officials = fetch_all("SELECT fullname, position FROM users WHERE role='Official' AND account_status='Approved' ORDER BY id ASC LIMIT 8")
    announcements = fetch_all("SELECT * FROM announcements WHERE status='Published' ORDER BY created_at DESC LIMIT 3")
    return render_template('index.html', services=services, officials=officials, announcements=announcements)

@app.route('/login.php', methods=['GET'])
@app.route('/login', methods=['GET'])
def login_page():
    if session.get('user_id'):
        return role_redirect()
    return render_template('login.html')

@app.route('/login_process.php', methods=['POST'])
@app.route('/login.php', methods=['POST'])
@app.route('/login', methods=['POST'])
def login_process():
    role = request.form.get('role', 'Resident')
    email = request.form.get('email', '').strip()
    password = request.form.get('password', '')
    user = fetch_one('SELECT * FROM users WHERE email=%s AND role=%s LIMIT 1', (email, role))
    if not user or not check_password(password, user.get('password','')):
        flash('Invalid email, password, or role.', 'danger')
        return redirect('login.php')
    settings = get_settings()
    if int(settings.get('maintenance_mode') or 0) == 1 and user.get('role') == 'Resident':
        return redirect('maintenance.php')
    session['user_id'] = user['id']
    session['fullname'] = user['fullname']
    session['role'] = user['role']
    session['status'] = user['account_status']
    log_activity(user['id'], 'Login', 'User logged in successfully.')
    resp = make_response(role_redirect())
    if request.form.get('rememberme'):
        token = secrets.token_urlsafe(32)
        execute('UPDATE users SET remember_token=%s WHERE id=%s', (hash_password(token), user['id']))
        resp.set_cookie('remember_me', f"{user['id']}:{token}", max_age=60*60*24*30, httponly=True, samesite='Lax')
    return resp

@app.route('/logout.php')
@app.route('/logout')
def logout():
    if session.get('user_id'):
        try:
            execute('UPDATE users SET remember_token=NULL WHERE id=%s', (session['user_id'],))
            log_activity(session['user_id'], 'Logout', 'User logged out.')
        except Exception:
            pass
    session.clear()
    resp = make_response(redirect('login.php'))
    resp.delete_cookie('remember_me')
    return resp

@app.before_request
def remember_me_auto_login():
    if session.get('user_id') or not request.cookies.get('remember_me'):
        return
    try:
        user_id, token = request.cookies.get('remember_me','').split(':', 1)
        user = fetch_one('SELECT * FROM users WHERE id=%s', (user_id,))
        if user and user.get('remember_token') and check_password(token, user['remember_token']):
            session['user_id'] = user['id']; session['fullname'] = user['fullname']; session['role'] = user['role']; session['status'] = user['account_status']
    except Exception:
        pass

@app.before_request
def block_resident_portal_during_maintenance():
    if not session.get('user_id'):
        return

    if session.get('role') != 'Resident':
        return

    settings = get_settings()

    if int(settings.get('maintenance_mode') or 0) != 1:
        return

    allowed_endpoints = {
        'maintenance',
        'logout',
        'assets',
        'uploads',
        'check_status'
    }

    if request.endpoint in allowed_endpoints:
        return

    return redirect('maintenance.php')

# ---------------------------------------------------------------------
# Registration and password reset endpoints
# ---------------------------------------------------------------------
@app.route('/register.php')
def register_page():
    settings = get_settings()

    if int(settings.get('allow_registration') or 0) == 0:
        return render_template('maintenance.html', sys_setting=settings)

    return render_template('register.html')


def validate_registration_form(form):
    role = form.get('role', 'Resident')
    fullname = form.get('fullname', '').strip()
    email = form.get('email', '').strip()
    password = form.get('password', '')
    confirm = form.get('confirm_password', '')
    if not fullname or not email or not password:
        raise ValueError('Full name, email, and password are required.')
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email):
        raise ValueError('Please enter a valid email address.')
    validate_password_strength(password)
    if password != confirm:
        raise ValueError('Passwords do not match.')
    if fetch_one('SELECT id FROM users WHERE email=%s', (email,)):
        raise ValueError('Email is already registered.')
    settings = get_settings()
    if role == 'Official' and form.get('access_code') != settings.get('official_code'):
        raise ValueError('Incorrect official access code.')
    if role == 'Admin' and form.get('access_code') != settings.get('admin_code'):
        raise ValueError('Incorrect admin access code.')

def validate_registration_files(files, role):
    if role != 'Resident':
        return

    id_front = files.get('id_front')
    id_back = files.get('id_back')
    profile_picture = files.get('profile_picture')

    if not id_front or not id_front.filename:
        raise ValueError('Please upload the front side of your ID.')

    if not id_back or not id_back.filename:
        raise ValueError('Please upload the back side of your ID.')

    if not profile_picture or not profile_picture.filename:
        raise ValueError('Please upload your profile picture.')

    if not allowed_file(id_front.filename):
        raise ValueError('Invalid front ID file. Please upload a valid image.')

    if not allowed_file(id_back.filename):
        raise ValueError('Invalid back ID file. Please upload a valid image.')

    if not allowed_file(profile_picture.filename):
        raise ValueError('Invalid profile picture. Please upload a valid image.')

@app.route('/send_verification_code.php', methods=['POST'])
@app.route('/resend_code.php', methods=['POST'])
def send_verification_code():
    try:
        settings = get_settings()

        if int(settings.get('allow_registration') or 0) == 0:
            return jsonify({
                'status': 'error',
                'message': 'Registration is currently disabled.'
            })

        validate_registration_form(request.form)

        role = request.form.get('role', 'Resident')
        validate_registration_files(request.files, role)

        data = dict(request.form)
        files = {}

        for field in ['id_front', 'id_back', 'profile_picture']:
            if request.files.get(field) and request.files[field].filename:
                files[field] = save_file(request.files[field], '', 'uploads')
            else:
                files[field] = ''

        code = generate_otp()
        token = secrets.token_urlsafe(16)

        PENDING_REGISTRATIONS[token] = {
            'data': data,
            'files': files,
            'code': code,
            'created_at': datetime.now(),
            'expiry': otp_expiry_time().isoformat()
        }

        session['pending_registration_token'] = token

        email = data.get('email', '').strip()
        send_gmail_otp(email, code, "Q:DOC Registration Verification Code")

        return jsonify({'status': 'success', 'masked_email': mask_email(email)})

    except Exception as exc:
        return jsonify({'status': 'error', 'message': str(exc)})

@app.route('/verify_and_save.php', methods=['POST'])
def verify_and_save():
    settings = get_settings()

    if int(settings.get('allow_registration') or 0) == 0:
        return jsonify({
            'status': 'error',
            'message': 'Registration is currently disabled.'
        })

    token = session.get('pending_registration_token')
    pending = PENDING_REGISTRATIONS.get(token)

    if not pending:
        return jsonify({'status':'error','message':'No pending registration found. Please try again.'})

    code = request.form.get('code', '').strip()

    if is_otp_expired(pending.get('expiry')):
        PENDING_REGISTRATIONS.pop(token, None)
        session.pop('pending_registration_token', None)
        return jsonify({'status': 'error', 'message': 'Verification code expired. Please request a new OTP.'})

    if code != pending['code']:
        return jsonify({'status': 'error', 'message': 'Invalid verification code.'})

    data = pending['data']
    files = pending['files']
    role = data.get('role','Resident')

    try:
        if role == 'Resident':
            contact = data.get('contact','').strip()

            if not re.fullmatch(r'[0-9]{11}', contact):
                raise ValueError('Contact number must be exactly 11 digits.')

            if fetch_one('SELECT id FROM users WHERE contact=%s', (contact,)):
                raise ValueError('Contact number is already registered.')

            birthdate = data.get('birthdate') or '1900-01-01'
            sex = data.get('sex') or 'Male'
            civil_status = data.get('civil_status') or 'Single'
            address = data.get('address','')
            account_status = 'Pending'
            position = None

        else:
            birthdate = '1900-01-01'
            sex = 'Male'
            civil_status = 'Single'
            address = 'Barangay Hall'
            account_status = 'Approved'
            position = data.get('position') or ('System Administrator' if role == 'Admin' else 'Official')

            contact = '09' + str(secrets.randbelow(10**9)).zfill(9)

            while fetch_one('SELECT id FROM users WHERE contact=%s', (contact,)):
                contact = '09' + str(secrets.randbelow(10**9)).zfill(9)

        new_id = execute('''INSERT INTO users
            (role, fullname, email, birthdate, sex, civil_status, contact, address, password, id_front, id_back, profile_picture, account_status, position, created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())''',
            (
                role,
                data.get('fullname'),
                data.get('email'),
                birthdate,
                sex,
                civil_status,
                contact,
                address,
                hash_password(data.get('password','')),
                files.get('id_front',''),
                files.get('id_back',''),
                files.get('profile_picture',''),
                account_status,
                position
            ),
            return_id=True
        )

        log_activity(new_id, 'Register', f'New {role} account created.')

        PENDING_REGISTRATIONS.pop(token, None)
        session.pop('pending_registration_token', None)

        return jsonify({'status':'success'})

    except mysql.connector.Error as exc:
        return jsonify({'status':'error','message': exc.msg})

    except Exception as exc:
        return jsonify({'status':'error','message': str(exc)})

@app.route('/forgot_password.php')
def forgot_password():
    return render_template('forgot_password.html')

@app.route('/forgot_process.php', methods=['POST'])
def forgot_process():
    email = request.form.get('email', '').strip()
    user = fetch_one('SELECT id,email FROM users WHERE email=%s LIMIT 1', (email,))
    if not user:
        return jsonify({'status': 'error', 'message': 'Email not found.'})
    code = generate_otp()
    session['reset_email'] = email
    session['reset_code'] = code
    session['reset_expiry'] = otp_expiry_time().isoformat()
    try:
        send_gmail_otp(email, code, "Q:DOC Password Reset Verification Code")
        return jsonify({'status': 'success', 'message': 'OTP sent to your email.', 'masked_email': mask_email(email)})
    except Exception as exc:
        return jsonify({'status': 'error', 'message': str(exc)})

@app.route('/verify_reset_otp.php', methods=['POST'])
def verify_reset_otp():
    code = request.form.get('code', '').strip()
    if is_otp_expired(session.get('reset_expiry')):
        for key in ['reset_email', 'reset_code', 'reset_expiry', 'reset_verified']:
            session.pop(key, None)
        return jsonify({'status': 'error', 'message': 'OTP expired. Please request a new code.'})
    if code != session.get('reset_code'):
        return jsonify({'status': 'error', 'message': 'Invalid code.'})
    session['reset_verified'] = True
    return jsonify({'status': 'success'})

@app.route('/update_password_final.php', methods=['POST'])
def update_password_final():
    if not session.get('reset_verified'):
        return jsonify({'status':'error','message':'Please verify OTP first.'})
    password = request.form.get('password','')
    confirm = request.form.get('confirm_password','')
    try:
        validate_password_strength(password)
    except ValueError as exc:
        return jsonify({'status':'error','message': str(exc)})
    if password != confirm:
        return jsonify({'status':'error','message':'Passwords do not match.'})
    execute('UPDATE users SET password=%s WHERE email=%s', (hash_password(password), session.get('reset_email')))
    for key in ['reset_email','reset_code','reset_expiry','reset_verified']:
        session.pop(key, None)
    return jsonify({'status':'success'})

# ---------------------------------------------------------------------
# Public utility pages
# ---------------------------------------------------------------------
@app.route('/maintenance.php')
def maintenance():
    return render_template('maintenance.html', sys_setting=get_settings())

@app.route('/access_denied.php')
def access_denied():
    user = current_user() or {}
    return render_template('access_denied.html', fullname=user.get('fullname', 'User'), status=user.get('account_status', session.get('status', '')))

@app.route('/check_status.php')
def check_status():
    if not session.get('user_id'):
        return jsonify({'status':'logged_out'})
    user = current_user()
    if not user:
        session.clear()
        return jsonify({'status':'logged_out'})
    session['status'] = user['account_status']
    return jsonify({'status': user['account_status'], 'role': user['role']})

# ---------------------------------------------------------------------
# Resident pages
# ---------------------------------------------------------------------
@app.route('/welcomepage_rsdnt.php')
@role_required('Resident')
def welcomepage_rsdnt():
    if session.get('status') != 'Approved':
        return redirect('pending_status.php')
    user = current_user()
    notif_result, unread_count = resident_notifications(user['id'])
    announcements = fetch_all("SELECT * FROM announcements WHERE status='Published' ORDER BY created_at DESC LIMIT 5")
    return render_template('welcomepage_rsdnt.html', user=user, first_name=(user.get('fullname') or 'Resident').split()[0], notif_result=notif_result, unread_count=unread_count, ann_result=announcements)

@app.route('/pending_status.php')
@login_required
def pending_status():
    user = current_user() or {}
    
    account_status = user.get('account_status', session.get('status','Pending'))
    if account_status == 'Approved':
        line_width, line_color = '100%', '#198754'
    elif account_status == 'Rejected':
        line_width, line_color = '100%', '#dc3545'
    else:
        line_width, line_color = '50%', '#ffc107'
    return render_template('pending_status.html', fullname=user.get('fullname','User'), account_status=account_status, line_width=line_width, line_color=line_color)

@app.route('/request_document.php', methods=['GET','POST'])
@role_required('Resident')
def request_document():
    user = current_user()
    docs = fetch_all('SELECT * FROM document_settings WHERE is_available=1 ORDER BY doc_name ASC')
    settings = get_settings()
    notif_result, unread_count = resident_notifications(user['id'])

    show_success = False
    new_req_id = None
    error_msg = None

    if request.method == 'POST':
        try:
            doc_type = request.form.get('document_type')
            purpose = request.form.get('purpose')
            payment_method = request.form.get('payment_method') or 'Cash'
            pickup_date = request.form.get('pickup_date') or None
            payment_reference = request.form.get('payment_reference') or ''

            doc = next((d for d in docs if d['doc_name'] == doc_type), None)

            if not doc:
                raise ValueError('Please select a valid document type.')

            price = float(doc.get('price') or 0)

            if price == 0:
                payment_method = 'Free'
                payment_status = 'Paid'
                payment_reference = ''
            else:
                if payment_method not in ['Cash', 'GCash', 'Maya', 'Bank Transfer']:
                    raise ValueError('Please select a valid payment method.')

                if payment_method in ['GCash', 'Maya', 'Bank Transfer']:
                    payment_reference = validate_payment_reference(payment_method, payment_reference)
                    payment_status = 'Paid'
                else:
                    payment_reference = ''
                    payment_status = 'Unpaid'

            saved = []

            for f in request.files.getlist('req_files') + request.files.getlist('req_files[]'):
                if f and f.filename:
                    saved.append(save_file(f, 'requirements', 'assets/uploads'))

            new_id = execute('''
                INSERT INTO requests
                (user_id, document_type, purpose, status, payment_method, payment_reference, pickup_date, payment_status, requirement_file, amount, request_date)
                VALUES (%s,%s,%s,'Pending',%s,%s,%s,%s,%s,%s,NOW())
            ''', (
                user['id'],
                doc_type,
                purpose,
                payment_method,
                payment_reference,
                pickup_date,
                payment_status,
                ','.join(saved),
                price
            ), return_id=True)

            log_activity(
                user['id'],
                'Request Document',
                f'Submitted a request for {doc_type}. Payment method: {payment_method}.'
            )

            send_notification(
                user['id'],
                'Request Submitted',
                f'Your {doc_type} request has been submitted and is now pending review.',
                new_id
            )

            admins = fetch_all("SELECT id FROM users WHERE role IN ('Admin','Official') AND account_status='Approved'")

            for admin in admins:
                send_notification(
                    admin['id'],
                    'New Document Request',
                    f"{user['fullname']} requested {doc_type}.",
                    new_id
                )

            show_success = True
            new_req_id = f"BRGY-{date.today().year}-{new_id:05d}"

        except Exception as exc:
            error_msg = str(exc)

    return render_template(
        'request_document.html',
        user_info=user,
        display_pic=normalize_upload_path(user.get('profile_picture')),
        docs_query=docs,
        docs=docs,
        notif_result=notif_result,
        unread_count=unread_count,
        show_success=show_success,
        new_req_id=new_req_id,
        error_msg=error_msg,
        GCASH_NUM=settings.get('gcash_number') or '',
        GCASH_QR=settings.get('gcash_qr') or '',
        MAYA_NUM=settings.get('maya_number') or '',
        MAYA_QR=settings.get('maya_qr') or '',
        BANK_NAME=settings.get('bank_name') or 'Bank Transfer',
        BANK_ACC=settings.get('bank_account_num') or '',
        BANK_USER=settings.get('bank_account_name') or '',
        BANK_HOLDER=settings.get('bank_account_name') or '',
        BANK_QR=settings.get('bank_qr') or ''
    )

@app.route('/track_request.php')
@role_required('Resident')
def track_request():
    user = current_user()
    notif_result, unread_count = resident_notifications(user['id'])
    req_id = parse_tracking_id(request.args.get('req_id'))
    tracking_data = None; view_mode = 'list'; search_error = False
    if req_id:
        tracking_data = fetch_one('SELECT * FROM requests WHERE id=%s AND user_id=%s', (req_id, user['id']))
        if tracking_data:
            view_mode = 'track'
        else:
            search_error = True
    res_list = fetch_all('SELECT * FROM requests WHERE user_id=%s ORDER BY request_date DESC', (user['id'],))
    return render_template('track_request.html', user=user, user_avatar=normalize_upload_path(user.get('profile_picture')), notif_result=notif_result, unread_count=unread_count, view_mode=view_mode, tracking_data=tracking_data, search_error=search_error, res_list=res_list)

@app.route('/profile_rsdnt.php', methods=['GET','POST'])
@role_required('Resident')
def profile_rsdnt():
    user = current_user()
    msg=''; msg_type='success'
    if request.method == 'POST':
        try:
            if request.files.get('profile_picture') and request.files['profile_picture'].filename:
                path = save_file(request.files['profile_picture'], '', 'uploads')
                execute('UPDATE users SET profile_picture=%s WHERE id=%s', (path, user['id']))
                msg='Profile picture updated successfully.'
            elif request.form.get('update_info') is not None:
                contact=request.form.get('contact','').strip(); civil_status=request.form.get('civil_status') or user.get('civil_status')
                if not re.fullmatch(r'[0-9]{11}', contact): raise ValueError('Contact number must be exactly 11 digits.')
                execute('UPDATE users SET civil_status=%s, contact=%s WHERE id=%s', (civil_status, contact, user['id']))
                msg='Profile updated successfully.'
            elif request.form.get('change_password') is not None or request.form.get('change_pass') is not None:
                current_password = request.form.get('current_password', '')
                new_password = request.form.get('new_password', '')
                confirm_password = request.form.get('confirm_password', '')

                if not current_password or not new_password or not confirm_password:
                    raise ValueError('Please complete all password fields.')

                if not check_password(current_password, user.get('password', '')):
                    raise ValueError('Current password is incorrect.')

                validate_password_strength(new_password)

                if new_password != confirm_password:
                    raise ValueError('New password and confirm password do not match.')

                if check_password(new_password, user.get('password', '')):
                    raise ValueError('New password cannot be the same as your current password.')

                new_hash = hash_password(new_password)

                execute(
                    'UPDATE users SET password=%s WHERE id=%s',
                    (new_hash, user['id'])
                )

                log_activity(
                    user['id'],
                    'Password Change',
                    'Resident changed account password.'
                )

                msg = 'Password changed successfully.'
            user = current_user()
        except Exception as exc:
            msg=str(exc); msg_type='danger'
    notif_result, unread_count = resident_notifications(user['id'])
    return render_template('profile_rsdnt.html', user=user, profile_pic=normalize_upload_path(user.get('profile_picture')), notif_result=notif_result, unread_count=unread_count, msg=msg, msg_type=msg_type)



@app.route('/send_profile_otp.php', methods=['POST'])
@login_required
def send_profile_otp():
    user = current_user()
    if not user:
        return jsonify({'status': 'error', 'message': 'Unauthorized.'})
    new_email = request.form.get('email', user.get('email', '')).strip()
    new_password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')
    new_contact = request.form.get('contact', user.get('contact', '')).strip()
    new_civil_status = request.form.get('civil_status', user.get('civil_status', 'Single'))
    if not new_email or '@' not in new_email:
        return jsonify({'status': 'error', 'message': 'Please enter a valid email address.', 'field': 'email'})
    existing = fetch_one('SELECT id FROM users WHERE email=%s AND id<>%s', (new_email, user['id']))
    if existing:
        return jsonify({'status': 'error', 'message': 'Email already taken by another user.', 'field': 'email'})
    if new_contact:
        if not re.fullmatch(r'[0-9]{11}', new_contact):
            return jsonify({'status': 'error', 'message': 'Contact number must be exactly 11 digits.', 'field': 'contact'})
        contact_owner = fetch_one('SELECT id FROM users WHERE contact=%s AND id<>%s', (new_contact, user['id']))
        if contact_owner:
            return jsonify({'status': 'error', 'message': 'Contact number already taken by another user.', 'field': 'contact'})
    if new_password:
        try:
            validate_password_strength(new_password)
        except ValueError as exc:
            return jsonify({'status': 'error', 'message': str(exc)})
        if confirm_password and new_password != confirm_password:
            return jsonify({'status': 'error', 'message': 'Passwords do not match.'})
    code = generate_otp()
    session['profile_otp'] = {
        'code': code,
        'expiry': otp_expiry_time().isoformat(),
        'data': {'email': new_email, 'password': new_password, 'contact': new_contact, 'civil_status': new_civil_status}
    }
    try:
        send_gmail_otp(new_email, code, "Q:DOC Profile Update Verification Code")
        return jsonify({'status': 'success', 'masked_email': mask_email(new_email)})
    except Exception as exc:
        return jsonify({'status': 'error', 'message': str(exc)})

@app.route('/resend_profile_code.php', methods=['GET', 'POST'])
@login_required
def resend_profile_code():
    profile_otp = session.get('profile_otp')
    if not profile_otp:
        return jsonify({'status': 'error', 'message': 'Session expired. Please try updating again.'})
    data = profile_otp.get('data', {})
    email = data.get('email', '').strip()
    if not email:
        return jsonify({'status': 'error', 'message': 'No email found for OTP.'})
    code = generate_otp()
    profile_otp['code'] = code
    profile_otp['expiry'] = otp_expiry_time().isoformat()
    session['profile_otp'] = profile_otp
    try:
        send_gmail_otp(email, code, "Q:DOC Profile Update Verification Code")
        return jsonify({'status': 'success', 'masked_email': mask_email(email)})
    except Exception as exc:
        return jsonify({'status': 'error', 'message': str(exc)})

@app.route('/verify_profile_update.php', methods=['POST'])
@login_required
def verify_profile_update():
    otp = session.get('profile_otp')
    if not otp:
        return jsonify({'status': 'error', 'message': 'Session expired. Please try again.'})
    code = request.form.get('code', '').strip()
    if code != otp.get('code'):
        return jsonify({'status': 'error', 'message': 'Invalid Verification Code.'})
    if is_otp_expired(otp.get('expiry')):
        session.pop('profile_otp', None)
        return jsonify({'status': 'error', 'message': 'Code expired.'})

    data = otp.get('data', {})
    fields = ['email=%s']
    params = [data.get('email')]

    if data.get('contact'):
        fields.append('contact=%s')
        params.append(data.get('contact'))
    if data.get('civil_status'):
        fields.append('civil_status=%s')
        params.append(data.get('civil_status'))
    if data.get('password'):
        fields.append('password=%s')
        params.append(hash_password(data.get('password')))

    params.append(session['user_id'])
    execute(f"UPDATE users SET {', '.join(fields)} WHERE id=%s", tuple(params))
    session.pop('profile_otp', None)
    updated = current_user()
    if updated:
        session['fullname'] = updated.get('fullname')
        session['role'] = updated.get('role')
        session['status'] = updated.get('account_status')
    log_activity(session.get('user_id'), 'Profile Update', f"Verified profile update to {data.get('email')}")
    return jsonify({'status': 'success'})

@app.route('/mark_notif_read.php', methods=['POST'])
@login_required
def mark_notif_read():
    execute('UPDATE notifications SET is_read=1 WHERE user_id=%s', (session['user_id'],))
    return jsonify({'status':'success'})

@app.route('/notif_read_and_redirect.php')
@login_required
def notif_read_and_redirect():
    notif_id = request.args.get('id') or request.args.get('notif_id')
    req_id = request.args.get('req_id')
    if notif_id:
        execute('UPDATE notifications SET is_read=1 WHERE id=%s AND user_id=%s', (notif_id, session['user_id']))
    return redirect(f'track_request.php?req_id={req_id}' if req_id else 'welcomepage_rsdnt.php')

# ---------------------------------------------------------------------
# Official pages
# ---------------------------------------------------------------------
@app.route('/dashboard_offcl.php')
@role_required('Official')
def dashboard_offcl():
    user = current_user()
    stats = {
        'total_users': table_count("SELECT COUNT(*) AS c FROM users WHERE role='Resident'"),
        'pending_users': table_count("SELECT COUNT(*) AS c FROM users WHERE role='Resident' AND account_status='Pending'"),
        'total_requests': table_count('SELECT COUNT(*) AS c FROM requests'),
        'pending_requests': table_count("SELECT COUNT(*) AS c FROM requests WHERE status='Pending'"),
        'active_requests': table_count("SELECT COUNT(*) AS c FROM requests WHERE status IN ('Approved','Processing','Ready for Pickup')"),
        'completed_requests': table_count("SELECT COUNT(*) AS c FROM requests WHERE status='Completed'"),
    }
    recent_rows = fetch_all('''SELECT r.*, u.fullname FROM requests r JOIN users u ON r.user_id=u.id ORDER BY r.request_date DESC LIMIT 5''')
    return render_template('dashboard_offcl.html', first_name=(user.get('fullname') or 'Official').split()[0], recent_res=recent_rows, stats=stats, **common_admin_context())

@app.route('/transactions_offcl.php')
@role_required('Official','Admin')
def transactions_offcl():
    return render_template('transactions_offcl.html', **common_admin_context())

@app.route('/profile_offcl.php', methods=['GET','POST'])
@role_required('Official')
def profile_offcl():
    return profile_admin_official('profile_offcl.html')

# ---------------------------------------------------------------------
# Admin pages
# ---------------------------------------------------------------------
@app.route('/dashboard_admin.php')
@role_required('Admin')
def dashboard_admin():
    filter_value = request.args.get('filter', 'today')
    custom_start = request.args.get('start', '')
    custom_end = request.args.get('end', '')
    start_date, end_date, filter_label = resolve_dashboard_dates(filter_value, custom_start, custom_end)
    sql_start = f"{start_date} 00:00:00"
    sql_end = f"{end_date} 23:59:59"
    total_users = table_count("SELECT COUNT(*) AS c FROM users WHERE role='Resident'")
    requests_count = table_count('SELECT COUNT(*) AS c FROM requests WHERE request_date BETWEEN %s AND %s', (sql_start, sql_end))
    pending_requests = table_count("SELECT COUNT(*) AS c FROM requests WHERE status='Pending'")
    completed_today = table_count(
        "SELECT COUNT(*) AS c FROM requests "
        "WHERE status IN ('Approved','Processing','Ready for Pickup','Completed','Rejected') "
        "AND updated_at BETWEEN %s AND %s",
        (sql_start, sql_end)
    )
    top = fetch_one(
        "SELECT document_type, COUNT(*) AS c FROM requests "
        "WHERE request_date BETWEEN %s AND %s "
        "GROUP BY document_type ORDER BY c DESC LIMIT 1",
        (sql_start, sql_end)
    )
    top_doc = top['document_type'] if top else 'No data yet'
    status_rows = fetch_all(
        "SELECT status, COUNT(*) AS c FROM requests "
        "WHERE request_date BETWEEN %s AND %s GROUP BY status",
        (sql_start, sql_end)
    )
    status_labels = [r['status'] for r in status_rows]
    status_data = [int(r['c']) for r in status_rows]
    chart_labels, chart_data = get_volume_chart(filter_value, sql_start, sql_end)
    activities = fetch_all(
        "SELECT l.*, COALESCE(u.fullname,'System') AS fullname "
        "FROM activity_logs l LEFT JOIN users u ON u.id=l.user_id "
        "ORDER BY l.created_at DESC LIMIT 6"
    )
    insights = build_insights(sql_start, sql_end, requests_count, completed_today, pending_requests)
    return render_template('dashboard_admin.html', pending_requests=pending_requests,
                           requests_count=requests_count, completed_today=completed_today,
                           total_users=total_users, top_doc=top_doc, activities=activities,
                           insights=insights, status_labels=status_labels, status_data=status_data,
                           chart_labels=chart_labels, chart_data=chart_data, filter=filter_value,
                           filterLabel=filter_label, startDate=start_date, endDate=end_date,
                           **common_admin_context())


def resolve_dashboard_dates(filter_value='today', custom_start='', custom_end=''):
    today = date.today()
    if filter_value == '7days':
        return (today - timedelta(days=7)).isoformat(), today.isoformat(), 'Last 7 Days'
    if filter_value == '30days':
        return (today - timedelta(days=30)).isoformat(), today.isoformat(), 'Last 30 Days'
    if filter_value == '90days':
        return (today - timedelta(days=90)).isoformat(), today.isoformat(), 'Last 90 Days'
    if filter_value == 'custom' and custom_start and custom_end:
        return custom_start, custom_end, f"{custom_start} - {custom_end}"
    return today.isoformat(), today.isoformat(), 'Today'


def get_volume_chart(filter_value, sql_start, sql_end):
    labels, values = [], []
    if filter_value == 'today':
        hourly = {h: 0 for h in range(24)}
        rows = fetch_all(
            "SELECT HOUR(request_date) AS label, COUNT(*) AS c "
            "FROM requests WHERE request_date BETWEEN %s AND %s "
            "GROUP BY HOUR(request_date)",
            (sql_start, sql_end)
        )
        for row in rows:
            hourly[int(row['label'])] = int(row['c'])
        labels = list(hourly.keys())
        values = list(hourly.values())
    else:
        rows = fetch_all(
            "SELECT DATE(request_date) AS label, COUNT(*) AS c "
            "FROM requests WHERE request_date BETWEEN %s AND %s "
            "GROUP BY DATE(request_date) ORDER BY DATE(request_date) ASC",
            (sql_start, sql_end)
        )
        for row in rows:
            d = row['label']
            labels.append(d.strftime('%b %d') if hasattr(d, 'strftime') else str(d))
            values.append(int(row['c']))
    return labels, values


def build_insights(sql_start=None, sql_end=None, requests_count=None, completed_period=None, pending_requests=None):
    total_residents = table_count("SELECT COUNT(*) AS c FROM users WHERE role='Resident'")
    pending = pending_requests if pending_requests is not None else table_count("SELECT COUNT(*) AS c FROM requests WHERE status='Pending'")
    total_requests = table_count('SELECT COUNT(*) AS c FROM requests')
    completed = table_count("SELECT COUNT(*) AS c FROM requests WHERE status='Completed'")
    overdue_rows = fetch_all(
        "SELECT id, pickup_date FROM requests "
        "WHERE pickup_date < CURDATE() AND status NOT IN ('Completed','Rejected')"
    )
    overdue_count = len(overdue_rows)
    max_overdue_days = 0
    for row in overdue_rows:
        try:
            max_overdue_days = max(max_overdue_days, (date.today() - row['pickup_date']).days)
        except Exception:
            pass
    payments_today = table_count("SELECT COUNT(*) AS c FROM requests WHERE payment_status='Paid' AND DATE(updated_at)=CURDATE()")
    docs_processed_today = table_count(
        "SELECT COUNT(*) AS c FROM requests WHERE DATE(updated_at)=CURDATE() "
        "AND status IN ('Approved','Processing','Ready for Pickup','Completed','Rejected')"
    )
    items = [
        {'color': 'primary', 'icon': 'ri-group-line', 'msg': f'{total_residents} Residents are currently registered in the system.'},
        {'color': 'danger' if overdue_count else 'success', 'icon': 'ri-timer-flash-line', 'msg': f'{overdue_count} Requests are overdue' + (f' (x{max_overdue_days} days).' if overdue_count else '.')},
        {'color': 'success', 'icon': 'ri-bank-card-line', 'msg': f'{payments_today} Payments recorded on this day.'},
        {'color': 'info', 'icon': 'ri-file-check-line', 'msg': f'{docs_processed_today} documents processed/updated.'},
    ]
    if total_requests > 0:
        efficiency = (completed / total_requests) * 100
        items.append({'color': 'warning' if pending > 10 else 'secondary', 'icon': 'ri-speed-up-line', 'msg': f'Efficiency score: {efficiency:.1f}% of all requests are completed.'})
    if sql_start and sql_end and requests_count is not None:
        try:
            days = max((datetime.fromisoformat(sql_end[:10]) - datetime.fromisoformat(sql_start[:10])).days + 1, 1)
            prev_start = (datetime.fromisoformat(sql_start[:10]) - timedelta(days=days)).strftime('%Y-%m-%d 00:00:00')
            prev_end = (datetime.fromisoformat(sql_start[:10]) - timedelta(days=1)).strftime('%Y-%m-%d 23:59:59')
            previous = table_count('SELECT COUNT(*) AS c FROM requests WHERE request_date BETWEEN %s AND %s', (prev_start, prev_end))
            if previous > 0:
                growth = ((requests_count - previous) / previous) * 100
                items.append({'color': 'success' if growth >= 0 else 'danger', 'icon': 'ri-line-chart-line', 'msg': f'Request volume changed by {growth:.1f}% compared with the previous period.'})
        except Exception:
            pass
    return items

@app.route('/users_admin.php')
@role_required('Admin')
def users_admin():
    return render_template('users_admin.html', **common_admin_context())

@app.route('/managedocs_admin.php', methods=['GET','POST'])
@role_required('Admin','Official')
def managedocs_admin():
    if request.method == 'POST':
        if request.form.get('delete_id'):
            doc_id = request.form.get('delete_id')
            old_doc = fetch_one('SELECT * FROM document_settings WHERE id=%s', (doc_id,))

            execute('DELETE FROM document_settings WHERE id=%s', (doc_id,))

            if old_doc:
                log_activity(
                    session.get('user_id'),
                    'Document Deleted',
                    f"Deleted document setting: {old_doc.get('doc_name')} with price {old_doc.get('price')}."
                )
            else:
                log_activity(
                    session.get('user_id'),
                    'Document Deleted',
                    f"Deleted document setting ID #{doc_id}."
                )

            flash('Document deleted.', 'success')

        else:
            doc_id = request.form.get('doc_id')
            name = request.form.get('doc_name', '').strip()
            price = request.form.get('price') or 0
            reqs = request.form.get('requirements', '')
            available = 1 if request.form.get('is_available') else 0

            if doc_id:
                old_doc = fetch_one('SELECT * FROM document_settings WHERE id=%s', (doc_id,))

                execute(
                    'UPDATE document_settings SET doc_name=%s, price=%s, requirements=%s, is_available=%s WHERE id=%s',
                    (name, price, reqs, available, doc_id)
                )

                changes = []

                if old_doc:
                    old_name = str(old_doc.get('doc_name') or '')
                    old_price = str(old_doc.get('price') or '0')
                    old_reqs = str(old_doc.get('requirements') or '')
                    old_available = int(old_doc.get('is_available') or 0)

                    if old_name != name:
                        changes.append(f'Document name changed from "{old_name}" to "{name}"')

                    if float(old_price or 0) != float(price or 0):
                        changes.append(f'Price changed from {old_price} to {price}')

                    if old_reqs != reqs:
                        changes.append('Requirements were updated')

                    if old_available != available:
                        changes.append(
                            f'Availability changed from {"Available" if old_available else "Unavailable"} to {"Available" if available else "Unavailable"}'
                        )

                change_text = '; '.join(changes) if changes else 'Saved with no detected changes'

                log_activity(
                    session.get('user_id'),
                    'Document Updated',
                    f'Updated document setting: {name}. {change_text}.'
                )

                flash('Document updated.', 'success')

            else:
                new_id = execute('''
                    INSERT INTO requests
                    (user_id, document_type, purpose, status, payment_method, payment_reference, pickup_date, payment_status, requirement_file, request_date)
                    VALUES (%s,%s,%s,'Pending',%s,%s,%s,%s,%s,NOW())
                ''', (
                    user['id'],
                    doc_type,
                    purpose,
                    payment_method,
                    payment_reference,
                    pickup_date,
                    payment_status,
                    ','.join(saved)
                ), return_id=True)

                log_activity(
                    session.get('user_id'),
                    'Document Added',
                    f'Added new document setting: {name} with price {price}. Availability: {"Available" if available else "Unavailable"}.'
                )

                flash('Document added.', 'success')

        return redirect('managedocs_admin.php')

    docs = fetch_all('SELECT * FROM document_settings ORDER BY doc_name ASC')
    return render_template('managedocs_admin.html', docs=docs, **common_admin_context())

@app.route('/announcement_admin.php', methods=['GET','POST'])
@role_required('Admin')
def announcement_admin():
    if request.method == 'POST':
        if request.form.get('delete_id'):
            delete_id = request.form.get('delete_id')
            old_ann = fetch_one('SELECT title FROM announcements WHERE id=%s', (delete_id,))
            old_title = old_ann.get('title') if old_ann else f'Announcement #{delete_id}'

            execute('DELETE FROM announcements WHERE id=%s', (delete_id,))

            log_activity(
                session.get('user_id'),
                'Announcement Deleted',
                f'Deleted announcement: {old_title}.'
            )

            flash('Announcement deleted.', 'success')

        else:
            ann_id = request.form.get('announcement_id') or request.form.get('id')
            title = request.form.get('title','').strip()
            content = request.form.get('content','').strip()
            status = request.form.get('status','Published')

            if ann_id:
                old_ann = fetch_one('SELECT title, content, status FROM announcements WHERE id=%s', (ann_id,))

                execute(
                    'UPDATE announcements SET title=%s, content=%s, status=%s WHERE id=%s',
                    (title, content, status, ann_id)
                )

                changes = []

                if old_ann:
                    if str(old_ann.get('title') or '') != title:
                        changes.append('title was changed')

                    if str(old_ann.get('content') or '') != content:
                        changes.append('content was updated')

                    if str(old_ann.get('status') or '') != status:
                        changes.append(f"status changed from {old_ann.get('status')} to {status}")

                change_text = ', '.join(changes) if changes else 'saved with no major content change'

                log_activity(
                    session.get('user_id'),
                    'Announcement Updated',
                    f'Updated announcement: {title}. Changes: {change_text}.'
                )

            else:
                new_id = execute(
                    'INSERT INTO announcements (title, content, status, created_at, updated_at) VALUES (%s,%s,%s,NOW(),NOW())',
                    (title, content, status),
                    return_id=True
                )

                log_activity(
                    session.get('user_id'),
                    'Announcement Posted',
                    f'Posted new announcement: {title}. Status: {status}.'
                )

            flash('Announcement saved.', 'success')

        return redirect('announcement_admin.php')

    announcements = fetch_all('SELECT * FROM announcements ORDER BY created_at DESC')

    return render_template(
        'announcement_admin.html',
        announcements=announcements,
        **common_admin_context()
    )

@app.route('/settings_admin.php', methods=['GET','POST'])
@role_required('Admin','Official')
def settings_admin():
    if request.method == 'POST':
        form = request.form
        current_settings = get_settings()
        changes = []

        def checkbox_enabled(field_name):
            values = form.getlist(field_name)
            return 1 if any(str(v).lower() in ['1', 'on', 'true', 'yes'] for v in values) else 0

        def record_change(label, old_value, new_value):
            old_text = str(old_value or '').strip()
            new_text = str(new_value or '').strip()

            if old_text != new_text:
                changes.append(f'{label}: "{old_text}" to "{new_text}"')

        def save_uploaded_file(field_name, current_value, default_value=''):
            uploaded = request.files.get(field_name)

            if uploaded and uploaded.filename:
                return save_file(uploaded, '', 'uploads')

            return current_value or default_value

        default_gcash_qr = 'uploads/1768004504_maya-qr.jpeg'
        default_maya_qr = 'uploads/1768004504_maya-qr.jpeg'
        default_bank_qr = 'uploads/1768004504_banktransfer-qr.png'

        try:
            brgy_name = form.get('brgy_name') or current_settings.get('brgy_name')
            city_name = form.get('city_name') or current_settings.get('city_name')
            province_name = form.get('province_name') or current_settings.get('province_name')

            email = form.get('sys_email') or form.get('email') or current_settings.get('email')
            contact_number = form.get('sys_contact') or form.get('contact_number') or current_settings.get('contact_number')

            captain_name = form.get('captain_name') or current_settings.get('captain_name')

            gcash_number = form.get('gcash_number') or current_settings.get('gcash_number')
            maya_number = form.get('maya_number') or current_settings.get('maya_number')
            bank_name = form.get('bank_name') or current_settings.get('bank_name')
            bank_account_num = form.get('bank_account_num') or current_settings.get('bank_account_num')
            bank_account_name = form.get('bank_account_name') or current_settings.get('bank_account_name')

            gcash_qr = current_settings.get('gcash_qr') or default_gcash_qr
            maya_qr = current_settings.get('maya_qr') or default_maya_qr
            bank_qr = current_settings.get('bank_qr') or default_bank_qr

            logo_left = current_settings.get('logo_left') or 'assets/images/city-logo.png'
            logo_right = current_settings.get('logo_right') or 'assets/images/brgy-logo.png'

            official_code = form.get('official_code') or current_settings.get('official_code')
            admin_code = form.get('admin_code') or current_settings.get('admin_code')

            maintenance_mode = int(current_settings.get('maintenance_mode') or 0)
            allow_registration = int(current_settings.get('allow_registration') or 0)

            if form.get('save_general') is not None:
                record_change('Barangay Name', current_settings.get('brgy_name'), brgy_name)
                record_change('City / Municipality', current_settings.get('city_name'), city_name)
                record_change('Province', current_settings.get('province_name'), province_name)
                record_change('System Email', current_settings.get('email'), email)
                record_change('Contact Number', current_settings.get('contact_number'), contact_number)

            if form.get('save_branding') is not None:
                record_change('Punong Barangay Name', current_settings.get('captain_name'), captain_name)

                old_logo_left = logo_left
                old_logo_right = logo_right

                logo_left = save_uploaded_file('logo_left', logo_left, 'assets/images/city-logo.png')
                logo_right = save_uploaded_file('logo_right', logo_right, 'assets/images/brgy-logo.png')

                if old_logo_left != logo_left:
                    changes.append('City logo was updated.')

                if old_logo_right != logo_right:
                    changes.append('Barangay logo was updated.')

            if form.get('save_payment') is not None:
                gcash_number = validate_ph_wallet_number(gcash_number, 'GCash number')
                maya_number = validate_ph_wallet_number(maya_number, 'Maya number')

                record_change('GCash Number', current_settings.get('gcash_number'), gcash_number)
                record_change('Maya Number', current_settings.get('maya_number'), maya_number)
                record_change('Bank Name', current_settings.get('bank_name'), bank_name)
                record_change('Bank Account Number', current_settings.get('bank_account_num'), bank_account_num)
                record_change('Bank Account Name', current_settings.get('bank_account_name'), bank_account_name)

                old_gcash_qr = gcash_qr
                old_maya_qr = maya_qr
                old_bank_qr = bank_qr

                gcash_qr = save_uploaded_file('gcash_qr', gcash_qr, default_gcash_qr)
                maya_qr = save_uploaded_file('maya_qr', maya_qr, default_maya_qr)
                bank_qr = save_uploaded_file('bank_qr', bank_qr, default_bank_qr)

                if old_gcash_qr != gcash_qr:
                    changes.append('GCash QR code was updated.')

                if old_maya_qr != maya_qr:
                    changes.append('Maya QR code was updated.')

                if old_bank_qr != bank_qr:
                    changes.append('Bank Transfer QR code was updated.')

            if form.get('save_system') is not None:
                old_allow_registration = allow_registration
                old_maintenance_mode = maintenance_mode

                allow_registration = checkbox_enabled('allow_registration')
                maintenance_mode = checkbox_enabled('maintenance_mode')

                if old_allow_registration != allow_registration:
                    changes.append(
                        f'Allow Registration changed from {"ON" if old_allow_registration else "OFF"} to {"ON" if allow_registration else "OFF"}.'
                    )

                if old_maintenance_mode != maintenance_mode:
                    changes.append(
                        f'Maintenance Mode changed from {"ON" if old_maintenance_mode else "OFF"} to {"ON" if maintenance_mode else "OFF"}.'
                    )

                if str(current_settings.get('official_code') or '') != str(official_code or ''):
                    changes.append('Official registration access code was updated.')

                if str(current_settings.get('admin_code') or '') != str(admin_code or ''):
                    changes.append('Admin registration access code was updated.')

            execute('''
                INSERT INTO system_settings (
                    id,
                    brgy_name,
                    city_name,
                    province_name,
                    email,
                    contact_number,
                    maintenance_mode,
                    captain_name,
                    gcash_number,
                    gcash_qr,
                    maya_number,
                    maya_qr,
                    bank_name,
                    bank_account_num,
                    bank_account_name,
                    bank_qr,
                    logo_left,
                    logo_right,
                    allow_registration,
                    official_code,
                    admin_code
                )
                VALUES (1,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON DUPLICATE KEY UPDATE
                    brgy_name=VALUES(brgy_name),
                    city_name=VALUES(city_name),
                    province_name=VALUES(province_name),
                    email=VALUES(email),
                    contact_number=VALUES(contact_number),
                    maintenance_mode=VALUES(maintenance_mode),
                    captain_name=VALUES(captain_name),
                    gcash_number=VALUES(gcash_number),
                    gcash_qr=VALUES(gcash_qr),
                    maya_number=VALUES(maya_number),
                    maya_qr=VALUES(maya_qr),
                    bank_name=VALUES(bank_name),
                    bank_account_num=VALUES(bank_account_num),
                    bank_account_name=VALUES(bank_account_name),
                    bank_qr=VALUES(bank_qr),
                    logo_left=VALUES(logo_left),
                    logo_right=VALUES(logo_right),
                    allow_registration=VALUES(allow_registration),
                    official_code=VALUES(official_code),
                    admin_code=VALUES(admin_code)
            ''', (
                brgy_name,
                city_name,
                province_name,
                email,
                contact_number,
                maintenance_mode,
                captain_name,
                gcash_number,
                gcash_qr,
                maya_number,
                maya_qr,
                bank_name,
                bank_account_num,
                bank_account_name,
                bank_qr,
                logo_left,
                logo_right,
                allow_registration,
                official_code,
                admin_code
            ))

            if form.get('save_payment') is not None:
                action = 'Payment Settings Update'
            elif form.get('save_branding') is not None:
                action = 'Certificate Settings Update'
            elif form.get('save_system') is not None:
                action = 'System Toggle Update'
            else:
                action = 'General Settings Update'

            description = '; '.join(changes) if changes else 'Saved settings with no detected changes.'

            log_activity(
                session.get('user_id'),
                action,
                description
            )

            if form.get('save_system') is not None:
                return redirect('settings_admin.php?tab=system&success=1')

            if form.get('save_payment') is not None:
                return redirect('settings_admin.php?tab=payment&success=1')

            if form.get('save_branding') is not None:
                return redirect('settings_admin.php?tab=branding&success=1')

            return redirect('settings_admin.php?tab=general&success=1')

        except Exception as exc:
            flash(str(exc), 'danger')

            if form.get('save_payment') is not None:
                return redirect('settings_admin.php?tab=payment')

            if form.get('save_system') is not None:
                return redirect('settings_admin.php?tab=system')

            if form.get('save_branding') is not None:
                return redirect('settings_admin.php?tab=branding')

            return redirect('settings_admin.php?tab=general')

    settings = get_settings()

    return render_template(
        'settings_admin.html',
        settings=settings,
        brgy_name=settings.get('brgy_name'),
        city_name=settings.get('city_name'),
        province=settings.get('province_name'),
        sys_email=settings.get('email'),
        sys_contact=settings.get('contact_number'),
        captain=settings.get('captain_name'),
        gcash_num=settings.get('gcash_number'),
        maya_num=settings.get('maya_number'),
        bank_name=settings.get('bank_name'),
        bank_num=settings.get('bank_account_num'),
        bank_holder=settings.get('bank_account_name'),
        bank_acc=settings.get('bank_account_num'),
        bank_user=settings.get('bank_account_name'),
        qr_gcash=settings.get('gcash_qr'),
        qr_maya=settings.get('maya_qr'),
        qr_bank=settings.get('bank_qr'),
        logo_l=settings.get('logo_left'),
        logo_r=settings.get('logo_right'),
        off_code=settings.get('official_code'),
        adm_code=settings.get('admin_code'),
        **common_admin_context()
    )

@app.route('/logs_admin.php')
@role_required('Admin')
def logs_admin():
    start_date = request.args.get('start','')
    end_date = request.args.get('end','')
    where = []
    params = []
    if start_date:
        where.append('DATE(l.created_at) >= %s')
        params.append(start_date)
    if end_date:
        where.append('DATE(l.created_at) <= %s')
        params.append(end_date)
    where_sql = 'WHERE ' + ' AND '.join(where) if where else ''
    rows=fetch_all(f'''SELECT l.*, u.fullname, u.role FROM activity_logs l LEFT JOIN users u ON l.user_id=u.id {where_sql} ORDER BY l.created_at DESC LIMIT 300''', tuple(params))
    return render_template('logs_admin.html', result=rows, rows=rows, start_date=start_date, end_date=end_date, **common_admin_context())

@app.route('/reports_admin.php')
@role_required('Admin','Official')
def reports_admin():
    rows=fetch_all('''SELECT r.*, u.fullname, d.price FROM requests r JOIN users u ON r.user_id=u.id LEFT JOIN document_settings d ON d.doc_name=r.document_type ORDER BY r.request_date DESC''')
    return render_template('reports_admin.html', rows=rows, **common_admin_context())

@app.route('/profile_admin.php', methods=['GET','POST'])
@role_required('Admin')
def profile_admin():
    return profile_admin_official('profile_admin.html')


def profile_admin_official(template_name):
    user=current_user()
    if request.method == 'POST':
        fullname=request.form.get('fullname', user.get('fullname')); email=request.form.get('email', user.get('email')); position=request.form.get('position', user.get('position'))
        execute('UPDATE users SET fullname=%s, email=%s, position=%s WHERE id=%s', (fullname,email,position,user['id']))
        session['fullname']=fullname; flash('Profile updated.', 'success')
        return redirect(request.path)
    return render_template(template_name, user=user, profile_pic=normalize_upload_path(user.get('profile_picture')), **common_admin_context())

# ---------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------
@app.route('/fetch_users.php')
@role_required('Admin','Official')
def fetch_users():
    rows=fetch_all('SELECT * FROM users ORDER BY created_at DESC')
    for r in rows:
        r['profile_picture']=normalize_upload_path(r.get('profile_picture'), '') if r.get('profile_picture') else ''
        r['id_front']=normalize_upload_path(r.get('id_front'), '') if r.get('id_front') else ''
        r['id_back']=normalize_upload_path(r.get('id_back'), '') if r.get('id_back') else ''
        for k,v in list(r.items()):
            if isinstance(v, (datetime, date)):
                r[k]=v.isoformat()
    return jsonify(rows)

@app.route('/get_user_details.php', methods=['GET','POST'])
@role_required('Admin','Official')
def get_user_details():
    user_id=request.form.get('id') or request.args.get('id')
    user=fetch_one('SELECT * FROM users WHERE id=%s', (user_id,))
    if not user:
        return jsonify({'status':'error','message':'User not found.'})
    user['profile_picture']=normalize_upload_path(user.get('profile_picture'), '') if user.get('profile_picture') else ''
    user['id_front']=normalize_upload_path(user.get('id_front'), '') if user.get('id_front') else ''
    user['id_back']=normalize_upload_path(user.get('id_back'), '') if user.get('id_back') else ''
    for k,v in list(user.items()):
        if isinstance(v, (datetime, date)):
            user[k]=v.isoformat()
    return jsonify({'status':'success','data':user})

@app.route('/user_actions.php', methods=['POST'])
@role_required('Admin','Official')
def user_actions():
    user_id=request.form.get('id')
    action=request.form.get('action')
    status='Approved' if action == 'approve' else 'Rejected' if action == 'reject' else None
    if not status:
        return jsonify({'status':'error','message':'Invalid action.'})
    execute('UPDATE users SET account_status=%s WHERE id=%s', (status, user_id))
    target = fetch_one('SELECT fullname FROM users WHERE id=%s', (user_id,)) or {}
    log_activity(session.get('user_id'), 'User Action', f"Set {target.get('fullname','user #' + str(user_id))} account to {status}.")
    try:
        send_notification(user_id, f'Account {status}', f'Your account has been {status.lower()} by the barangay office.')
    except Exception:
        pass
    return jsonify({'status':'success','message':f'User {status.lower()}.'})

@app.route('/fetch_requests.php')
@role_required('Admin','Official')
def fetch_requests():
    search=request.args.get('search','').strip()
    params=[]; where=''
    if search:
        where='WHERE u.fullname LIKE %s OR r.document_type LIKE %s OR r.status LIKE %s OR r.id LIKE %s'
        s=f'%{search}%'; params=[s,s,s,s]
    rows=fetch_all(f'''SELECT r.*, u.fullname, u.contact FROM requests r JOIN users u ON r.user_id=u.id {where} ORDER BY r.request_date DESC''', tuple(params))
    for r in rows:
        r['formatted_pickup_date'] = r['pickup_date'].strftime('%b %d, %Y') if isinstance(r.get('pickup_date'), date) else (r.get('pickup_date') or 'Pending')
        for k,v in list(r.items()):
            if isinstance(v, datetime): r[k]=v.isoformat(sep=' ')
            elif isinstance(v, date): r[k]=v.isoformat()
    return jsonify(rows)

@app.route('/request_actions.php', methods=['POST'])
@role_required('Admin','Official')
def request_actions():
    rid = request.form.get('id')
    action = request.form.get('action')
    payload = request.form.get('payload', '')
    row = fetch_one('SELECT * FROM requests WHERE id=%s', (rid,))
    if not row:
        return jsonify({'status': 'error', 'message': 'Request not found.'})

    if action == 'update_status':
        if payload not in REQUEST_STATUSES:
            return jsonify({'status': 'error', 'message': 'Invalid status.'})
        execute('UPDATE requests SET status=%s, updated_at=NOW() WHERE id=%s', (payload, rid))
        title_map = {
            'Pending': 'Status Update',
            'Approved': 'Request Approved',
            'Processing': 'Processing Started',
            'Ready for Pickup': 'Ready for Pickup',
            'Completed': 'Request Completed',
            'Rejected': 'Request Rejected',
        }
        message_map = {
            'Pending': f"Your {row['document_type']} request is pending review.",
            'Approved': f"Your {row['document_type']} request has been approved.",
            'Processing': f"Your {row['document_type']} request is now being processed.",
            'Ready for Pickup': f"Your {row['document_type']} is ready for pickup at the barangay hall.",
            'Completed': f"Your {row['document_type']} request has been completed.",
            'Rejected': f"Your {row['document_type']} request was rejected. Please check the official note.",
        }
        send_notification(row['user_id'], title_map.get(payload, 'Status Update'), message_map.get(payload, f"Your request is now {payload}."), rid)
        log_activity(session.get('user_id'), 'Status Update', f"Updated request #{rid} to {payload}.")
        return jsonify({'status': 'success', 'message': 'Status updated.'})

    if action == 'toggle_payment':
        if payload not in PAYMENT_STATUSES:
            return jsonify({'status': 'error', 'message': 'Invalid payment status.'})
        execute('UPDATE requests SET payment_status=%s, updated_at=NOW() WHERE id=%s', (payload, rid))
        send_notification(row['user_id'], 'Payment Update', f"Payment for your {row['document_type']} request is now marked as {payload}.", rid)
        log_activity(session.get('user_id'), 'Payment Update', f"Marked request #{rid} payment as {payload}.")
        return jsonify({'status': 'success', 'message': 'Payment status updated.'})

    if action == 'save_note':
        execute('UPDATE requests SET official_notes=%s, updated_at=NOW() WHERE id=%s', (payload, rid))
        send_notification(row['user_id'], 'New Message from Official', f"A barangay official added a note to your {row['document_type']} request.", rid)
        log_activity(session.get('user_id'), 'Official Note', 'Added a note to user request.')
        return jsonify({'status': 'success', 'message': 'Note saved.'})

    return jsonify({'status': 'error', 'message': 'Invalid action.'})

@app.route('/fetch_reports.php')
@role_required('Admin','Official')
def fetch_reports():
    search = request.args.get('search', '').strip()
    start_date = request.args.get('start', '').strip()
    end_date = request.args.get('end', '').strip()
    status = request.args.get('status', '').strip()
    payment = request.args.get('payment', '').strip()
    where = []
    params = []
    if search:
        where.append('(u.fullname LIKE %s OR r.document_type LIKE %s OR r.payment_reference LIKE %s OR r.id LIKE %s)')
        like = f'%{search}%'
        params.extend([like, like, like, like])
    if start_date:
        where.append('DATE(r.request_date) >= %s')
        params.append(start_date)
    if end_date:
        where.append('DATE(r.request_date) <= %s')
        params.append(end_date)
    if status:
        where.append('r.status = %s')
        params.append(status)
    if payment:
        where.append('r.payment_status = %s')
        params.append(payment)
    where_sql = 'WHERE ' + ' AND '.join(where) if where else ''
    sql = (
        "SELECT r.*, u.fullname, IFNULL(d.price,0) AS price "
        "FROM requests r "
        "JOIN users u ON u.id=r.user_id "
        "LEFT JOIN document_settings d ON d.doc_name=r.document_type "
        f"{where_sql} "
        "ORDER BY r.request_date DESC"
    )
    rows = fetch_all(sql, tuple(params))
    for r in rows:
        req_date = r.get('request_date')
        r['ref_no'] = request_ref(r.get('id'), req_date)
        if isinstance(req_date, datetime):
            r['formatted_date'] = req_date.strftime('%m/%d/%y %I:%M %p').replace(' 0', ' ')
        elif isinstance(req_date, date):
            r['formatted_date'] = req_date.strftime('%m/%d/%y')
        else:
            r['formatted_date'] = str(req_date or '')
        for k, v in list(r.items()):
            if isinstance(v, datetime):
                r[k] = v.isoformat(sep=' ')
            elif isinstance(v, date):
                r[k] = v.isoformat()
    return jsonify(rows)

@app.route('/ajax_log.php', methods=['POST'])
def ajax_log():
    action = request.form.get('action', 'System Action')
    description = request.form.get('description', 'Action recorded.')
    log_activity(session.get('user_id'), action, description)
    return jsonify({'status': 'success'})

@app.route('/print_document.php')
@role_required('Admin','Official')
def print_document():
    rid = request.args.get('id') or request.args.get('request_id')
    row = fetch_one(
        "SELECT r.*, u.fullname, u.address, u.birthdate, u.sex, u.civil_status, u.contact, u.profile_picture "
        "FROM requests r JOIN users u ON r.user_id=u.id WHERE r.id=%s",
        (rid,)
    )
    if not row:
        flash('Request not found.', 'danger')
        return redirect('transactions_offcl.php')
    settings = get_settings()
    doc_type = row.get('document_type') or 'Document'
    fullname = (row.get('fullname') or '').upper()
    address = (row.get('address') or '').upper()
    purpose = row.get('purpose') or 'Official use'
    birthdate = row.get('birthdate').strftime('%m/%d/%Y') if row.get('birthdate') else 'N/A'
    sex = (row.get('sex') or '').upper()
    civil_status = (row.get('civil_status') or '').upper()
    id_no = request_ref(row.get('id'), row.get('request_date'))
    date_issued = date.today().strftime('%m-%d-%Y')
    valid_until = (date.today() + timedelta(days=365)).strftime('%m-%d-%Y')
    date_day = str(date.today().day)
    if 10 <= date.today().day % 100 <= 20:
        date_day += 'th'
    else:
        date_day += {1:'st', 2:'nd', 3:'rd'}.get(date.today().day % 10, 'th')
    date_month = date.today().strftime('%B')
    date_year = str(date.today().year)
    profile_pic = normalize_upload_path(row.get('profile_picture'), 'assets/images/default-id.jpg')
    verify_url = get_public_base_url() + url_for('verify_document', id=row.get('id'))
    qr_url = 'https://api.qrserver.com/v1/create-qr-code/?size=300x300&margin=10&data=' + quote_plus(verify_url)
    body_content = build_document_body(doc_type, fullname, address, purpose)
    log_activity(session.get('user_id'), 'Print Document', f"Printed {doc_type} for request {id_no}.")
    return render_template('print_document.html', row=row, settings=settings, doc_type=doc_type,
                           fullname=fullname, address=address, purpose=purpose, birthdate=birthdate,
                           sex=sex, civil_status=civil_status, id_no=id_no, date_issued=date_issued,
                           valid_until=valid_until, date_day=date_day, date_month=date_month,
                           date_year=date_year, profile_pic=profile_pic, qr_url=qr_url,
                           body_content=body_content, is_id=(doc_type == 'Barangay ID'),
                           **common_admin_context())


def build_document_body(doc_type, fullname, address, purpose):
    if doc_type == 'Barangay Clearance':
        return f"""
        <p><strong>TO WHOM IT MAY CONCERN:</strong></p>
        <p class='indent'>This is to certify that <strong>{fullname}</strong>, of legal age, is a bonafide resident of <strong>{address}</strong>, within the jurisdiction of this Barangay.</p>
        <p class='indent'>This is to certify further that the above-mentioned person has <strong>NO DEROGATORY RECORD</strong> on file in this office as of this date and is known to be a person of good moral character.</p>
        <p class='indent'>This certification is issued upon the request of the interested party for the purpose of: <br><strong>{purpose}</strong>.</p>
        """
    if doc_type == 'Certificate of Indigency':
        return f"""
        <p><strong>TO WHOM IT MAY CONCERN:</strong></p>
        <p class='indent'>This is to certify that <strong>{fullname}</strong>, of legal age, is a resident of <strong>{address}</strong>.</p>
        <p class='indent'>This further certifies that the above-named person belongs to an <strong>INDIGENT FAMILY</strong> in this Barangay and may require financial, medical, educational, or other lawful assistance.</p>
        <p class='indent'>This certification is issued for the purpose of: <strong>{purpose}</strong>.</p>
        """
    if doc_type == 'Certificate of Residency':
        return f"""
        <p><strong>TO WHOM IT MAY CONCERN:</strong></p>
        <p class='indent'>This is to certify that <strong>{fullname}</strong>, of legal age, is a permanent resident of <strong>{address}</strong>.</p>
        <p class='indent'>Based on records available in this office, the above-named person is known as a resident within the territorial jurisdiction of this Barangay.</p>
        <p class='indent'>This certification is issued upon request for the purpose of: <strong>{purpose}</strong>.</p>
        """
    if doc_type == 'Business Permit':
        return f"""
        <p><strong>TO WHOM IT MAY CONCERN:</strong></p>
        <p class='indent'>This is to certify that <strong>{fullname}</strong> has applied for barangay clearance/permit relative to the operation of a business located at <strong>{address}</strong>.</p>
        <p class='indent'>The applicant has complied with the basic barangay documentary requirements and is hereby granted this Barangay Business Permit/Clearance subject to existing barangay ordinances and regulations.</p>
        <p class='indent'>This certification is issued for the application or renewal of the appropriate business permit for the purpose of: <strong>{purpose}</strong>.</p>
        """
    if doc_type == 'Solo Parent Application':
        return f"""
        <p><strong>TO WHOM IT MAY CONCERN:</strong></p>
        <p class='indent'>This is to certify that <strong>{fullname}</strong>, of legal age, is a resident of <strong>{address}</strong>.</p>
        <p class='indent'>This document is issued in support of the resident's Solo Parent application or related documentary requirement.</p>
        <p class='indent'>Purpose: <strong>{purpose}</strong>.</p>
        """
    return f"""
    <p><strong>TO WHOM IT MAY CONCERN:</strong></p>
    <p class='indent'>This is to certify that <strong>{fullname}</strong> is a resident of <strong>{address}</strong>.</p>
    <p class='indent'>This <strong>{doc_type.upper()}</strong> is issued upon request for the purpose of: <strong>{purpose}</strong>.</p>
    """


@app.route('/verify_document.php')
def verify_document():
    rid = request.args.get('id')

    row = fetch_one(
        """
        SELECT 
            r.*,
            u.fullname,
            u.address,
            u.birthdate,
            u.sex,
            u.civil_status,
            u.contact,
            u.profile_picture
        FROM requests r
        JOIN users u ON r.user_id = u.id
        WHERE r.id = %s
        """,
        (rid,)
    )

    if not row:
        return """
        <div style="font-family: Arial, sans-serif; min-height: 100vh; background:#eef3f8; display:flex; align-items:center; justify-content:center; padding:30px;">
            <div style="background:#fff; max-width:520px; width:100%; border-radius:18px; padding:35px; text-align:center; box-shadow:0 18px 45px rgba(0,0,0,0.12);">
                <div style="display:inline-block; background:#dc3545; color:white; padding:14px 32px; border-radius:40px; font-size:24px; font-weight:800; margin-bottom:25px;">
                    ❌ Invalid Document
                </div>
                <h2 style="color:#1f2937; margin-bottom:10px;">Document Not Found</h2>
                <p style="color:#6b7280;">This QR code does not match any valid Q-DOC record.</p>
            </div>
        </div>
        """, 404

    doc_type = row.get('document_type') or 'Document'
    fullname = row.get('fullname') or 'Resident'
    purpose = row.get('purpose') or 'Official use'
    address = row.get('address') or ''
    captain_name = 'HON. Johnny C. Co'
    settings = get_settings()
    sex = row.get('sex') or ''
    civil_status = row.get('civil_status') or ''
    status = row.get('status') or ''
    reference_no = request_ref(row.get('id'), row.get('request_date'))

    request_date = row.get('request_date')
    if isinstance(request_date, datetime):
        date_issued = request_date.strftime('%m-%d-%Y')
    elif isinstance(request_date, date):
        date_issued = request_date.strftime('%m-%d-%Y')
    else:
        date_issued = date.today().strftime('%m-%d-%Y')

    valid_until = ''
    try:
        if isinstance(request_date, datetime):
            valid_until = (request_date.date() + timedelta(days=365)).strftime('%m-%d-%Y')
        elif isinstance(request_date, date):
            valid_until = (request_date + timedelta(days=365)).strftime('%m-%d-%Y')
        else:
            valid_until = (date.today() + timedelta(days=365)).strftime('%m-%d-%Y')
    except Exception:
        valid_until = (date.today() + timedelta(days=365)).strftime('%m-%d-%Y')

    birthdate = row.get('birthdate')
    if isinstance(birthdate, datetime):
        birthdate_text = birthdate.strftime('%m/%d/%Y')
    elif isinstance(birthdate, date):
        birthdate_text = birthdate.strftime('%m/%d/%Y')
    else:
        birthdate_text = str(birthdate or 'N/A')

    city_logo = url_for('assets', filename='images/city-logo.png')
    brgy_logo = url_for('assets', filename='images/brgy-logo.png')
    default_pic = url_for('assets', filename='images/default-id.jpg')

    profile_pic = normalize_upload_path(row.get('profile_picture'), '')
    if profile_pic:
        if profile_pic.startswith('uploads/'):
            profile_pic_url = '/' + profile_pic
        elif profile_pic.startswith('assets/'):
            profile_pic_url = '/' + profile_pic
        else:
            profile_pic_url = default_pic
    else:
        profile_pic_url = default_pic

    verify_url = get_public_base_url() + url_for('verify_document', id=row.get('id'))
    small_qr = 'https://api.qrserver.com/v1/create-qr-code/?size=180x180&margin=8&data=' + quote_plus(verify_url)

    if status == 'Rejected':
        badge_color = '#dc3545'
        badge_text = '❌ Invalid Document'
    else:
        badge_color = '#22b14c'
        badge_text = '✅ Valid Document'

    if doc_type == 'Barangay ID':
        return f"""
        <!doctype html>
        <html>
        <head>
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>Q-DOC Verification - {reference_no}</title>
            <style>
                body {{
                    margin: 0;
                    font-family: Arial, Helvetica, sans-serif;
                    background: #eef3f8;
                    color: #111827;
                    padding: 35px 15px;
                }}
                .valid-badge {{
                    background: {badge_color};
                    color: white;
                    font-size: 26px;
                    font-weight: 800;
                    padding: 16px 36px;
                    border-radius: 45px;
                    display: block;
                    width: fit-content;
                    margin: 0 auto 35px auto;
                    box-shadow: 0 12px 28px rgba(34,177,76,0.28);
                }}
                .id-card {{
                    width: 100%;
                    max-width: 820px;
                    background: white;
                    border-radius: 12px;
                    overflow: hidden;
                    margin: 0 auto 28px auto;
                    box-shadow: 0 16px 42px rgba(0,0,0,0.12);
                    border: 1px solid #d9e2ec;
                }}
                .card-header {{
                    background: #123f78;
                    color: white;
                    padding: 14px 20px;
                    display: flex;
                    align-items: center;
                    justify-content: space-between;
                    text-align: center;
                }}
                .card-header img {{
                    width: 58px;
                    height: 58px;
                    object-fit: contain;
                }}
                .header-text {{
                    flex: 1;
                    font-size: 13px;
                    letter-spacing: 1px;
                    line-height: 1.35;
                }}
                .header-text strong {{
                    display: block;
                    font-size: 24px;
                    letter-spacing: 3px;
                }}
                .front-content {{
                    display: grid;
                    grid-template-columns: 200px 1fr 120px;
                    gap: 22px;
                    padding: 24px;
                    align-items: center;
                    min-height: 270px;
                    background: linear-gradient(rgba(255,255,255,.90), rgba(255,255,255,.90));
                }}
                .photo {{
                    width: 180px;
                    height: 180px;
                    border: 5px solid #14406f;
                    object-fit: cover;
                    background: #d1f0f4;
                }}
                .name {{
                    font-size: 30px;
                    font-weight: 900;
                    margin-bottom: 8px;
                    text-transform: uppercase;
                }}
                .info {{
                    font-size: 15px;
                    line-height: 1.55;
                }}
                .label {{
                    font-weight: 800;
                    color: #374151;
                    display: inline-block;
                    min-width: 110px;
                }}
                .qr {{
                    width: 110px;
                    height: 110px;
                }}
                .signature {{
                    text-align: center;
                    padding-top: 18px;
                    font-size: 12px;
                    font-weight: 700;
                }}
                .back-title {{
                    background: #123f78;
                    color: white;
                    font-size: 26px;
                    letter-spacing: 4px;
                    font-weight: 900;
                    padding: 18px 24px;
                }}
                .back-body {{
                    padding: 28px 26px 80px 26px;
                    min-height: 210px;
                    position: relative;
                }}
                .line {{
                    border-bottom: 1px solid #cbd5e1;
                    height: 24px;
                    margin-bottom: 18px;
                }}
                .footer-note {{
                    border-top: 1px solid #e5e7eb;
                    text-align: center;
                    padding: 14px;
                    font-size: 12px;
                    font-weight: 800;
                }}
                .confirm {{
                    text-align:center;
                    color:#4b5563;
                    font-size: 24px;
                    line-height:1.4;
                    margin-top: 28px;
                }}
                .confirm strong {{
                    color:#123f78;
                }}
                @media(max-width: 700px) {{
                    .front-content {{
                        grid-template-columns: 1fr;
                        text-align: center;
                    }}
                    .photo {{
                        margin: 0 auto;
                    }}
                    .qr {{
                        margin: 0 auto;
                    }}
                    .name {{
                        font-size: 22px;
                    }}
                    .header-text strong {{
                        font-size: 17px;
                    }}
                }}
            </style>
        </head>
        <body>
            <div class="valid-badge">{badge_text}</div>

            <div class="id-card">
                <div class="card-header">
                    <img src="{city_logo}">
                    <div class="header-text">
                        REPUBLIC OF THE PHILIPPINES<br>
                        CITY OF PARANAQUE
                        <strong>BARANGAY STO. NIÑO</strong>
                    </div>
                    <img src="{brgy_logo}">
                </div>

                <div class="front-content">
                    <div>
                        <img class="photo" src="{profile_pic_url}">
                    </div>

                    <div>
                        <div class="name">{fullname}</div>
                        <div class="info">
                            <div><span class="label">ADDRESS:</span> {address}</div>
                            <div><span class="label">BIRTHDATE:</span> {birthdate_text}</div>
                            <div><span class="label">SEX:</span> {sex}</div>
                            <div><span class="label">CIVIL STATUS:</span> {civil_status}</div>
                            <div><span class="label">STATUS:</span> RESIDENT</div>
                            <br>
                            <div><span class="label">DATE ISSUED:</span> {date_issued}</div>
                            <div><span class="label">VALID UNTIL:</span> {valid_until}</div>
                        </div>

                        <div class="signature">
                            <u>{captain_name}</u><br>
                            PUNONG BARANGAY
                        </div>
                    </div>

                    <div>
                        <img class="qr" src="{small_qr}">
                    </div>
                </div>
            </div>

            <div class="id-card">
                <div class="back-title">ID NO. {reference_no}</div>
                <div class="back-body">
                    <strong><em>IN CASE OF EMERGENCY</em></strong><br><br>
                    <strong>CONTACT PERSON:</strong>
                    <div class="line"></div>
                    <strong>CONTACT NUMBER:</strong>
                    <div class="line"></div>
                    <strong><em>"THIS IS NOT TRANSFERABLE"</em></strong>
                </div>
                <div class="footer-note">
                    IF FOUND PLEASE RETURN TO:<br>
                    BARANGAY HALL, STO. NIÑO, PARANAQUE CITY
                </div>
            </div>

            <div class="confirm">
                This page confirms the validity of<br>
                Reference No. <strong>{reference_no}</strong>.
            </div>
        </body>
        </html>
        """

    return f"""
    <!doctype html>
    <html>
    <head>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Q-DOC Verification - {reference_no}</title>
        <style>
            body {{
                margin: 0;
                font-family: Arial, Helvetica, sans-serif;
                background: #eef3f8;
                color: #111827;
                padding: 35px 15px;
            }}
            .valid-badge {{
                background: {badge_color};
                color: white;
                font-size: 26px;
                font-weight: 800;
                padding: 16px 36px;
                border-radius: 45px;
                display: block;
                width: fit-content;
                margin: 0 auto 35px auto;
                box-shadow: 0 12px 28px rgba(34,177,76,0.28);
            }}
            .doc-card {{
                width: 100%;
                max-width: 760px;
                background: white;
                border-radius: 12px;
                overflow: hidden;
                margin: 0 auto 28px auto;
                box-shadow: 0 16px 42px rgba(0,0,0,0.12);
                border: 1px solid #d9e2ec;
            }}
            .card-header {{
                background: #123f78;
                color: white;
                padding: 14px 20px;
                display: flex;
                align-items: center;
                justify-content: space-between;
                text-align: center;
            }}
            .card-header img {{
                width: 58px;
                height: 58px;
                object-fit: contain;
            }}
            .header-text {{
                flex: 1;
                font-size: 13px;
                letter-spacing: 1px;
                line-height: 1.35;
            }}
            .header-text strong {{
                display: block;
                font-size: 24px;
                letter-spacing: 3px;
            }}
            .doc-body {{
                padding: 55px 42px 35px 42px;
                min-height: 560px;
                position: relative;
                text-align: left;
            }}
            .doc-title {{
                text-align: center;
                font-size: 34px;
                font-weight: 900;
                color: #123f78;
                margin-bottom: 36px;
                border-bottom: 5px solid #f4c430;
                width: fit-content;
                margin-left: auto;
                margin-right: auto;
                padding-bottom: 6px;
            }}
            .info-box {{
                border: 1px solid #e5e7eb;
                padding: 25px;
                background: rgba(255,255,255,0.88);
                position: relative;
                z-index: 2;
            }}
            .label {{
                color: #6b7280;
                font-size: 17px;
                font-weight: 800;
                margin-top: 18px;
                text-transform: uppercase;
            }}
            .value {{
                color: #111827;
                font-size: 27px;
                font-weight: 900;
                text-transform: uppercase;
                margin-bottom: 10px;
            }}
            .qr-bg {{
                display: block;
                width: 180px;
                opacity: 0.09;
                margin: 38px auto 8px auto;
            }}
            .scan-text {{
                text-align: center;
                color: #cbd5e1;
                font-weight: 800;
                letter-spacing: 1px;
            }}
            .footer {{
                border-top: 1px solid #e5e7eb;
                text-align: center;
                padding: 13px;
                font-size: 11px;
                font-weight: 900;
            }}
            .confirm {{
                text-align:center;
                color:#4b5563;
                font-size: 24px;
                line-height:1.4;
                margin-top: 28px;
            }}
            .confirm strong {{
                color:#123f78;
            }}
            @media(max-width: 700px) {{
                .doc-body {{
                    padding: 35px 22px;
                    min-height: 500px;
                }}
                .doc-title {{
                    font-size: 25px;
                }}
                .value {{
                    font-size: 21px;
                }}
                .header-text strong {{
                    font-size: 17px;
                }}
            }}
        </style>
    </head>
    <body>
        <div class="valid-badge">{badge_text}</div>

        <div class="doc-card">
            <div class="card-header">
                <img src="{city_logo}">
                <div class="header-text">
                    REPUBLIC OF THE PHILIPPINES<br>
                    CITY OF PARANAQUE
                    <strong>BARANGAY STO. NIÑO</strong>
                </div>
                <img src="{brgy_logo}">
            </div>

            <div class="doc-body">
                <div class="doc-title">DOCUMENT VERIFIED</div>

                <div class="info-box">
                    <div class="label">Document Type</div>
                    <div class="value">{doc_type}</div>

                    <div class="label">Issued To</div>
                    <div class="value">{fullname}</div>

                    <div class="label">Purpose</div>
                    <div class="value">{purpose}</div>

                    <div class="label">Date Issued</div>
                    <div class="value">{date_issued}</div>
                </div>

                <img class="qr-bg" src="{small_qr}">
                <div class="scan-text">SCAN TO RE-VERIFY</div>
            </div>

            <div class="footer">OFFICIAL BARANGAY DOCUMENT SYSTEM</div>
        </div>

        <div class="confirm">
            This page confirms the validity of<br>
            Reference No. <strong>{reference_no}</strong>.
        </div>
    </body>
    </html>
    """

@app.route('/view_id.php')
@role_required('Admin','Official')
def view_id():
    user_id=request.args.get('id')
    user=fetch_one('SELECT * FROM users WHERE id=%s', (user_id,))
    if not user:
        return 'User not found', 404
    return render_template('view_id.html', user=user, **common_admin_context())

if __name__ == '__main__':
    print('Q:DOC Flask starting...')
    print('Project folder:', BASE_DIR)
    print('.env path:', BASE_DIR / '.env')
    print('.env exists:', (BASE_DIR / '.env').exists())
    print('DB_USER:', os.getenv('DB_USER'))
    print('DB_PASSWORD loaded:', 'YES' if os.getenv('DB_PASSWORD') else 'NO')
    app.run(debug=True, host='0.0.0.0', port=5000)

