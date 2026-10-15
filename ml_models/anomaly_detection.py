#!/usr/bin/env python3
"""
Anomaly detection module for climate data.
Detects temperature anomalies, rainfall extremes, and unusual patterns.
"""

import numpy as np
import pickle
import os
from datetime import datetime


class AnomalyDetector:
    """Detect anomalies in climate data using statistical methods."""

    def __init__(self):
        self.models = {}
        self.thresholds = {}
        self.load_models()

    def load_models(self):
        """Load trained anomaly detection models."""
        models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saved_models')

        model_files = {
            'heatwave': 'heatwave_model.pkl',
            'flood': 'flood_model.pkl',
            'anomaly': 'anomaly_model.pkl'
        }

        for name, filename in model_files.items():
            filepath = os.path.join(models_dir, filename)
            if os.path.exists(filepath):
                with open(filepath, 'rb') as f:
                    self.models[name] = pickle.load(f)

    def detect_temperature_anomaly(self, temperature, region_stats=None):
        """
        Detect if a temperature reading is anomalous.
        Uses Z-score method or model-based detection.
        """
        model = self.models.get('heatwave')
        if model is None and 'anomaly' in self.models:
            baseline = self.models['anomaly'].get('baselines', {}).get('temperature', {})
            if baseline:
                model = {
                    'mean_temp': baseline.get('mean', 20.0),
                    'std_temp': baseline.get('std', 5.0),
                    'threshold': 35.0,
                }

        if model is not None:
            threshold = model.get('threshold', 35.0)
            mean_temp = model.get('mean_temp', 20.0)
            std_temp = model.get('std_temp', 5.0)

            z_score = abs(temperature - mean_temp) / std_temp if std_temp > 0 else 0

            return {
                'is_anomaly': z_score > 2.0 or temperature > threshold,
                'type': 'heatwave' if temperature > threshold else 'cold_spell' if temperature < mean_temp - 2 * std_temp else 'normal',
                'z_score': round(z_score, 2),
                'severity': self._classify_severity(z_score),
                'threshold': threshold,
                'value': temperature
            }

        # Fallback: simple threshold
        return {
            'is_anomaly': temperature > 40 or temperature < -10,
            'type': 'heatwave' if temperature > 40 else 'cold_spell' if temperature < -10 else 'normal',
            'z_score': 0,
            'severity': 'unknown',
            'threshold': 40,
            'value': temperature
        }

    def detect_rainfall_anomaly(self, rainfall, historical_data=None):
        """Detect anomalous rainfall patterns."""
        if historical_data:
            mean_rain = np.mean(historical_data)
            std_rain = np.std(historical_data)
            z_score = abs(rainfall - mean_rain) / std_rain if std_rain > 0 else 0
        else:
            # Use trained baselines when available, else generic defaults
            trained = self.models.get('anomaly', {}).get('baselines', {}).get('rainfall')
            if trained:
                mean_rain = trained.get('mean', 50)
                std_rain = trained.get('std', 25)
            else:
                mean_rain = 50
                std_rain = 25
            z_score = abs(rainfall - mean_rain) / std_rain if std_rain > 0 else 0

        is_extreme = rainfall > mean_rain + 2 * std_rain
        is_flood_risk = rainfall > 100

        return {
            'is_anomaly': z_score > 2.0,
            'type': 'extreme_rainfall' if is_extreme else 'flood_risk' if is_flood_risk else 'normal',
            'z_score': round(z_score, 2),
            'severity': self._classify_severity(z_score),
            'value': rainfall,
            'threshold': round(mean_rain + 2 * std_rain, 2)
        }

    def detect_flood_risk(self, rainfall, humidity, wind_speed=None):
        """Assess flood risk based on multiple factors."""
        risk_score = 0.0
        factors = []

        # Rainfall factor (60% weight)
        if rainfall > 100:
            risk_score += 0.6
            factors.append(f"Extreme rainfall: {rainfall}mm")
        elif rainfall > 50:
            risk_score += 0.3
            factors.append(f"High rainfall: {rainfall}mm")

        # Humidity factor (30% weight)
        if humidity > 85:
            risk_score += 0.3
            factors.append(f"Very high humidity: {humidity}%")
        elif humidity > 70:
            risk_score += 0.15
            factors.append(f"High humidity: {humidity}%")

        # Wind factor (10% weight)
        if wind_speed and wind_speed > 30:
            risk_score += 0.1
            factors.append(f"Strong winds: {wind_speed}km/h")

        risk_level = 'low'
        if risk_score > 0.7:
            risk_level = 'critical'
        elif risk_score > 0.5:
            risk_level = 'high'
        elif risk_score > 0.3:
            risk_level = 'moderate'

        return {
            'risk_score': round(risk_score, 2),
            'risk_level': risk_level,
            'factors': factors,
            'rainfall': rainfall,
            'humidity': humidity,
            'wind_speed': wind_speed
        }

    def detect_air_quality_anomaly(self, aqi):
        """Detect air quality anomalies."""
        categories = [
            (50, 'Good', 'success'),
            (100, 'Moderate', 'info'),
            (150, 'Unhealthy for Sensitive Groups', 'warning'),
            (200, 'Unhealthy', 'warning'),
            (300, 'Very Unhealthy', 'danger'),
            (500, 'Hazardous', 'danger')
        ]

        category = 'Good'
        severity = 'success'
        for threshold, cat, sev in categories:
            if aqi <= threshold:
                category = cat
                severity = sev
                break

        return {
            'is_anomaly': aqi > 150,
            'aqi': aqi,
            'category': category,
            'severity': severity,
            'health_impact': self._get_health_impact(aqi)
        }

    def batch_detect(self, records):
        """Run anomaly detection on a batch of records."""
        results = []
        for record in records:
            result = {
                'timestamp': record.get('date', ''),
                'region': record.get('region', ''),
                'anomalies': []
            }

            if 'temperature' in record:
                temp_anomaly = self.detect_temperature_anomaly(record['temperature'])
                if temp_anomaly['is_anomaly']:
                    result['anomalies'].append({'type': 'temperature', **temp_anomaly})

            if 'rainfall' in record:
                rain_anomaly = self.detect_rainfall_anomaly(record['rainfall'])
                if rain_anomaly['is_anomaly']:
                    result['anomalies'].append({'type': 'rainfall', **rain_anomaly})

            if 'aqi' in record:
                aqi_anomaly = self.detect_air_quality_anomaly(record['aqi'])
                if aqi_anomaly['is_anomaly']:
                    result['anomalies'].append({'type': 'air_quality', **aqi_anomaly})

            if result['anomalies']:
                results.append(result)

        return results

    def _classify_severity(self, z_score):
        """Classify anomaly severity based on Z-score."""
        if z_score > 3:
            return 'critical'
        elif z_score > 2.5:
            return 'severe'
        elif z_score > 2:
            return 'moderate'
        else:
            return 'mild'

    def _get_health_impact(self, aqi):
        """Get health impact description for AQI level."""
        if aqi <= 50:
            return "Air quality is satisfactory, posing little or no health risk."
        elif aqi <= 100:
            return "Air quality is acceptable. Some pollutants may pose moderate health concern for sensitive individuals."
        elif aqi <= 150:
            return "Members of sensitive groups may experience health effects. General public is less likely to be affected."
        elif aqi <= 200:
            return "Some members of the general public may experience health effects; sensitive groups may experience more serious effects."
        elif aqi <= 300:
            return "Health alert: The entire population is more likely to be affected."
        else:
            return "Health warning of emergency conditions. The entire population is at risk."


if __name__ == '__main__':
    detector = AnomalyDetector()

    # Test detections
    print("Temperature anomaly:", detector.detect_temperature_anomaly(42.5))
    print("Rainfall anomaly:", detector.detect_rainfall_anomaly(120))
    print("Flood risk:", detector.detect_flood_risk(90, 85, 25))
    print("Air quality:", detector.detect_air_quality_anomaly(180))
