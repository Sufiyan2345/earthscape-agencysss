import os
import sys
import time
import logging
from flask import Flask, redirect, url_for, render_template, request
from flask.json.provider import DefaultJSONProvider
from flask_login import LoginManager, current_user
from bson import ObjectId
from config import config_map
from utils.database import init_db
from utils.helper import ensure_directories, get_cached_value

# Harden flask_login against malformed/legacy remember-me cookie values
# (e.g. an old Mongo ObjectId stored in the cookie) so it never crashes.
try:
    import flask_login.login_manager as _flm

    _orig_load_user_from_remember_cookie = _flm.LoginManager._load_user_from_remember_cookie

    def _safe_load_user_from_remember_cookie(self, cookie):
        try:
            return _orig_load_user_from_remember_cookie(self, cookie)
        except Exception:
            # Bad/legacy cookie value: drop it from this request so the
            # visitor continues as anonymous instead of the app crashing.
            try:
                from flask import request as _request
                cookie_name = self._get_cookie_name() \
                    if hasattr(self, '_get_cookie_name') \
                    else getattr(self, 'cookie_name', 'remember_token')
                _request.cookies = {k: v for k, v in _request.cookies.items()
                                    if k != cookie_name}
            except Exception:
                pass
            return None

    _flm.LoginManager._load_user_from_remember_cookie = _safe_load_user_from_remember_cookie
except Exception:
    pass


class MongoJSONProvider(DefaultJSONProvider):
    """Custom JSON provider that handles MongoDB ObjectId and other BSON types."""
    def default(self, o):
        if isinstance(o, ObjectId):
            return str(o)
        return super().default(o)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)] if os.environ.get('VERCEL') else [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), 'logs', 'app.log'), mode='a')
    ],
)
logger = logging.getLogger(__name__)


