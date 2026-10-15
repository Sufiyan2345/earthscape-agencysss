from flask import render_template, redirect, url_for, flash, jsonify, Response
from flask_login import login_required
from admin import admin_bp
from auth.decorators import admin_required
from models.realtime_model import RealtimeStream
from utils.database import get_collection
from ml_models.anomaly_detection import AnomalyDetector
from utils.realtime_anomalies import detect_latest_reading
import json
import math
import time
import numpy as np
from datetime import datetime


@admin_bp.route('/realtime')
@login_required
@admin_required
def realtime():
    """Admin real-time streaming monitoring dashboard."""
    streams = RealtimeStream.get_all()

    # Compute summary stats
    active_streams = sum(1 for s in streams if s.get('status') == 'active')
    total_readings = 0
    current_temp = 0.0
    anomalies = 0

    try:
        readings_col = get_collection('realtime_readings')
        total_readings = readings_col.count_documents({})

        latest = readings_col.find_one(
            {'temperature': {'$ne': None}},
            sort=[('timestamp', -1)],
        )
        current_temp = round(latest['temperature'], 1) if latest and latest.get('temperature') else 0.0

        # Count anomalies using real AnomalyDetector
        anomaly_count = _count_realtime_anomalies()
        anomalies = anomaly_count
    except Exception:
        pass

    # Get latest readings for chart
    latest_readings = []
    if streams:
        try:
            readings_col = get_collection('realtime_readings')
            for stream in streams[:3]:
                readings = list(readings_col.find(
                    {'stream_id': stream['id']}
                ).sort('timestamp', -1).limit(20))
                latest_readings.extend([dict(r) for r in readings])
        except Exception:
            pass

    # Get batch-realtime sync stats
    sync_stats = _get_sync_stats()

    return render_template('admin/realtime.html',
                         streams=streams,
                         active_streams=active_streams,
                         total_readings=total_readings,
                         current_temp=current_temp,
                         anomalies=anomalies,
                         latest_readings=latest_readings,
                         sync_stats=sync_stats,
                         active_page='realtime')


@admin_bp.route('/realtime/<int:stream_id>/readings')
@login_required
@admin_required
def stream_readings(stream_id):
    readings = RealtimeStream.get_readings(stream_id, limit=50)
    stream = RealtimeStream.get_by_id(stream_id)
    streams = RealtimeStream.get_all()

    active_streams = sum(1 for s in streams if s.get('status') == 'active')
    total_readings = len(readings)
    current_temp = round(readings[0].get('temperature', 0) or 0, 1) if readings else 0.0

    # Run real anomaly detection on readings
    anomaly_results = _analyze_stream_readings(readings)

    return render_template('admin/realtime.html',
                         streams=streams,
                         readings=readings,
                         latest_readings=readings,
                         anomaly_results=anomaly_results,
                         current_stream=stream,
                         active_streams=active_streams,
                         total_readings=total_readings,
                         current_temp=current_temp,
                         anomalies=len(anomaly_results.get('anomalies', [])),
                         sync_stats=_get_sync_stats(),
                         active_page='realtime')


@admin_bp.route('/realtime/<int:stream_id>/data')
@login_required
@admin_required
def stream_data(stream_id):
    """JSON endpoint for live data polling / SSE fallback."""
    readings = RealtimeStream.get_readings(stream_id, limit=20)
    # Run anomaly detection on latest readings
    detector = AnomalyDetector()
    anomaly_flags = detect_latest_reading(detector, readings[0] if readings else None)
    return jsonify({
        'readings': readings,
        'anomalies': anomaly_flags,
        'timestamp': datetime.utcnow().isoformat()
    })


