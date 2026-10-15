"""
Notification and alert service for EarthScape Climate System.
Handles automated threshold checking, alert creation, and notification delivery.
"""
from models.alert_model import Alert
from utils.database import get_collection, next_id
from config import Config
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import math


def _safe_number(value):
    """Convert external reading values to finite floats or None."""
    if value is None or value == '':
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def get_thresholds():
    """Get unified alert thresholds from DB, falling back to config defaults."""
    col = get_collection('system_settings')
    docs = col.find({'setting_key': {'$regex': '^alert_threshold_'}})

    thresholds = dict(Config.ALERT_THRESHOLDS)
    for doc in docs:
        key = doc['setting_key'].replace('alert_threshold_', '')
        try:
            thresholds[key] = float(doc['setting_value'])
        except (ValueError, TypeError):
            pass
    return thresholds


def get_threshold_value(key):
    """Get a single threshold value by key (handles both with and without _max/_min)."""
    thresholds = get_thresholds()
    # Try exact match first
    if key in thresholds:
        return thresholds[key]
    # Try with _max suffix
    if f'{key}_max' in thresholds:
        return thresholds[f'{key}_max']
    # Try with _min suffix
    if f'{key}_min' in thresholds:
        return thresholds[f'{key}_min']
    return None


def check_and_create_alerts(data_point, source='realtime', location=None):
    """
    Check data point against thresholds and create alerts if exceeded.
    Returns list of created alert IDs.
    """
    thresholds = get_thresholds()
    alerts_created = []
    data_point = dict(data_point or {})
    for field in ('temperature', 'rainfall', 'wind_speed', 'air_quality_index',
                  'humidity', 'co2_level'):
        data_point[field] = _safe_number(data_point.get(field))

    def create_alert(**kwargs):
        kwargs['source'] = source
        kwargs['dedupe_key'] = f"{kwargs['category']}:{location or 'global'}"
        alert_id = Alert.create(**kwargs)
        if alert_id not in alerts_created:
            alerts_created.append(alert_id)
            _send_email_notification(alert_id)

    # Temperature checks
    temp = data_point.get('temperature')
    if temp is not None:
        if temp > thresholds.get('temperature_max', 45.0):
            create_alert(
                title='High Temperature Alert',
                message=f"Temperature {temp}°C exceeds threshold of {thresholds['temperature_max']}°C",
                alert_type='danger', severity='high', category='temperature',
                threshold_value=thresholds['temperature_max'],
                actual_value=temp, location=location, created_by=None
            )
        elif temp < thresholds.get('temperature_min', -30.0):
            create_alert(
                title='Low Temperature Alert',
                message=f"Temperature {temp}°C below threshold of {thresholds['temperature_min']}°C",
                alert_type='warning', severity='medium', category='temperature',
                threshold_value=thresholds['temperature_min'],
                actual_value=temp, location=location, created_by=None
            )

    # Rainfall check
    rainfall = data_point.get('rainfall')
    if rainfall is not None and rainfall > thresholds.get('rainfall_max', 200.0):
        create_alert(
            title='Heavy Rainfall Alert',
            message=f"Rainfall {rainfall}mm exceeds threshold of {thresholds['rainfall_max']}mm",
            alert_type='warning', severity='high', category='rainfall',
            threshold_value=thresholds['rainfall_max'],
            actual_value=rainfall, location=location, created_by=None
        )

    # Wind speed check
    wind = data_point.get('wind_speed')
    if wind is not None and wind > thresholds.get('wind_speed_max', 120.0):
        create_alert(
            title='High Wind Speed Alert',
            message=f"Wind speed {wind}km/h exceeds threshold of {thresholds['wind_speed_max']}km/h",
            alert_type='danger', severity='high', category='wind',
            threshold_value=thresholds['wind_speed_max'],
            actual_value=wind, location=location, created_by=None
        )

    # Air quality check
    aqi = data_point.get('air_quality_index')
    if aqi is not None and aqi > thresholds.get('air_quality_max', 300.0):
        create_alert(
            title='Poor Air Quality Alert',
            message=f"AQI {aqi} exceeds threshold of {thresholds['air_quality_max']}",
            alert_type='warning', severity='medium', category='air_quality',
            threshold_value=thresholds['air_quality_max'],
            actual_value=aqi, location=location, created_by=None
        )

    # Humidity check
    humidity = data_point.get('humidity')
    if humidity is not None and humidity > thresholds.get('humidity_max', 95.0):
        create_alert(
            title='High Humidity Alert',
            message=f"Humidity {humidity}% exceeds threshold of {thresholds['humidity_max']}%",
            alert_type='warning', severity='medium', category='humidity',
            threshold_value=thresholds['humidity_max'],
            actual_value=humidity, location=location, created_by=None
        )

    # CO2 check
    co2 = data_point.get('co2_level')
    if co2 is not None and co2 > thresholds.get('co2_max', 500.0):
        create_alert(
            title='High CO2 Level Alert',
            message=f"CO2 level {co2}ppm exceeds threshold of {thresholds['co2_max']}ppm",
            alert_type='warning', severity='medium', category='co2',
            threshold_value=thresholds['co2_max'],
            actual_value=co2, location=location, created_by=None
        )

    return alerts_created


