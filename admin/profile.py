import os
from werkzeug.utils import secure_filename
from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from admin import admin_bp
from auth.decorators import admin_required
from models.feedback_model import Feedback
from models.dataset_model import Dataset
from models.alert_model import Alert
from utils.database import get_collection, next_id

PROFILE_UPLOAD_FOLDER = os.path.join('static', 'uploads', 'profiles')
ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'}


def _allowed_image(filename):
    return '.' in filename and \
        filename.rsplit('.', 1)[1].lower() in ALLOWED_IMAGE_EXTENSIONS


def _save_profile_image(file, prefix):
    """Save an uploaded image under static/uploads/profiles and return its path."""
    if not file or not file.filename:
        return None
    if not _allowed_image(file.filename):
        flash('Unsupported image format. Allowed: PNG, JPG, JPEG, GIF, WEBP, BMP.', 'danger')
        return False
    os.makedirs(PROFILE_UPLOAD_FOLDER, exist_ok=True)
    ext = file.filename.rsplit('.', 1)[1].lower()
    safe_name = '{}_{}.{}'.format(prefix, current_user.id, ext)
    filepath = os.path.abspath(os.path.join(PROFILE_UPLOAD_FOLDER, safe_name))
    file.save(filepath)
    return 'uploads/profiles/' + safe_name


@admin_bp.route('/profile', methods=['GET', 'POST'])
@login_required
@admin_required
def profile():
    """Handle admin profile updates, password changes, and display account stats."""
    if request.method == 'POST':
        action = request.form.get('action', 'update_profile')

        if action == 'update_profile':
            full_name = request.form.get('full_name', '').strip()
            email = request.form.get('email', '').strip()
            phone = request.form.get('phone', '').strip()
            department = request.form.get('department', '').strip()

            if not full_name or not email:
                flash('Full name and email are required.', 'danger')
            else:
                # Check if email is already taken by another user
                users_col = get_collection('users')
                existing = users_col.find_one({'email': email, 'id': {'$ne': current_user.id}})
                if existing:
                    flash('That email is already in use by another account.', 'danger')
                else:
                    updates = {
                        'full_name': full_name,
                        'email': email,
                        'phone': phone,
                        'department': department,
                    }

                    avatar_path = _save_profile_image(request.files.get('avatar'), 'avatar')
                    if avatar_path is False:
                        return redirect(url_for('admin.profile'))
                    if avatar_path:
                        updates['avatar'] = avatar_path

                    banner_path = _save_profile_image(request.files.get('banner'), 'banner')
                    if banner_path is False:
                        return redirect(url_for('admin.profile'))
                    if banner_path:
                        updates['banner'] = banner_path

                    current_user.update_profile(**updates)
                    flash('Profile updated successfully.', 'success')

        elif action == 'change_password':
            current_password = request.form.get('current_password', '')
            new_password = request.form.get('new_password', '')
            confirm_password = request.form.get('confirm_password', '')

            if not current_password:
                flash('Current password is required.', 'danger')
            elif not current_user.check_password(current_password):
                flash('Current password is incorrect.', 'danger')
            elif len(new_password) < 6:
                flash('New password must be at least 6 characters.', 'danger')
            elif new_password != confirm_password:
                flash('New passwords do not match.', 'danger')
            else:
                current_user.update_password(new_password)
                flash('Password changed successfully.', 'success')

        elif action == 'update_preferences':
            theme = request.form.get('theme', 'light')
            notifications = request.form.get('notifications', 'enabled')
            settings_col = get_collection('system_settings')
            for key, value in [('theme', theme), ('email_notifications', notifications)]:
                setting_key = f'user_pref_{key}'
                existing = settings_col.find_one({'setting_key': setting_key, 'user_id': current_user.id})
                if existing:
                    settings_col.update_one(
                        {'id': existing['id']},
                        {'$set': {'setting_value': value}},
                    )
                else:
                    settings_col.insert_one({
                        'id': next_id('system_settings'),
                        'setting_key': setting_key,
                        'setting_value': value,
                        'user_id': current_user.id,
                    })
            flash('Preferences updated.', 'success')

        return redirect(url_for('admin.profile'))

    # GET: Load admin stats
    users_col = get_collection('users')
    total_users = users_col.count_documents({})

    total_datasets = len(Dataset.get_all())
    total_alerts = len(Alert.get_all())
    total_feedback = len(Feedback.get_all())

    # Recent activity
    recent_activity = [
        {'icon': 'sign-in-alt', 'description': 'Logged in', 'time': 'Just now'},
        {'icon': 'user-shield', 'description': 'Admin access granted', 'time': 'Account creation'},
    ]

    return render_template('admin/profile.html',
                         active_page='profile',
                         total_users=total_users,
                         total_datasets=total_datasets,
                         total_alerts=total_alerts,
                         total_feedback=total_feedback,
                         recent_activity=recent_activity)
