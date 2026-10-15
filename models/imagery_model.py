"""
Satellite imagery ingestion store.

Analysts ingest satellite/aerial imagery; every image is persisted with its
extracted spectral indicators so the Admin panel can monitor and manage the
ingested imagery corpus.
"""
import os
from utils.database import get_collection, next_id
from config import basedir
from datetime import datetime


class SatelliteImage:

    @staticmethod
    def resolve_file_path(image):
        """Resolve an image path after restarts or project moves."""
        stored_path = image.get('stored_path') if image else None
        if stored_path and os.path.isfile(stored_path):
            return stored_path

        filenames = []
        if stored_path:
            filenames.append(os.path.basename(stored_path))
        if image and image.get('filename'):
            filenames.append(os.path.basename(image['filename']))
        if not filenames:
            return None

        upload_folder = os.path.join(basedir, 'static', 'uploads', 'satellite_imagery')
        for filename in filenames:
            current_path = os.path.join(upload_folder, filename)
            if os.path.isfile(current_path):
                return current_path
        return None

    @staticmethod
    def create(meta):
        """Insert an ingested imagery record. Returns the new id."""
        col = get_collection('satellite_imagery')
        image_id = next_id('satellite_imagery')
        doc = dict(meta)
        doc['id'] = image_id
        doc.setdefault('created_at', datetime.utcnow().isoformat())
        col.insert_one(doc)
        return image_id

    @staticmethod
    def get_all(limit=60):
        return list(
            get_collection('satellite_imagery').find().sort('created_at', -1).limit(limit)
        )

    @staticmethod
    def get_by_id(image_id):
        return get_collection('satellite_imagery').find_one({'id': int(image_id)})

    @staticmethod
    def delete(image_id):
        get_collection('satellite_imagery').delete_one({'id': int(image_id)})

    @staticmethod
    def update(image_id, **kwargs):
        allowed = {'platform', 'latitude', 'longitude', 'capture_date', 'station_name',
                   'filename', 'stored_path', 'hdfs_path', 'file_size', 'metrics', 'dataset_id'}
        updates = {k: v for k, v in kwargs.items() if k in allowed}
        if updates:
            updates['updated_at'] = datetime.utcnow().isoformat()
            get_collection('satellite_imagery').update_one(
                {'id': int(image_id)}, {'$set': updates}
            )

    @staticmethod
    def get_stats():
        """Aggregate monitoring stats for the admin dashboard."""
        col = get_collection('satellite_imagery')
        total = col.count_documents({})
        by_platform = {}
        for doc in col.find({}, {'platform': 1}):
            key = doc.get('platform') or 'Unknown'
            by_platform[key] = by_platform.get(key, 0) + 1
        pipeline = [
            {'$group': {
                '_id': None,
                'avg_cloud': {'$avg': '$metrics.cloud_cover'},
                'avg_lst': {'$avg': '$metrics.land_surface_temp'},
                'avg_vegetation': {'$avg': '$metrics.vegetation_index'},
            }}
        ]
        agg = list(col.aggregate(pipeline))
        agg = agg[0] if agg else {}
        return {
            'total': total,
            'by_platform': by_platform,
            'avg_cloud': round(agg.get('avg_cloud') or 0, 1),
            'avg_lst': round(agg.get('avg_lst') or 0, 1),
            'avg_vegetation': round(agg.get('avg_vegetation') or 0, 1),
        }
