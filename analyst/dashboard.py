from flask import render_template
from flask_login import login_required
from analyst import analyst_bp
from auth.decorators import analyst_required
from models.climate_model import ClimateData
from models.dataset_model import Dataset
from models.alert_model import Alert
from models.prediction_model import Prediction
from models.realtime_model import RealtimeStream
from utils.helper import get_system_stats, get_cached_value
from utils.database import get_collection
import json


@analyst_bp.route('/')
@analyst_bp.route('/dashboard')
@login_required
@analyst_required
def dashboard():
    stats = get_cached_value('analyst:system_stats', get_system_stats, ttl_seconds=30)
    datasets = get_cached_value('analyst:datasets', lambda: Dataset.get_all(limit=10), ttl_seconds=30)
    climate_summary = get_cached_value('analyst:climate_summary', ClimateData.get_summary, ttl_seconds=30)
    monthly_trends = get_cached_value('analyst:monthly_trends', ClimateData.get_monthly_trends, ttl_seconds=30)
    recent_alerts = get_cached_value('analyst:recent_alerts', lambda: Alert.get_all(limit=5), ttl_seconds=30)
    active_streams = get_cached_value('analyst:active_streams', lambda: RealtimeStream.get_all(status='active'), ttl_seconds=30)
    regional = get_cached_value('analyst:regional_data', ClimateData.get_regional_data, ttl_seconds=30)

    # Count records by data source
    source_counts = get_cached_value('analyst:source_counts', _count_by_source, ttl_seconds=30)

    # Average climate values
    summary = climate_summary or {}
    avg_temp = round(summary.get('avg_temp', 0) or 0, 1)
    avg_rainfall = round(summary.get('avg_rainfall', 0) or 0, 1)
    avg_co2 = round(summary.get('avg_co2', 0) or 0, 1)
    avg_aqi = round(summary.get('avg_aqi', 0) or 0, 0)

    # Build chart data from real monthly trends
    temperature_data = []
    rainfall_data = []
    humidity_data = []
    co2_data = []
    chart_labels = []
    for item in monthly_trends:
        chart_labels.append(item.get('month', ''))
        temperature_data.append(round(item.get('avg_temp', 0) or 0, 1))
        rainfall_data.append(round(item.get('total_rainfall', 0) or 0, 1))
        humidity_data.append(round(item.get('avg_humidity', 0) or 0, 1))
        co2_data.append(round(item.get('avg_co2', 0) or 0, 1))

    # Anomaly chart data from monthly trends
    anomaly_counts = get_cached_value('analyst:anomaly_counts', _get_monthly_anomaly_counts, ttl_seconds=30)

    # Prediction trend
    prediction_trend = get_cached_value('analyst:prediction_trend', _get_prediction_trend, ttl_seconds=30)

    # Recent climate data table
    recent_climate = get_cached_value('analyst:recent_climate', lambda: ClimateData.get_latest_readings(limit=10), ttl_seconds=30)

    # Recent predictions table
    recent_predictions = get_cached_value('analyst:recent_predictions', lambda: Prediction.get_all(limit=5), ttl_seconds=30)

    # Real activity from activity_log
    recent_activities = []
    try:
        col = get_collection('activity_log')
        activities = list(col.find().sort('created_at', -1).limit(8))
        recent_activities = [dict(a) for a in activities]
    except Exception:
        pass

    active_alerts = Alert.get_unread_count()
    unread_alerts = active_alerts
    predictions = stats.get('total_predictions', 0)

    return render_template('analyst/dashboard.html',
                         datasets=datasets,
                         weather_records=source_counts.get('weather', 0),
                         satellite_records=source_counts.get('satellite', 0),
                         sensor_records=source_counts.get('sensor', 0),
                         realtime_records=source_counts.get('realtime', 0),
                         avg_temp=avg_temp,
                         avg_rainfall=avg_rainfall,
                         avg_co2=avg_co2,
                         avg_aqi=int(avg_aqi),
                         active_alerts=active_alerts,
                         predictions=predictions,
                         unread_alerts=unread_alerts,
                         chart_labels=json.dumps(chart_labels),
                         temperature_data=json.dumps(temperature_data),
                         rainfall_data=json.dumps(rainfall_data),
                         humidity_data=json.dumps(humidity_data),
                         co2_data=json.dumps(co2_data),
                         anomaly_counts=json.dumps(anomaly_counts),
                         prediction_trend=json.dumps(prediction_trend),
                         regional=json.dumps(regional),
                         recent_climate=recent_climate,
                         recent_predictions=recent_predictions,
                         recent_activities=recent_activities,
                         latest_alerts=recent_alerts,
                         active_streams=active_streams,
                         active_page='dashboard')


