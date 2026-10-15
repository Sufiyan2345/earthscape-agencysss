import os
import json
import uuid
import time
from datetime import datetime
from config import Config

_CACHE = {}


def get_cached_value(key, factory, ttl_seconds=30):
    """Return cached value for a short TTL to reduce repeated expensive DB queries."""
    now = time.monotonic()
    entry = _CACHE.get(key)
    if entry and now - entry['time'] < ttl_seconds:
        return entry['value']
    value = factory()
    _CACHE[key] = {'time': now, 'value': value}
    return value


def invalidate_cache(prefix=None):
    """Drop cached values so freshly written data shows up immediately.

    Pass a prefix (e.g. 'climate:') to clear a subset, or nothing to clear all.
    """
    if prefix is None:
        _CACHE.clear()
        return
    for key in [k for k in list(_CACHE.keys()) if str(k).startswith(prefix)]:
        _CACHE.pop(key, None)


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS


def get_file_extension(filename):
    return filename.rsplit('.', 1)[1].lower() if '.' in filename else ''


def generate_unique_filename(filename):
    ext = get_file_extension(filename)
    unique = str(uuid.uuid4())[:8]
    timestamp = datetime.utcnow().strftime('%Y%m%d%H%M%S')
    return f"{timestamp}_{unique}.{ext}"


def format_file_size(size_bytes):
    if size_bytes == 0:
        return "0 B"
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    i = 0
    size = float(size_bytes)
    while size >= 1024 and i < len(units) - 1:
        size /= 1024
        i += 1
    return f"{size:.2f} {units[i]}"


def format_datetime(dt_input):
    """Format datetime object or ISO string to readable format: 'August 28, 2026 19:33'"""
    if not dt_input:
        return 'N/A'
    
    try:
        # Handle datetime objects from MongoDB
        if isinstance(dt_input, datetime):
            dt = dt_input
        else:
            # Handle ISO strings
            dt_string = str(dt_input)
            dt = datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
        
        return dt.strftime('%B %d, %Y %H:%M')
    except (ValueError, AttributeError, TypeError):
        return 'N/A'


def format_date(dt_input):
    """Format datetime object or ISO string to date only: 'August 28, 2026'"""
    if not dt_input:
        return 'N/A'
    
    try:
        # Handle datetime objects from MongoDB
        if isinstance(dt_input, datetime):
            dt = dt_input
        else:
            # Handle ISO strings
            dt_string = str(dt_input)
            dt = datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
        
        return dt.strftime('%B %d, %Y')
    except (ValueError, AttributeError, TypeError):
        return 'N/A'


def time_ago(dt_input):
    """Format datetime to relative time: '5 minutes ago'"""
    if not dt_input:
        return 'N/A'
    
    try:
        # Handle datetime objects from MongoDB
        if isinstance(dt_input, datetime):
            dt = dt_input
        else:
            # Handle ISO strings
            dt_string = str(dt_input)
            dt = datetime.fromisoformat(dt_string.replace('Z', '+00:00'))
        
        now = datetime.utcnow()
        diff = now - dt
        seconds = diff.total_seconds()
        if seconds < 60:
            return 'Just now'
        elif seconds < 3600:
            mins = int(seconds / 60)
            return f'{mins} minute{"s" if mins != 1 else ""} ago'
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f'{hours} hour{"s" if hours != 1 else ""} ago'
        elif seconds < 2592000:
            days = int(seconds / 86400)
            return f'{days} day{"s" if days != 1 else ""} ago'
        else:
            return dt.strftime('%B %d, %Y')
    except (ValueError, AttributeError, TypeError):
        return 'N/A'


