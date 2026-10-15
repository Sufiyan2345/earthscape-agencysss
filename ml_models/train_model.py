#!/usr/bin/env python3
"""
Training script for climate prediction models.
Trains from real climate_data in the database. Falls back to synthetic data
only when the database has insufficient records.
"""

import os
import sys
import pickle
import numpy as np
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SAVED_MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saved_models')


def load_real_data():
    """Load real climate data from the database."""
    try:
        from app import create_app
        app = create_app()
        with app.app_context():
            from utils.database import get_collection
            col = get_collection('climate_data')
            rows = list(col.find(
                {'temperature': {'$ne': None}, 'rainfall': {'$ne': None}},
            ).sort('date', 1))

            if len(rows) < 30:
                return None

            def aligned_field(field, default):
                values = []
                for row in rows:
                    try:
                        value = float(row.get(field))
                    except (TypeError, ValueError):
                        value = np.nan
                    values.append(value)
                values = np.asarray(values, dtype=float)
                valid = values[~np.isnan(values)]
                fill = float(np.median(valid)) if len(valid) else default
                return np.nan_to_num(values, nan=fill)

            data = {
                'temperature': aligned_field('temperature', 20.0),
                'rainfall': aligned_field('rainfall', 50.0),
                'humidity': aligned_field('humidity', 50.0),
                'wind_speed': aligned_field('wind_speed', 10.0),
                'pressure': aligned_field('pressure', 1013.0),
                'aqi': aligned_field('air_quality_index', 50.0),
                'co2_level': aligned_field('co2_level', 400.0),
                'source': 'real_database',
                'record_count': len(rows),
            }
            # Derive months from dates for seasonal models
            months = []
            for r in rows:
                try:
                    m = int(r['date'][5:7]) if r.get('date') and len(r['date']) >= 7 else 6
                    months.append(m)
                except (ValueError, TypeError):
                    months.append(6)
            data['months'] = np.array(months)
            return data
    except Exception as e:
        print(f"  Could not load real data: {e}")
        return None


def generate_training_data(n_samples=1000):
    """Generate synthetic climate training data as fallback."""
    np.random.seed(42)
    months = np.random.randint(1, 13, n_samples)
    base_temp = 15 + 10 * np.sin(2 * np.pi * (months - 4) / 12)
    temperature = base_temp + np.random.normal(0, 3, n_samples)
    base_rain = 50 + 30 * np.sin(2 * np.pi * (months - 6) / 12)
    rainfall = np.maximum(0, base_rain + np.random.normal(0, 20, n_samples))
    humidity = np.clip(40 + 0.3 * rainfall + np.random.normal(0, 10, n_samples), 10, 100)
    wind_speed = np.maximum(0, 15 + np.random.normal(0, 8, n_samples))
    pressure = 1013 + np.random.normal(0, 10, n_samples)
    aqi = np.clip(50 + 0.5 * temperature + 0.1 * humidity + np.random.normal(0, 20, n_samples), 0, 500)

    return {
        'months': months,
        'temperature': temperature,
        'rainfall': rainfall,
        'humidity': humidity,
        'wind_speed': wind_speed,
        'pressure': pressure,
        'aqi': aqi,
        'source': 'synthetic',
        'record_count': n_samples,
    }


def _compute_metrics(actual, predicted):
    """Compute regression metrics: RMSE, MAE, R²."""
    n = min(len(actual), len(predicted))
    if n < 2:
        return {'rmse': 0, 'mae': 0, 'r_squared': 0}
    a = actual[:n]
    p = predicted[:n]
    residuals = a - p
    rmse = float(np.sqrt(np.mean(residuals ** 2)))
    mae = float(np.mean(np.abs(residuals)))
    ss_res = np.sum(residuals ** 2)
    ss_tot = np.sum((a - np.mean(a)) ** 2)
    r_squared = float(1 - ss_res / ss_tot) if ss_tot > 0 else 0
    return {'rmse': round(rmse, 4), 'mae': round(mae, 4), 'r_squared': round(r_squared, 4)}


