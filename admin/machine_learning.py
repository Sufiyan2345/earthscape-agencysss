from flask import render_template, url_for, jsonify, request, redirect, flash
from flask_login import login_required, current_user
from admin import admin_bp
from auth.decorators import admin_required
from models.prediction_model import Prediction
from models.climate_model import ClimateData
from models.model_version import ModelVersion
from models.correlation_model import CorrelationRun
from utils.database import get_collection, log_activity
import json


# ── Model metadata ──────────────────────────────────────────────────────────

ML_MODELS = [
    {'id': 'temperature', 'name': 'Temperature Prediction Model',
     'description': 'Predicts future temperature trends using polynomial regression on historical climate data.',
     'icon': 'fa-thermometer-half', 'color': 'var(--red)'},
    {'id': 'rainfall', 'name': 'Rainfall Prediction Model',
     'description': 'Forecasts rainfall patterns and precipitation probability using historical data.',
     'icon': 'fa-tint', 'color': 'var(--blue)'},
    {'id': 'anomaly', 'name': 'Anomaly Detection Model',
     'description': 'Detects statistical anomalies using Z-score analysis on temperature, rainfall, and air quality.',
     'icon': 'fa-exclamation-triangle', 'color': 'var(--orange)'},
    {'id': 'air_quality', 'name': 'Air Quality Prediction Model',
     'description': 'Predicts AQI based on CO2 levels, wind patterns, and historical pollution data.',
     'icon': 'fa-wind', 'color': 'var(--gray-500)'},
    {'id': 'flood', 'name': 'Flood Risk Assessment Model',
     'description': 'Assesses flood probability based on rainfall intensity, humidity, and wind data.',
     'icon': 'fa-water', 'color': 'var(--blue)'},
    {'id': 'climate_trend', 'name': 'Climate Trend Analysis Model',
     'description': 'Long-term climate trend analysis including temperature trajectories and CO2 paths.',
     'icon': 'fa-chart-line', 'color': 'var(--primary)'},
]


def _get_model_info():
    """Build model info list enriched with active version data."""
    active_versions = {v['model_type']: v for v in ModelVersion.get_active()}
    info = []
    for m in ML_MODELS:
        entry = dict(m)
        v = active_versions.get(m['id'])
        entry['validation_r2'] = None
        if v:
            metrics = v.get('metrics') or {}
            if isinstance(metrics, str):
                try:
                    metrics = json.loads(metrics)
                except (json.JSONDecodeError, TypeError):
                    metrics = {}
            validation = metrics.get('validation') if isinstance(metrics, dict) else None
            if validation:
                entry['validation_r2'] = round(validation.get('r_squared', 0) * 100, 1)
        if v:
            entry['accuracy'] = round(v.get('accuracy', 0), 1)
            entry['status'] = 'trained'
            entry['last_trained'] = (v.get('created_at') or '')[:10]
            entry['version'] = v.get('version', 1)
            entry['trained_on'] = v.get('trained_on_data', '{}')
            if isinstance(entry['trained_on'], str):
                try:
                    entry['trained_on'] = json.loads(entry['trained_on'])
                except (json.JSONDecodeError, TypeError):
                    entry['trained_on'] = {}
        else:
            entry['accuracy'] = 0
            entry['status'] = 'untrained'
            entry['last_trained'] = 'Never'
            entry['version'] = 0
            entry['trained_on'] = {}
        info.append(entry)
    return info


def _parse_prediction(p):
    """Parse one raw prediction document for display."""
    pred = dict(p)
    try:
        result = json.loads(p.get('prediction_result', '{}')) if isinstance(p.get('prediction_result'), str) else (p.get('prediction_result') or {})
        pred['result'] = result
        pred['result_summary'] = ', '.join(f'{k}: {v}' for k, v in list(result.items())[:5]) if isinstance(result, dict) else str(result)[:120]
    except (json.JSONDecodeError, TypeError):
        pred['result'] = {}
        pred['result_summary'] = str(p.get('prediction_result', 'N/A'))[:120]
    try:
        params = json.loads(p.get('input_params', '{}')) if isinstance(p.get('input_params'), str) else (p.get('input_params') or {})
        pred['input'] = ', '.join(f'{k}: {v}' for k, v in params.items()) if isinstance(params, dict) else str(params)
        pred['input_params_parsed'] = params if isinstance(params, dict) else {}
    except (json.JSONDecodeError, TypeError):
        pred['input'] = str(p.get('input_params', 'N/A'))[:50]
        pred['input_params_parsed'] = {}
    pred['confidence'] = round((p.get('confidence', 0) or 0) * 100, 1)
    pred['timestamp'] = (p.get('created_at') or 'N/A')[:16]
    return pred


