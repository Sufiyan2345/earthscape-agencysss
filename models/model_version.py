from utils.database import get_collection, next_id
from utils.helper import get_cached_value
from datetime import datetime
import json


class ModelVersion:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    @staticmethod
    def create(model_type, model_name, version, accuracy, metrics,
               trained_on_data, file_path, trained_by, is_active=1):
        col = get_collection('model_versions')
        # Deactivate previous active versions of this model_type
        col.update_many(
            {'model_type': model_type, 'is_active': 1},
            {'$set': {'is_active': 0}}
        )
        vid = next_id('model_versions')
        col.insert_one({
            'id': vid,
            'model_type': model_type,
            'model_name': model_name,
            'version': version,
            'accuracy': accuracy,
            'metrics': json.dumps(metrics) if isinstance(metrics, dict) else metrics,
            'trained_on_data': json.dumps(trained_on_data) if isinstance(trained_on_data, dict) else trained_on_data,
            'file_path': file_path,
            'is_active': is_active,
            'trained_by': trained_by,
            'created_at': datetime.utcnow().isoformat(),
        })
        return vid

    @staticmethod
    def activate(version_id):
        """Activate one version and archive other versions of its model."""
        col = get_collection('model_versions')
        version = col.find_one({'id': int(version_id)})
        if not version:
            return False
        col.update_many({'model_type': version['model_type'], 'is_active': 1},
                       {'$set': {'is_active': 0}})
        col.update_one({'id': int(version_id)}, {'$set': {'is_active': 1}})
        return True

    @staticmethod
    def get_all(limit=100):
        return list(get_collection('model_versions').find().sort('created_at', -1).limit(limit))

    @staticmethod
    def get_by_id(version_id):
        return get_collection('model_versions').find_one({'id': int(version_id)})

    @staticmethod
    def get_active():
        """Get the active version of each model type."""
        return list(
            get_collection('model_versions').find({'is_active': 1}).sort('model_type', 1)
        )

    @staticmethod
    def get_active_by_type(model_type):
        docs = list(
            get_collection('model_versions').find(
                {'model_type': model_type, 'is_active': 1}
            ).sort('version', -1).limit(1)
        )
        return docs[0] if docs else None

    @staticmethod
    def get_history(model_type, limit=20):
        return list(
            get_collection('model_versions').find({'model_type': model_type})
            .sort('version', -1).limit(limit)
        )

    @staticmethod
    def get_next_version(model_type):
        pipeline = [
            {'$match': {'model_type': model_type}},
            {'$group': {'_id': None, 'max_ver': {'$max': '$version'}}},
        ]
        result = list(get_collection('model_versions').aggregate(pipeline))
        if result and result[0].get('max_ver') is not None:
            return result[0]['max_ver'] + 1
        return 1

    @staticmethod
    def get_count():
        return get_cached_value('ml_models:count', lambda: get_collection('model_versions').count_documents({}), ttl_seconds=60)

    @staticmethod
    def delete(version_id):
        get_collection('model_versions').delete_one({'id': int(version_id)})
