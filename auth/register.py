from flask import render_template, request, redirect, url_for, flash
from auth import auth_bp
from models.user_model import User


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        full_name = request.form.get('full_name', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        phone = request.form.get('phone', '')

        # Public registration can create analyst accounts only. Admin roles
        # are assigned by an authenticated administrator.
        role = 'analyst'

        errors = []
        if not username or len(username) < 3:
            errors.append('Username must be at least 3 characters.')
        if not email or '@' not in email:
            errors.append('Valid email is required.')
        if not full_name:
            errors.append('Full name is required.')
        if not password or len(password) < 6:
            errors.append('Password must be at least 6 characters.')
        if password != confirm_password:
            errors.append('Passwords do not match.')

        if User.get_by_username(username):
            errors.append('Username already exists.')
        if User.get_by_email(email):
            errors.append('Email already registered.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('auth/register.html')

        try:
            User.create(
                username=username,
                email=email,
                password=password,
                full_name=full_name,
                role=role,
                phone=phone
            )
            panel = 'Admin Panel' if role == 'admin' else 'Analyst Panel'
            flash(f'Account created successfully! You will be directed to the {panel} after login.', 'success')
            return redirect(url_for('auth.login'))
        except Exception as e:
            flash(f'Registration failed: {str(e)}', 'danger')

    return render_template('auth/register.html')