def _parse_predictions(limit=50):
    """Fetch and parse prediction history."""
    return [_parse_prediction(p) for p in Prediction.get_all(limit=limit)]


def _monitoring_stats(models, predictions):
    """Aggregate monitoring metrics for the ML model dashboard."""
    trained = sum(1 for m in models if m.get('status') == 'trained')
    untrained = len(models) - trained
    avg_acc = round(sum(m.get('accuracy', 0) for m in models) / max(1, len(models)), 1)

    runs_by_model = {m['id']: 0 for m in models}
    for p in predictions:
        key = p.get('model_type') or 'other'
        runs_by_model[key] = runs_by_model.get(key, 0) + 1

    confidences = [p.get('confidence', 0) for p in predictions]
    avg_conf = round(sum(confidences) / len(confidences) * 100, 1) if confidences else 0

    last_run = predictions[0].get('created_at', 'Never')[:16] if predictions else 'Never'

    return {
        'total_models': len(models),
        'trained': trained,
        'untrained': untrained,
        'avg_accuracy': avg_acc,
        'total_runs': len(predictions),
        'avg_confidence': avg_conf,
        'runs_by_model': runs_by_model,
        'last_run': last_run,
        'version_count': len(ModelVersion.get_all()),
    }


# ── Page routes ─────────────────────────────────────────────────────────────

@admin_bp.route('/machine-learning')
@login_required
@admin_required
def machine_learning():
    """ML Model Monitoring: training status, update status, availability."""
    models = _get_model_info()
    predictions = _parse_predictions()
    return render_template('admin/machine_learning.html',
                         models=models,
                         predictions=predictions,
                         stats=_monitoring_stats(models, predictions),
                         active_page='machine_learning')


@admin_bp.route('/machine-learning/retrain', methods=['POST'])
@login_required
@admin_required
def retrain_models():
    """Retrain all models from the latest climate database records."""
    from ml_models.train_model import train_all_models
    try:
        results, data = train_all_models(user_id=current_user.id)
        from utils.model_cache import invalidate_models
        invalidate_models()
        log_activity(current_user.id, 'retrain_models',
                     f"Retrained {len(results)} models on {data.get('record_count', 0)} "
                     f"{data.get('source', 'unknown')} records",
                     request.remote_addr or '')
        flash(f"Successfully retrained {len(results)} models on "
              f"{data.get('record_count', 0)} {data.get('source', 'unknown')} records.",
              'success')
    except Exception as e:
        flash(f'Model retraining failed: {str(e)}', 'danger')
    return redirect(url_for('admin.machine_learning'))


@admin_bp.route('/machine-learning/predictions/<int:pred_id>')
@login_required
@admin_required
def view_prediction(pred_id):
    """Admin monitor: view full details of any prediction run."""
    pred = Prediction.get_by_id(pred_id)
    if not pred:
        flash('Prediction not found.', 'danger')
        return redirect(url_for('admin.machine_learning'))
    return render_template('admin/prediction_detail.html',
                         pred=_parse_prediction(pred),
                         active_page='machine_learning')


