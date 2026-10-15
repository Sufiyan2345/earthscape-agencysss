from utils.database import get_collection, next_id
from utils.helper import get_cached_value, invalidate_cache
from datetime import datetime, timedelta


class Alert:
    @staticmethod
    def create(title, message, alert_type='warning', severity='medium',
               category='weather', threshold_value=None, actual_value=None,
               location=None, created_by=None, source='manual', dedupe_key=None):
        col = get_collection('alerts')
        if dedupe_key:
            cutoff = (datetime.utcnow() - timedelta(minutes=15)).isoformat()
            recent = col.find_one({
                'dedupe_key': dedupe_key,
                'is_resolved': 0,
                'created_at': {'$gte': cutoff},
            })
            if recent:
                return recent.get('id')
        alert_id = next_id('alerts')
        col.insert_one({
            'id': alert_id,
            'title': title,
            'message': message,
            'alert_type': alert_type,
            'severity': severity,
            'category': category,
            'threshold_value': threshold_value,
            'actual_value': actual_value,
            'location': location,
            'is_read': 0,
            'is_resolved': 0,
            'resolved_by': None,
            'resolved_at': None,
            'created_by': created_by,
            'source': source,
            'dedupe_key': dedupe_key or '',
            'created_at': datetime.utcnow().isoformat(),
        })
        invalidate_cache('alerts:')
        return alert_id

    @staticmethod
    def get_all(limit=100, severity=None, is_read=None):
        col = get_collection('alerts')
        query = {}
        if severity:
            query['severity'] = severity
        if is_read is not None:
            query['is_read'] = is_read
        return list(col.find(query).sort('created_at', -1).limit(limit))

    @staticmethod
    def get_by_id(alert_id):
        return get_collection('alerts').find_one({'id': int(alert_id)})

    @staticmethod
    def mark_read(alert_id):
        get_collection('alerts').update_one(
            {'id': int(alert_id)}, {'$set': {'is_read': 1}}
        )
        invalidate_cache('alerts:')

    @staticmethod
    def mark_all_read():
        get_collection('alerts').update_many(
            {'is_read': 0}, {'$set': {'is_read': 1}}
        )
        invalidate_cache('alerts:')

    @staticmethod
    def resolve(alert_id, resolved_by):
        get_collection('alerts').update_one(
            {'id': int(alert_id)},
            {'$set': {
                'is_resolved': 1,
                'resolved_by': resolved_by,
                'resolved_at': datetime.utcnow().isoformat(),
            }}
        )
        invalidate_cache('alerts:')

    @staticmethod
    def delete(alert_id):
        get_collection('alerts').delete_one({'id': int(alert_id)})
        invalidate_cache('alerts:')

    @staticmethod
    def get_unread_count():
        return get_cached_value('alerts:unread_count', lambda: get_collection('alerts').count_documents({'is_read': 0}), ttl_seconds=15)

    @staticmethod
    def get_count():
        return get_cached_value('alerts:total_count', lambda: get_collection('alerts').count_documents({}), ttl_seconds=60)

    @staticmethod
    def get_by_severity():
        pipeline = [
            {'$group': {'_id': '$severity', 'count': {'$sum': 1}}},
        ]
        result = {}
        for doc in get_collection('alerts').aggregate(pipeline):
            if doc['_id']:
                result[doc['_id']] = doc['count']
        return result

    @staticmethod
    def check_thresholds(data_point, thresholds):
        alerts_triggered = []
        if data_point.get('temperature') and data_point['temperature'] > thresholds.get('temperature_max', 45):
            alerts_triggered.append({
                'title': 'High Temperature Alert',
                'message': f"Temperature {data_point['temperature']}°C exceeds threshold of {thresholds['temperature_max']}°C",
                'alert_type': 'danger',
                'severity': 'high',
                'category': 'temperature',
                'threshold_value': thresholds['temperature_max'],
                'actual_value': data_point['temperature'],
            })
        if data_point.get('rainfall') and data_point['rainfall'] > thresholds.get('rainfall_max', 200):
            alerts_triggered.append({
                'title': 'Heavy Rainfall Alert',
                'message': f"Rainfall {data_point['rainfall']}mm exceeds threshold of {thresholds['rainfall_max']}mm",
                'alert_type': 'warning',
                'severity': 'high',
                'category': 'rainfall',
                'threshold_value': thresholds['rainfall_max'],
                'actual_value': data_point['rainfall'],
            })
        if data_point.get('air_quality_index') and data_point['air_quality_index'] > thresholds.get('air_quality_max', 300):
            alerts_triggered.append({
                'title': 'Poor Air Quality Alert',
                'message': f"AQI {data_point['air_quality_index']} exceeds threshold of {thresholds['air_quality_max']}",
                'alert_type': 'warning',
                'severity': 'medium',
                'category': 'air_quality',
                'threshold_value': thresholds['air_quality_max'],
                'actual_value': data_point['air_quality_index'],
            })
        if data_point.get('wind_speed') and data_point['wind_speed'] > thresholds.get('wind_speed_max', 120):
            alerts_triggered.append({
                'title': 'High Wind Speed Alert',
                'message': f"Wind speed {data_point['wind_speed']}km/h exceeds threshold of {thresholds['wind_speed_max']}km/h",
                'alert_type': 'danger',
                'severity': 'high',
                'category': 'wind',
                'threshold_value': thresholds['wind_speed_max'],
                'actual_value': data_point['wind_speed'],
            })
        return alerts_triggered
