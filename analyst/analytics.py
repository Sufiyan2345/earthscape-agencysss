from flask import render_template, jsonify, request, redirect, url_for, flash
from flask_login import login_required, current_user
from analyst import analyst_bp
from auth.decorators import analyst_required
from models.climate_model import ClimateData
from models.prediction_model import Prediction
from models.anomaly_model import AnomalyRun
import json


def _clean_summary(summary):
    """Ensure every stat the templates format is a real number (Mongo may
    return explicit nulls when a field is missing from all records)."""
    for key in ('avg_temp', 'avg_rainfall', 'avg_humidity', 'avg_wind',
                'avg_co2', 'avg_aqi', 'avg_pressure', 'avg_visibility',
                'avg_uv_index', 'avg_soil_moisture'):
        if summary.get(key) is None:
            summary[key] = 0
    return summary


@analyst_bp.route('/analytics')
@login_required
@analyst_required
def analytics():
    regions = ClimateData.get_regions()
    years = ClimateData.get_available_years()
    summary = _clean_summary(ClimateData.get_summary())
    regional = ClimateData.get_regional_data()
    return render_template('analyst/analytics.html',
                         summary=summary,
                         regions=regions,
                         years=years,
                         regional=regional,
                         active_page='analytics')


@analyst_bp.route('/analytics/chart-data')
@login_required
@analyst_required
def analytics_chart_data():
    variables = request.args.getlist('variables') or ['temperature', 'rainfall']
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    region = request.args.get('region', '')
    group_by = request.args.get('group_by', 'month')
    data = ClimateData.get_chart_data(variables, start_date or None, end_date or None,
                                      region or None, group_by)
    return jsonify(data)


@analyst_bp.route('/analytics/regional-data')
@login_required
@analyst_required
def analytics_regional_data():
    data = ClimateData.get_regional_data()
    return jsonify(data)


@analyst_bp.route('/analytics/regional-data/delete-many', methods=['POST'])
@login_required
@analyst_required
def delete_regional_stations():
    """Delete all observations represented by selected regional rows."""
    station_names = [name.strip() for name in request.form.getlist('station_names') if name.strip()]
    deleted = ClimateData.delete_by_stations(station_names)
    if deleted:
        flash(f'{deleted} climate record(s) from {len(station_names)} station(s) deleted successfully.', 'success')
    else:
        flash('Select at least one regional station to delete.', 'warning')
    return redirect(url_for('analyst.analytics'))


@analyst_bp.route('/analytics/regional-data/delete', methods=['POST'])
@login_required
@analyst_required
def delete_regional_station():
    """Delete all climate records represented by one regional row."""
    station_name = request.form.get('station_name', '').strip()
    deleted = ClimateData.delete_by_stations([station_name]) if station_name else 0
    if deleted:
        flash(f'{deleted} climate record(s) from station "{station_name}" deleted successfully.', 'success')
    else:
        flash('Regional station was not found.', 'warning')
    return redirect(url_for('analyst.analytics'))


@analyst_bp.route('/analytics/visualization-state')
@login_required
@analyst_required
def analytics_visualization_state():
    return jsonify(ClimateData.get_visualization_state(
        request.args.get('start_date'), request.args.get('end_date'), request.args.get('region')))


@analyst_bp.route('/analytics/anomalies', methods=['GET', 'POST'])
@login_required
@analyst_required
def analytics_anomalies():
    """Analyst = perform anomaly detection: pick a threshold, run, review."""
    if request.method == 'POST':
        threshold = request.form.get('threshold', 2.0)
        run = AnomalyRun.execute(
            threshold, run_by=current_user.id,
            run_by_name=getattr(current_user, 'full_name', None) or current_user.username,
        )
        if run['status'] == 'completed':
            flash(f"Anomaly run #{run['id']} completed — {run['anomalies_found']} "
                  f"anomalie(s) found ({run['critical_count']} critical) across "
                  f"{run['records_scanned']} records.", 'success')
        else:
            flash(f"Anomaly run #{run['id']} failed: {run['error']}", 'danger')
        return redirect(url_for('analyst.analytics_anomalies'))

    latest = AnomalyRun.get_latest_completed()
    threshold = request.args.get('threshold', latest.get('threshold', 2.0) if latest else 2.0, type=float)
    anomalies = latest.get('anomalies', []) if latest else ClimateData.get_anomalies(threshold)
    summary = _clean_summary(ClimateData.get_summary())
    return render_template('analyst/anomalies.html',
                         anomalies=anomalies,
                         threshold=threshold,
                         total_found=len(anomalies),
                         summary=summary,
                         runs=AnomalyRun.get_all(limit=20),
                         latest_run=latest,
                         active_page='anomalies')