def _send_email_notification(alert_id):
    """Send email notification for an alert if email notifications are enabled."""
    try:
        col = get_collection('system_settings')
        enabled = col.find_one({'setting_key': 'alert_email_enabled'})

        if not enabled or enabled.get('setting_value', '').lower() != 'true':
            return

        if not Config.MAIL_USERNAME or not Config.MAIL_PASSWORD:
            return

        alert = Alert.get_by_id(alert_id)
        if not alert:
            return

        recipients = _get_notification_recipients(alert.get('category'), alert.get('severity'))

        if not recipients:
            return

        subject = f"[EarthScape Alert] {alert.get('severity', 'medium').upper()}: {alert.get('title', 'Alert')}"
        body = f"""
        <html>
        <body style="font-family: Arial, sans-serif; line-height: 1.6;">
            <h2 style="color: #dc2626;">EarthScape Climate Alert</h2>
            <p><strong>Severity:</strong> {alert.get('severity', 'medium').upper()}</p>
            <p><strong>Category:</strong> {alert.get('category', 'weather').replace('_', ' ').title()}</p>
            <p><strong>Location:</strong> {alert.get('location') or 'Not specified'}</p>
            <p><strong>Message:</strong> {alert.get('message', '')}</p>
            <p><strong>Threshold:</strong> {alert.get('threshold_value')}</p>
            <p><strong>Actual Value:</strong> {alert.get('actual_value')}</p>
            <p><strong>Time:</strong> {alert.get('created_at')}</p>
            <hr style="margin: 20px 0; border: 1px solid #e5e7eb;">
            <p style="color: #6b7280; font-size: 12px;">This is an automated alert from EarthScape Climate System.</p>
        </body>
        </html>
        """

        msg = MIMEMultipart()
        msg['From'] = Config.MAIL_USERNAME
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'html'))

        for recipient in recipients:
            msg['To'] = recipient
            try:
                with smtplib.SMTP(Config.MAIL_SERVER, Config.MAIL_PORT) as server:
                    if Config.MAIL_USE_TLS:
                        server.starttls()
                    server.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
                    server.send_message(msg)
            except Exception as e:
                print(f"Failed to send email to {recipient}: {e}")
                continue

    except Exception as e:
        print(f"Email notification error: {e}")


def _get_notification_recipients(category=None, severity=None):
    """Get list of user emails who should receive this alert based on their preferences."""
    users_col = get_collection('users')
    prefs_col = get_collection('notification_preferences')

    cat = category or 'all'
    sev = severity or 'all'

    # Users who explicitly enabled this category+severity
    enabled_prefs = list(prefs_col.find({
        'category': cat, 'severity': sev, 'enabled': 1
    }))
    enabled_user_ids = {p['user_id'] for p in enabled_prefs}

    # All verified users with email
    verified_users = list(users_col.find({
        'is_verified': 1,
        'email': {'$ne': None, '$exists': True},
    }))

    # Users who have ANY preference set for this category+severity
    users_with_prefs = {p['user_id'] for p in prefs_col.find({
        'category': cat, 'severity': sev
    })}

    recipients = []
    for u in verified_users:
        uid = u['id']
        email = u.get('email')
        if not email:
            continue
        # Include if: explicitly enabled, OR has no preference set (defaults to enabled)
        if uid in enabled_user_ids or uid not in users_with_prefs:
            recipients.append(email)

    return recipients