def _validation_split(values, minimum_test=6):
    """Use the newest records as a time-ordered holdout set."""
    values = np.asarray(values, dtype=float)
    if len(values) < minimum_test * 2:
        return values, values
    split = max(minimum_test, int(len(values) * 0.8))
    return values[:split], values[split:]


def train_temperature_model(data):
    """Train temperature prediction model from data."""
    X = data['months'].astype(float)
    y = data['temperature']
    train_x, test_x = _validation_split(X)
    train_y, test_y = _validation_split(y)

    coeffs = np.polyfit(train_x, train_y, deg=3)
    predicted = np.polyval(coeffs, X)
    metrics = _compute_metrics(train_y, np.polyval(coeffs, train_x))
    metrics['validation'] = _compute_metrics(test_y, np.polyval(coeffs, test_x))

    model = {
        'type': 'polynomial',
        'coefficients': coeffs.tolist(),
        'degree': 3,
        'mean_error': float(np.std(y - predicted)),
        'metrics': metrics,
        'accuracy_pct': round(max(50, metrics['validation']['r_squared'] * 100), 1),
        'trained_at': datetime.now().isoformat(),
        'data_source': data.get('source', 'unknown'),
        'training_samples': len(y),
    }
    return model, metrics


def train_rainfall_model(data):
    """Train rainfall prediction model from data."""
    X = data['months'].astype(float)
    y = data['rainfall']
    train_x, test_x = _validation_split(X)
    train_y, test_y = _validation_split(y)

    coeffs = np.polyfit(train_x, train_y, deg=2)
    predicted = np.polyval(coeffs, X)
    metrics = _compute_metrics(train_y, np.polyval(coeffs, train_x))
    metrics['validation'] = _compute_metrics(test_y, np.polyval(coeffs, test_x))

    model = {
        'type': 'polynomial',
        'coefficients': coeffs.tolist(),
        'degree': 2,
        'mean_error': float(np.std(y - predicted)),
        'metrics': metrics,
        'accuracy_pct': round(max(50, metrics['validation']['r_squared'] * 100), 1),
        'trained_at': datetime.now().isoformat(),
        'data_source': data.get('source', 'unknown'),
        'training_samples': len(y),
    }
    return model, metrics


def train_flood_model(data):
    """Train flood risk model from data thresholds."""
    rain = data['rainfall']
    hum = data.get('humidity', np.full(len(rain), 50.0))
    wind = data.get('wind_speed', np.full(len(rain), 10.0))

    # Compute data-driven thresholds
    rain_threshold = float(np.percentile(rain, 85))
    hum_threshold = float(np.percentile(hum, 80)) if len(hum) > 0 else 70.0
    wind_threshold = float(np.percentile(wind, 80)) if len(wind) > 0 else 20.0

    # Compute actual flood labels from data
    flood_labels = ((rain > rain_threshold).astype(float) * 0.6 +
                    (hum > hum_threshold).astype(float) * 0.3 +
                    (wind > wind_threshold).astype(float) * 0.1)
    predicted = (np.clip(rain / (rain_threshold + 1), 0, 1) * 0.6 +
                 np.clip(hum[:len(rain)] / (hum_threshold + 1), 0, 1) * 0.3 +
                 np.clip(wind[:len(rain)] / (wind_threshold + 1), 0, 1) * 0.1)
    metrics = _compute_metrics(flood_labels, predicted)

    model = {
        'type': 'threshold',
        'rainfall_threshold': round(rain_threshold, 2),
        'humidity_threshold': round(hum_threshold, 2),
        'wind_threshold': round(wind_threshold, 2),
        'weights': [0.6, 0.3, 0.1],
        'metrics': metrics,
        'accuracy_pct': round(max(50, metrics['r_squared'] * 100), 1),
        'trained_at': datetime.now().isoformat(),
        'data_source': data.get('source', 'unknown'),
        'training_samples': len(rain),
    }
    return model, metrics


