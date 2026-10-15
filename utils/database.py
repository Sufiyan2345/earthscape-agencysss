"""
MongoDB database layer for EarthScape Climate System.

Replaces the previous SQLite (sqlite3) layer with pymongo.
All collections are backed by a single MongoDB Atlas database.
"""
import atexit
import json
import os
import threading
from datetime import datetime
from pymongo import MongoClient, ASCENDING, DESCENDING, ReturnDocument
from bson import ObjectId
from config import Config

try:
    import mongomock
except Exception:  # pragma: no cover - falls back to installed package later
    mongomock = None

_client = None
_db = None
_lock = threading.Lock()


# ── Document sanitizer ────────────────────────────────────────────────────────

def _sanitize(doc):
    """Remove MongoDB _id from a document dict (in-place) and return it."""
    if doc is not None and '_id' in doc:
        del doc['_id']
    return doc


class _SanitizedCursor:
    """Wraps a pymongo cursor to strip _id from every document."""
    def __init__(self, cursor):
        self._cursor = cursor

    def __iter__(self):
        for doc in self._cursor:
            yield _sanitize(doc)

    def __next__(self):
        return _sanitize(next(self._cursor))

    def sort(self, *args, **kwargs):
        self._cursor = self._cursor.sort(*args, **kwargs)
        return self

    def limit(self, *args, **kwargs):
        self._cursor = self._cursor.limit(*args, **kwargs)
        return self

    def skip(self, *args, **kwargs):
        self._cursor = self._cursor.skip(*args, **kwargs)
        return self

    def count(self, *args, **kwargs):
        return self._cursor.count(*args, **kwargs)


class _SanitizedCollection:
    """Wraps a pymongo collection to strip _id from all read results."""
    def __init__(self, collection):
        self._col = collection

    def _persist_if_mocked(self):
        try:
            if _client is not None and mongomock is not None and isinstance(_client, mongomock.MongoClient):
                _save_fallback_db(_db)
        except Exception:
            pass

    def find(self, *args, **kwargs):
        return _SanitizedCursor(self._col.find(*args, **kwargs))

    def find_one(self, *args, **kwargs):
        return _sanitize(self._col.find_one(*args, **kwargs))

    def find_one_and_update(self, *args, **kwargs):
        result = self._col.find_one_and_update(*args, **kwargs)
        self._persist_if_mocked()
        return _sanitize(result)

    def find_one_and_replace(self, *args, **kwargs):
        result = self._col.find_one_and_replace(*args, **kwargs)
        self._persist_if_mocked()
        return _sanitize(result)

    def find_one_and_delete(self, *args, **kwargs):
        result = self._col.find_one_and_delete(*args, **kwargs)
        self._persist_if_mocked()
        return _sanitize(result)

    def aggregate(self, *args, **kwargs):
        # Do NOT sanitize aggregation results — _id is the grouping key, not a doc primary key
        return self._col.aggregate(*args, **kwargs)

    # Pass-through for write operations and utilities
    def insert_one(self, *args, **kwargs):
        result = self._col.insert_one(*args, **kwargs)
        self._persist_if_mocked()
        return result

    def insert_many(self, *args, **kwargs):
        result = self._col.insert_many(*args, **kwargs)
        self._persist_if_mocked()
        return result

    def update_one(self, *args, **kwargs):
        result = self._col.update_one(*args, **kwargs)
        self._persist_if_mocked()
        return result

    def update_many(self, *args, **kwargs):
        result = self._col.update_many(*args, **kwargs)
        self._persist_if_mocked()
        return result

    def delete_one(self, *args, **kwargs):
        result = self._col.delete_one(*args, **kwargs)
        self._persist_if_mocked()
        return result

    def delete_many(self, *args, **kwargs):
        result = self._col.delete_many(*args, **kwargs)
        self._persist_if_mocked()
        return result

    def count_documents(self, *args, **kwargs):
        return self._col.count_documents(*args, **kwargs)

    def estimated_document_count(self, *args, **kwargs):
        return self._col.estimated_document_count(*args, **kwargs)

    def create_index(self, *args, **kwargs):
        return self._col.create_index(*args, **kwargs)

    def drop(self, *args, **kwargs):
        result = self._col.drop(*args, **kwargs)
        self._persist_if_mocked()
        return result

    def distinct(self, *args, **kwargs):
        return self._col.distinct(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._col, name)


# ── Connection ────────────────────────────────────────────────────────────────

