from flask import render_template
from flask_login import login_required
from admin import admin_bp
from auth.decorators import admin_required
from models.user_model import User
from models.dataset_model import Dataset
from models.climate_model import ClimateData
from models.alert_model import Alert
from models.prediction_model import Prediction
from models.realtime_model import RealtimeStream
from models.feedback_model import Feedback
from models.report_model import Report
from utils.mapreduce import MapReduceManager
from utils.helper import get_system_stats, format_file_size, get_cached_value
from utils.database import get_collection
import json


@admin_bp.route('/')
@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    stats = get_cached_value('admin:system_stats', get_system_stats, ttl_seconds=30)
    recent_alerts = get_cached_value('admin:recent_alerts', lambda: Alert.get_all(limit=5), ttl_seconds=30)
    recent_feedback = get_cached_value('admin:recent_feedback', lambda: Feedback.get_all(limit=5), ttl_seconds=30)
    role_counts = get_cached_value('admin:role_counts', User.count_by_role, ttl_seconds=30)
    monthly_trends = get_cached_value('admin:monthly_trends', ClimateData.get_monthly_trends, ttl_seconds=30)

    # Prepare chart data from real monthly trends (no synthetic fallback).
    # get_monthly_trends() returns newest-first; iterate reversed so chart
    # timelines run left-to-right in chronological order.
    chart_labels = []
    chart_temps = []
    chart_rainfall = []
    chart_humidity = []
    chart_wind = []
    chart_co2 = []
    chart_aqi = []
    for item in reversed(monthly_trends):
        chart_labels.append(item.get('month', ''))
        chart_temps.append(round(item.get('avg_temp', 0) or 0, 1))
        chart_rainfall.append(round(item.get('total_rainfall', 0) or 0, 1))
        chart_humidity.append(round(item.get('avg_humidity', 0) or 0, 1))
        chart_wind.append(round(item.get('avg_wind', 0) or 0, 1))
        chart_co2.append(round(item.get('avg_co2', 0) or 0, 1))
        chart_aqi.append(round(item.get('avg_aqi', 0) or 0, 1))

    # Regional data for comparison chart
    regional = get_cached_value('admin:regional_data', ClimateData.get_regional_data, ttl_seconds=30)

    # Get recent activity log
    recent_activities = get_cached_value('admin:recent_activities', lambda: [dict(a) for a in list(get_collection('activity_log').find().sort('created_at', -1).limit(10))], ttl_seconds=30)

    # Get MapReduce job stats
    mr_jobs = get_cached_value('admin:mr_jobs', MapReduceManager.get_all_jobs, ttl_seconds=30)
    active_jobs = sum(1 for j in mr_jobs if j.get('status') == 'running')
    completed_jobs = sum(1 for j in mr_jobs if j.get('status') == 'completed')

    # Get feedback stats
    open_feedback = get_cached_value('admin:open_feedback', Feedback.get_open_count, ttl_seconds=30)
    total_feedback = get_cached_value('admin:total_feedback', Feedback.get_count, ttl_seconds=30)

    # Get dataset stats
    datasets = get_cached_value('admin:datasets', lambda: Dataset.get_all(limit=5), ttl_seconds=30)

    # Get report count
    total_reports = get_cached_value('admin:total_reports', Report.get_count, ttl_seconds=30)

    # HDFS storage total
    def _get_hdfs_storage():
        try:
            files_col = get_collection('hdfs_files')
            size_pipeline = list(files_col.aggregate([
                {'$match': {'is_directory': 0}},
                {'$group': {'_id': None, 'total': {'$sum': {'$ifNull': ['$file_size', 0]}}}},
            ]))
            return size_pipeline[0]['total'] if size_pipeline else 0
        except Exception:
            return 0

    hdfs_storage_bytes = get_cached_value('admin:hdfs_storage', _get_hdfs_storage, ttl_seconds=30)
    hdfs_storage = hdfs_storage_bytes

    # Realtime records count
    realtime_readings_count = get_cached_value('admin:realtime_count', lambda: get_collection('realtime_readings').count_documents({}), ttl_seconds=30)

    # ML model versions count
    ml_models_count = get_cached_value('admin:ml_models', lambda: get_collection('model_versions').count_documents({}), ttl_seconds=30)

    # Enrich stats with additional data
    stats['active_mr_jobs'] = active_jobs
    stats['completed_mr_jobs'] = completed_jobs
    stats['open_feedback'] = open_feedback
    stats['total_feedback'] = total_feedback
    stats['total_reports'] = total_reports
    stats['hdfs_storage'] = format_file_size(hdfs_storage)
    stats['hdfs_storage_bytes'] = hdfs_storage
    stats['realtime_records'] = realtime_readings_count
    stats['ml_models'] = ml_models_count

    # ── System-level chart data ───────────────────────────────────────────

    # Dataset Upload Trend (monthly counts)
    ds_trend = get_cached_value('admin:ds_trend', _get_dataset_upload_trend, ttl_seconds=30)

    # Processing Jobs breakdown
    job_status_counts = {'pending': 0, 'running': 0, 'completed': 0, 'failed': 0}
    for j in mr_jobs:
        s = j.get('status', 'pending')
        if s in job_status_counts:
            job_status_counts[s] += 1

    # Alert Trend (monthly alert counts)
    alert_trend = get_cached_value('admin:alert_trend', _get_alert_trend, ttl_seconds=30)

    # Prediction Statistics (monthly prediction counts)
    prediction_trend = get_cached_value('admin:prediction_trend', _get_prediction_trend, ttl_seconds=30)

    # Data Distribution (by data_source)
    data_distribution = get_cached_value('admin:data_distribution', _get_data_distribution, ttl_seconds=30)

    # Data quality: compute missing value stats per field (cached 60s because
    # it scans the whole climate_data collection).
    data_quality = get_cached_value('admin:data_quality', _compute_data_quality, ttl_seconds=60)
    stats['data_quality'] = data_quality

    return render_template('admin/dashboard.html',
                         stats=stats,
                         recent_alerts=recent_alerts,
                         recent_feedback=recent_feedback,
                         role_counts=role_counts,
                         monthly_trends=monthly_trends,
                         chart_labels=json.dumps(chart_labels),
                         chart_temps=json.dumps(chart_temps),
                         chart_rainfall=json.dumps(chart_rainfall),
                         chart_humidity=json.dumps(chart_humidity),
                         chart_wind=json.dumps(chart_wind),
                         chart_co2=json.dumps(chart_co2),
                         chart_aqi=json.dumps(chart_aqi),
                         regional=json.dumps(regional),
                         recent_activities=recent_activities,
                         datasets=datasets,
                         ds_trend=json.dumps(ds_trend),
                         job_status_counts=json.dumps(job_status_counts),
                         alert_trend=json.dumps(alert_trend),
                         prediction_trend=json.dumps(prediction_trend),
                         data_distribution=json.dumps(data_distribution),
                         active_page='dashboard')