def get_alert_delivery_config():
    """Return live alert delivery settings used by admin and analyst panels."""
    col = get_collection('system_settings')
    doc_email = col.find_one({'setting_key': 'alert_email_enabled'})
    doc_in_app = col.find_one({'setting_key': 'alert_in_app_enabled'})
    doc_realtime = col.find_one({'setting_key': 'alert_realtime_enabled'})
    doc_interval = col.find_one({'setting_key': 'alert_realtime_interval'})

    return {
        'email_enabled': str((doc_email or {}).get('setting_value', 'true')).lower() == 'true',
        'in_app_enabled': str((doc_in_app or {}).get('setting_value', 'true')).lower() == 'true',
        'realtime_enabled': str((doc_realtime or {}).get('setting_value', 'true')).lower() == 'true',
        'refresh_interval': int((doc_interval or {}).get('setting_value', '30000') or 30000),
    }


def set_alert_delivery_config(config):
    """Persist alert delivery settings into system settings."""
    col = get_collection('system_settings')
    mapping = {
        'alert_email_enabled': str(bool(config.get('email_enabled', True))).lower(),
        'alert_in_app_enabled': str(bool(config.get('in_app_enabled', True))).lower(),
        'alert_realtime_enabled': str(bool(config.get('realtime_enabled', True))).lower(),
        'alert_realtime_interval': str(max(15000, int(config.get('refresh_interval', 30000)))),
    }
    for key, value in mapping.items():
        existing = col.find_one({'setting_key': key})
        if existing:
            col.update_one({'setting_key': key}, {'$set': {'setting_value': value, 'updated_at': datetime.utcnow().isoformat()}})
        else:
            col.insert_one({
                'id': next_id('system_settings'),
                'setting_key': key,
                'setting_value': value,
                'setting_type': 'string',
                'description': 'Alert delivery configuration',
                'updated_at': datetime.utcnow().isoformat(),
            })


def get_user_notification_preferences(user_id):
    """Get notification preferences for a user."""
    col = get_collection('notification_preferences')
    docs = list(col.find({'user_id': user_id}))

    prefs = {}
    for doc in docs:
        key = f"{doc['category']}_{doc['severity']}"
        prefs[key] = {
            'enabled': bool(doc.get('enabled', 0)),
            'category': doc['category'],
            'severity': doc['severity']
        }

    # Default preferences if none set
    if not prefs:
        prefs = {
            'temperature_high': {'enabled': True, 'category': 'temperature', 'severity': 'high'},
            'temperature_medium': {'enabled': True, 'category': 'temperature', 'severity': 'medium'},
            'rainfall_high': {'enabled': True, 'category': 'rainfall', 'severity': 'high'},
            'air_quality_high': {'enabled': True, 'category': 'air_quality', 'severity': 'high'},
            'air_quality_medium': {'enabled': True, 'category': 'air_quality', 'severity': 'medium'},
            'wind_high': {'enabled': True, 'category': 'wind', 'severity': 'high'},
            'humidity_high': {'enabled': True, 'category': 'humidity', 'severity': 'high'},
            'co2_high': {'enabled': True, 'category': 'co2', 'severity': 'high'},
        }

    return prefs


def set_user_notification_preferences(user_id, preferences):
    """
    Set notification preferences for a user.
    preferences: dict with keys like 'temperature_high', 'rainfall_high', etc. and boolean values
    """
    col = get_collection('notification_preferences')

    # Delete existing preferences
    col.delete_many({'user_id': user_id})

    # Insert new preferences
    for key, enabled in preferences.items():
        parts = key.rsplit('_', 1)
        if len(parts) == 2:
            category, severity = parts
            col.insert_one({
                'user_id': user_id,
                'category': category,
                'severity': severity,
                'enabled': 1 if enabled else 0,
                'created_at': datetime.utcnow().isoformat(),
            })


# ========== Private per-user in-app notifications ==========
# Used for direct communication between Admin and a specific user
# (e.g. Admin responds to that user's feedback).