def _connect():
    """Establish (or reuse) a pymongo connection and return the database handle."""
    global _client, _db
    if _db is not None:
        return _db
    with _lock:
        if _db is not None:
            return _db

        try:
            _client = MongoClient(
                Config.MONGO_URI,
                serverSelectionTimeoutMS=3000,
                connectTimeoutMS=3000,
            )
            _client.admin.command('ping')
            _db = _client[Config.MONGO_DB]
            print(f"[MongoDB] Connected to {Config.MONGO_DB} via {Config.MONGO_URI}")
            return _db
        except Exception as exc:
            if mongomock is None:
                raise RuntimeError(
                    "MongoDB is unavailable and mongomock is not installed. "
                    "Install mongomock or start a local MongoDB service."
                ) from exc

            _client = mongomock.MongoClient()
            _db = _client[Config.MONGO_DB]
            _load_fallback_db(_db)
            atexit.register(_save_fallback_db, _db)
            print(
                f"[MongoDB] Using local fallback database because '{Config.MONGO_URI}' is unavailable: {exc}"
            )
            return _db


def _fallback_store_path():
    """Path for the local JSON store used when MongoDB is unavailable."""
    if os.environ.get('VERCEL'):
        base_dir = os.path.join(os.environ.get('EARTHSCAPE_RUNTIME_DIR', '/tmp/earthscape-climate'), 'data')
    else:
        base_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
    os.makedirs(base_dir, exist_ok=True)
    return os.path.join(base_dir, 'mongomock_fallback.json')


def _load_fallback_db(db):
    """Restore collection state from the local JSON fallback store."""
    path = _fallback_store_path()
    if not os.path.exists(path):
        return
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return
        for collection_name, documents in data.items():
            collection = db[collection_name]
            collection.delete_many({})
            if documents:
                collection.insert_many(documents)
    except Exception as exc:
        print(f"[MongoDB fallback] Failed to restore local store: {exc}")


def _save_fallback_db(db):
    """Persist the fallback mock database to a local JSON store."""
    path = _fallback_store_path()
    try:
        payload = {}
        for collection_name in db.list_collection_names():
            docs = []
            for doc in db[collection_name].find():
                clean_doc = dict(doc)
                clean_doc.pop('_id', None)
                docs.append(clean_doc)
            payload[collection_name] = docs
        with open(path, 'w', encoding='utf-8') as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, default=str)
    except Exception as exc:
        print(f"[MongoDB fallback] Failed to save local store: {exc}")


def get_db():
    """Return the pymongo database handle (singleton)."""
    return _connect()


def get_collection(name):
    """Return a sanitized pymongo collection by name (auto-strips _id from reads)."""
    return _SanitizedCollection(_connect()[name])


# ── Auto-increment IDs ────────────────────────────────────────────────────────