@admin_bp.route('/realtime/<int:stream_id>/stream')
@login_required
@admin_required
def sse_stream(stream_id):
    """Server-Sent Events endpoint for true real-time streaming."""
    def event_stream():
        last_count = 0
        detector = AnomalyDetector()
        while True:
            readings_col = get_collection('realtime_readings')
            current_count = readings_col.count_documents({'stream_id': stream_id})

            if current_count != last_count:
                readings = list(readings_col.find(
                    {'stream_id': stream_id}
                ).sort('timestamp', -1).limit(5))

                # Run the same checks as the polling endpoint.
                anomaly_flags = detect_latest_reading(
                    detector if readings else AnomalyDetector(),
                    dict(readings[0]) if readings else None,
                )

                data = {
                    'readings': [dict(r) for r in readings],
                    'anomalies': anomaly_flags,
                    'count': current_count,
                    'timestamp': datetime.utcnow().isoformat()
                }
                yield f"data: {json.dumps(data)}\n\n"
                last_count = current_count

            time.sleep(2)

    return Response(event_stream(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


@admin_bp.route('/realtime/batch-baselines')
@login_required
@admin_required
def batch_baselines():
    """Compute realtime alert thresholds from batch (climate_data) analysis."""
    baselines = _compute_baselines()
    return jsonify(baselines)


# ── Helper functions ────────────────────────────────────────────────────────

def _count_realtime_anomalies():
    """Count anomalies in realtime readings using AnomalyDetector."""
    try:
        col = get_collection('realtime_readings')
        rows = list(col.find(
            {'temperature': {'$ne': None}}
        ).sort('timestamp', -1).limit(100))

        if not rows:
            return 0

        detector = AnomalyDetector()
        count = 0
        for r in rows:
            temp = r['temperature']
            result = detector.detect_temperature_anomaly(temp)
            if result.get('is_anomaly'):
                count += 1

            aqi = r.get('air_quality_index')
            if aqi is not None:
                aqi_result = detector.detect_air_quality_anomaly(aqi)
                if aqi_result.get('is_anomaly'):
                    count += 1

        return count
    except Exception:
        return 0


def _analyze_stream_readings(readings):
    """Run full anomaly analysis on stream readings using AnomalyDetector."""
    if not readings:
        return {'anomalies': [], 'summary': {}}

    detector = AnomalyDetector()
    anomalies = []

    for r in readings:
        temp = r.get('temperature')
        if temp is not None:
            result = detector.detect_temperature_anomaly(temp)
            if result.get('is_anomaly'):
                anomalies.append({
                    'timestamp': r.get('timestamp', ''),
                    'metric': 'temperature',
                    'value': temp,
                    'type': result.get('type', 'unknown'),
                    'severity': result.get('severity', 'unknown'),
                    'z_score': result.get('z_score', 0),
                })

        aqi = r.get('air_quality_index')
        if aqi is not None:
            result = detector.detect_air_quality_anomaly(aqi)
            if result.get('is_anomaly'):
                anomalies.append({
                    'timestamp': r.get('timestamp', ''),
                    'metric': 'air_quality',
                    'value': aqi,
                    'type': 'air_quality',
                    'severity': result.get('severity', 'unknown'),
                    'category': result.get('category', ''),
                })

        rain = r.get('rainfall')
        hum = r.get('humidity')
        wind = r.get('wind_speed')
        if rain is not None and hum is not None:
            flood = detector.detect_flood_risk(rain, hum, wind)
            if flood.get('risk_level') in ('high', 'critical'):
                anomalies.append({
                    'timestamp': r.get('timestamp', ''),
                    'metric': 'flood_risk',
                    'value': flood.get('risk_score', 0),
                    'type': 'flood_risk',
                    'severity': flood.get('risk_level', 'unknown'),
                    'factors': flood.get('factors', []),
                })

    return {
        'anomalies': anomalies,
        'summary': {
            'total_readings': len(readings),
            'anomalies_found': len(anomalies),
            'anomaly_rate': round(len(anomalies) / max(1, len(readings)) * 100, 1),
        }
    }


def _get_sync_stats():
    """Get statistics about realtime-to-batch sync status (monitoring view)."""
    try:
        readings_col = get_collection('realtime_readings')
        climate_col = get_collection('climate_data')
        total_rt = readings_col.count_documents({})
        synced = climate_col.count_documents({'data_source': 'realtime'})
        # Readings received but not yet promoted into the batch collection
        pending = max(0, total_rt - synced)
        return {
            'total_realtime_readings': total_rt,
            'synced_to_batch': synced,
            'pending_sync': pending,
        }
    except Exception:
        return {'total_realtime_readings': 0, 'synced_to_batch': 0, 'pending_sync': 0}


def _compute_baselines():
    """Compute baselines from batch climate_data for realtime alert thresholds."""
    try:
        col = get_collection('climate_data')
        pipeline = [
            {'$match': {'temperature': {'$ne': None}}},
            {'$group': {
                '_id': None,
                'avg_temp': {'$avg': '$temperature'},
                'avg_humidity': {'$avg': '$humidity'},
                'avg_rainfall': {'$avg': '$rainfall'},
                'avg_wind': {'$avg': '$wind_speed'},
                'avg_aqi': {'$avg': '$air_quality_index'},
                'min_temp': {'$min': '$temperature'},
                'max_temp': {'$max': '$temperature'},
                'min_aqi': {'$min': '$air_quality_index'},
                'max_aqi': {'$max': '$air_quality_index'},
            }},
        ]
        result = list(col.aggregate(pipeline))

        if result and result[0].get('avg_temp') is not None:
            stats = result[0]
            avg_temp = stats['avg_temp'] or 0
            avg_humidity = stats['avg_humidity'] or 0
            avg_rainfall = stats['avg_rainfall'] or 0
            avg_wind = stats['avg_wind'] or 0
            avg_aqi = stats['avg_aqi'] or 0

            return {
                'temperature': {
                    'mean': round(avg_temp, 2),
                    'alert_low': round(avg_temp - 15, 2),
                    'alert_high': round(avg_temp + 15, 2),
                    'absolute_min': round(stats['min_temp'] or 0, 2),
                    'absolute_max': round(stats['max_temp'] or 0, 2),
                },
                'humidity': {'mean': round(avg_humidity, 2)},
                'rainfall': {'mean': round(avg_rainfall, 2), 'flood_threshold': round(avg_rainfall + 50, 2)},
                'wind_speed': {'mean': round(avg_wind, 2)},
                'air_quality': {
                    'mean': round(avg_aqi, 2),
                    'alert_threshold': round(avg_aqi + 100, 2),
                },
                'source': 'batch_climate_data',
            }
        return {'error': 'No batch data available for baselines'}
    except Exception as e:
        return {'error': str(e)}
