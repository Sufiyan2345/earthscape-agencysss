#!/usr/bin/env python3
"""
Data preprocessing module for climate data.
Handles cleaning, normalization, feature extraction, and transformation.
"""

import numpy as np
from datetime import datetime


class ClimatePreprocessor:
    """Preprocess climate data for ML model consumption."""

    def __init__(self):
        self.scaling_params = {}
        self.feature_names = ['temperature', 'rainfall', 'humidity', 'wind_speed', 'pressure', 'aqi']

    def clean_data(self, data):
        """
        Clean raw climate data:
        - Remove null/NaN values
        - Handle outliers
        - Fill missing values
        """
        cleaned = {}
        for key, values in data.items():
            arr = np.array(values, dtype=float)
            # Replace NaN with median
            mask = np.isnan(arr)
            if mask.any():
                median = np.nanmedian(arr)
                arr[mask] = median
            cleaned[key] = arr
        return cleaned

    def remove_outliers(self, data, method='iqr', threshold=1.5):
        """Remove outliers using IQR or Z-score method."""
        cleaned = {}
        for key, values in data.items():
            arr = np.array(values, dtype=float)
            if method == 'iqr':
                q1 = np.percentile(arr, 25)
                q3 = np.percentile(arr, 75)
                iqr = q3 - q1
                lower = q1 - threshold * iqr
                upper = q3 + threshold * iqr
                mask = (arr >= lower) & (arr <= upper)
                cleaned[key] = arr[mask]
            elif method == 'zscore':
                mean = np.mean(arr)
                std = np.std(arr)
                z_scores = np.abs((arr - mean) / std) if std > 0 else np.zeros_like(arr)
                mask = z_scores < threshold
                cleaned[key] = arr[mask]
            else:
                cleaned[key] = arr
        return cleaned

    def normalize(self, data, method='minmax'):
        """Normalize data using min-max or z-score normalization."""
        normalized = {}
        for key, values in data.items():
            arr = np.array(values, dtype=float)
            if method == 'minmax':
                min_val = np.min(arr)
                max_val = np.max(arr)
                if max_val - min_val > 0:
                    normalized[key] = (arr - min_val) / (max_val - min_val)
                else:
                    normalized[key] = np.zeros_like(arr)
                self.scaling_params[key] = {'min': float(min_val), 'max': float(max_val), 'method': 'minmax'}
            elif method == 'zscore':
                mean = np.mean(arr)
                std = np.std(arr)
                if std > 0:
                    normalized[key] = (arr - mean) / std
                else:
                    normalized[key] = np.zeros_like(arr)
                self.scaling_params[key] = {'mean': float(mean), 'std': float(std), 'method': 'zscore'}
        return normalized

    def extract_features(self, data):
        """Extract additional features from raw climate data."""
        features = dict(data)

        # Temperature features
        if 'temperature' in data:
            temp = data['temperature']
            features['temp_squared'] = temp ** 2
            features['temp_deviation'] = np.abs(temp - np.mean(temp))

        # Rainfall features
        if 'rainfall' in data:
            rain = data['rainfall']
            features['rainfall_cumulative'] = np.cumsum(rain)
            features['rainfall_binary'] = (rain > 0).astype(float)

        # Humidity features
        if 'humidity' in data:
            hum = data['humidity']
            features['humidity_category'] = np.where(hum < 30, 'low',
                                           np.where(hum < 60, 'moderate', 'high'))

        # Wind features
        if 'wind_speed' in data:
            wind = data['wind_speed']
            features['wind_category'] = np.where(wind < 10, 'calm',
                                      np.where(wind < 25, 'moderate', 'strong'))

        return features

    def create_lag_features(self, data, lag=1):
        """Create lagged features for time series analysis."""
        lagged = {}
        for key, values in data.items():
            arr = np.array(values, dtype=float)
            lagged[f'{key}_lag_{lag}'] = np.roll(arr, lag)
            lagged[f'{key}_lag_{lag}'][:lag] = arr[:lag]  # Fill initial values
        return lagged

    def create_rolling_features(self, data, window=7):
        """Create rolling window statistics."""
        rolling = {}
        for key, values in data.items():
            arr = np.array(values, dtype=float)
            # Rolling mean
            rolling_mean = np.convolve(arr, np.ones(window)/window, mode='same')
            rolling[f'{key}_rolling_mean_{window}'] = rolling_mean
            # Rolling std
            rolling_std = np.array([np.std(arr[max(0, i-window):i+1]) for i in range(len(arr))])
            rolling[f'{key}_rolling_std_{window}'] = rolling_std
        return rolling

    def preprocess_pipeline(self, raw_data):
        """Run full preprocessing pipeline."""
        # Step 1: Clean data
        cleaned = self.clean_data(raw_data)

        # Step 2: Remove outliers
        filtered = self.remove_outliers(cleaned, method='iqr')

        # Step 3: Extract features
        featured = self.extract_features(filtered)

        # Step 4: Normalize
        normalized = self.normalize(featured, method='minmax')

        return normalized


def preprocess_climate_record(record):
    """Preprocess a single climate record."""
    preprocessor = ClimatePreprocessor()
    return preprocessor.clean_data(record)


if __name__ == '__main__':
    # Test preprocessing
    sample_data = {
        'temperature': [22.5, 23.1, np.nan, 24.0, 22.8, 100.0, 23.5, 22.9],
        'rainfall': [10, 15, 0, 20, 5, 8, np.nan, 12],
        'humidity': [65, 70, 68, 72, 60, 75, 66, 71]
    }

    preprocessor = ClimatePreprocessor()
    result = preprocessor.preprocess_pipeline(sample_data)
    print("Preprocessing complete!")
    for key, values in result.items():
        print(f"  {key}: {values[:5]}...")
