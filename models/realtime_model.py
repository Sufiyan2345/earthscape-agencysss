from utils.database import get_collection, next_id
from utils.helper import get_cached_value
from datetime import datetime
import json


class RealtimeStream:
    @staticmethod
    def create(stream_name, source_type, source_location, latitude, longitude, created_by, config='{}'):
        col = get_collection('realtime_streams')
        stream_id = next_id('realtime_streams')
        now = datetime.utcnow().isoformat()
        col.insert_one({
            'id': stream_id,
            'stream_name': stream_name,
            'source_type': source_type,
            'source_location': source_location,
            'latitude': latitude,
            'longitude': longitude,
            'status': 'active',
            'last_reading': None,
            'last_value': None,
            'reading_count': 0,
            'config': config,
            'created_by': created_by,
            'created_at': now,
            'updated_at': now,
        })
        return stream_id

    @staticmethod
    def get_all(status=None):
        col = get_collection('realtime_streams')
        if status:
            return list(col.find({'status': status}).sort('created_at', -1))
        return list(col.find().sort('created_at', -1))

    @staticmethod
    def get_by_id(stream_id):
        return get_collection('realtime_streams').find_one({'id': int(stream_id)})

    @staticmethod
    def update_reading(stream_id, last_reading, last_value, reading_count=None):
        updates = {
            'last_reading': last_reading,
            'last_value': last_value,
            'updated_at': datetime.utcnow().isoformat(),
        }
        if reading_count is not None:
            updates['reading_count'] = reading_count
        get_collection('realtime_streams').update_one(
            {'id': int(stream_id)}, {'$set': updates}
        )

    @staticmethod
    def toggle_status(stream_id):
        col = get_collection('realtime_streams')
        doc = col.find_one({'id': int(stream_id)})
        if doc:
            new_status = 'inactive' if doc.get('status') == 'active' else 'active'
            col.update_one(
                {'id': int(stream_id)},
                {'$set': {'status': new_status, 'updated_at': datetime.utcnow().isoformat()}}
            )

    @staticmethod
    def delete(stream_id):
        get_collection('realtime_readings').delete_many({'stream_id': int(stream_id)})
        get_collection('realtime_streams').delete_one({'id': int(stream_id)})

    @staticmethod
    def add_reading(stream_id, temperature=None, humidity=None, rainfall=None,
                    wind_speed=None, pressure=None, co2_level=None, air_quality_index=None,
                    publish=True):
        col_streams = get_collection('realtime_streams')
        col_readings = get_collection('realtime_readings')

        stream = col_streams.find_one({'id': int(stream_id)})
        location = stream.get('source_location') or stream.get('stream_name') if stream else None

        reading_id = next_id('realtime_readings')
        now = datetime.utcnow().isoformat()
        reading = {
            'id': reading_id,
            'stream_id': int(stream_id),
            'temperature': temperature,
            'humidity': humidity,
            'rainfall': rainfall,
            'wind_speed': wind_speed,
            'pressure': pressure,
            'co2_level': co2_level,
            'air_quality_index': air_quality_index,
            'location': location,
            'timestamp': now,
            'synced_to_batch': False,
        }
        col_readings.insert_one(reading)

        # Promote every realtime reading immediately so batch analysis sees a
        # continuous stream. The source id makes retries and manual sync safe.
        try:
            climate_col = get_collection('climate_data')
            if not climate_col.find_one({'realtime_reading_id': reading_id}):
                climate_col.insert_one({
                    'id': next_id('climate_data'),
                    'realtime_reading_id': reading_id,
                    'station_name': location,
                    'date': now[:10],
                    'temperature': temperature,
                    'humidity': humidity,
                    'rainfall': rainfall,
                    'wind_speed': wind_speed,
                    'pressure': pressure,
                    'co2_level': co2_level,
                    'air_quality_index': air_quality_index,
                    'data_source': 'realtime',
                    'created_at': now,
                })
                col_readings.update_one({'id': reading_id}, {'$set': {'synced_to_batch': True}})
        except Exception as exc:
            print(f"Realtime batch promotion failed: {exc}")

        # Update stream metadata
        col_streams.update_one(
            {'id': int(stream_id)},
            {'$set': {
                'last_reading': now,
                'last_value': temperature,
                'updated_at': now,
            }, '$inc': {'reading_count': 1}}
        )

        try:
            from utils.ingestion_backend import broker
            if publish:
                broker.publish({'event': 'climate.reading', 'stream_id': int(stream_id), 'reading': reading})
        except Exception:
            pass

        # Automatically check thresholds and create alerts
        try:
            from utils.notifications import check_and_create_alerts
            data_point = {
                'temperature': temperature,
                'humidity': humidity,
                'rainfall': rainfall,
                'wind_speed': wind_speed,
                'co2_level': co2_level,
                'air_quality_index': air_quality_index
            }
            check_and_create_alerts(data_point, source='realtime', location=location)
        except Exception as e:
            print(f"Auto-alert check failed: {e}")

    @staticmethod
    def get_readings(stream_id, limit=100):
        return list(
            get_collection('realtime_readings').find(
                {'stream_id': int(stream_id)}
            ).sort('timestamp', -1).limit(limit)
        )

    @staticmethod
    def get_latest_reading(stream_id):
        docs = list(
            get_collection('realtime_readings').find(
                {'stream_id': int(stream_id)}
            ).sort('timestamp', -1).limit(1)
        )
        return docs[0] if docs else None

    @staticmethod
    def get_count():
        return get_cached_value('realtime_streams:count', lambda: get_collection('realtime_streams').count_documents({}), ttl_seconds=30)

    @staticmethod
    def get_active_count():
        return get_cached_value('realtime_streams:active_count', lambda: get_collection('realtime_streams').count_documents({'status': 'active'}), ttl_seconds=30)
