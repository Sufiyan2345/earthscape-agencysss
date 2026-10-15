from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from admin import admin_bp
from auth.decorators import admin_required
from models.user_model import User
from utils.database import log_activity


@admin_bp.route('/users')
@login_required
@admin_required
def users():
    role_filter = request.args.get('role', None)
    all_users = User.get_all(role=role_filter)
    return render_template('admin/users.html', users=all_users, active_page='users', role_filter=role_filter)


@admin_bp.route('/users/create', methods=['POST'])
@login_required
@admin_required
def create_user():
    username = request.form.get('username', '').strip()
    email = request.form.get('email', '').strip()
    full_name = request.form.get('full_name', '').strip()
    password = request.form.get('password', '')
    role = request.form.get('role', 'analyst')
    department = request.form.get('department', 'Climate Science')
    phone = request.form.get('phone', '')

    if not username or not email or not password or not full_name:
        flash('All required fields must be filled.', 'danger')
        return redirect(url_for('admin.users'))

    if User.get_by_username(username):
        flash('Username already exists.', 'danger')
        return redirect(url_for('admin.users'))

    if User.get_by_email(email):
        flash('Email already registered.', 'danger')
        return redirect(url_for('admin.users'))

    try:
        user_id = User.create(username, email, password, full_name, role, department, phone)
        log_activity(current_user.id, 'create_user', f'Created user {username}', request.remote_addr)
        flash(f'User {username} created successfully.', 'success')
    except Exception as e:
        flash(f'Error creating user: {str(e)}', 'danger')

    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_user(user_id):
    if user_id == current_user.id:
        flash('Cannot deactivate your own account.', 'danger')
        return redirect(url_for('admin.users'))

    User.toggle_active(user_id)
    log_activity(current_user.id, 'toggle_user', f'Toggled user {user_id}', request.remote_addr)
    flash('User status updated.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    if user_id == current_user.id:
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            return jsonify({'success': False, 'message': 'Cannot delete your own account.'}), 400
        flash('Cannot delete your own account.', 'danger')
        return redirect(url_for('admin.users'))

    User.delete_user(user_id)
    log_activity(current_user.id, 'delete_user', f'Deleted user {user_id}', request.remote_addr)

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({'success': True, 'message': 'User deleted successfully.'})

    flash('User deleted successfully.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>/change-role', methods=['POST'])
@login_required
@admin_required
def change_user_role(user_id):
    if user_id == current_user.id:
        flash('Cannot change your own role.', 'danger')
        return redirect(url_for('admin.users'))

    new_role = request.form.get('role', '').strip()
    if new_role not in ('admin', 'analyst'):
        flash('Invalid role.', 'danger')
        return redirect(url_for('admin.users'))

    User.change_role(user_id, new_role)
    log_activity(current_user.id, 'change_role', f'Changed role of user {user_id} to {new_role}', request.remote_addr)
    flash(f'User role changed to {new_role}.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/<int:user_id>')
@login_required
@admin_required
def view_user(user_id):
    user = User.get_by_id(user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin.users'))
    return render_template('admin/users.html', view_user=user, users=User.get_all(), active_page='users')
