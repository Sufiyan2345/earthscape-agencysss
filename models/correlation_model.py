"""
Correlation analysis run store.
Analysts perform correlation runs; every run is persisted so the Admin
panel can monitor results and processing status.
"""
from utils.database import get_collection, next_id
from datetime import datetime
import numpy as np


class CorrelationRun:
    # Variables an analyst can correlate (keys match climate_data fields)
    AVAILABLE_VARIABLES = [
        {'key': 'temperature', 'label': 'Temperature (°C)'},
        {'key': 'rainfall', 'label': 'Rainfall (mm)'},
        {'key': 'humidity', 'label': 'Humidity (%)'},
        {'key': 'wind_speed', 'label': 'Wind Speed (km/h)'},
        {'key': 'pressure', 'label': 'Pressure (hPa)'},
        {'key': 'co2_level', 'label': 'CO₂ Level (ppm)'},
        {'key': 'air_quality_index', 'label': 'Air Quality Index'},
    ]

    @staticmethod
    def execute(variables, run_by, run_by_name):
        """Run a correlation analysis over the selected variables and persist
        the outcome (completed or failed). Returns the run document."""
        col = get_collection('correlation_runs')
        run_id = next_id('correlation_runs')
        valid_keys = {v['key'] for v in CorrelationRun.AVAILABLE_VARIABLES}
        selected = [v for v in variables if v in valid_keys]

        doc = {
            'id': run_id,
            'status': 'failed',
            'run_by': run_by,
            'run_by_name': run_by_name,
            'variables': selected,
            'total_records': 0,
            'significant_pairs': 0,
            'strongest_pair': None,
            'pairwise_correlations': [],
            'correlation_matrix': {},
            'method': 'Pearson correlation coefficient',
            'error': None,
            'created_at': datetime.utcnow().isoformat(),
        }

        try:
            if len(selected) < 2:
                raise ValueError('Select at least two variables to correlate.')

            from models.climate_model import ClimateData
            from ml_models.correlation_analysis import CorrelationAnalyzer

            raw = ClimateData.get_correlation_data(selected)
            if not raw:
                raise ValueError('No climate data available for correlation analysis.')

            # Row-aligned float lists: keeps only records where every selected
            # variable has a numeric value (string-typed uploads are coerced).
            data, aligned = ClimateData.align_correlation_rows(raw, selected)
            if len(data) < 2:
                raise ValueError('Not enough numeric records for the selected '
                                 'variables - check your climate data.')

            analyzer = CorrelationAnalyzer()
            analyzer.load_data(data)
            pairwise = analyzer.compute_pairwise_correlations()
            matrix = analyzer.compute_correlation_matrix()

            doc.update({
                'status': 'completed',
                'variables': list(data.keys()),
                'total_records': aligned,
                'significant_pairs': sum(1 for p in pairwise if p.get('significant')),
                'strongest_pair': {
                    'pair': f"{pairwise[0]['variable_1']} ↔ {pairwise[0]['variable_2']}",
                    'correlation': pairwise[0]['correlation'],
                } if pairwise else None,
                'pairwise_correlations': CorrelationRun._convert(pairwise),
                'correlation_matrix': CorrelationRun._convert(matrix or {}),
            })
        except Exception as e:
            doc['error'] = str(e)

        col.insert_one(doc)
        return doc

    @staticmethod
    def _convert(obj):
        """Make numpy types JSON/Mongo friendly."""
        if isinstance(obj, dict):
            return {k: CorrelationRun._convert(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [CorrelationRun._convert(v) for v in obj]
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return CorrelationRun._convert(obj.tolist())
        return obj

    @staticmethod
    def get_all(limit=20):
        return list(
            get_collection('correlation_runs').find().sort('created_at', -1).limit(limit)
        )

    @staticmethod
    def get_by_id(run_id):
        return get_collection('correlation_runs').find_one({'id': int(run_id)})

    @staticmethod
    def delete(run_id):
        get_collection('correlation_runs').delete_one({'id': int(run_id)})

    @staticmethod
    def get_latest_completed():
        return get_collection('correlation_runs').find_one(
            {'status': 'completed'}, sort=[('created_at', -1)]
        )

    @staticmethod
    def get_stats():
        col = get_collection('correlation_runs')
        return {
            'total': col.count_documents({}),
            'completed': col.count_documents({'status': 'completed'}),
            'failed': col.count_documents({'status': 'failed'}),
        }