def _count_by_source():
    """Count climate records by their dataset category or realtime source."""
    try:
        col = get_collection('climate_data')
        result = {}
        dataset_categories = {
            doc.get('id'): str(doc.get('category', '')).strip().lower()
            for doc in get_collection('datasets').find({}, {'id': 1, 'category': 1})
        }
        grouped = col.aggregate([
            {'$group': {
                '_id': {'dataset_id': '$dataset_id', 'data_source': '$data_source'},
                'count': {'$sum': 1},
            }},
        ])
        category_aliases = {
            'weather': 'weather',
            'satellite': 'satellite',
            'sensor': 'sensor',
            'sensors': 'sensor',
            'satellite_imagery': 'satellite',
        }
        for doc in grouped:
            source = doc['_id'].get('data_source')
            if source == 'realtime':
                category = 'realtime'
            else:
                category = category_aliases.get(
                    dataset_categories.get(doc['_id'].get('dataset_id'), ''),
                    category_aliases.get(source),
                )
            if category:
                result[category] = result.get(category, 0) + doc['count']
        return result
    except Exception:
        return {}


def _get_monthly_anomaly_counts():
    """Get monthly counts of climate anomalies (high z-score records)."""
    try:
        col = get_collection('climate_data')
        stats = next(col.aggregate([
            {'$match': {'temperature': {'$ne': None}}},
            {'$group': {
                '_id': None,
                'mean': {'$avg': '$temperature'},
                'stddev': {'$stdDevPop': '$temperature'},
            }},
        ]), None)
        if not stats:
            return []
        mean = stats.get('mean', 0)
        stddev = stats.get('stddev') or 0
        if stddev == 0:
            return []
        pipeline = [
            {'$match': {'temperature': {'$ne': None}, 'date': {'$ne': None}}},
            {'$addFields': {
                'month': {'$substrCP': ['$date', 0, 7]},
                'is_anomaly': {
                    '$gt': [
                        {'$abs': {'$subtract': ['$temperature', mean]}},
                        {'$multiply': [stddev, 2.5]}
                    ]
                }
            }},
            {'$match': {'is_anomaly': True}},
            {'$group': {'_id': '$month', 'count': {'$sum': 1}}},
            {'$sort': {'_id': -1}},
            {'$limit': 12},
        ]
        results = [{'month': doc['_id'], 'count': doc['count']} for doc in col.aggregate(pipeline)]
        results.reverse()
        return results
    except Exception:
        return []


def _get_prediction_trend():
    """Monthly prediction counts aligned to the latest climate months."""
    try:
        col = get_collection('predictions')
        pipeline = [
            {'$match': {'created_at': {'$ne': None}}},
            {'$addFields': {'month': {'$substrCP': ['$created_at', 0, 7]}}},
            {'$group': {'_id': '$month', 'count': {'$sum': 1}}},
            {'$sort': {'_id': -1}},
            {'$limit': 12},
        ]
        counts = {}
        for doc in col.aggregate(pipeline):
            if doc.get('_id'):
                counts[doc['_id']] = doc['count']

        climate_months = [item.get('month') for item in ClimateData.get_monthly_trends()
                          if item.get('month')]
        months = list(reversed(climate_months[:12]))
        if not months:
            months = sorted(counts)[-12:]
        return [{'month': month, 'count': counts.get(month, 0)} for month in months]
    except Exception:
        return []
