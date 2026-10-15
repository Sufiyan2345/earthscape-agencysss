"""Optional production ingestion backends for provider, broker, and HDFS IO."""
import json
import os
import threading
from datetime import datetime

import requests

from config import Config


def provider_status():
    """Return live provider availability without failing the dashboard."""
    status = {'weather': {'name': 'Open-Meteo', 'available': False},
              'satellite': {'name': 'NASA POWER', 'available': False}}
    try:
        response = requests.get('https://api.open-meteo.com/v1/forecast', params={
            'latitude': 0, 'longitude': 0, 'current': 'temperature_2m',
        }, timeout=3)
        status['weather']['available'] = response.ok
    except requests.RequestException:
        pass
    try:
        response = requests.get('https://power.larc.nasa.gov/api/temporal/daily/point', params={
            'parameters': 'T2M', 'community': 'AG', 'longitude': 0, 'latitude': 0,
            'start': datetime.utcnow().strftime('%Y%m%d'),
            'end': datetime.utcnow().strftime('%Y%m%d'), 'format': 'JSON',
        }, timeout=3)
        status['satellite']['available'] = response.ok
    except requests.RequestException:
        pass
    return status


class ClimateEventBroker:
    """Kafka producer with an explicit unavailable fallback."""
    def __init__(self):
        self.servers = os.environ.get('KAFKA_BOOTSTRAP_SERVERS', '').strip()
        self.topic = os.environ.get('KAFKA_CLIMATE_TOPIC', 'earthscape.climate.readings')
        self._producer = None
        if self.servers:
            try:
                from kafka import KafkaProducer
                self._producer = KafkaProducer(
                    bootstrap_servers=[item.strip() for item in self.servers.split(',')],
                    value_serializer=lambda value: json.dumps(value).encode('utf-8'),
                    request_timeout_ms=5000,
                )
            except Exception:
                self._producer = None

    @property
    def available(self):
        return self._producer is not None

    def publish(self, event):
        if not self._producer:
            return False
        try:
            self._producer.send(self.topic, event)
            self._producer.flush(timeout=5)
            return True
        except Exception:
            return False

    def start_consumer(self, handler):
        if not self.servers or os.environ.get('KAFKA_CONSUME', 'true').lower() != 'true':
            return False

        def consume():
            try:
                from kafka import KafkaConsumer
                consumer = KafkaConsumer(
                    self.topic, bootstrap_servers=[item.strip() for item in self.servers.split(',')],
                    group_id=os.environ.get('KAFKA_CONSUMER_GROUP', 'earthscape-climate'),
                    auto_offset_reset='latest', value_deserializer=lambda value: json.loads(value.decode('utf-8')),
                )
                for message in consumer:
                    handler(message.value)
            except Exception:
                return

        threading.Thread(target=consume, daemon=True, name='earthscape-kafka-consumer').start()
        return True


broker = ClimateEventBroker()


def handle_climate_event(event):
    """Persist external Kafka readings through the canonical realtime model."""
    reading = event.get('reading') or {}
    stream_id = event.get('stream_id')
    if not stream_id or not isinstance(reading, dict):
        return
    from utils.database import get_collection
    if reading.get('id') and get_collection('realtime_readings').find_one({'id': reading['id']}):
        return
    from models.realtime_model import RealtimeStream
    RealtimeStream.add_reading(
        stream_id,
        temperature=reading.get('temperature'), humidity=reading.get('humidity'),
        rainfall=reading.get('rainfall'), wind_speed=reading.get('wind_speed'),
        pressure=reading.get('pressure'), co2_level=reading.get('co2_level'),
        air_quality_index=reading.get('air_quality_index'), publish=False,
    )


def verified_hdfs_upload(local_path, hdfs_path, replication=3):
    """Upload to HDFS and verify existence plus byte length."""
    from utils.webhdfs import real_hdfs
    if not real_hdfs.upload_from_file(local_path, hdfs_path, replication=replication):
        raise RuntimeError('HDFS upload was rejected.')
    if not real_hdfs.exists(hdfs_path):
        raise RuntimeError(f'HDFS verification failed: {hdfs_path} is missing.')
    status = real_hdfs.get_file_status(hdfs_path) or {}
    expected = os.path.getsize(local_path)
    actual = status.get('length')
    if actual is not None and int(actual) != expected:
        raise RuntimeError(f'HDFS verification failed: expected {expected} bytes, received {actual}.')
    return {'path': hdfs_path, 'size': expected, 'verified': True}
