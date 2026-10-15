from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from admin import admin_bp
from auth.decorators import admin_required
from models.alert_model import Alert
from utils.notifications import (
    get_thresholds, check_and_create_alerts,
    get_user_notification_preferences, set_user_notification_preferences,
    get_user_notifications, get_user_unread_notification_count,
    mark_user_notifications_read, get_alert_delivery_config, set_alert_delivery_config
)
from utils.database import get_collection, next_id
from datetime import datetime as dt


@admin_bp.route('/alerts', methods=['GET', 'POST'])
@login_required
@admin_required
def alerts():
    if request.method == 'POST' and request.form.get('action') == 'update_thresholds':
        settings_col = get_collection('system_settings')
        # Unified keys matching check_and_create_alerts() lookups
        threshold_map = {
            'temperature_max': request.form.get('temperature_max', ''),
            'temperature_min': request.form.get('temperature_min', ''),
            'rainfall_max': request.form.get('rainfall_max', ''),
            'wind_speed_max': request.form.get('wind_speed_max', ''),
            'air_quality_max': request.form.get('air_quality_max', ''),
            'humidity_max': request.form.get('humidity_max', ''),
            'co2_max': request.form.get('co2_max', ''),
        }
        updated = 0
        for key, value in threshold_map.items():
            if not value:
                continue
            try:
                value = str(float(value))
            except ValueError:
                flash(f'Invalid value for {key.replace("_", " ")} — skipped.', 'warning')
                continue
            setting_key = f'alert_threshold_{key}'
            existing = settings_col.find_one({'setting_key': setting_key})
            if existing:
                settings_col.update_one(
                    {'setting_key': setting_key},
                    {'$set': {'setting_value': value, 'updated_by': current_user.id,
                              'updated_at': dt.utcnow().isoformat()}},
                )
            else:
                settings_col.insert_one({
                    'id': next_id('system_settings'),
                    'setting_key': setting_key,
                    'setting_value': value,
                    'setting_type': 'float',
                    'description': f'Alert threshold for {key.replace("_", " ")}',
                })
            updated += 1
        flash(f'Alert thresholds updated ({updated} settings saved).', 'success')
        return redirect(url_for('admin.alerts'))

    if request.method == 'POST' and request.form.get('action') == 'update_delivery_settings':
        config = {
            'email_enabled': request.form.get('alert_email_enabled') == 'on',
            'in_app_enabled': request.form.get('alert_in_app_enabled') == 'on',
            'realtime_enabled': request.form.get('alert_realtime_enabled') == 'on',
            'refresh_interval': request.form.get('alert_refresh_interval', 30000, type=int),
        }
        set_alert_delivery_config(config)
        flash('Notification delivery settings updated.', 'success')
        return redirect(url_for('admin.alerts'))

    severity = request.args.get('severity', None)
    all_alerts = Alert.get_all(severity=severity)
    unread_count = Alert.get_unread_count()
    thresholds = get_thresholds()
    delivery_config = get_alert_delivery_config()
    return render_template('admin/alerts.html', alerts=all_alerts, unread_count=unread_count,
                         active_page='alerts', severity_filter=severity, thresholds=thresholds,
                         delivery_config=delivery_config)


@admin_bp.route('/alerts/<int:alert_id>/read', methods=['POST'])
@login_required
@admin_required
def read_alert(alert_id):
    Alert.mark_read(alert_id)
    return redirect(url_for('admin.alerts'))


@admin_bp.route('/alerts/read-all', methods=['POST'])
@login_required
@admin_required
def read_all_alert():
    Alert.mark_all_read()
    mark_user_notifications_read(current_user.id)
    flash('All alerts marked as read.', 'success')
    return redirect(url_for('admin.alerts'))