@admin_bp.route('/machine-learning/predictions/<int:pred_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_prediction(pred_id):
    """Admin manage: remove any prediction run from the history."""
    pred = Prediction.get_by_id(pred_id)
    if not pred:
        flash('Prediction not found.', 'danger')
    else:
        Prediction.delete(pred_id)
        try:
            log_activity(current_user.id, 'delete_prediction',
                         f"Deleted prediction #{pred_id} ({pred.get('model_name', 'unknown')})",
                         request.remote_addr or '')
        except Exception:
            pass
        flash(f'Prediction #{pred_id} deleted.', 'success')
    return redirect(url_for('admin.machine_learning'))


@admin_bp.route('/machine-learning/correlation')
@login_required
@admin_required
def correlation_analysis():
    """Admin = monitor correlation results and processing status (read-only)."""
    runs = CorrelationRun.get_all(limit=20)
    latest = CorrelationRun.get_latest_completed()
    stats = CorrelationRun.get_stats()
    return render_template('admin/correlation.html',
                         runs=runs, latest_run=latest, run_stats=stats,
                         active_page='correlation')


@admin_bp.route('/machine-learning/correlation/data')
@login_required
@admin_required
def correlation_data():
    """JSON of the latest completed analyst run (falls back to live computation)."""
    latest = CorrelationRun.get_latest_completed()
    if latest:
        return jsonify({
            'source': 'run',
            'run_id': latest['id'],
            'run_by_name': latest.get('run_by_name', ''),
            'generated_at': latest.get('created_at', ''),
            'pairwise_correlations': latest.get('pairwise_correlations', []),
            'correlation_matrix': latest.get('correlation_matrix', {}),
            'total_records': latest.get('total_records', 0),
        })
    results = ClimateData.get_correlation_results()
    results['source'] = 'live'
    return jsonify(results)


@admin_bp.route('/machine-learning/model-versions')
@login_required
@admin_required
def model_versions():
    """List all model versions (training/update history)."""
    versions = ModelVersion.get_all()
    parsed = []
    for v in versions:
        entry = dict(v)
        try:
            entry['metrics_parsed'] = json.loads(v.get('metrics', '{}')) if isinstance(v.get('metrics'), str) else (v.get('metrics') or {})
        except (json.JSONDecodeError, TypeError):
            entry['metrics_parsed'] = {}
        try:
            entry['data_parsed'] = json.loads(v.get('trained_on_data', '{}')) if isinstance(v.get('trained_on_data'), str) else (v.get('trained_on_data') or {})
        except (json.JSONDecodeError, TypeError):
            entry['data_parsed'] = {}
        parsed.append(entry)
    return render_template('admin/model_versions.html',
                         versions=parsed,
                         active_page='machine_learning')


@admin_bp.route('/machine-learning/model-versions/<int:version_id>/rollback', methods=['POST'])
@login_required
@admin_required
def rollback_model_version(version_id):
    """Restore an archived model version after a drift or quality review."""
    version = ModelVersion.get_by_id(version_id)
    if not version:
        flash('Model version not found.', 'danger')
    elif ModelVersion.activate(version_id):
        from utils.model_cache import invalidate_models
        invalidate_models()
        flash(f"{version.get('model_name', 'Model')} rolled back to v{version.get('version') }.", 'success')
    return redirect(url_for('admin.model_versions'))


@admin_bp.route('/machine-learning/accuracy')
@login_required
@admin_required
def model_accuracy():
    """Validate model predictions against actual outcomes."""
    pred_col = get_collection('predictions')
    climate_col = get_collection('climate_data')

    # Get predictions for temperature/rainfall models
    rows = list(pred_col.find(
        {'model_type': {'$in': ['temperature', 'rainfall']}}
    ).sort('created_at', -1).limit(50))

    # Single batch aggregation to compute post-prediction averages per created_at,
    # avoiding N+1 per-row aggregate calls.
    pipeline = [
        {'$match': {'created_at': {'$gt': rows[-1].get('created_at', '')}}},
        {'$limit': 100},
        {'$group': {'_id': None, 'avg_temp': {'$avg': '$temperature'}, 'avg_rain': {'$avg': '$rainfall'}}},
    ]
    avg_result = list(climate_col.aggregate(pipeline))
    global_avg_temp = avg_result[0].get('avg_temp') if avg_result else None
    global_avg_rain = avg_result[0].get('avg_rain') if avg_result else None

    # Attach the single batch average to each prediction row
    for r in rows:
        r['actual_avg_temp'] = global_avg_temp
        r['actual_avg_rain'] = global_avg_rain

    validations = []
    for r in rows:
        entry = dict(r)
        try:
            result = json.loads(r['prediction_result']) if isinstance(r['prediction_result'], str) else (r['prediction_result'] or {})
        except (json.JSONDecodeError, TypeError):
            result = {}

        if r['model_type'] == 'temperature' and entry.get('actual_avg_temp') and result.get('predicted_avg_temp'):
            predicted = result['predicted_avg_temp']
            actual = entry['actual_avg_temp']
            entry['error_pct'] = round(abs(predicted - actual) / max(0.1, abs(actual)) * 100, 1)
            entry['accuracy_pct'] = round(max(0, 100 - entry['error_pct']), 1)
            validations.append(entry)
        elif r['model_type'] == 'rainfall' and entry.get('actual_avg_rain') and result.get('predicted_rainfall_mm'):
            predicted = result['predicted_rainfall_mm']
            actual = entry['actual_avg_rain']
            entry['error_pct'] = round(abs(predicted - actual) / max(0.1, abs(actual)) * 100, 1)
            entry['accuracy_pct'] = round(max(0, 100 - entry['error_pct']), 1)
            validations.append(entry)

    avg_accuracy = round(sum(v['accuracy_pct'] for v in validations) / max(1, len(validations)), 1) if validations else 0
    return jsonify({
        'validations': validations[:20],
        'avg_accuracy': avg_accuracy,
        'total_validated': len(validations),
    })
