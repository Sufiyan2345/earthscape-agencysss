from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from admin import admin_bp
from auth.decorators import admin_required
from models.feedback_model import Feedback
from models.dataset_model import Dataset
from models.alert_model import Alert
from utils.database import get_collection, next_id
from utils.profile_images import save_profile_image


def _save_profile_image(file, prefix):
    """Persist a profile image and return its legacy URL path."""
    try:
        return save_profile_image(file, prefix, current_user.id)
    except ValueError as exc:
        flash(str(exc), 'danger')
        return False


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