def create_user_notification(user_id, title, message, link='', category='feedback', reference=None):
    """Create a private in-app notification visible only to the given user."""
    col = get_collection('user_notifications')
    notif_id = next_id('user_notifications')
    col.insert_one({
        'id': notif_id,
        'user_id': user_id,
        'title': title,
        'message': message,
        'link': link,
        'category': category,
        'reference': reference or '',
        'is_read': 0,
        'created_at': datetime.utcnow().isoformat(),
    })
    return notif_id


def get_user_notifications(user_id, limit=10):
    """Latest private notifications for one user (newest first)."""
    return list(
        get_collection('user_notifications')
        .find({'user_id': user_id}).sort('created_at', -1).limit(limit)
    )


def get_user_unread_notification_count(user_id):
    key = 'notifications:unread:{}'.format(user_id)
    from utils.helper import get_cached_value
    return get_cached_value(key, lambda: get_collection('user_notifications').count_documents(
        {'user_id': user_id, 'is_read': 0}), ttl_seconds=15)


def user_can_receive_alert(user_id, category, severity):
    """Return whether a user's saved preference allows this alert."""
    prefs = list(get_collection('notification_preferences').find({
        'user_id': user_id,
        'category': category,
        'severity': severity,
    }))
    return not prefs or any(bool(pref.get('enabled')) for pref in prefs)


def get_user_alerts(user_id, limit=100):
    """Return global climate alerts allowed by the user's preferences."""
    preferences = list(get_collection('notification_preferences').find({
        'user_id': user_id,
    }))
    preference_map = {}
    for preference in preferences:
        preference_map.setdefault(
            (preference.get('category'), preference.get('severity')),
            [],
        ).append(bool(preference.get('enabled')))

    def allowed(alert):
        key = (alert.get('category', 'weather'), alert.get('severity', 'medium'))
        saved = preference_map.get(key)
        return not saved or any(saved)

    alerts = Alert.get_all(limit=max(limit * 3, limit))
    return [alert for alert in alerts if allowed(alert)][:limit]


def get_user_unread_alert_count(user_id):
    """Count unread global alerts visible to a user."""
    key = 'alerts:unread:{}'.format(user_id)
    from utils.helper import get_cached_value
    return get_cached_value(
        key,
        lambda: sum(1 for alert in get_user_alerts(user_id, limit=1000)
                    if not alert.get('is_read')),
        ttl_seconds=15,
    )


def get_support_recipients():
    """Return configured support recipients, falling back to active admins."""
    configured = get_collection('system_settings').find_one({'setting_key': 'support_email'})
    raw = (configured or {}).get('setting_value') or Config.SUPPORT_EMAIL
    recipients = [email.strip() for email in str(raw).split(',') if email.strip()]
    if recipients:
        return recipients
    return [u.get('email') for u in get_collection('users').find({
        'role': 'admin', 'email': {'$exists': True, '$ne': None}
    }) if u.get('email')]


def mark_user_notifications_read(user_id, reference=None):
    """Mark a user's private notifications as read (all, or one reference)."""
    query = {'user_id': user_id, 'is_read': 0}
    if reference:
        query['reference'] = reference
    get_collection('user_notifications').update_many(query, {'$set': {'is_read': 1}})


class NotificationManager:
    """Simple notification manager for backward compatibility."""

    @staticmethod
    def send_email(to_email=None, to=None, subject='', body=''):
        """Send an email notification."""
        recipient = to_email or to
        if not recipient:
            return False

        try:
            if not Config.MAIL_USERNAME or not Config.MAIL_PASSWORD:
                print(f"Email not configured. Would send to {recipient}: {subject}")
                return False

            msg = MIMEMultipart()
            msg['From'] = Config.MAIL_USERNAME
            msg['To'] = recipient
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))

            with smtplib.SMTP(Config.MAIL_SERVER, Config.MAIL_PORT) as server:
                if Config.MAIL_USE_TLS:
                    server.starttls()
                server.login(Config.MAIL_USERNAME, Config.MAIL_PASSWORD)
                server.send_message(msg)
            return True
        except Exception as e:
            print(f"Failed to send email to {recipient}: {e}")
            return False
