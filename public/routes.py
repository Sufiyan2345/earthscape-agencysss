from flask import render_template, request, redirect, url_for, flash, jsonify, send_file, session
from public import public_bp
from models.feedback_model import Feedback
from models.knowledge_model import KnowledgeBase
from models.climate_model import ClimateData
from models.alert_model import Alert
from models.realtime_model import RealtimeStream
from models.imagery_model import SatelliteImage
from utils.notifications import NotificationManager
from utils.database import get_collection
import os


def _safe_float(value):
    """Coerce stored values (strings included) to a rounded float; None if invalid."""
    if value is None or value == '':
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _public_stats():
    """Live figures from the database for the public landing page.
    Never raises — an empty/broken DB just renders zeros."""
    stats = {'total_records': 0, 'regions': 0, 'years': 0, 'alerts': 0}
    try:
        summary = ClimateData.get_summary()
        stats['total_records'] = int(summary.get('total_records') or 0)
        stats['regions'] = len(ClimateData.get_regions())
        stats['years'] = len(ClimateData.get_available_years())
        stats['alerts'] = Alert.get_count()
    except Exception:
        pass
    return stats


def _public_indicators():
    """Live climate indicators from the database for Climate Insights."""
    indicators = {'avg_temp': 0, 'avg_rainfall': 0, 'avg_co2': 0,
                  'avg_aqi': 0, 'avg_humidity': 0, 'total_records': 0}
    try:
        summary = ClimateData.get_summary()
        for key in indicators:
            indicators[key] = round(float(summary.get(key) or 0), 1)
    except Exception:
        pass
    return indicators


@public_bp.route('/')
def index():
    stations, realtime_summary = _public_realtime()
    return render_template('public/index.html', stats=_public_stats(),
                         images=_public_imagery(limit=8),
                         realtime_stations=stations,
                         realtime_summary=realtime_summary)


@public_bp.route('/about')
def about():
    return render_template('public/about.html')


@public_bp.route('/services')
def services():
    return render_template('public/services.html')


@public_bp.route('/climate-insights')
def climate_insights():
    years = []
    try:
        years = ClimateData.get_available_years()
    except Exception:
        pass
    return render_template('public/climate_insights.html',
                         indicators=_public_indicators(), years=years)


@public_bp.route('/climate-insights/chart-data')
def climate_insights_chart_data():
    """Read-only chart data for the public Climate Insights explorer.
    View/explore only — returns aggregates, never writes anything."""
    year = (request.args.get('year') or '').strip()
    payload = {'labels': [], 'temperature': [], 'rainfall': [],
               'humidity': [], 'aqi': [], 'regional': []}
    try:
        monthly = ClimateData.get_monthly_trends(year=year or None)
        if not year:
            monthly.reverse()  # model returns latest 24 months newest-first
        for doc in monthly:
            payload['labels'].append(doc.get('month') or '')
            payload['temperature'].append(round(float(doc.get('avg_temp') or 0), 1))
            payload['rainfall'].append(round(float(doc.get('total_rainfall') or 0), 1))
            payload['humidity'].append(round(float(doc.get('avg_humidity') or 0), 1))
            payload['aqi'].append(round(float(doc.get('avg_aqi') or 0), 1))
        if not year:
            for doc in ClimateData.get_regional_data():
                payload['regional'].append({
                    'station': doc.get('station_name') or 'Unknown',
                    'avg_temp': round(float(doc.get('avg_temp') or 0), 1),
                    'total_rainfall': round(float(doc.get('total_rainfall') or 0), 1),
                    'avg_aqi': round(float(doc.get('avg_aqi') or 0), 1),
                    'readings': int(doc.get('readings') or 0),
                })
    except Exception:
        pass
    return jsonify(payload)


@public_bp.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        email = request.form.get('email', '').strip()
        subject = request.form.get('subject', '').strip()
        category = request.form.get('category', 'general')
        message = request.form.get('message', '').strip()

        if not name or not email or not subject or not message:
            flash('Please fill in all required fields.', 'danger')
            return render_template('public/contact.html')

        fb_id = None
        try:
            fb_id = Feedback.create(
                subject=f'[Contact] {subject}',
                message=f'From: {name} ({email})\n\n{message}',
                category=category,
                priority='medium',
                user_id=None,
                full_name=name,
                email=email
            )
            # Remember this visitor's submitted contact messages so the navbar
            # notification bell can surface admin replies to their own messages.
            ids = list(session.get('contact_fb_ids') or [])
            if fb_id not in ids:
                ids.append(fb_id)
            session['contact_fb_ids'] = ids
            session['contact_email'] = email
            NotificationManager.send_email(
                to_email='info@earthscape.org',
                subject=f'Contact Form: {subject}',
                body=f'From: {name}\nEmail: {email}\n\n{message}'
            )
            flash('Your message has been sent successfully! We will get back to you soon.', 'success')
            return redirect(url_for('public.contact'))
        except Exception as e:
            flash(f'Failed to send message. Please try again later.', 'danger')

    return render_template('public/contact.html')


