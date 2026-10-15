import pandas as pd
import numpy as np
from datetime import datetime


class DataPreprocessor:
    """Data preprocessing utilities for climate data."""

    @staticmethod
    def clean_dataframe(df):
        """Clean and preprocess a climate DataFrame."""
        result = df.copy()

        # Handle missing values
        numeric_cols = result.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            if result[col].isnull().sum() > 0:
                result[col] = result[col].fillna(result[col].median())

        # Remove duplicates
        result = result.drop_duplicates()

        return result

    @staticmethod
    def normalize_data(df, columns=None):
        """Normalize numeric columns to 0-1 range."""
        result = df.copy()
        if columns is None:
            columns = result.select_dtypes(include=[np.number]).columns
        for col in columns:
            if col in result.columns:
                min_val = result[col].min()
                max_val = result[col].max()
                if max_val > min_val:
                    result[col] = (result[col] - min_val) / (max_val - min_val)
        return result

    @staticmethod
    def detect_outliers(df, column, method='zscore', threshold=3.0):
        """Detect outliers in a column."""
        if column not in df.columns:
            return []
        data = df[column].dropna()
        if method == 'zscore':
            mean = data.mean()
            std = data.std()
            if std == 0:
                return []
            z_scores = np.abs((data - mean) / std)
            outliers = data[z_scores > threshold]
            return outliers.index.tolist()
        elif method == 'iqr':
            Q1 = data.quantile(0.25)
            Q3 = data.quantile(0.75)
            IQR = Q3 - Q1
            lower = Q1 - 1.5 * IQR
            upper = Q3 + 1.5 * IQR
            outliers = data[(data < lower) | (data > upper)]
            return outliers.index.tolist()
        return []

    @staticmethod
    def generate_sample_data(records=100):
        """Generate sample climate data for testing."""
        np.random.seed(42)
        dates = pd.date_range('2024-01-01', periods=records, freq='D')
        stations = ['Station_Alpha', 'Station_Beta', 'Station_Gamma', 'Station_Delta', 'Station_Epsilon']

        data = []
        for i, date in enumerate(dates):
            station = stations[i % len(stations)]
            record = {
                'station_name': station,
                'latitude': round(np.random.uniform(-90, 90), 4),
                'longitude': round(np.random.uniform(-180, 180), 4),
                'elevation': round(np.random.uniform(0, 5000), 1),
                'date': date.strftime('%Y-%m-%d'),
                'temperature': round(np.random.normal(25, 8), 1),
                'humidity': round(np.random.uniform(30, 95), 1),
                'rainfall': round(max(0, np.random.exponential(10)), 1),
                'wind_speed': round(max(0, np.random.normal(20, 10)), 1),
                'wind_direction': round(np.random.uniform(0, 360), 1),
                'pressure': round(np.random.normal(1013, 10), 1),
                'co2_level': round(np.random.normal(415, 20), 1),
                'air_quality_index': round(max(0, np.random.normal(80, 30)), 0),
                'visibility': round(np.random.uniform(1, 20), 1),
                'cloud_cover': round(np.random.uniform(0, 100), 1),
                'uv_index': round(max(0, np.random.normal(5, 2)), 1),
                'soil_moisture': round(np.random.uniform(10, 80), 1),
                'snow_depth': round(max(0, np.random.normal(5, 10)), 1),
            }
            data.append(record)
        return data

    @staticmethod
    def compute_statistics(df):
        """Compute descriptive statistics for climate data."""
        stats = {}
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            stats[col] = {
                'mean': round(df[col].mean(), 2),
                'median': round(df[col].median(), 2),
                'std': round(df[col].std(), 2),
                'min': round(df[col].min(), 2),
                'max': round(df[col].max(), 2),
                'count': int(df[col].count()),
                'missing': int(df[col].isnull().sum()),
            }
        return stats