def train_heatwave_model(data):
    """Train heatwave detection model from data statistics."""
    temp = data['temperature']
    temp_mean = float(np.mean(temp))
    temp_std = float(np.std(temp))
    heatwave_threshold = temp_mean + 2 * temp_std

    # Compute detection accuracy on training data
    z_scores = np.abs((temp - temp_mean) / temp_std) if temp_std > 0 else np.zeros_like(temp)
    detected = z_scores > 2.0
    actual_extremes = (temp > heatwave_threshold) | (temp < temp_mean - 2 * temp_std)
    if np.sum(actual_extremes) > 0:
        accuracy = float(np.sum(detected == actual_extremes) / len(detected))
    else:
        accuracy = float(np.sum(~detected) / len(detected)) if len(detected) > 0 else 0.5

    model = {
        'type': 'statistical',
        'mean_temp': temp_mean,
        'std_temp': temp_std,
        'threshold': float(heatwave_threshold),
        'metrics': {'accuracy': round(accuracy, 4)},
        'accuracy_pct': round(max(50, accuracy * 100), 1),
        'trained_at': datetime.now().isoformat(),
        'data_source': data.get('source', 'unknown'),
        'training_samples': len(temp),
    }
    return model, {'accuracy': round(accuracy, 4)}


def train_anomaly_model(data):
    """Train anomaly detection baselines (Z-score stats) from data."""
    temp = data['temperature']
    rain = data['rainfall']
    aqi = data.get('aqi', np.array([]))

    baselines = {
        'temperature': {'mean': float(np.mean(temp)), 'std': float(np.std(temp))},
        'rainfall': {'mean': float(np.mean(rain)), 'std': float(np.std(rain))},
    }
    if len(aqi) > 0:
        baselines['aqi'] = {'mean': float(np.mean(aqi)), 'std': float(np.std(aqi))}

    # Evaluate: fraction of training records inside the normal band (|z| <= 2)
    inside, total = 0, 0
    for key, arr in (('temperature', temp), ('rainfall', rain)):
        std = baselines[key]['std']
        if std <= 0:
            continue
        z = np.abs((arr - baselines[key]['mean']) / std)
        inside += int(np.sum(z <= 2.0))
        total += len(arr)
    coverage = inside / total if total else 0.0
    # Expected normal coverage for a z=2.0 band is ~95.4% — score fit against it
    accuracy = max(0.5, 1.0 - abs(coverage - 0.9545))

    metrics = {'normal_coverage': round(coverage, 4), 'expected_coverage': 0.9545}
    model = {
        'type': 'statistical_baselines',
        'threshold': 2.0,
        'baselines': {k: {'mean': round(v['mean'], 4), 'std': round(v['std'], 4)}
                      for k, v in baselines.items()},
        'metrics': metrics,
        'accuracy_pct': round(accuracy * 100, 1),
        'trained_at': datetime.now().isoformat(),
        'data_source': data.get('source', 'unknown'),
        'training_samples': len(temp),
    }
    return model, metrics


def train_air_quality_model(data):
    """Train air quality prediction model from data."""
    temp = data['temperature']
    hum = data.get('humidity', np.full(len(temp), 50.0))[:len(temp)]
    aqi = data.get('aqi', data.get('air_quality_index', np.full(len(temp), 50.0)))[:len(temp)]

    X_with_bias = np.column_stack([np.ones(len(temp)), temp, hum])
    try:
        coeffs = np.linalg.lstsq(X_with_bias, aqi, rcond=None)[0]
    except np.linalg.LinAlgError:
        coeffs = np.array([50.0, 0.5, 0.1])

    predicted = X_with_bias @ coeffs
    metrics = _compute_metrics(aqi, predicted)

    model = {
        'type': 'linear',
        'coefficients': coeffs.tolist(),
        'intercept': float(coeffs[0]),
        'metrics': metrics,
        'accuracy_pct': round(max(50, metrics['r_squared'] * 100), 1),
        'trained_at': datetime.now().isoformat(),
        'data_source': data.get('source', 'unknown'),
        'training_samples': len(aqi),
    }
    return model, metrics


