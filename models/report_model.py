from utils.database import get_collection, next_id
from utils.helper import get_cached_value
from datetime import datetime
import json


class Report:
    @staticmethod
    def create(title, description, report_type, category, generated_by,
               file_path='', chart_paths='[]', dataset_ids='[]', summary='', status='completed'):
        col = get_collection('reports')
        report_id = next_id('reports')
        col.insert_one({
            'id': report_id,
            'title': title,
            'description': description,
            'report_type': report_type,
            'category': category,
            'file_path': file_path,
            'chart_paths': chart_paths,
            'dataset_ids': dataset_ids,
            'summary': summary,
            'generated_by': generated_by,
            'status': status,
            'created_at': datetime.utcnow().isoformat(),
        })
        return report_id

    @staticmethod
    def get_all(report_type=None, limit=50):
        col = get_collection('reports')
        if report_type:
            return list(col.find({'report_type': report_type}).sort('created_at', -1).limit(limit))
        return list(col.find().sort('created_at', -1).limit(limit))

    @staticmethod
    def get_by_id(report_id):
        return get_collection('reports').find_one({'id': int(report_id)})

    @staticmethod
    def delete(report_id):
        get_collection('reports').delete_one({'id': int(report_id)})

    @staticmethod
    def get_count():
        return get_cached_value('reports:count', lambda: get_collection('reports').count_documents({}), ttl_seconds=60)

    @staticmethod
    def get_by_type():
        pipeline = [
            {'$group': {'_id': '$report_type', 'count': {'$sum': 1}}},
        ]
        return {doc['_id']: doc['count']
                for doc in get_collection('reports').aggregate(pipeline)
                if doc['_id']}
