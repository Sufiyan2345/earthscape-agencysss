from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from admin import admin_bp
from auth.decorators import admin_required
from utils.database import get_collection, next_id
from config import Config
from datetime import datetime
import json


@admin_bp.route('/settings')
@login_required
@admin_required
def settings():
    col = get_collection('system_settings')
    settings_list = list(col.find().sort('setting_key', 1))

    # If no settings exist, create defaults
    if not settings_list:
        _init_default_settings()
        settings_list = list(col.find().sort('setting_key', 1))

    # Get current thresholds from DB or config
    thresholds = _get_thresholds()

    return render_template('admin/settings.html',
                         settings=[dict(s) for s in settings_list],
                         thresholds=thresholds,
                         active_page='settings')


@admin_bp.route('/settings/update', methods=['POST'])
@login_required
@admin_required
def update_settings():
    col = get_collection('system_settings')
    keys = request.form.getlist('setting_key')
    values = request.form.getlist('setting_value')

    updated_count = 0
    for key, value in zip(keys, values):
        col.update_one(
            {'setting_key': key},
            {'$set': {'setting_value': value, 'updated_by': current_user.id, 'updated_at': datetime.utcnow().isoformat()}},
        )
        updated_count += 1

    flash(f'{updated_count} settings updated successfully.', 'success')
    return redirect(url_for('admin.settings'))


@admin_bp.route('/settings/thresholds', methods=['POST'])
@login_required
@admin_required
def update_thresholds():
    """Persist alert thresholds to the database."""
    col = get_collection('system_settings')

    threshold_keys = {
        'temperature_max': request.form.get('temperature_max', 45.0, type=float),
        'temperature_min': request.form.get('temperature_min', -30.0, type=float),
        'rainfall_max': request.form.get('rainfall_max', 200.0, type=float),
        'wind_speed_max': request.form.get('wind_speed_max', 120.0, type=float),
        'air_quality_max': request.form.get('air_quality_max', 300.0, type=float),
        'humidity_max': request.form.get('humidity_max', 95.0, type=float),
        'co2_max': request.form.get('co2_max', 500.0, type=float),
    }

    for key, value in threshold_keys.items():
        setting_key = f'alert_threshold_{key}'
        existing = col.find_one({'setting_key': setting_key})

        if existing:
            col.update_one(
                {'setting_key': setting_key},
                {'$set': {'setting_value': str(value), 'updated_by': current_user.id, 'updated_at': datetime.utcnow().isoformat()}},
            )
        else:
            col.insert_one({
                'id': next_id('system_settings'),
                'setting_key': setting_key,
                'setting_value': str(value),
                'setting_type': 'float',
                'description': f'Alert threshold for {key.replace("_", " ")}',
                'updated_by': current_user.id,
            })

    flash('Alert thresholds updated and saved successfully.', 'success')
    return redirect(url_for('admin.settings'))


@admin_bp.route('/settings/add', methods=['POST'])
@login_required
@admin_required
def add_setting():
    """Add a new system setting."""
    key = request.form.get('setting_key', '').strip()
    value = request.form.get('setting_value', '').strip()
    setting_type = request.form.get('setting_type', 'string')
    description = request.form.get('description', '')

    if not key:
        flash('Setting key is required.', 'danger')
        return redirect(url_for('admin.settings'))

    col = get_collection('system_settings')
    try:
        existing = col.find_one({'setting_key': key})
        if existing:
            flash(f'Setting "{key}" already exists. Use edit instead.', 'danger')
        else:
            col.insert_one({
                'id': next_id('system_settings'),
                'setting_key': key,
                'setting_value': value,
                'setting_type': setting_type,
                'description': description,
                'updated_by': current_user.id,
            })
            flash(f'Setting "{key}" added successfully.', 'success')
    except Exception as e:
        flash(f'Failed to add setting: {str(e)}', 'danger')

    return redirect(url_for('admin.settings'))


@admin_bp.route('/settings/<int:setting_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_setting(setting_id):
    """Delete a system setting."""
    col = get_collection('system_settings')
    col.delete_one({'id': setting_id})
    flash('Setting deleted successfully.', 'success')
    return redirect(url_for('admin.settings'))


def _get_thresholds():
    """Get alert thresholds from DB, falling back to config defaults."""
    col = get_collection('system_settings')
    rows = list(col.find({'setting_key': {'$regex': '^alert_threshold_'}}))

    thresholds = dict(Config.ALERT_THRESHOLDS)
    for row in rows:
        key = row['setting_key'].replace('alert_threshold_', '')
        try:
            thresholds[key] = float(row['setting_value'])
        except (ValueError, TypeError):
            pass
    return thresholds


def _init_default_settings():
    """Initialize default system settings in the database."""
    defaults = [
        ('system_name', 'EarthScape Climate System', 'string', 'Application name'),
        ('system_version', '1.0.0', 'string', 'Application version'),
        ('maintenance_mode', 'false', 'boolean', 'Enable maintenance mode'),
        ('max_upload_size_mb', '500', 'integer', 'Maximum upload file size in MB'),
        ('data_retention_days', '365', 'integer', 'Days to retain historical data'),
        ('auto_backup_enabled', 'true', 'boolean', 'Enable automatic daily backups'),
        ('backup_time', '02:00', 'string', 'Daily backup time (24h format)'),
        ('log_level', 'INFO', 'string', 'Application log level'),
        ('session_timeout_minutes', '60', 'integer', 'User session timeout'),
        ('max_login_attempts', '5', 'integer', 'Maximum failed login attempts before lockout'),
        ('registration_enabled', 'true', 'boolean', 'Allow new user registration'),
        ('email_notifications', 'true', 'boolean', 'Enable email notifications'),
        ('alert_threshold_temperature_max', '45.0', 'float', 'Alert threshold for max temperature'),
        ('alert_threshold_temperature_min', '-30.0', 'float', 'Alert threshold for min temperature'),
        ('alert_threshold_rainfall_max', '200.0', 'float', 'Alert threshold for max rainfall'),
        ('alert_threshold_humidity_max', '95.0', 'float', 'Alert threshold for max humidity'),
        ('alert_threshold_wind_speed_max', '120.0', 'float', 'Alert threshold for max wind speed'),
        ('alert_threshold_air_quality_max', '300.0', 'float', 'Alert threshold for max AQI'),
        ('alert_threshold_co2_max', '500.0', 'float', 'Alert threshold for max CO2'),
    ]

    col = get_collection('system_settings')
    for key, value, stype, desc in defaults:
        try:
            existing = col.find_one({'setting_key': key})
            if not existing:
                col.insert_one({
                    'id': next_id('system_settings'),
                    'setting_key': key,
                    'setting_value': value,
                    'setting_type': stype,
                    'description': desc,
                })
        except Exception:
            pass

