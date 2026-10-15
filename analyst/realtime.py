from flask import render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import login_required, current_user
from analyst import analyst_bp
from auth.decorators import analyst_required
from models.realtime_model import RealtimeStream
from utils.database import get_collection, next_id
from utils.model_cache import get_anomaly_detector
from utils.realtime_anomalies import detect_latest_reading
import json
import math
import time
import numpy as np
from datetime import datetime


@analyst_bp.route('/realtime')
@login_required
@analyst_required
def realtime():
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
            sort=[('timestamp', -1)]
        )
        current_temp = round(latest['temperature'], 1) if latest and latest.get('temperature') else 0.0

        # Count anomalies using real AnomalyDetector
        anomalies = _count_realtime_anomalies()
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
                latest_readings.extend(readings)
        except Exception:
            pass

    # Get batch-realtime sync stats
    sync_stats = _get_sync_stats()

    return render_template('analyst/realtime.html',
                         streams=streams,
                         active_streams=active_streams,
                         total_readings=total_readings,
                         current_temp=current_temp,
                         anomalies=anomalies,
                         latest_readings=latest_readings,
                         sync_stats=sync_stats,
                         active_page='realtime')


@analyst_bp.route('/realtime/create', methods=['POST'])
@login_required
@analyst_required
def create_stream():
    stream_name = request.form.get('stream_name', '').strip()
    source_type = request.form.get('source_type', 'sensor')
    source_location = request.form.get('source_location', '')
    latitude = request.form.get('latitude', 0, type=float)
    longitude = request.form.get('longitude', 0, type=float)

    if not stream_name:
        flash('Stream name is required.', 'danger')
        return redirect(url_for('analyst.realtime'))

    RealtimeStream.create(stream_name, source_type, source_location, latitude, longitude, current_user.id)
    flash(f'Stream "{stream_name}" created successfully.', 'success')
    return redirect(url_for('analyst.realtime'))


@analyst_bp.route('/realtime/<int:stream_id>/toggle', methods=['POST'])
@login_required
@analyst_required
def toggle_stream(stream_id):
    RealtimeStream.toggle_status(stream_id)
    flash('Stream status toggled successfully.', 'success')
    return redirect(url_for('analyst.realtime'))


