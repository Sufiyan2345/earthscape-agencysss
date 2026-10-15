from flask import render_template, jsonify, request
from flask_login import login_required
from admin import admin_bp
from auth.decorators import admin_required
from models.climate_model import ClimateData
from models.prediction_model import Prediction
from models.anomaly_model import AnomalyRun


def _clean_summary(summary):
    """Ensure every stat the templates format is a real number (Mongo may
    return explicit nulls when a field is missing from all records)."""
    for key in ('avg_temp', 'avg_rainfall', 'avg_humidity', 'avg_wind',
                'avg_co2', 'avg_aqi', 'avg_pressure', 'avg_visibility',
                'avg_uv_index', 'avg_soil_moisture'):
        if summary.get(key) is None:
            summary[key] = 0
    return summary


@admin_bp.route('/analytics')
@login_required
@admin_required
def analytics():
    regions = ClimateData.get_regions()
    years = ClimateData.get_available_years()
    summary = _clean_summary(ClimateData.get_summary())
    regional = ClimateData.get_regional_data()
    return render_template('admin/analytics.html',
                         summary=summary,
                         regions=regions,
                         years=years,
                         regional=regional,
                         active_page='analytics')


@admin_bp.route('/analytics/chart-data')
@login_required
@admin_required
def analytics_chart_data():
    variables = request.args.getlist('variables') or ['temperature', 'rainfall']
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    region = request.args.get('region', '')
    group_by = request.args.get('group_by', 'month')
    data = ClimateData.get_chart_data(variables, start_date or None, end_date or None,
                                      region or None, group_by)
    return jsonify(data)


@admin_bp.route('/analytics/regional-data')
@login_required
@admin_required
def analytics_regional_data():
    data = ClimateData.get_regional_data()
    return jsonify(data)


@admin_bp.route('/analytics/visualization-state')
@login_required
@admin_required
def analytics_visualization_state():
    return jsonify(ClimateData.get_visualization_state(
        request.args.get('start_date'), request.args.get('end_date'), request.args.get('region')))


@admin_bp.route('/analytics/anomalies')
@login_required
@admin_required
def analytics_anomalies():
    """Admin = monitor anomaly detection results and processing status."""
    latest = AnomalyRun.get_latest_completed()
    threshold = request.args.get('threshold', latest.get('threshold', 2.0) if latest else 2.0, type=float)
    anomalies = latest.get('anomalies', []) if latest else ClimateData.get_anomalies(threshold)
    summary = _clean_summary(ClimateData.get_summary())
    return render_template('admin/anomalies.html',
                         anomalies=anomalies,
                         threshold=threshold,
                         total_found=len(anomalies),
                         summary=summary,
                         runs=AnomalyRun.get_all(limit=20),
                         latest_run=latest,
                         run_stats=AnomalyRun.get_stats(),
                         active_page='anomalies')


@admin_bp.route('/analytics/anomaly-data')
@login_required
@admin_required
def analytics_anomaly_data():
    """JSON of the latest completed analyst run (falls back to live scan)."""
    latest = AnomalyRun.get_latest_completed()
    if latest:
        return jsonify(latest.get('anomalies', []))
    threshold = request.args.get('threshold', 2.0, type=float)
    return jsonify(ClimateData.get_anomalies(threshold))


@admin_bp.route('/analytics/forecast')
@login_required
@admin_required
def analytics_forecast():
    predictions = Prediction.get_all(limit=100)
    monthly = ClimateData.get_monthly_trends()
    return render_template('admin/forecast.html',
                         predictions=predictions,
                         monthly=monthly,
                         active_page='forecast')


def _monthly_as_periods(monthly):
    """Normalize monthly trend docs for the forecast chart (expects 'period').
    get_monthly_trends() returns newest-first, so reverse into ascending
    chronological order for a correct forecast overlay."""
    return [{
        'period': m.get('month'),
        'avg_temp': m.get('avg_temp'),
        'total_rainfall': m.get('total_rainfall'),
        'avg_humidity': m.get('avg_humidity'),
        'record_count': m.get('record_count'),
    } for m in reversed(monthly)]


@admin_bp.route('/analytics/forecast-data')
@login_required
@admin_required
def analytics_forecast_data():
    predictions = Prediction.get_all(limit=100)
    monthly = ClimateData.get_monthly_trends()
    # Live forecast recomputed from current data on every request, so the
    # charts update as soon as new climate records are added.
    live_forecast = Prediction.get_live_forecast(list(reversed(monthly)))
    # When a model was retrained/run after the last data update, show its
    # predictions instead of the plain linear projection.
    latest_records = ClimateData.get_latest_readings(limit=1)
    latest_data_ts = latest_records[0].get('created_at', '') if latest_records else ''
    live_forecast = Prediction.overlay_latest_ml(live_forecast, predictions, latest_data_ts)
    return jsonify({'predictions': predictions,
                    'historical': _monthly_as_periods(monthly),
                    'live_forecast': live_forecast})


@admin_bp.route('/analytics/export-config')
@login_required
@admin_required
def analytics_export_config():
    """Return chart configuration for client-side export."""
    return jsonify({'status': 'ok'})
