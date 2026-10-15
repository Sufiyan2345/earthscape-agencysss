"""
MongoDB integration for EarthScape Climate System.

This module re-exports the core database helpers from utils.database
and provides convenience functions for connection status checks.

MongoDB is the primary (and only) datastore -- no SQLite fallback.
"""
from datetime import datetime
from config import Config

# Re-export core helpers so existing imports keep working
from utils.database import get_db, get_collection, next_id


def is_mongo_available():
    """Check whether MongoDB is reachable."""
    try:
        db = get_db()
        db.command('ping')
        return True
    except Exception:
        return False


def mongo_status():
    """Return a dict describing the current MongoDB connection."""
    try:
        db = get_db()
        collections = db.list_collection_names()
        return {
            'status': 'connected',
            'backend': 'MongoDB',
            'uri': Config.MONGO_URI,
            'database': Config.MONGO_DB,
            'collections': len(collections),
            'collection_names': collections,
        }
    except Exception as e:
        return {'status': 'error', 'backend': 'MongoDB', 'error': str(e)}