@public_bp.route('/contact/lookup', methods=['POST'])
def contact_lookup():
    """Let a visitor view admin replies to their contact messages by entering
    the email they used. Remembered in the session so the bell + this page
    stay in sync on return visits."""
    email = (request.form.get('lookup_email') or '').strip()
    if email:
        session['contact_email'] = email
        try:
            ids = [d['id'] for d in get_collection('feedback')
                   .find({'email': email}, {'id': 1})]
            existing = list(session.get('contact_fb_ids') or [])
            for i in ids:
                if i not in existing:
                    existing.append(i)
            session['contact_fb_ids'] = existing
        except Exception:
            pass
    return redirect(url_for('public.contact'))


# ── Public contact-reply notifications ──────────────────────────────────────

def _public_contact_replies(email=None):
    """Admin replies to a visitor's contact messages.

    Matching priority:
      1. an explicit email passed in (manual "check my replies" lookup),
      2. the contact message ids submitted earlier this session,
      3. the visitor's email remembered from a prior submission.
    Never raises — returns an empty list when there is nothing to show."""
    ids = list(session.get('contact_fb_ids') or [])
    deleted = set(str(i) for i in (session.get('contact_replies_deleted') or []))
    sess_email = session.get('contact_email')
    col = get_collection('feedback')
    query = {'response': {'$ne': None}}

    if email:
        query['email'] = email
        session['contact_email'] = email
    elif ids:
        active_ids = [i for i in ids if str(i) not in deleted]
        if not active_ids:
            return []
        query['id'] = {'$in': active_ids}
    elif sess_email:
        query['email'] = sess_email
    else:
        return []

    if deleted and 'id' not in query and email:
        # Keep the email lookup strict while still hiding deleted items from the UI.
        doc_ids = [d.get('id') for d in col.find({'email': email, 'response': {'$ne': None}}, {'id': 1}) if str(d.get('id')) not in deleted]
        if not doc_ids:
            return []
        query['id'] = {'$in': doc_ids}

    try:
        docs = list(col.find(query).sort('responded_at', -1).limit(30))
    except Exception:
        return []

    read = set(session.get('contact_replies_read') or [])
    col_users = get_collection('users')
    replies = []
    for d in docs:
        rb = d.get('responded_by')
        name = ''
        if rb is not None:
            try:
                u = col_users.find_one({'id': int(rb)}, {'full_name': 1, 'username': 1})
                if u:
                    name = u.get('full_name') or u.get('username', '')
            except Exception:
                pass
        rid = d.get('id')
        replies.append({
            'id': rid,
            'subject': d.get('subject') or 'Contact message',
            'message': d.get('message') or '',
            'response': d.get('response') or '',
            'responded_by': name,
            'responded_at': (d.get('responded_at') or '')[:16].replace('T', ' '),
            'read': rid in read,
        })
    return replies


@public_bp.route('/contact/replies')
def contact_replies():
    """JSON feed of admin replies to the visitor's contact messages."""
    email = request.args.get('email', '').strip() or None
    replies = _public_contact_replies(email)
    return jsonify({
        'replies': replies,
        'unread': sum(1 for r in replies if not r['read']),
    })


@public_bp.route('/contact/replies/check', methods=['POST'])
def contact_replies_check():
    """Look up admin replies by an email the visitor provides, and remember
    that email in the session so the bell stays in sync afterwards."""
    data = request.get_json(silent=True) or {}
    email = (data.get('email') or '').strip()
    if not email:
        return jsonify({'replies': [], 'unread': 0})
    replies = _public_contact_replies(email)
    return jsonify({
        'replies': replies,
        'unread': sum(1 for r in replies if not r['read']),
    })


@public_bp.route('/contact/replies/mark-read', methods=['POST'])
def contact_replies_mark_read():
    """Persist which reply ids the visitor has seen (stored in the session)."""
    data = request.get_json(silent=True) or {}
    ids = data.get('ids') or []
    read = set(session.get('contact_replies_read') or [])
    for i in ids:
        try:
            read.add(int(i))
        except (TypeError, ValueError):
            read.add(i)
    session['contact_replies_read'] = list(read)
    return jsonify({'ok': True})


@public_bp.route('/contact/replies/delete', methods=['POST'])
def contact_replies_delete():
    """Hide a reply from the user's public inbox without deleting the admin record."""
    data = request.get_json(silent=True) or {}
    ids = data.get('ids') or []
    deleted = set(session.get('contact_replies_deleted') or [])
    read = set(session.get('contact_replies_read') or [])
    for i in ids:
        try:
            normalized = int(i)
        except (TypeError, ValueError):
            normalized = i
        deleted.add(normalized)
        read.discard(normalized)
    session['contact_replies_deleted'] = list(deleted)
    session['contact_replies_read'] = list(read)
    return jsonify({'ok': True})


@public_bp.route('/help')
def help_page():
    search = request.args.get('search', None)
    category = request.args.get('category', None)
    articles = KnowledgeBase.get_all(category=category, search=search, published_only=True)
    categories = KnowledgeBase.get_categories()
    return render_template('public/help.html', articles=articles, categories=categories,
                         category_filter=category, search_query=search)