def _compute_data_quality():
    """Compute data quality metrics: missing values per field in a single aggregation pass."""
    try:
        col = get_collection('climate_data')
        total = col.count_documents({})
        if total == 0:
            return {'total_records': 0, 'fields': [], 'completeness_pct': 0}

        fields = ['temperature', 'humidity', 'rainfall', 'wind_speed', 'pressure',
                  'co2_level', 'air_quality_index', 'visibility', 'cloud_cover',
                  'uv_index', 'soil_moisture', 'snow_depth']
        field_metrics = {}
        for field in fields:
            field_metrics[f'{field}_missing'] = {'$sum': {'$cond': [{'$eq': [f'${field}', None]}, 1, 0]}}
            field_metrics[f'{field}_present'] = {'$sum': {'$cond': [{'$ne': [f'${field}', None]}, 1, 0]}}

        pipeline = [{'$group': {'_id': None, 'total': {'$sum': 1}, **field_metrics}}]
        result = list(col.aggregate(pipeline))
        if not result:
            return {'total_records': total, 'fields': [], 'overall_completeness_pct': 0, 'total_missing_values': 0}

        row = result[0]
        field_stats = []
        total_missing = 0
        total_cells = total * len(fields)
        for field in fields:
            missing = row.get(f'{field}_missing', 0)
            present = row.get(f'{field}_present', 0)
            total_missing += missing
            field_stats.append({
                'field': field,
                'missing': missing,
                'present': present,
                'completeness_pct': round((present / total) * 100, 1) if total else 0,
            })

        overall_completeness = round(((total_cells - total_missing) / total_cells) * 100, 1) if total_cells else 0
        return {
            'total_records': total,
            'fields': field_stats,
            'overall_completeness_pct': overall_completeness,
            'total_missing_values': total_missing,
        }
    except Exception:
        return {'total_records': 0, 'fields': [], 'completeness_pct': 0}


def _get_dataset_upload_trend():
    """Monthly dataset upload counts for the last 12 months."""
    try:
        col = get_collection('datasets')
        pipeline = [
            {'$match': {'created_at': {'$ne': None}}},
            {'$addFields': {'month': {'$substrCP': ['$created_at', 0, 7]}}},
            {'$group': {'_id': '$month', 'count': {'$sum': 1}}},
            {'$sort': {'_id': -1}},
            {'$limit': 12},
        ]
        results = []
        for doc in col.aggregate(pipeline):
            results.append({'month': doc['_id'], 'count': doc['count']})
        results.reverse()
        return results
    except Exception:
        return []


def _get_alert_trend():
    """Monthly alert counts for the last 12 months."""
    try:
        col = get_collection('alerts')
        pipeline = [
            {'$match': {'created_at': {'$ne': None}}},
            {'$addFields': {'month': {'$substrCP': ['$created_at', 0, 7]}}},
            {'$group': {'_id': '$month', 'count': {'$sum': 1}}},
            {'$sort': {'_id': -1}},
            {'$limit': 12},
        ]
        results = []
        for doc in col.aggregate(pipeline):
            results.append({'month': doc['_id'], 'count': doc['count']})
        results.reverse()
        return results
    except Exception:
        return []


def _get_prediction_trend():
    """Prediction counts aligned to the latest real climate-data months."""
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


def _get_data_distribution():
    """Count of climate records by data source."""
    try:
        col = get_collection('climate_data')
        pipeline = [
            {'$group': {'_id': {'$ifNull': ['$data_source', 'batch']}, 'count': {'$sum': 1}}},
            {'$sort': {'count': -1}},
        ]
        results = []
        for doc in col.aggregate(pipeline):
            results.append({'source': doc['_id'], 'count': doc['count']})
        return results
    except Exception:
        return []
