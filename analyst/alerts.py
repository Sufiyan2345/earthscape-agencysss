from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from analyst import analyst_bp
from auth.decorators import analyst_required
from models.alert_model import Alert
from utils.notifications import (
    get_thresholds, check_and_create_alerts,
    get_user_notification_preferences, set_user_notification_preferences,
    get_user_notifications, get_user_unread_notification_count,
    mark_user_notifications_read, get_user_alerts, get_user_unread_alert_count,
    get_alert_delivery_config
)
from utils.database import get_collection


@analyst_bp.route('/alerts')
@login_required
@analyst_required
def alerts():
    """Analyst = monitor only: view/filter alerts and mark them read.
    Thresholds, resolving and deleting are Admin responsibilities."""
    filter_type = request.args.get('filter', 'all')
    if request.args.get('mark_all_read') == 'true':
        Alert.mark_all_read()
        flash('All alerts marked as read.', 'success')
        return redirect(url_for('analyst.alerts'))

    all_alerts = get_user_alerts(current_user.id, limit=100)
    if filter_type != 'all':
        all_alerts = [a for a in all_alerts if a.get('severity', '') == filter_type]

    unread_count = get_user_unread_alert_count(current_user.id)
    thresholds = get_thresholds()
    severity_counts = Alert.get_by_severity()
    delivery_config = get_alert_delivery_config()

    return render_template('analyst/alerts.html',
                         alerts=all_alerts,
                         unread_count=unread_count,
                         thresholds=thresholds,
                         severity_counts=severity_counts,
                         filter_type=filter_type,
                         delivery_config=delivery_config,
                         active_page='alerts')


@analyst_bp.route('/alerts/<int:alert_id>')
@login_required
@analyst_required
def view_alert(alert_id):
    """View detailed information about a specific alert."""
    alert = Alert.get_by_id(alert_id)
    if not alert:
        flash('Alert not found.', 'danger')
        return redirect(url_for('analyst.alerts'))
    return render_template('analyst/alert_detail.html',
                         alert=alert,
                         active_page='alerts')


@analyst_bp.route('/alerts/<int:alert_id>/read', methods=['POST'])
@login_required
@analyst_required
def read_alert(alert_id):
    Alert.mark_read(alert_id)
    return redirect(url_for('analyst.alerts'))


@analyst_bp.route('/alerts/<int:alert_id>/delete', methods=['POST'])
@login_required
@analyst_required
def delete_alert(alert_id):
    alert = Alert.get_by_id(alert_id)
    if not alert:
        flash('Alert not found.', 'danger')
        return redirect(url_for('analyst.alerts'))
    Alert.delete(alert_id)
    flash(f'Alert "{alert.get("title", "")}" deleted.', 'success')
    return redirect(url_for('analyst.alerts'))


@analyst_bp.route('/alerts/read-all', methods=['POST'])
@login_required
@analyst_required
def read_all_alert():
    Alert.mark_all_read()
    mark_user_notifications_read(current_user.id)
    flash('All alerts marked as read.', 'success')
    return redirect(url_for('analyst.alerts'))


@analyst_bp.route('/alerts/unread-count')
@login_required
def unread_count():
    return jsonify({'count': Alert.get_unread_count()
                    + get_user_unread_notification_count(current_user.id)})


@analyst_bp.route('/alerts/recent')
@login_required
def recent_alerts():
    """JSON endpoint for notification dropdown (climate alerts + private
    notifications such as Admin feedback responses)."""
    limit = request.args.get('limit', 5, type=int)
    result = []

    # Private notifications for this user first (direct Admin -> user messages)
    for n in get_user_notifications(current_user.id, limit=limit):
        result.append({
            'id': n['id'],
            'title': n['title'],
            'message': n['message'][:100],
            'severity': 'info',
            'category': n.get('category', 'feedback'),
            'is_read': n['is_read'],
            'created_at': n['created_at'],
            'link': n.get('link', ''),
        })

    for a in get_user_alerts(current_user.id, limit=limit):
        result.append({
            'id': a['id'],
            'title': a['title'],
            'message': a['message'][:100],
            'severity': a['severity'],
            'category': a['category'],
            'is_read': a['is_read'],
            'created_at': a['created_at'],
            'link': '',
        })

    unread = get_user_unread_alert_count(current_user.id) + get_user_unread_notification_count(current_user.id)
    return jsonify({'alerts': result[:limit * 2], 'unread': unread})


@analyst_bp.route('/alerts/check-now', methods=['POST'])
@login_required
@analyst_required
def check_alerts_now():
    """Manually re-run the threshold check on the latest realtime readings
    so analysts can spot significant events immediately."""
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
    return redirect(url_for('analyst.alerts'))


@analyst_bp.route('/alerts/preferences', methods=['GET', 'POST'])
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
        return redirect(url_for('analyst.alert_preferences'))

    prefs = get_user_notification_preferences(current_user.id)
    return render_template('analyst/alert_preferences.html',
                         preferences=prefs,
                         active_page='alerts')
