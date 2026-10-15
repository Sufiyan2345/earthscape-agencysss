from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from analyst import analyst_bp
from auth.decorators import analyst_required
from models.prediction_model import Prediction
from models.dataset_model import Dataset
from models.climate_model import ClimateData
from models.model_version import ModelVersion
from models.correlation_model import CorrelationRun
from utils.database import get_collection
from utils.model_cache import get_climate_predictor, get_anomaly_detector, get_preprocessor
import numpy as np
import json
import os
from datetime import datetime


# ── Model metadata ──────────────────────────────────────────────────────────

ML_MODELS = [
    {'id': 'temperature', 'name': 'Temperature Prediction Model',
     'description': 'Predicts future temperature trends using polynomial regression on historical climate data.',
     'icon': 'fa-thermometer-half', 'color': 'var(--red)',
     'input_hint': 'Enter forecast days (e.g., 30)', 'retrainable': True},
    {'id': 'rainfall', 'name': 'Rainfall Prediction Model',
     'description': 'Forecasts rainfall patterns and precipitation probability using historical data.',
     'icon': 'fa-tint', 'color': 'var(--blue)',
     'input_hint': 'Enter forecast days (e.g., 7)', 'retrainable': True},
    {'id': 'anomaly', 'name': 'Anomaly Detection Model',
     'description': 'Detects statistical anomalies using Z-score analysis on temperature, rainfall, and air quality.',
     'icon': 'fa-exclamation-triangle', 'color': 'var(--orange)',
     'input_hint': 'Enter threshold (e.g., 2.0)', 'retrainable': True},
    {'id': 'air_quality', 'name': 'Air Quality Prediction Model',
     'description': 'Predicts AQI based on CO2 levels, wind patterns, and historical pollution data.',
     'icon': 'fa-wind', 'color': 'var(--gray-500)',
     'input_hint': 'Enter location code (e.g., urban)', 'retrainable': True},
    {'id': 'flood', 'name': 'Flood Risk Assessment Model',
     'description': 'Assesses flood probability based on rainfall intensity, humidity, and wind data.',
     'icon': 'fa-water', 'color': 'var(--blue)',
     'input_hint': 'Enter rainfall mm (e.g., 100)', 'retrainable': True},
    {'id': 'climate_trend', 'name': 'Climate Trend Analysis Model',
     'description': 'Long-term climate trend analysis including temperature trajectories and CO2 paths.',
     'icon': 'fa-chart-line', 'color': 'var(--primary)',
     'input_hint': 'Enter years to project (e.g., 10)', 'retrainable': True},
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
    pred['created_at_iso'] = p.get('created_at') or 'N/A'
    return pred


def _parse_predictions(limit=50):
    """Fetch and parse prediction history."""
    return [_parse_prediction(p) for p in Prediction.get_all(limit=limit)]


# ── Page routes ─────────────────────────────────────────────────────────────

@analyst_bp.route('/machine-learning')
@login_required
@analyst_required
def machine_learning():
    datasets = Dataset.get_approved()
    return render_template('analyst/machine_learning.html',
                         models=_get_model_info(),
                         predictions=_parse_predictions(),
                         datasets=datasets,
                         active_page='machine_learning')


@analyst_bp.route('/machine-learning/correlation')
@login_required
@analyst_required
def correlation_analysis():
    """Analyst = perform correlation analysis: choose variables, run, review."""
    runs = CorrelationRun.get_all(limit=20)
    latest = CorrelationRun.get_latest_completed()
    return render_template('analyst/correlation.html',
                         available_variables=CorrelationRun.AVAILABLE_VARIABLES,
                         runs=runs, latest_run=latest,
                         active_page='correlation')


@analyst_bp.route('/machine-learning/correlation/run', methods=['POST'])
@login_required
@analyst_required
def run_correlation():
    """Execute a correlation run on the selected variables and persist it."""
    selected = request.form.getlist('variables')
    run = CorrelationRun.execute(
        selected, run_by=current_user.id,
        run_by_name=getattr(current_user, 'full_name', None) or current_user.username,
    )
    if run['status'] == 'completed':
        flash(f"Correlation run #{run['id']} completed — "
              f"{run['significant_pairs']} significant pair(s) found across "
              f"{run['total_records']} records.", 'success')
    else:
        flash(f"Correlation run #{run['id']} failed: {run['error']}", 'danger')
    return redirect(url_for('analyst.correlation_analysis'))


@analyst_bp.route('/machine-learning/correlation/data')
@login_required
@analyst_required
def correlation_data():
    """JSON of the latest completed run (falls back to live computation)."""
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


@analyst_bp.route('/machine-learning/correlation/runs/<int:run_id>/delete', methods=['POST'])
@login_required
@analyst_required
def delete_correlation_run(run_id):
    """Delete a saved correlation run."""
    run = CorrelationRun.get_by_id(run_id)
    if not run:
        flash('Correlation run not found.', 'danger')
        return redirect(url_for('analyst.correlation_analysis'))
    if run.get('run_by') != current_user.id:
        flash('You can only delete your own correlation runs.', 'warning')
        return redirect(url_for('analyst.correlation_analysis'))
    CorrelationRun.delete(run_id)
    flash(f'Correlation run #{run_id} deleted.', 'success')
    return redirect(url_for('analyst.correlation_analysis'))


@analyst_bp.route('/machine-learning/model-versions')
@login_required
@analyst_required
def model_versions():
    """List all model versions."""
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
    return render_template('analyst/model_versions.html',
                         versions=parsed,
                         active_page='machine_learning')


@analyst_bp.route('/machine-learning/model-versions/<int:version_id>/delete', methods=['POST'])
@login_required
@analyst_required
def delete_model_version(version_id):
    """Delete an archived model version. Active versions are protected."""
    version = ModelVersion.get_by_id(version_id)
    if not version:
        flash('Model version not found.', 'danger')
        return redirect(url_for('analyst.model_versions'))
    if version.get('is_active'):
        flash('Active model versions cannot be deleted. Retrain the model first — '
              'the old version is archived automatically.', 'warning')
        return redirect(url_for('analyst.model_versions'))
    file_path = version.get('file_path') or ''
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except OSError:
            pass
    ModelVersion.delete(version_id)
    flash(f'{version.get("model_name", "Model")} v{version.get("version", "?")} deleted.', 'success')
    return redirect(url_for('analyst.model_versions'))


def _record_retrain_prediction(model_type, model, user_id):
    """Store a fresh Prediction right after a model is (re)trained so the
    Forecast charts immediately reflect the retrained model."""
    coeffs = model.get('coefficients')
    if not coeffs:
        return
    # Next period = month after the newest climate record (fallback: next month)
    month = None
    try:
        latest = ClimateData.get_monthly_trends()
        period = latest[0].get('month') if latest else None
        if period:
            month = int(period[5:7]) + 1
            if month > 12:
                month = 1
    except (ValueError, TypeError, IndexError):
        month = None
    if not month:
        month = datetime.now().month % 12 + 1
    predicted = float(np.polyval(np.array(coeffs, dtype=float), float(month)))
    if model_type == 'temperature':
        result = {'predicted_avg_temp': round(predicted, 1), 'month': month,
                  'model_used': 'retrained_polynomial', 'source': 'retrain'}
        model_name = 'Temperature Prediction Model'
    elif model_type == 'rainfall':
        result = {'predicted_rainfall_mm': round(max(0.0, predicted), 1), 'month': month,
                  'model_used': 'retrained_polynomial', 'source': 'retrain'}
        model_name = 'Rainfall Prediction Model'
    else:
        return
    confidence = round(min(0.95, max(0.5, (model.get('accuracy_pct') or 50) / 100.0)), 3)
    Prediction.create(
        model_name=model_name, model_type=model_type,
        input_params={'source': 'retrain', 'month': month},
        prediction_result=result, confidence=confidence,
        created_by=user_id,
    )


@analyst_bp.route('/machine-learning/retrain', methods=['POST'])
@login_required
@analyst_required
def retrain_models():
    """Retrain all models from real database data."""
    from ml_models.train_model import train_all_models
    try:
        results, data = train_all_models(user_id=current_user.id)
        # Store fresh predictions so the Forecast charts reflect the
        # retrained temperature/rainfall models immediately.
        for mt in ('temperature', 'rainfall'):
            if mt in results:
                try:
                    _record_retrain_prediction(mt, results[mt]['model'], current_user.id)
                except Exception:
                    pass
        total = len(results)
        source = data.get('source', 'unknown')
        records = data.get('record_count', 0)
        flash(f'Successfully retrained {total} models on {records} {source} records.', 'success')
        from utils.model_cache import invalidate_models
        invalidate_models()
    except Exception as e:
        flash(f'Model retraining failed: {str(e)}', 'danger')
    return redirect(url_for('analyst.machine_learning'))


@analyst_bp.route('/machine-learning/retrain/<model_type>', methods=['POST'])
@login_required
@analyst_required
def retrain_single_model(model_type):
    """Retrain a single model from real database data."""
    from ml_models.train_model import (
        load_real_data, generate_training_data, save_model,
        train_temperature_model, train_rainfall_model, train_flood_model,
        train_heatwave_model, train_air_quality_model, train_climate_trend_model,
        train_anomaly_model
    )
    train_funcs = {
        'temperature': ('temperature_model.pkl', 'Temperature Prediction', train_temperature_model),
        'rainfall': ('rainfall_model.pkl', 'Rainfall Prediction', train_rainfall_model),
        'flood': ('flood_model.pkl', 'Flood Risk Detection', train_flood_model),
        'heatwave': ('heatwave_model.pkl', 'Heatwave Detection', train_heatwave_model),
        'anomaly': ('anomaly_model.pkl', 'Anomaly Detection', train_anomaly_model),
        'air_quality': ('air_quality_model.pkl', 'Air Quality Prediction', train_air_quality_model),
        'climate_trend': ('climate_trend_model.pkl', 'Climate Trend Analysis', train_climate_trend_model),
    }
    if model_type not in train_funcs:
        flash('Unknown model type.', 'danger')
        return redirect(url_for('analyst.machine_learning'))

    try:
        data = load_real_data()
        if data is None:
            data = generate_training_data(1000)
        filename, name, train_func = train_funcs[model_type]
        model, metrics = train_func(data)
        validation = metrics.get('validation') if isinstance(metrics, dict) else None
        if validation and validation.get('r_squared', 0) < -0.5:
            flash(f'{name} was not activated because holdout validation is too weak '
                  f'(R² {validation["r_squared"]}).', 'warning')
            return redirect(url_for('analyst.machine_learning'))
        filepath = save_model(model, filename)

        version_num = ModelVersion.get_next_version(model_type)
        ModelVersion.create(
            model_type=model_type, model_name=name, version=version_num,
            accuracy=model.get('accuracy_pct', 0), metrics=metrics,
            trained_on_data={'source': data.get('source', 'unknown'), 'records': data['record_count']},
            file_path=filepath, trained_by=current_user.id,
        )
        if model_type in ('temperature', 'rainfall'):
            try:
                _record_retrain_prediction(model_type, model, current_user.id)
            except Exception:
                pass
        flash(f'{name} retrained (v{version_num}). Accuracy: {model.get("accuracy_pct", 0)}% on {data["record_count"]} records.', 'success')
        from utils.model_cache import invalidate_models
        invalidate_models()
    except Exception as e:
        flash(f'Retraining failed: {str(e)}', 'danger')
    return redirect(url_for('analyst.machine_learning'))


@analyst_bp.route('/machine-learning/predict', methods=['POST'])
@login_required
@analyst_required
def ml_predict():
    model_type = request.form.get('model_type', 'temperature')
    dataset_id = request.form.get('dataset_id', type=int)
    input_data = request.form.get('input_data', '')

    raw_data = ClimateData.get_correlation_data()
    summary = ClimateData.get_summary(dataset_id) if dataset_id else ClimateData.get_summary()

    # Use ClimatePreprocessor to clean data
    preprocessor = get_preprocessor()
    processed = _preprocess_raw(raw_data, preprocessor)

    if model_type == 'temperature':
        result, confidence, model_name = _predict_temperature(processed, raw_data, summary)
    elif model_type == 'rainfall':
        result, confidence, model_name = _predict_rainfall(processed, raw_data, summary)
    elif model_type == 'anomaly':
        result, confidence, model_name = _detect_anomalies(raw_data, summary)
    elif model_type == 'air_quality':
        result, confidence, model_name = _predict_air_quality(processed, raw_data, summary)
    elif model_type == 'flood':
        result, confidence, model_name = _assess_flood_risk(raw_data, summary)
    elif model_type == 'climate_trend':
        result, confidence, model_name = _analyze_climate_trend(processed, raw_data, summary)
    else:
        result, confidence, model_name = {'info': 'Unknown model type'}, 0.5, 'Unknown Model'

    input_params = {'dataset_id': dataset_id}
    if input_data:
        input_params['custom_input'] = input_data

    Prediction.create(
        model_name=model_name, model_type=model_type,
        input_params=input_params, prediction_result=result,
        confidence=confidence, created_by=current_user.id,
        dataset_id=dataset_id
    )
    flash(f'{model_name} completed. Confidence: {round(confidence * 100, 1)}%', 'success')
    return redirect(url_for('analyst.machine_learning'))


@analyst_bp.route('/machine-learning/predictions/<int:pred_id>')
@login_required
@analyst_required
def view_ml_prediction(pred_id):
    """View full details of a prediction run (own runs only)."""
    pred = Prediction.get_by_id(pred_id)
    if not pred or pred.get('created_by') != current_user.id:
        flash('Prediction not found.', 'danger')
        return redirect(url_for('analyst.machine_learning'))
    return render_template('analyst/prediction_detail.html',
                         pred=_parse_prediction(pred),
                         active_page='machine_learning')


@analyst_bp.route('/machine-learning/predictions/<int:pred_id>/delete', methods=['POST'])
@login_required
@analyst_required
def delete_ml_prediction(pred_id):
    """Delete a prediction run (own runs only)."""
    pred = Prediction.get_by_id(pred_id)
    if not pred:
        flash('Prediction not found.', 'danger')
    elif pred.get('created_by') != current_user.id:
        flash('You can only delete your own prediction runs.', 'warning')
    else:
        Prediction.delete(pred_id)
        flash(f'Prediction #{pred_id} deleted.', 'success')
    return redirect(url_for('analyst.machine_learning'))


@analyst_bp.route('/machine-learning/accuracy')
@login_required
@analyst_required
def model_accuracy():
    """Validate model predictions against actual outcomes."""
    pred_col = get_collection('predictions')
    climate_col = get_collection('climate_data')

    rows = list(pred_col.find(
        {'model_type': {'$in': ['temperature', 'rainfall']}}
    ).sort('created_at', -1).limit(50))

    # Single batch aggregation to compute post-prediction averages, avoiding
    # N+1 per-row aggregate calls.
    pipeline = [
        {'$match': {'created_at': {'$gt': rows[-1].get('created_at', '')}}},
        {'$limit': 100},
        {'$group': {'_id': None, 'avg_temp': {'$avg': '$temperature'}, 'avg_rain': {'$avg': '$rainfall'}}},
    ]
    avg_result = list(climate_col.aggregate(pipeline))
    global_avg_temp = avg_result[0].get('avg_temp') if avg_result else None
    global_avg_rain = avg_result[0].get('avg_rain') if avg_result else None

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


# ── Helper: preprocess raw data ────────────────────────────────────────────

def _preprocess_raw(raw_data, preprocessor):
    """Use ClimatePreprocessor to clean and prepare data for ML models."""
    if not raw_data:
        return {}
    data_dict = {}
    for var in ['temperature', 'rainfall', 'humidity', 'wind_speed', 'pressure', 'air_quality_index', 'co2_level']:
        vals = [r[var] for r in raw_data if r.get(var) is not None]
        if vals:
            data_dict[var] = vals
    if data_dict:
        cleaned = preprocessor.clean_data(data_dict)
        return cleaned
    return data_dict


# ── Real ML prediction functions ────────────────────────────────────────────

def _correlation_context(variable):
    """Attach strongest observed relationships to prediction results."""
    try:
        pairs = ClimateData.get_correlation_results().get('pairwise_correlations', [])
        return [p for p in pairs if variable in (p.get('variable_1'), p.get('variable_2'))][:3]
    except Exception:
        return []

def _predict_temperature(cleaned, raw_data, summary):
    """Temperature prediction using trained model and actual data."""
    temps = cleaned.get('temperature', [])
    if len(temps) == 0:
        return {'error': 'No temperature data available'}, 0.5, 'Temperature Prediction Model'

    arr = np.array(temps, dtype=float)
    n = len(arr)

    predictor = get_climate_predictor()
    if 'temperature' in predictor.models:
        month = datetime.now().month
        pred = predictor.predict_temperature(month)
        result = {
            'predicted_avg_temp': pred['predicted_value'],
            'model_used': pred.get('model', 'trained_polynomial'),
            'model_confidence': pred.get('confidence', 75),
            'month': month,
        }
    else:
        mean_temp = float(np.mean(arr))
        std_temp = float(np.std(arr))
        slope = float(np.polyfit(np.arange(n), arr, 1)[0]) if n > 1 else 0
        forecast_step = min(30, n)
        result = {
            'predicted_avg_temp': round(mean_temp + slope * forecast_step, 1),
            'predicted_max_temp': round(float(np.max(arr)) + slope * forecast_step * 0.5, 1),
            'predicted_min_temp': round(float(np.min(arr)) + slope * forecast_step * 0.5, 1),
            'trend': 'increasing' if slope > 0.01 else ('decreasing' if slope < -0.01 else 'stable'),
            'trend_slope_per_record': round(slope, 6),
            'confidence_interval': f"[{round(mean_temp - 1.96 * std_temp, 1)}, {round(mean_temp + 1.96 * std_temp, 1)}]",
            'model_used': 'linear_trend_fallback',
        }

    result['historical_mean'] = round(float(np.mean(arr)), 2)
    result['historical_std'] = round(float(np.std(arr)), 2)
    result['data_points'] = n
    result['correlation_context'] = _correlation_context('temperature')

    cv = float(np.std(arr)) / abs(float(np.mean(arr))) if float(np.mean(arr)) != 0 else 1
    confidence = round(max(0.5, min(0.95, 1.0 - cv * 0.3)), 3)
    return result, confidence, 'Temperature Prediction Model'


def _predict_rainfall(cleaned, raw_data, summary):
    """Rainfall prediction using trained model and actual data."""
    rains = cleaned.get('rainfall', [])
    if len(rains) == 0:
        return {'error': 'No rainfall data available'}, 0.5, 'Rainfall Prediction Model'

    arr = np.array(rains, dtype=float)
    n = len(arr)
    mean_rain = float(np.mean(arr))

    predictor = get_climate_predictor()
    if 'rainfall' in predictor.models:
        month = datetime.now().month
        pred = predictor.predict_rainfall(month)
        result = {
            'predicted_rainfall_mm': pred['predicted_value'],
            'model_used': pred.get('model', 'trained_polynomial'),
            'month': month,
        }
    else:
        slope = float(np.polyfit(np.arange(n), arr, 1)[0]) if n > 1 else 0
        result = {
            'predicted_rainfall_mm': round(mean_rain + slope * 7, 1),
            'model_used': 'linear_trend_fallback',
        }

    rainy_days = int(np.sum(arr > 0))
    result['correlation_context'] = _correlation_context('rainfall')
    prob_rain = round(rainy_days / n, 3) if n > 0 else 0
    recent_heavy = sum(1 for r in rains[-30:] if r > 50)
    flood_risk = 'high' if recent_heavy > 5 else ('moderate' if recent_heavy > 2 else 'low')
    slope_val = float(np.polyfit(np.arange(n), arr, 1)[0]) if n > 1 else 0
    pattern = 'above_normal' if slope_val > 0.1 else ('below_normal' if slope_val < -0.1 else 'normal')

    result.update({
        'probability_of_rain': prob_rain,
        'flood_risk': flood_risk,
        'expected_days_with_rain': min(n, int(prob_rain * 30)),
        'dominant_pattern': pattern,
        'historical_avg_mm': round(mean_rain, 2),
        'data_points': n,
    })
    confidence = round(max(0.5, min(0.92, 0.6 + 0.3 * min(1, n / 500))), 3)
    return result, confidence, 'Rainfall Prediction Model'


def _detect_anomalies(raw_data, summary):
    """Anomaly detection using real Z-score analysis."""
    detector = get_anomaly_detector()
    records = []
    for r in raw_data:
        rec = {}
        if r.get('temperature') is not None:
            rec['temperature'] = float(r['temperature'])
        if r.get('rainfall') is not None:
            rec['rainfall'] = float(r['rainfall'])
        if r.get('air_quality_index') is not None:
            rec['aqi'] = float(r['air_quality_index'])
        if r.get('date'):
            rec['date'] = r['date']
        if r.get('station_name'):
            rec['region'] = r['station_name']
        if rec:
            records.append(rec)

    anomalies = detector.batch_detect(records[:5000])
    total_anomalies = sum(len(a.get('anomalies', [])) for a in anomalies)

    severity_dist = {'high': 0, 'medium': 0, 'low': 0}
    type_counts = {'temperature': 0, 'rainfall': 0, 'air_quality': 0}
    for a in anomalies:
        for anom in a.get('anomalies', []):
            sev = anom.get('severity', 'mild')
            if sev in ('critical', 'severe'):
                severity_dist['high'] += 1
            elif sev == 'moderate':
                severity_dist['medium'] += 1
            else:
                severity_dist['low'] += 1
            atype = anom.get('type', 'temperature')
            if atype in type_counts:
                type_counts[atype] += 1

    most_common = max(type_counts, key=type_counts.get) if any(type_counts.values()) else 'none'
    n = len(records)
    confidence = round(max(0.7, min(0.95, 0.75 + 0.2 * min(1, n / 1000))), 3)

    trained = detector.models.get('anomaly')
    result = {
        'anomalies_detected': total_anomalies,
        'most_common_type': most_common,
        'severity_distribution': severity_dist,
        'type_breakdown': type_counts,
        'analysis_method': ('Z-score with trained baselines (threshold 2.0)' if trained
                            else 'Z-score with threshold 2.0'),
        'model_used': 'trained_anomaly_baselines' if trained else 'default_thresholds',
        'records_analyzed': n,
        'anomaly_rate_pct': round(total_anomalies / max(1, n) * 100, 2),
    }
    return result, confidence, 'Anomaly Detection Model'


def _predict_air_quality(cleaned, raw_data, summary):
    """Air quality prediction using trained model and actual data."""
    aqi_vals = cleaned.get('air_quality_index', [])
    co2_vals = cleaned.get('co2_level', [])
    temp_vals = cleaned.get('temperature', [])
    hum_vals = cleaned.get('humidity', [])

    if len(aqi_vals) == 0:
        return {'error': 'No air quality data available'}, 0.5, 'Air Quality Prediction Model'

    arr = np.array(aqi_vals, dtype=float)
    n = len(arr)

    predictor = get_climate_predictor()
    if 'air_quality' in predictor.models and len(temp_vals) > 0 and len(hum_vals) > 0:
        pred = predictor.predict_air_quality(float(np.mean(temp_vals)), float(np.mean(hum_vals)))
        result = {
            'predicted_aqi': pred['predicted_value'],
            'model_used': pred.get('model', 'trained_linear'),
            'category': pred.get('category', 'Moderate'),
        }
    else:
        mean_aqi = float(np.mean(arr))
        recent = aqi_vals[-30:] if n >= 30 else aqi_vals
        recent_mean = sum(recent) / len(recent)
        older = aqi_vals[:30] if n >= 30 else aqi_vals
        older_mean = sum(older) / len(older)
        if recent_mean > mean_aqi * 1.1:
            trend = 'deteriorating'
        elif recent_mean < mean_aqi * 0.9:
            trend = 'improving'
        else:
            trend = 'stable'
        predicted_aqi = round(max(0, recent_mean), 0)
        result = {
            'predicted_aqi': predicted_aqi,
            'trend': trend,
            'model_used': 'statistical_fallback',
        }

    predicted_aqi = result.get('predicted_aqi', 50)
    if predicted_aqi <= 50:
        result['dominant_pollutant'] = 'PM2.5'
        result['health_advisory'] = 'Good'
    elif predicted_aqi <= 100:
        result['dominant_pollutant'] = 'PM10'
        result['health_advisory'] = 'Moderate'
    elif predicted_aqi <= 150:
        result['dominant_pollutant'] = 'O3'
        result['health_advisory'] = 'Unhealthy for Sensitive Groups'
    else:
        result['dominant_pollutant'] = 'NO2'
        result['health_advisory'] = 'Unhealthy'

    result['historical_avg_aqi'] = round(float(np.mean(arr)), 1)
    result['co2_avg_ppm'] = round(float(np.mean(co2_vals)), 1) if len(co2_vals) > 0 else 0
    result['data_points'] = n

    confidence = round(max(0.5, min(0.92, 0.6 + 0.3 * min(1, n / 500))), 3)
    return result, confidence, 'Air Quality Prediction Model'


def _assess_flood_risk(raw_data, summary):
    """Flood risk assessment using AnomalyDetector."""
    detector = get_anomaly_detector()
    rains = [r['rainfall'] for r in raw_data if r.get('rainfall') is not None]
    humidities = [r['humidity'] for r in raw_data if r.get('humidity') is not None]
    winds = [r['wind_speed'] for r in raw_data if r.get('wind_speed') is not None]

    if not rains:
        return {'error': 'No rainfall data available'}, 0.5, 'Flood Risk Assessment Model'

    recent_rain = rains[-1]
    recent_hum = humidities[-1] if humidities else 50
    recent_wind = winds[-1] if winds else 0

    assessment = detector.detect_flood_risk(recent_rain, recent_hum, recent_wind)
    n = len(rains)

    result = {
        'flood_probability': assessment['risk_score'],
        'risk_level': assessment['risk_level'],
        'estimated_water_level_m': round(assessment['risk_score'] * 3, 2),
        'affected_area_km2': round(assessment['risk_score'] * 25, 1),
        'contributing_factors': assessment['factors'],
        'data_points': n,
    }
    confidence = round(max(0.5, min(0.90, 0.55 + 0.3 * min(1, n / 300))), 3)
    return result, confidence, 'Flood Risk Assessment Model'


def _analyze_climate_trend(cleaned, raw_data, summary):
    """Climate trend analysis using ClimatePredictor and real data."""
    temps = cleaned.get('temperature', [])
    co2_vals = cleaned.get('co2_level', [])
    n = len(temps)

    result = {}

    predictor = get_climate_predictor()
    trend_pred = predictor.predict_climate_trend(months_ahead=12)
    result['overall_trend'] = trend_pred.get('overall_trend', 'unknown')
    result['temp_rate_per_month'] = trend_pred.get('temp_rate', 0)
    result['rainfall_rate_per_month'] = trend_pred.get('rainfall_rate', 0)

    if n > 2:
        arr = np.array(temps, dtype=float)
        slope = float(np.polyfit(np.arange(n), arr, 1)[0])
        result['temp_trend_per_decade'] = round(slope * 365 * 10 / max(1, n), 4)
        result['mean_temperature'] = round(float(np.mean(arr)), 2)
        result['sea_level_rise_mm_per_year'] = round(max(0, (float(np.mean(arr)) - 14) * 0.8), 1)

    if len(co2_vals) > 2:
        co2_arr = np.array(co2_vals, dtype=float)
        co2_slope = float(np.polyfit(np.arange(len(co2_arr)), co2_arr, 1)[0])
        result['co2_trend_ppm_per_year'] = round(co2_slope * 365 / max(1, len(co2_arr)), 4)
        result['current_co2_ppm'] = round(float(co2_arr[-1]), 1)

    result['data_points'] = n
    if not result or result.get('data_points') == 0:
        result = {'info': 'Insufficient data for trend analysis'}

    confidence = round(max(0.5, min(0.88, 0.5 + 0.3 * min(1, n / 500))), 3)
    return result, confidence, 'Climate Trend Analysis Model'
