from flask import render_template, request, redirect, url_for, flash
from flask_login import login_user, current_user
from auth import auth_bp
from models.user_model import User
from urllib.parse import urlsplit
from time import monotonic


_LOGIN_FAILURES = {}
_MAX_LOGIN_ATTEMPTS = 5
_LOCKOUT_SECONDS = 300


def _login_key(username):
    return '{}:{}'.format(request.remote_addr or 'unknown', username.lower())


def _is_safe_next(target):
    """Only allow local relative redirects after authentication."""
    if not target:
        return False
    parsed = urlsplit(target)
    return not parsed.scheme and not parsed.netloc and target.startswith('/') and not target.startswith('//')


def _is_role_destination(target, role):
    """Prevent post-login redirects into a panel the authenticated role cannot use."""
    if not _is_safe_next(target):
        return False
    path = urlsplit(target).path
    prefix = '/admin' if role == 'admin' else '/analyst'
    return path == prefix or path.startswith(prefix + '/')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('analyst.dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        remember = request.form.get('remember', False)

        if not username or not password:
            flash('Please provide both username and password.', 'danger')
            return render_template('auth/login.html')

        key = _login_key(username)
        now = monotonic()
        failure = _LOGIN_FAILURES.get(key)
        if failure and now - failure['started'] < _LOCKOUT_SECONDS and failure['count'] >= _MAX_LOGIN_ATTEMPTS:
            flash('Too many failed attempts. Please try again in a few minutes.', 'warning')
            return render_template('auth/login.html'), 429
        if failure and now - failure['started'] >= _LOCKOUT_SECONDS:
            _LOGIN_FAILURES.pop(key, None)

        user = User.get_by_username(username)
        if user is None:
            user = User.get_by_email(username)

        if user is None or not user.check_password(password):
            failure = _LOGIN_FAILURES.setdefault(key, {'count': 0, 'started': now})
            if now - failure['started'] >= _LOCKOUT_SECONDS:
                failure.update(count=0, started=now)
            failure['count'] += 1
            flash('Invalid username or password.', 'danger')
            return render_template('auth/login.html')

        if not user.is_active:
            flash('Your account has been deactivated. Contact administrator.', 'danger')
            return render_template('auth/login.html')

        login_user(user, remember=bool(remember))
        _LOGIN_FAILURES.pop(key, None)
        user.record_login()

        next_page = request.args.get('next')
        if _is_role_destination(next_page, user.role):
            return redirect(next_page)

        if user.role == 'admin':
            return redirect(url_for('admin.dashboard'))
        return redirect(url_for('analyst.dashboard'))

    return render_template('auth/login.html')