def create_app(config_name='development'):
    app = Flask(__name__)
    app.json_provider_class = MongoJSONProvider
    app.json = MongoJSONProvider(app)
    app.config.from_object(config_map[config_name])

    if os.environ.get('VERCEL'):
        required_environment = (
            'MONGO_URI',
            'SECRET_KEY',
            'INITIAL_ADMIN_PASSWORD',
            'INITIAL_ANALYST_PASSWORD',
            'INITIAL_ANALYSIS_USER_PASSWORD',
        )
        missing_environment = [
            name for name in required_environment if not os.environ.get(name)
        ]
        if missing_environment:
            raise RuntimeError(
                'Missing required Vercel environment variables: '
                + ', '.join(missing_environment)
            )

    from ml_models.scheduler import start_scheduler
    start_scheduler(app)

    # Ensure all directories exist
    ensure_directories()

    # Initialize database
    with app.app_context():
        init_db()

    # Setup Flask-Login
    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message_category = 'info'
    login_manager.login_message = 'Please log in to access this page.'

    @login_manager.user_loader
    def load_user(user_id):
        from models.user_model import User
        from bson import ObjectId as _ObjectId
        from bson.errors import InvalidId
        from utils.database import get_collection
        # Numeric user ids (normal case)
        try:
            return User.get_by_id(int(user_id))
        except Exception:
            pass
        # Stale/legacy cookie values (e.g. a Mongo ObjectId string)
        try:
            doc = User._doc_to_user(
                get_collection('users').find_one({'_id': _ObjectId(user_id)}))
            if doc:
                return doc
        except Exception:
            pass
        return None

    # Register blueprints
    from auth import auth_bp
    from admin import admin_bp
    from analyst import analyst_bp
    from public import public_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp)
    app.register_blueprint(analyst_bp)
    app.register_blueprint(public_bp)

    try:
        from utils.ingestion_backend import broker, handle_climate_event
        broker.start_consumer(handle_climate_event)
    except Exception as exc:
        logger.warning('Kafka consumer unavailable: %s', exc)

    # Compress text responses with gzip when the client supports it.
    @app.after_request
    def compress_response(response):
        if response.direct_passthrough:
            return response
        if response.content_type and not response.content_type.startswith(('text/', 'application/json', 'application/javascript', 'application/xml')):
            return response
        if response.status_code not in (200, 201, 202):
            return response
        accept_encoding = request.headers.get('Accept-Encoding', '')
        if 'gzip' not in accept_encoding.lower():
            return response
        if 'Content-Encoding' in response.headers:
            return response
        try:
            import gzip
            data = response.get_data()
            if len(data) < 200:
                return response
            gzip_buffer = gzip.compress(data, compresslevel=6)
            response.set_data(gzip_buffer)
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Content-Length'] = str(len(gzip_buffer))
            response.headers['Vary'] = 'Accept-Encoding'
        except Exception:
            pass
        return response

    # Cache headers: static assets are cached in the browser for a day
    # (huge speedup - CSS/JS are not re-downloaded on every page),
    # while authenticated HTML pages stay uncacheable for security.
    @app.after_request
    def set_no_cache(response):
        if request.path.startswith('/static/'):
            response.headers['Cache-Control'] = 'public, max-age=86400'
            return response
        if current_user and current_user.is_authenticated:
            response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
            response.headers['Pragma'] = 'no-cache'
            response.headers['Expires'] = '0'
        return response

    # Template context processors
    # Unread badge count, cached briefly per user so every page render does
    # not hit MongoDB twice (the 10s dropdown poll keeps it fresh anyway).
    _unread_cache = {}
    _UNREAD_TTL = 15.0

    @app.context_processor
    def inject_globals():
        from models.alert_model import Alert
        from models.climate_model import ClimateData
        from models.realtime_model import RealtimeStream
        unread_alerts = 0
        auth_stats = {'sensors': 0, 'records': 0, 'uptime': '100.0%'}
        try:
            streams = get_cached_value(
                'auth:realtime_streams',
                RealtimeStream.get_all,
                ttl_seconds=60,
            )
            records = get_cached_value(
                'auth:climate_summary',
                ClimateData.get_summary,
                ttl_seconds=60,
            )
            total_streams = len(streams)
            active_streams = sum(1 for stream in streams if stream.get('status') == 'active')
            uptime = (active_streams / total_streams * 100) if total_streams else 100.0
            auth_stats = {
                'sensors': total_streams,
                'records': int(records.get('total_records') or 0),
                'uptime': f'{uptime:.1f}%',
            }
        except Exception:
            pass
        if current_user and current_user.is_authenticated:
            from utils.notifications import get_user_unread_notification_count
            key = current_user.id
            now = time.time()
            cached = _unread_cache.get(key)
            if cached and now - cached[1] < _UNREAD_TTL:
                unread_alerts = cached[0]
            else:
                unread_alerts = Alert.get_unread_count() + \
                    get_user_unread_notification_count(current_user.id)
                _unread_cache[key] = (unread_alerts, now)
        return dict(unread_alerts=unread_alerts, auth_stats=auth_stats)

    # Jinja filter: safely coerce any stored value (strings from uploaded
    # files included) to a float for number formatting; None if invalid.
    @app.template_filter('num')
    def as_num(value):
        # Render missing/empty metrics (None or Jinja Undefined) as None so
        # templates using `v is not none else 'N/A'` fall back cleanly instead
        # of trying to `"%.1f"|format('')` and 500-ing the page.
        if value is None or value == '':
            return None
        try:
            return float(value)
        except Exception:
            return None

    # Jinja filters for datetime formatting
    from utils.helper import format_datetime as fmt_datetime, format_date as fmt_date, time_ago as fmt_time_ago
    
    @app.template_filter('fmtdatetime')
    def format_datetime_filter(value):
        return fmt_datetime(value)
    
    @app.template_filter('fmtdate')
    def format_date_filter(value):
        return fmt_date(value)
    
    @app.template_filter('timeago')
    def time_ago_filter(value):
        return fmt_time_ago(value)

    # Error handlers
    @app.errorhandler(403)
    def forbidden(e):
        if not current_user or not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        return render_template('public/base.html', error='403 - Forbidden'), 403

    @app.errorhandler(404)
    def not_found(e):
        return render_template('public/base.html', error='404 - Page Not Found'), 404

    @app.errorhandler(500)
    def internal_error(e):
        return render_template('public/base.html', error='500 - Internal Server Error'), 500

    # Startup verification: prints the code version and confirms the 'num'
    # template filter is registered. If you do NOT see these two lines in
    # your terminal after restarting, an old server process is still
    # running on port 5000 and must be killed first.
    print('=' * 60)
    print('EarthScape code version: 20260813 (num filter + perf fixes)')
    print("Jinja 'num' filter registered: {}".format('num' in app.jinja_env.filters))
    print('=' * 60)
    logger.info("EarthScape Climate System initialized successfully.")
    return app


if __name__ == '__main__':
    app = create_app()
    # debug=False: debug mode adds significant per-request overhead;
    # the app has proper 403/404/500 error handlers instead.
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