@admin_bp.route('/alerts/<int:alert_id>')
@login_required
@admin_required
def view_alert(alert_id):
    """View detailed information about a specific alert."""
    alert = Alert.get_by_id(alert_id)
    if not alert:
        flash('Alert not found.', 'danger')
        return redirect(url_for('admin.alerts'))
    return render_template('admin/alert_detail.html',
                         alert=alert,
                         active_page='alerts')


@admin_bp.route('/alerts/<int:alert_id>/resolve', methods=['POST'])
@login_required
@admin_required
def resolve_alert(alert_id):
    Alert.resolve(alert_id, current_user.id)
    flash('Alert resolved.', 'success')
    return redirect(url_for('admin.alerts'))


@admin_bp.route('/alerts/<int:alert_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_alert(alert_id):
    Alert.delete(alert_id)
    flash('Alert deleted.', 'success')
    return redirect(url_for('admin.alerts'))


@admin_bp.route('/alerts/create', methods=['POST'])
@login_required
@admin_required
def create_alert():
    title = request.form.get('title', '').strip()
    message = request.form.get('message', '').strip()
    severity = request.form.get('severity', 'medium')
    category = request.form.get('category', 'weather')

    if not title or not message:
        flash('Title and message are required.', 'danger')
        return redirect(url_for('admin.alerts'))

    Alert.create(title=title, message=message, severity=severity,
                category=category, created_by=current_user.id)
    flash('Alert created.', 'success')
    return redirect(url_for('admin.alerts'))


@admin_bp.route('/alerts/unread-count')
@login_required
def unread_count():
    return jsonify({'count': Alert.get_unread_count() + get_user_unread_notification_count(current_user.id)})


@admin_bp.route('/alerts/recent')
@login_required
def recent_alerts():
    """JSON endpoint for notification dropdown."""
    limit = request.args.get('limit', 5, type=int)
    result = []
    for n in get_user_notifications(current_user.id, limit=limit):
        result.append({
            'id': n['id'], 'title': n['title'], 'message': n['message'][:100],
            'severity': 'info', 'category': n.get('category', 'feedback'),
            'is_read': n['is_read'], 'created_at': n['created_at'],
            'link': n.get('link', ''),
        })
    alerts = Alert.get_all(limit=limit)
    for a in alerts:
        result.append({
            'id': a['id'],
            'title': a['title'],
            'message': a['message'][:100],
            'severity': a['severity'],
            'category': a['category'],
            'is_read': a['is_read'],
            'created_at': a['created_at'], 'link': ''
        })
    return jsonify({'alerts': result[:limit * 2], 'unread': Alert.get_unread_count() + get_user_unread_notification_count(current_user.id)})


@admin_bp.route('/alerts/check-now', methods=['POST'])
@login_required
@admin_required
def check_alerts_now():
    """Manually trigger threshold check on latest realtime readings."""
    try:
        col = get_collection('realtime_readings')
        readings = list(col.find().sort('timestamp', -1).limit(10))
        
        created = 0
        for r in readings:
            data = dict(r)
            alerts = check_and_create_alerts(data, source='manual_check')
            created += len(alerts)
        
        flash(f'Threshold check complete: {created} new alerts created.', 'success')
    except Exception as e:
        flash(f'Alert check failed: {str(e)}', 'danger')
    return redirect(url_for('admin.alerts'))


@admin_bp.route('/alerts/bulk-action', methods=['POST'])
@login_required
@admin_required
def bulk_alert_action():
    """Bulk resolve or delete selected alerts."""
    action = request.form.get('action', '')
    alert_ids = request.form.getlist('alert_ids')
    
    if not alert_ids:
        flash('No alerts selected.', 'warning')
        return redirect(url_for('admin.alerts'))
    
    count = 0
    alerts_col = get_collection('alerts')
    try:
        int_ids = [int(aid) for aid in alert_ids]
        if action == 'resolve':
            alerts_col.update_many(
                {'id': {'$in': int_ids}},
                {'$set': {'is_resolved': 1, 'resolved_by': current_user.id, 'resolved_at': dt.utcnow().isoformat()}},
            )
            count = len(alert_ids)
            flash(f'{count} alerts resolved.', 'success')
        elif action == 'delete':
            alerts_col.delete_many({'id': {'$in': int_ids}})
            count = len(alert_ids)
            flash(f'{count} alerts deleted.', 'success')
    except Exception as e:
        flash(f'Bulk action failed: {str(e)}', 'danger')
    
    return redirect(url_for('admin.alerts'))


@admin_bp.route('/alerts/preferences', methods=['GET', 'POST'])
@login_required
def alert_preferences():
    """Manage per-user notification preferences."""
    if request.method == 'POST':
        prefs = {}
        for key in request.form:
            if key.startswith('pref_'):
                category_severity = key.replace('pref_', '')
                prefs[category_severity] = request.form.get(key) == 'on'
        
        set_user_notification_preferences(current_user.id, prefs)
        flash('Notification preferences updated.', 'success')
        return redirect(url_for('admin.alert_preferences'))
    
    prefs = get_user_notification_preferences(current_user.id)
    return render_template('admin/alert_preferences.html',
                         preferences=prefs,
                         active_page='alerts')


@admin_bp.route('/alerts/rules')
@login_required
@admin_required
def alert_rules():
    """View and manage alert rule enable/disable toggles."""
    from utils.notifications import get_threshold_value
    settings_col = get_collection('system_settings')
    
    # Define all alert rules with their database keys
    rules = []
    rule_defs = [
        ('temperature_max', 'temperature', 'Temperature Threshold', '°C'),
        ('rainfall_max', 'rainfall', 'Rainfall Threshold', 'mm'),
        ('co2_max', 'co2', 'CO₂ Threshold', 'ppm'),
        ('humidity_max', 'humidity_low', 'Humidity Low Threshold', '%'),
        ('wind_speed_max', 'wind_speed', 'Wind Speed Threshold', 'km/h'),
        ('air_quality_max', 'air_quality', 'Air Quality Threshold', 'AQI'),
    ]
    for db_key, rule_key, name, unit in rule_defs:
        enabled_doc = settings_col.find_one({'setting_key': f'alert_rule_enabled_{rule_key}'})
        enabled = True if not enabled_doc else enabled_doc.get('setting_value', 'true') == 'true'
        threshold_val = get_threshold_value(db_key)
        threshold_display = f"{threshold_val}" if threshold_val is not None else 'Not Set'
        rules.append({
            'key': rule_key,
            'db_key': db_key,
            'name': name,
            'unit': unit,
            'threshold': threshold_display,
            'enabled': enabled,
        })
    
    return render_template('admin/alert_rules.html', rules=rules, active_page='alerts')


@admin_bp.route('/alerts/rules/<rule_key>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_alert_rule(rule_key):
    """Enable or disable a specific alert rule."""
    settings_col = get_collection('system_settings')
    doc = settings_col.find_one({'setting_key': f'alert_rule_enabled_{rule_key}'})
    
    if doc:
        current = doc.get('setting_value', 'true') == 'true'
        new_val = 'false' if current else 'true'
        settings_col.update_one(
            {'setting_key': f'alert_rule_enabled_{rule_key}'},
            {'$set': {'setting_value': new_val}}
        )
    else:
        # If no record exists, the rule was enabled by default; disable it
        from utils.database import next_id
        from datetime import datetime
        settings_col.insert_one({
            'id': next_id('system_settings'),
            'setting_key': f'alert_rule_enabled_{rule_key}',
            'setting_value': 'false',
            'setting_type': 'boolean',
            'description': f'Enable {rule_key} alert rule',
            'updated_by': current_user.id,
            'updated_at': datetime.utcnow().isoformat(),
            'user_id': None,
        })
    
    flash(f'Alert rule "{rule_key}" toggled.', 'success')
    return redirect(url_for('admin.alert_rules'))