@analyst_bp.route('/analytics/anomaly-data')
@login_required
@analyst_required
def analytics_anomaly_data():
    """JSON of the latest completed run's anomalies (falls back to live scan)."""
    latest = AnomalyRun.get_latest_completed()
    if latest:
        return jsonify(latest.get('anomalies', []))
    threshold = request.args.get('threshold', 2.0, type=float)
    return jsonify(ClimateData.get_anomalies(threshold))


@analyst_bp.route('/analytics/anomalies/runs/<int:run_id>/delete', methods=['POST'])
@login_required
@analyst_required
def delete_anomaly_run(run_id):
    """Delete a saved anomaly detection run (analyst-owned action)."""
    run = AnomalyRun.get_by_id(run_id)
    if not run:
        flash('Anomaly run not found.', 'danger')
        return redirect(url_for('analyst.analytics_anomalies'))
    if run.get('run_by') != current_user.id:
        flash('You can only delete your own anomaly runs.', 'warning')
        return redirect(url_for('analyst.analytics_anomalies'))
    AnomalyRun.delete(run_id)
    flash(f'Anomaly run #{run_id} deleted.', 'success')
    return redirect(url_for('analyst.analytics_anomalies'))


@analyst_bp.route('/analytics/forecast')
@login_required
@analyst_required
def analytics_forecast():
    predictions = Prediction.get_all(limit=100)
    monthly = ClimateData.get_monthly_trends()
    return render_template('analyst/forecast.html',
                         predictions=predictions,
                         monthly=monthly,
                         active_page='forecast')


def _prediction_detail(p):
    """Parse a prediction doc (JSON result/params) for the detail panel."""
    detail = dict(p)
    for key in ('prediction_result', 'input_params'):
        raw = p.get(key)
        if isinstance(raw, str):
            try:
                detail[key] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                detail[key] = {'raw': raw}
        elif raw is None:
            detail[key] = {}
    if not isinstance(detail.get('prediction_result'), dict):
        detail['prediction_result'] = {'raw': str(detail.get('prediction_result'))}
    if not isinstance(detail.get('input_params'), dict):
        detail['input_params'] = {'raw': str(detail.get('input_params'))}
    return detail


@analyst_bp.route('/analytics/forecast/predictions/<int:prediction_id>')
@login_required
@analyst_required
def view_prediction(prediction_id):
    """Show a single prediction's full result on the forecast page."""
    prediction = Prediction.get_by_id(prediction_id)
    if not prediction:
        flash('Prediction not found.', 'danger')
        return redirect(url_for('analyst.analytics_forecast'))
    return render_template('analyst/forecast.html',
                         predictions=Prediction.get_all(limit=100),
                         monthly=ClimateData.get_monthly_trends(),
                         prediction_detail=_prediction_detail(prediction),
                         active_page='forecast')


@analyst_bp.route('/analytics/forecast/predictions/<int:prediction_id>/delete', methods=['POST'])
@login_required
@analyst_required
def delete_prediction(prediction_id):
    """Delete a stored prediction from the history."""
    prediction = Prediction.get_by_id(prediction_id)
    if not prediction:
        flash('Prediction not found.', 'danger')
        return redirect(url_for('analyst.analytics_forecast'))
    Prediction.delete(prediction_id)
    flash(f'Prediction #{prediction_id} ({prediction.get("model_name", "")}) deleted.', 'success')
    return redirect(url_for('analyst.analytics_forecast'))


@analyst_bp.route('/analytics/forecast/predictions/delete-many', methods=['POST'])
@login_required
@analyst_required
def delete_predictions():
    """Delete the selected prediction history records."""
    raw_ids = request.form.getlist('prediction_ids')
    try:
        prediction_ids = [int(pred_id) for pred_id in raw_ids]
    except (TypeError, ValueError):
        prediction_ids = []
    deleted = Prediction.delete_many(prediction_ids)
    if deleted:
        flash(f'{deleted} prediction(s) deleted successfully.', 'success')
    else:
        flash('Select at least one prediction to delete.', 'warning')
    return redirect(url_for('analyst.analytics_forecast'))


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


@analyst_bp.route('/analytics/forecast-data')
@login_required
@analyst_required
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