def next_id(collection_name):
    """
    Atomically generate and return the next integer ID for *collection_name*.

    Uses a ``counters`` collection so that existing integer-based URL routes
    (e.g. ``/feedback/<int:id>``) continue to work without changes.
    """
    counters = get_collection('counters')
    doc = counters.find_one_and_update(
        {'_id': collection_name},
        {'$inc': {'seq': 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return doc['seq']


def next_ids(collection_name, count):
    """Atomically reserve a contiguous range of integer IDs for a batch."""
    if count <= 0:
        return []
    counters = get_collection('counters')
    doc = counters.find_one_and_update(
        {'_id': collection_name},
        {'$inc': {'seq': count}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    first_id = doc['seq'] - count + 1
    return range(first_id, doc['seq'] + 1)


# ── Initialization ────────────────────────────────────────────────────────────

def init_db():
    """
    Create indexes on all collections and seed default data
    (admin/analyst users, system settings, HDFS datanodes, partitions).
    """
    db = get_db()

    # ── Indexes ───────────────────────────────────────────────────────────────
    db.users.create_index([('username', ASCENDING)], unique=True)
    db.users.create_index([('email', ASCENDING)], unique=True)
    db.users.create_index([('role', ASCENDING)])

    db.datasets.create_index([('status', ASCENDING)])
    db.datasets.create_index([('category', ASCENDING)])
    db.datasets.create_index([('uploaded_by', ASCENDING)])

    db.satellite_imagery.create_index([('id', ASCENDING)], unique=True)
    db.satellite_imagery.create_index([('uploaded_by', ASCENDING)])

    db.climate_data.create_index([('dataset_id', ASCENDING)])
    db.climate_data.create_index([('date', ASCENDING)])
    db.climate_data.create_index([('station_name', ASCENDING)])
    db.climate_data.create_index([('dataset_id', ASCENDING), ('date', ASCENDING)])
    db.climate_data.create_index([('date', ASCENDING), ('station_name', ASCENDING)])
    db.climate_data.create_index([('temperature', ASCENDING)])
    db.climate_data.create_index([('rainfall', ASCENDING)])
    db.climate_data.create_index([('created_at', DESCENDING)])

    db.predictions.create_index([('model_name', ASCENDING)])
    db.predictions.create_index([('created_by', ASCENDING)])
    db.predictions.create_index([('created_by', ASCENDING), ('created_at', DESCENDING)])
    db.predictions.create_index([('model_name', ASCENDING), ('created_at', DESCENDING)])

    db.realtime_streams.create_index([('status', ASCENDING)])
    db.realtime_streams.create_index([('created_by', ASCENDING)])
    db.realtime_readings.create_index([('stream_id', ASCENDING)])
    db.realtime_readings.create_index([('timestamp', DESCENDING)])
    db.realtime_readings.create_index([('stream_id', ASCENDING), ('timestamp', DESCENDING)])

    db.alerts.create_index([('severity', ASCENDING)])
    db.alerts.create_index([('is_read', ASCENDING)])
    db.alerts.create_index([('created_at', DESCENDING)])
    db.alerts.create_index([('is_read', ASCENDING), ('created_at', DESCENDING)])
    db.alerts.create_index([('severity', ASCENDING), ('is_read', ASCENDING)])

    db.reports.create_index([('report_type', ASCENDING)])
    db.reports.create_index([('generated_by', ASCENDING)])

    db.feedback.create_index([('status', ASCENDING)])
    db.feedback.create_index([('user_id', ASCENDING)])
    db.feedback.create_index([('category', ASCENDING)])
    db.feedback.create_index([('status', ASCENDING), ('created_at', DESCENDING)])

    db.activity_log.create_index([('user_id', ASCENDING)])
    db.activity_log.create_index([('created_at', DESCENDING)])
    db.activity_log.create_index([('user_id', ASCENDING), ('created_at', DESCENDING)])

    db.system_settings.create_index([('setting_key', ASCENDING)], unique=True)

    db.notification_preferences.create_index(
        [('user_id', ASCENDING), ('category', ASCENDING), ('severity', ASCENDING)],
        unique=True,
    )

    db.knowledge_base.create_index([('category', ASCENDING)])
    db.knowledge_base.create_index([('is_published', ASCENDING)])

    db.model_versions.create_index([('model_type', ASCENDING)])
    db.model_versions.create_index([('is_active', ASCENDING)])

    db.hdfs_files.create_index([('file_path', ASCENDING)], unique=True)
    db.hdfs_datanodes.create_index([('node_name', ASCENDING)], unique=True)
    db.hdfs_blocks.create_index([('file_id', ASCENDING)])
    db.hdfs_partitions.create_index([('partition_key', ASCENDING)], unique=True)


    # ── Seed default admin / analyst users only when the database is empty ─────
    from werkzeug.security import generate_password_hash
    now = datetime.utcnow().isoformat()

    if db.users.count_documents({}) == 0:
        default_users = [
            {
                'username': 'admin',
                'email': 'admin@earthscape.org',
                'password': os.environ.get('INITIAL_ADMIN_PASSWORD', 'admin123'),
                'full_name': 'System Administrator',
                'role': 'admin',
                'department': 'IT Administration',
            },
            {
                'username': 'analyst',
                'email': 'analyst@earthscape.org',
                'password': os.environ.get('INITIAL_ANALYST_PASSWORD', 'analyst123'),
                'full_name': 'Climate Analyst',
                'role': 'analyst',
                'department': 'Climate Science',
            },
            {
                'username': 'analysis123',
                'email': 'analysis123@earthscape.org',
                'password': os.environ.get('INITIAL_ANALYSIS_USER_PASSWORD', 'user123'),
                'full_name': 'Analysis User',
                'role': 'analyst',
                'department': 'Climate Analysis',
            },
        ]

        for user_data in default_users:
            db.users.insert_one({
                'id': next_id('users'),
                'username': user_data['username'],
                'email': user_data['email'],
                'password_hash': generate_password_hash(user_data['password']),
                'full_name': user_data['full_name'],
                'role': user_data['role'],
                'department': user_data['department'],
                'phone': '',
                'avatar': 'default.png',
                'is_active': 1,
                'is_verified': 1,
                'last_login': None,
                'created_at': now,
                'updated_at': now,
            })

    existing_admin = db.users.find_one({'role': 'admin'})
    if existing_admin and existing_admin.get('username') != 'admin':
        db.users.update_one(
            {'_id': existing_admin['_id']},
            {'$set': {'username': 'admin', 'updated_at': datetime.utcnow().isoformat()}}
        )

    # ── Seed default system settings ──────────────────────────────────────────
    defaults = [
        ('site_name', 'EarthScape Climate System', 'string', 'Application name'),
        ('alert_email_enabled', 'false', 'boolean', 'Enable email alerts'),
        ('data_retention_days', '365', 'integer', 'Data retention period'),
        ('max_upload_size_mb', '500', 'integer', 'Maximum upload size in MB'),
        ('realtime_interval', '30', 'integer', 'Real-time data polling interval in seconds'),
        ('hdfs_replication', '3', 'integer', 'HDFS replication factor'),
        ('hdfs_block_size_mb', '128', 'integer', 'HDFS block size in MB'),
        ('hdfs_compression', 'gzip', 'string', 'Default compression: none/gzip/snappy'),
        ('maintenance_mode', 'false', 'boolean', 'Enable maintenance mode'),
    ]
    for key, value, stype, desc in defaults:
        if db.system_settings.count_documents({'setting_key': key}) == 0:
            db.system_settings.insert_one({
                'id': next_id('system_settings'),
                'setting_key': key,
                'setting_value': value,
                'setting_type': stype,
                'description': desc,
                'updated_by': None,
                'updated_at': datetime.utcnow().isoformat(),
                'user_id': None,
            })

    # ── Seed default HDFS datanodes ───────────────────────────────────────────
    if db.hdfs_datanodes.count_documents({}) == 0:
        now = datetime.utcnow().isoformat()
        nodes = [
            ('datanode-1', '127.0.0.1', 9866, 'alive', 10737418240, 0, 10737418240, 0, now, '/rack-1'),
            ('datanode-2', '127.0.0.1', 9867, 'alive', 10737418240, 0, 10737418240, 0, now, '/rack-1'),
            ('datanode-3', '127.0.0.1', 9868, 'alive', 10737418240, 0, 10737418240, 0, now, '/rack-2'),
        ]
        for n in nodes:
            db.hdfs_datanodes.insert_one({
                'id': next_id('hdfs_datanodes'),
                'node_name': n[0], 'host': n[1], 'port': n[2],
                'status': n[3], 'capacity': n[4], 'used': n[5],
                'remaining': n[6], 'block_count': n[7],
                'last_heartbeat': n[8], 'rack': n[9],
                'created_at': now,
            })

    # ── Seed default HDFS partitions ──────────────────────────────────────────
    if db.hdfs_partitions.count_documents({}) == 0:
        now = datetime.utcnow().isoformat()
        partitions = [
            ('climate_data', 'type', 'all', '/climate', 0, 0, '', 'active'),
            ('climate_data_satellite', 'type', 'satellite', '/climate/satellite', 0, 0, 'climate_data', 'active'),
            ('climate_data_weather', 'type', 'weather', '/climate/weather', 0, 0, 'climate_data', 'active'),
            ('climate_data_sensor', 'type', 'sensor', '/climate/sensors', 0, 0, 'climate_data', 'active'),
        ]
        for p in partitions:
            db.hdfs_partitions.insert_one({
                'id': next_id('hdfs_partitions'),
                'partition_key': p[0], 'partition_type': p[1],
                'partition_value': p[2], 'hdfs_path': p[3],
                'record_count': p[4], 'total_size': p[5],
                'parent_partition': p[6], 'status': p[7],
                'created_at': now,
            })


# ── Activity logging ──────────────────────────────────────────────────────────

def log_activity(user_id, action, details='', ip_address=''):
    """Insert a row into the activity_log collection."""
    try:
        get_collection('activity_log').insert_one({
            'id': next_id('activity_log'),
            'user_id': user_id,
            'action': action,
            'details': details,
            'ip_address': ip_address,
            'created_at': datetime.utcnow().isoformat(),
        })
    except Exception:
        pass