# ── Realtime Climate (public, read-only) ────────────────────────────────────

_REALTIME_FIELDS = ('temperature', 'humidity', 'rainfall', 'wind_speed',
                    'pressure', 'co2_level', 'air_quality_index')


def _public_realtime():
    """Latest readings from active real-time streams for the public page.
    Never raises — an empty/broken DB just renders an empty payload."""
    stations = []
    summary = {'active_streams': 0, 'total_readings': 0, 'last_update': None}
    try:
        active = RealtimeStream.get_all(status='active')[:12]
        summary['active_streams'] = RealtimeStream.get_active_count()
        for stream in active:
            latest = RealtimeStream.get_latest_reading(stream['id']) or {}
            history = RealtimeStream.get_readings(stream['id'], limit=18)
            station = {
                'id': stream['id'],
                'name': stream.get('stream_name') or 'Stream #{}'.format(stream['id']),
                'location': stream.get('source_location') or stream.get('stream_name') or 'Unknown',
                'source_type': stream.get('source_type') or 'sensor',
                'timestamp': latest.get('timestamp') or stream.get('last_reading'),
                'readings': {f: _safe_float(latest.get(f)) for f in _REALTIME_FIELDS},
                'history': [
                    {
                        'timestamp': item.get('timestamp'),
                        'readings': {f: _safe_float(item.get(f)) for f in _REALTIME_FIELDS},
                    }
                    for item in reversed(history)
                ],
                'has_data': any(latest.get(f) is not None for f in _REALTIME_FIELDS),
            }
            stations.append(station)
            if station['timestamp'] and (summary['last_update'] is None
                                         or station['timestamp'] > summary['last_update']):
                summary['last_update'] = station['timestamp']
        summary['total_readings'] = sum(s.get('reading_count') or 0 for s in active)
    except Exception:
        pass
    return stations, summary


@public_bp.route('/realtime-climate')
def realtime_climate():
    """Public real-time climate conditions from the monitoring network."""
    stations, summary = _public_realtime()
    return render_template('public/realtime_climate.html',
                         stations=stations, summary=summary)


@public_bp.route('/realtime-climate/data')
def realtime_climate_data():
    """JSON feed of the latest readings (used for auto-refresh)."""
    stations, summary = _public_realtime()
    return jsonify({'stations': stations, 'summary': summary})


# ── Public Alerts ────────────────────────────────────────────────────────────

def _public_alerts(limit=50):
    """Recent climate alerts for the public page. Never raises."""
    alerts = []
    counts = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}
    try:
        for a in Alert.get_all(limit=limit):
            severity = (a.get('severity') or 'medium').lower()
            counts[severity] = counts.get(severity, 0) + 1
            alerts.append({
                'id': a.get('id'),
                'title': a.get('title') or 'Climate Alert',
                'message': a.get('message') or '',
                'severity': severity,
                'alert_type': a.get('alert_type') or 'warning',
                'category': a.get('category') or 'weather',
                'location': a.get('location') or '',
                'is_resolved': int(a.get('is_resolved') or 0),
                'created_at': a.get('created_at') or '',
            })
    except Exception:
        pass
    return alerts, counts


@public_bp.route('/alerts')
def public_alerts():
    """Public-relevant climate alerts and significant events."""
    alerts, counts = _public_alerts()
    return render_template('public/alerts.html', alerts=alerts, counts=counts)


@public_bp.route('/alerts/data')
def public_alerts_data():
    """JSON feed of recent alerts (used for auto-refresh)."""
    alerts, counts = _public_alerts()
    return jsonify({'alerts': alerts, 'counts': counts})


# ── Public Satellite Imagery gallery ────────────────────────────────────────

def _public_imagery(limit=8):
    """Latest ingested satellite imagery for the public home page.
    Never raises — an empty/broken DB just renders an empty list."""
    images = []
    try:
        for img in SatelliteImage.get_all(limit=limit):
            metrics = img.get('metrics') or {}
            images.append({
                'id': img.get('id'),
                'name': img.get('filename') or img.get('station_name') or 'Satellite Image',
                'platform': img.get('platform') or 'Unknown',
                'capture_date': (img.get('capture_date') or '')[:10],
                'latitude': _safe_float(img.get('latitude')),
                'longitude': _safe_float(img.get('longitude')),
                'width': int(metrics.get('width') or 0),
                'height': int(metrics.get('height') or 0),
                'land_surface_temp': _safe_float(metrics.get('land_surface_temp')),
                'cloud_cover': _safe_float(metrics.get('cloud_cover')),
                'vegetation_index': _safe_float(metrics.get('vegetation_index')),
            })
    except Exception:
        pass
    return images


@public_bp.route('/satellite-imagery/<int:image_id>/image')
def public_imagery_file(image_id):
    """Serve a stored satellite image for the public gallery (read-only)."""
    img = SatelliteImage.get_by_id(image_id)
    stored_path = SatelliteImage.resolve_file_path(img)
    if not stored_path:
        return 'Image not found', 404
    return send_file(stored_path)