def ensure_directories():
    dirs = [
        Config.UPLOAD_FOLDER,
        os.path.join(Config.UPLOAD_FOLDER, 'weather'),
        os.path.join(Config.UPLOAD_FOLDER, 'satellite'),
        os.path.join(Config.UPLOAD_FOLDER, 'sensors'),
        os.path.join(Config.UPLOAD_FOLDER, 'realtime'),
        os.path.join(Config.UPLOAD_FOLDER, 'hdfs'),
        os.path.join(Config.UPLOAD_FOLDER, 'hdfs', '.blocks'),
        os.path.join(Config.UPLOAD_FOLDER, 'hdfs', 'climate'),
        os.path.join(Config.UPLOAD_FOLDER, 'hdfs', 'climate', 'satellite'),
        os.path.join(Config.UPLOAD_FOLDER, 'hdfs', 'climate', 'weather'),
        os.path.join(Config.UPLOAD_FOLDER, 'hdfs', 'climate', 'sensors'),
        os.path.join(Config.UPLOAD_FOLDER, 'hdfs', 'climate', 'realtime'),
        os.path.join(Config.UPLOAD_FOLDER, 'hdfs', 'climate', 'archive'),
        Config.DATASETS_FOLDER,
        os.path.join(Config.DATASETS_FOLDER, 'weather'),
        os.path.join(Config.DATASETS_FOLDER, 'satellite'),
        os.path.join(Config.DATASETS_FOLDER, 'sensors'),
        os.path.join(Config.DATASETS_FOLDER, 'sample'),
        Config.REPORTS_FOLDER,
        os.path.join(Config.REPORTS_FOLDER, 'generated_reports'),
        os.path.join(Config.REPORTS_FOLDER, 'charts'),
        Config.LOGS_FOLDER,
        Config.MODELS_FOLDER,
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)


def get_system_stats():
    return get_cached_value('system:stats', _compute_system_stats, ttl_seconds=30)

def _compute_system_stats():
    from models.user_model import User
    from models.dataset_model import Dataset
    from models.alert_model import Alert
    from models.prediction_model import Prediction
    from models.realtime_model import RealtimeStream
    from models.climate_model import ClimateData
    from utils.mapreduce import MapReduceManager

    return {
        'total_users': User.get_count(),
        'total_datasets': Dataset.get_count(),
        'total_climate_records': ClimateData.get_total_count(),
        'total_alerts': Alert.get_count(),
        'unread_alerts': Alert.get_unread_count(),
        'total_predictions': Prediction.get_count(),
        'active_streams': RealtimeStream.get_active_count(),
        'total_jobs': MapReduceManager.get_job_count(),
    }


def generate_sample_csv(filepath, records=100):
    """Generate a sample climate CSV file."""
    import numpy as np
    import pandas as pd

    np.random.seed(42)
    dates = pd.date_range('2024-01-01', periods=records, freq='D')
    stations = ['Station_Alpha', 'Station_Beta', 'Station_Gamma', 'Station_Delta']

    data = []
    for i, date in enumerate(dates):
        data.append({
            'station_name': stations[i % len(stations)],
            'latitude': round(np.random.uniform(10, 50), 4),
            'longitude': round(np.random.uniform(-100, -60), 4),
            'elevation': round(np.random.uniform(0, 3000), 1),
            'date': date.strftime('%Y-%m-%d'),
            'temperature': round(np.random.normal(25, 8), 1),
            'humidity': round(np.random.uniform(30, 95), 1),
            'rainfall': round(max(0, np.random.exponential(10)), 1),
            'wind_speed': round(max(0, np.random.normal(20, 10)), 1),
            'wind_direction': round(np.random.uniform(0, 360), 1),
            'pressure': round(np.random.normal(1013, 10), 1),
            'co2_level': round(np.random.normal(415, 20), 1),
            'air_quality_index': round(max(0, np.random.normal(80, 30)), 0),
            'visibility': round(np.random.uniform(1, 20), 1),
            'cloud_cover': round(np.random.uniform(0, 100), 1),
            'uv_index': round(max(0, np.random.normal(5, 2)), 1),
            'soil_moisture': round(np.random.uniform(10, 80), 1),
            'snow_depth': round(max(0, np.random.normal(5, 10)), 1),
        })

    df = pd.DataFrame(data)
    df.to_csv(filepath, index=False)
    return filepath
