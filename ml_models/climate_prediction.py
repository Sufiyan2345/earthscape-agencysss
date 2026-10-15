#!/usr/bin/env python3
"""
Climate prediction module for forecasting temperature, rainfall, and other climate variables.
Uses trained models or statistical methods for predictions.
"""

import numpy as np
import pickle
import os
from datetime import datetime, timedelta


class ClimatePredictor:
    """Make climate predictions using trained ML models."""

    def __init__(self):
        self.models = {}
        self.load_models()

    def load_models(self):
        """Load all trained prediction models."""
        models_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'saved_models')

        model_files = {
            'temperature': 'temperature_model.pkl',
            'rainfall': 'rainfall_model.pkl',
            'air_quality': 'air_quality_model.pkl',
            'climate_trend': 'climate_trend_model.pkl'
        }

        for name, filename in model_files.items():
            filepath = os.path.join(models_dir, filename)
            if os.path.exists(filepath):
                with open(filepath, 'rb') as f:
                    self.models[name] = pickle.load(f)

    def predict_temperature(self, month, region=None):
        """Predict temperature for a given month."""
        if 'temperature' in self.models:
            model = self.models['temperature']
            coeffs = model['coefficients']
            degree = model['degree']
            predicted = np.polyval(coeffs, month)
            confidence = max(50, 95 - model['mean_error'] * 2)
        else:
            # Fallback: seasonal model
            predicted = 15 + 10 * np.sin(2 * np.pi * (month - 4) / 12)
            confidence = 70

        return {
            'predicted_value': round(predicted, 2),
            'unit': '°C',
            'confidence': round(confidence, 1),
            'month': month,
            'model': 'polynomial' if 'temperature' in self.models else 'seasonal_estimate',
            'timestamp': datetime.now().isoformat()
        }

    def predict_rainfall(self, month, region=None):
        """Predict rainfall for a given month."""
        if 'rainfall' in self.models:
            model = self.models['rainfall']
            coeffs = model['coefficients']
            predicted = max(0, np.polyval(coeffs, month))
            confidence = max(50, 90 - model['mean_error'])
        else:
            predicted = max(0, 50 + 30 * np.sin(2 * np.pi * (month - 6) / 12))
            confidence = 65

        return {
            'predicted_value': round(predicted, 2),
            'unit': 'mm',
            'confidence': round(confidence, 1),
            'month': month,
            'model': 'polynomial' if 'rainfall' in self.models else 'seasonal_estimate',
            'timestamp': datetime.now().isoformat()
        }

    def predict_air_quality(self, temperature, humidity):
        """Predict air quality index based on temperature and humidity."""
        if 'air_quality' in self.models:
            model = self.models['air_quality']
            coeffs = model['coefficients']
            predicted = coeffs[0] + coeffs[1] * temperature + coeffs[2] * humidity
        else:
            predicted = 50 + 0.5 * temperature + 0.1 * humidity

        predicted = max(0, min(500, predicted))

        return {
            'predicted_value': round(predicted, 1),
            'unit': 'AQI',
            'confidence': 75.0,
            'inputs': {'temperature': temperature, 'humidity': humidity},
            'category': self._aqi_category(predicted),
            'timestamp': datetime.now().isoformat()
        }

    def predict_climate_trend(self, months_ahead=12):
        """Predict climate trends for future months."""
        if 'climate_trend' in self.models:
            model = self.models['climate_trend']
            temp_slope = model['temp_slope']
            rain_slope = model['rain_slope']
        else:
            temp_slope = 0.02
            rain_slope = -0.01

        predictions = []
        for i in range(1, months_ahead + 1):
            temp_change = temp_slope * i
            rain_change = rain_slope * i
            predictions.append({
                'month_offset': i,
                'temp_change': round(temp_change, 3),
                'rainfall_change': round(rain_change, 3),
                'trend': 'warming' if temp_change > 0 else 'cooling'
            })

        return {
            'predictions': predictions,
            'overall_trend': 'warming' if temp_slope > 0 else 'cooling',
            'temp_rate': round(temp_slope, 4),
            'rainfall_rate': round(rain_slope, 4),
            'timestamp': datetime.now().isoformat()
        }

    def comprehensive_forecast(self, month, region=None):
        """Generate comprehensive climate forecast."""
        temp = self.predict_temperature(month, region)
        rain = self.predict_rainfall(month, region)
        trend = self.predict_climate_trend(3)

        return {
            'temperature': temp,
            'rainfall': rain,
            'trend': trend,
            'region': region or 'global',
            'generated_at': datetime.now().isoformat(),
            'summary': self._generate_summary(temp, rain, trend)
        }

    def _aqi_category(self, aqi):
        """Classify AQI value."""
        if aqi <= 50:
            return 'Good'
        elif aqi <= 100:
            return 'Moderate'
        elif aqi <= 150:
            return 'Unhealthy for Sensitive Groups'
        elif aqi <= 200:
            return 'Unhealthy'
        elif aqi <= 300:
            return 'Very Unhealthy'
        return 'Hazardous'

    def _generate_summary(self, temp, rain, trend):
        """Generate human-readable forecast summary."""
        summary_parts = []

        temp_val = temp['predicted_value']
        if temp_val > 35:
            summary_parts.append("Expect very hot conditions")
        elif temp_val > 25:
            summary_parts.append("Expect warm conditions")
        elif temp_val > 15:
            summary_parts.append("Expect mild conditions")
        else:
            summary_parts.append("Expect cool conditions")

        rain_val = rain['predicted_value']
        if rain_val > 80:
            summary_parts.append("with heavy rainfall likely")
        elif rain_val > 30:
            summary_parts.append("with moderate rainfall")
        elif rain_val > 0:
            summary_parts.append("with light rainfall possible")
        else:
            summary_parts.append("with dry conditions")

        if trend['overall_trend'] == 'warming':
            summary_parts.append(". Long-term trend shows warming pattern")

        return ''.join(summary_parts) + "."


if __name__ == '__main__':
    predictor = ClimatePredictor()

    print("Temperature prediction (July):", predictor.predict_temperature(7))
    print("Rainfall prediction (July):", predictor.predict_rainfall(7))
    print("Air quality prediction:", predictor.predict_air_quality(30, 70))
    print("Comprehensive forecast:", predictor.comprehensive_forecast(7, 'North America'))