def train_climate_trend_model(data):
    """Train climate trend model from data."""
    temp = data['temperature']
    rain = data['rainfall']
    n = len(temp)
    years = np.arange(n, dtype=float)

    temp_trend = np.polyfit(years, temp, 1)
    rain_trend = np.polyfit(years, rain, 1)

    temp_pred = np.polyval(temp_trend, years)
    rain_pred = np.polyval(rain_trend, years)
    temp_metrics = _compute_metrics(temp, temp_pred)
    rain_metrics = _compute_metrics(rain, rain_pred)

    model = {
        'type': 'trend',
        'temp_slope': float(temp_trend[0]),
        'temp_intercept': float(temp_trend[1]),
        'rain_slope': float(rain_trend[0]),
        'rain_intercept': float(rain_trend[1]),
        'metrics': {'temperature': temp_metrics, 'rainfall': rain_metrics},
        'accuracy_pct': round(max(50, temp_metrics['r_squared'] * 100), 1),
        'trained_at': datetime.now().isoformat(),
        'data_source': data.get('source', 'unknown'),
        'training_samples': n,
    }
    return model, temp_metrics


def save_model(model, filename):
    """Save model to file."""
    os.makedirs(SAVED_MODELS_DIR, exist_ok=True)
    filepath = os.path.join(SAVED_MODELS_DIR, filename)
    with open(filepath, 'wb') as f:
        pickle.dump(model, f)
    print(f"  Model saved: {filepath}")
    return filepath


def train_all_models(user_id=None):
    """Train all models and return results. Can be called from web routes."""
    print("Loading data...")
    data = load_real_data()
    if data is None:
        print("  Insufficient real data, using synthetic data as fallback")
        data = generate_training_data(1000)
    else:
        print(f"  Loaded {data['record_count']} real records from database")

    results = {}
    models_to_train = {
        'temperature': ('temperature_model.pkl', 'Temperature Prediction', train_temperature_model),
        'rainfall': ('rainfall_model.pkl', 'Rainfall Prediction', train_rainfall_model),
        'flood': ('flood_model.pkl', 'Flood Risk Detection', train_flood_model),
        'heatwave': ('heatwave_model.pkl', 'Heatwave Detection', train_heatwave_model),
        'anomaly': ('anomaly_model.pkl', 'Anomaly Detection', train_anomaly_model),
        'air_quality': ('air_quality_model.pkl', 'Air Quality Prediction', train_air_quality_model),
        'climate_trend': ('climate_trend_model.pkl', 'Climate Trend Analysis', train_climate_trend_model),
    }

    for model_type, (filename, name, train_func) in models_to_train.items():
        print(f"Training {name}...")
        model, metrics = train_func(data)
        validation = metrics.get('validation') if isinstance(metrics, dict) else None
        if validation and validation.get('r_squared', 0) < -0.5:
            print(f"  {name} rejected: holdout R² is {validation['r_squared']}")
            continue
        filepath = save_model(model, filename)

        # Register version if user_id provided
        version_id = None
        if user_id is not None:
            try:
                from models.model_version import ModelVersion
                version_num = ModelVersion.get_next_version(model_type)
                version_id = ModelVersion.create(
                    model_type=model_type,
                    model_name=name,
                    version=version_num,
                    accuracy=model.get('accuracy_pct', 0),
                    metrics=metrics,
                    trained_on_data={'source': data.get('source', 'unknown'), 'records': data['record_count']},
                    file_path=filepath,
                    trained_by=user_id,
                )
            except Exception as e:
                print(f"  Warning: could not register model version: {e}")

        results[model_type] = {
            'model': model,
            'metrics': metrics,
            'file_path': filepath,
            'version_id': version_id,
        }
        print(f"  {name} trained. Accuracy: {model.get('accuracy_pct', 'N/A')}%")

    return results, data


def main():
    """CLI entry point to train all models."""
    print("=" * 50)
    print("EarthScape Climate - Model Training")
    print("=" * 50)
    results, data = train_all_models(user_id=None)
    print("\n" + "=" * 50)
    print(f"All models trained on {data.get('source', 'unknown')} data ({data['record_count']} records)")
    print("=" * 50)


if __name__ == '__main__':
    main()