@analyst_bp.route('/realtime/<int:stream_id>/readings')
@login_required
@analyst_required
def stream_readings(stream_id):
    readings = RealtimeStream.get_readings(stream_id, limit=50)
    stream = RealtimeStream.get_by_id(stream_id)
    streams = RealtimeStream.get_all()

    active_streams = sum(1 for s in streams if s.get('status') == 'active')
    total_readings = len(readings)
    current_temp = round(readings[0].get('temperature', 0) or 0, 1) if readings else 0.0

    # Run real anomaly detection on readings
    anomaly_results = _analyze_stream_readings(readings)

    return render_template('analyst/realtime.html',
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


@analyst_bp.route('/realtime/<int:stream_id>/simulate', methods=['POST'])
@login_required
@analyst_required
def simulate_reading(stream_id):
    """Generate a realistic reading based on historical climate patterns for the stream."""
    streams_col = get_collection('realtime_streams')
    readings_col = get_collection('realtime_readings')

    # Get stream info for location-based simulation
    stream = streams_col.find_one({'id': stream_id})

    # Get recent readings to base simulation on (for temporal continuity)
    recent = list(readings_col.find(
        {'stream_id': stream_id}
    ).sort('timestamp', -1).limit(10))

    now = datetime.utcnow()
    hour = now.hour
    month = now.month

    # Seasonal base temperature (Northern hemisphere model)
    seasonal_bases = {
        1: 5, 2: 7, 3: 12, 4: 17, 5: 22, 6: 27,
        7: 30, 8: 29, 9: 24, 10: 18, 11: 12, 12: 7
    }
    base_temp = seasonal_bases.get(month, 15)

    # Diurnal cycle: coolest at 5am, warmest at 3pm
    diurnal_offset = -5 * math.cos((hour - 15) * math.pi / 12)

    # If recent readings exist, blend with them for continuity
    if recent:
        last_temp = recent[0]['temperature'] or base_temp + diurnal_offset
        last_humidity = recent[0]['humidity'] or 60
        # Blend: 70% model, 30% last reading for smooth transitions
        temp = round(0.7 * (base_temp + diurnal_offset) + 0.3 * last_temp + np.random.normal(0, 1.0), 1)
        humidity = round(0.6 * (65 - diurnal_offset * 0.8) + 0.4 * last_humidity + np.random.normal(0, 2.0), 1)
        humidity = max(15, min(100, humidity))
    else:
        temp = round(base_temp + diurnal_offset + np.random.normal(0, 2.0), 1)
        humidity = round(max(15, min(100, 65 - diurnal_offset * 0.8 + np.random.normal(0, 5.0))), 1)

    # Rainfall: exponential with seasonal weighting (wetter in summer)
    rain_prob = 0.3 if month in (6, 7, 8, 9) else 0.15
    if np.random.random() < rain_prob:
        rainfall = round(max(0, np.random.exponential(8)), 1)
    else:
        rainfall = 0.0

    # Wind speed: Weibull-like distribution
    wind = round(max(0, np.random.weibull(2) * 12 + 5), 1)

    # Pressure: seasonal variation around 1013 hPa
    pressure = round(1013 + 5 * math.sin(month * math.pi / 6) + np.random.normal(0, 3), 1)

    # CO2: gradual upward trend with seasonal cycle
    co2 = round(415 + 10 * math.sin(month * math.pi / 6) + np.random.normal(0, 3), 1)

    # AQI: correlated with temperature and wind
    base_aqi = 50 + (temp - 20) * 1.5 - wind * 0.5
    aqi = round(max(0, min(500, base_aqi + np.random.normal(0, 10))), 0)

    RealtimeStream.add_reading(stream_id, temperature=temp, humidity=humidity,
                              rainfall=rainfall, wind_speed=wind, pressure=pressure,
                              co2_level=co2, air_quality_index=aqi)
    RealtimeStream.update_reading(stream_id, datetime.utcnow().isoformat(), temp)

    flash(f'Simulated reading added: {temp}°C, humidity {humidity}%, rainfall {rainfall}mm.', 'success')
    return redirect(url_for('analyst.realtime'))


@analyst_bp.route('/realtime/<int:stream_id>/simulate-batch', methods=['POST'])
@login_required
@analyst_required
def simulate_batch(stream_id):
    """Process a burst of simulated realtime readings (batch of live data)."""
    count = min(max(request.form.get('count', 10, type=int) or 10, 1), 50)
    stream = RealtimeStream.get_by_id(stream_id)
    if not stream:
        flash('Stream not found.', 'danger')
        return redirect(url_for('analyst.realtime'))

    last_temp = None
    for _ in range(count):
        temp = round(15 + np.random.normal(8, 5) + np.random.uniform(-3, 3), 1)
        humidity = round(max(15, min(100, 60 + np.random.normal(0, 12))), 1)
        rainfall = round(max(0, np.random.exponential(6)), 1) if np.random.random() < 0.25 else 0.0
        wind = round(max(0, np.random.weibull(2) * 12 + 5), 1)
        pressure = round(1013 + np.random.normal(0, 4), 1)
        co2 = round(415 + np.random.normal(0, 6), 1)
        aqi = round(max(0, min(500, 50 + (temp - 20) * 1.5 - wind * 0.5 + np.random.normal(0, 10))), 0)
        RealtimeStream.add_reading(stream_id, temperature=temp, humidity=humidity,
                                   rainfall=rainfall, wind_speed=wind, pressure=pressure,
                                   co2_level=co2, air_quality_index=aqi)
        last_temp = temp

    flash(f'Processed {count} realtime readings for "{stream.get("stream_name")}" (last temp: {last_temp}°C).', 'success')
    return redirect(url_for('analyst.realtime'))


@analyst_bp.route('/realtime/<int:stream_id>/add-reading', methods=['POST'])
@login_required
@analyst_required
def add_manual_reading(stream_id):
    """Manually enter a realtime climate reading for processing."""
    stream = RealtimeStream.get_by_id(stream_id)
    if not stream:
        flash('Stream not found.', 'danger')
        return redirect(url_for('analyst.realtime'))

    def _num(field):
        val = request.form.get(field, '')
        if val is None or str(val).strip() == '':
            return None
        try:
            return float(val)
        except (ValueError, TypeError):
            return None

    temperature = _num('temperature')
    humidity = _num('humidity')
    rainfall = _num('rainfall')
    wind_speed = _num('wind_speed')
    pressure = _num('pressure')
    co2_level = _num('co2_level')
    aqi = _num('air_quality_index')

    if all(v is None for v in (temperature, humidity, rainfall, wind_speed, pressure, co2_level, aqi)):
        flash('Enter at least one measurement value.', 'warning')
        return redirect(url_for('analyst.realtime'))

    RealtimeStream.add_reading(stream_id, temperature=temperature, humidity=humidity,
                               rainfall=rainfall, wind_speed=wind_speed, pressure=pressure,
                               co2_level=co2_level, air_quality_index=aqi)
    flash(f'Reading submitted to "{stream.get("stream_name")}" for processing.', 'success')
    return redirect(url_for('analyst.realtime'))


@analyst_bp.route('/realtime/<int:stream_id>/delete', methods=['POST'])
@login_required
@analyst_required
def delete_stream(stream_id):
    RealtimeStream.delete(stream_id)
    flash('Stream deleted successfully.', 'success')
    return redirect(url_for('analyst.realtime'))


@analyst_bp.route('/realtime/<int:stream_id>/data')
@login_required
@analyst_required
def stream_data(stream_id):
    """JSON endpoint with readings and real anomaly detection."""
    readings = RealtimeStream.get_readings(stream_id, limit=20)

    # Run real anomaly detection on latest readings
    anomaly_flags = []
    if readings:
        detector = get_anomaly_detector()
        latest = readings[0]
        temp = latest.get('temperature')
        if temp is not None:
            result = detector.detect_temperature_anomaly(temp)
            if result.get('is_anomaly'):
                anomaly_flags.append({
                    'type': result.get('type', 'unknown'),
                    'severity': result.get('severity', 'unknown'),
                    'z_score': result.get('z_score', 0),
                    'value': temp,
                })

        aqi = latest.get('air_quality_index')
        if aqi is not None:
            aqi_result = detector.detect_air_quality_anomaly(aqi)
            if aqi_result.get('is_anomaly'):
                anomaly_flags.append({
                    'type': 'air_quality',
                    'severity': aqi_result.get('severity', 'unknown'),
                    'category': aqi_result.get('category', ''),
                    'value': aqi,
                })

        rain = latest.get('rainfall')
        hum = latest.get('humidity')
        wind = latest.get('wind_speed')
        if rain is not None and hum is not None:
            flood = detector.detect_flood_risk(rain, hum, wind)
            if flood.get('risk_level') in ('high', 'critical'):
                anomaly_flags.append({
                    'type': 'flood_risk',
                    'severity': flood.get('risk_level', 'unknown'),
                    'risk_score': flood.get('risk_score', 0),
                    'factors': flood.get('factors', []),
                })

    return jsonify({
        'readings': readings,
        'anomalies': anomaly_flags,
        'timestamp': datetime.utcnow().isoformat()
    })


@analyst_bp.route('/realtime/<int:stream_id>/stream')
@login_required
@analyst_required
def sse_stream(stream_id):
    """Server-Sent Events endpoint for true real-time streaming."""
    def event_stream():
        last_count = 0
        readings_col = get_collection('realtime_readings')
        detector = get_anomaly_detector()
        while True:
            current_count = readings_col.count_documents({'stream_id': stream_id})
            if current_count != last_count:
                readings = list(readings_col.find(
                    {'stream_id': stream_id}
                ).sort('timestamp', -1).limit(5))
                anomaly_flags = detect_latest_reading(detector, readings[0] if readings else None)

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


@analyst_bp.route('/realtime/sync-to-batch', methods=['POST'])
@login_required
@analyst_required
def sync_to_batch():
    """Promote realtime readings into climate_data for batch processing."""
    try:
        readings_col = get_collection('realtime_readings')
        streams_col = get_collection('realtime_streams')
        readings = list(readings_col.find({'synced_to_batch': {'$ne': True}}).sort('timestamp', -1).limit(500))

        if not readings:
            flash('No realtime readings to sync.', 'warning')
            return redirect(url_for('analyst.realtime'))

        # Resolve stream info
        stream_ids = list(set(r.get('stream_id') for r in readings if r.get('stream_id')))
        stream_map = {}
        if stream_ids:
            for s in streams_col.find({'id': {'$in': stream_ids}}):
                stream_map[s['id']] = s

        climate_col = get_collection('climate_data')
        synced = 0
        for r in readings:
            rd = dict(r)
            stream_info = stream_map.get(rd.get('stream_id'), {})
            station = stream_info.get('stream_name') or stream_info.get('source_location') or 'Realtime Sensor'
            date_val = rd.get('timestamp', '')[:10] if rd.get('timestamp') else datetime.utcnow().strftime('%Y-%m-%d')

            climate_col.insert_one({
                'id': next_id('climate_data'),
                'realtime_reading_id': rd.get('id'),
                'station_name': station,
                'date': date_val,
                'temperature': rd.get('temperature'),
                'humidity': rd.get('humidity'),
                'rainfall': rd.get('rainfall'),
                'wind_speed': rd.get('wind_speed'),
                'pressure': rd.get('pressure'),
                'co2_level': rd.get('co2_level'),
                'air_quality_index': rd.get('air_quality_index'),
                'data_source': 'realtime',
            })
            synced += 1
            readings_col.update_one({'id': rd.get('id')}, {'$set': {'synced_to_batch': True}})

        flash(f'Successfully synced {synced} realtime readings to batch processing.', 'success')
    except Exception as e:
        flash(f'Sync failed: {str(e)}', 'danger')

    return redirect(url_for('analyst.realtime'))


@analyst_bp.route('/realtime/batch-baselines')
@login_required
def batch_baselines():
    """Compute realtime alert thresholds from batch climate_data analysis."""
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

        detector = get_anomaly_detector()
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

    detector = get_anomaly_detector()
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
    """Get statistics about realtime-to-batch sync status."""
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
            avg_temp = stats.get('avg_temp') or 0
            avg_humidity = stats.get('avg_humidity') or 0
            avg_rainfall = stats.get('avg_rainfall') or 0
            avg_wind = stats.get('avg_wind') or 0
            avg_aqi = stats.get('avg_aqi') or 0

            return {
                'temperature': {
                    'mean': round(avg_temp, 2),
                    'alert_low': round(avg_temp - 15, 2),
                    'alert_high': round(avg_temp + 15, 2),
                    'absolute_min': round(stats.get('min_temp') or 0, 2),
                    'absolute_max': round(stats.get('max_temp') or 0, 2),
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
