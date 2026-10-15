"""
Anomaly detection run store.
Analysts perform anomaly detection runs; every run is persisted so the Admin
panel can monitor results and processing status.
"""
from utils.database import get_collection, next_id
from datetime import datetime


class AnomalyRun:
    MIN_THRESHOLD = 0.5
    MAX_THRESHOLD = 5.0

    @staticmethod
    def execute(threshold, run_by, run_by_name):
        """Run Z-score anomaly detection at the given threshold and persist
        the outcome (completed or failed). Returns the run document."""
        col = get_collection('anomaly_runs')
        run_id = next_id('anomaly_runs')

        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            threshold = 2.0
        threshold = min(max(threshold, AnomalyRun.MIN_THRESHOLD), AnomalyRun.MAX_THRESHOLD)

        doc = {
            'id': run_id,
            'status': 'failed',
            'threshold': threshold,
            'records_scanned': 0,
            'anomalies_found': 0,
            'critical_count': 0,
            'anomalies': [],
            'method': 'Z-score deviation analysis (temperature & rainfall)',
            'run_by': run_by,
            'run_by_name': run_by_name,
            'error': None,
            'created_at': datetime.utcnow().isoformat(),
        }

        try:
            from models.climate_model import ClimateData

            doc['records_scanned'] = min(
                get_collection('climate_data').count_documents({}), 50000
            )
            if doc['records_scanned'] == 0:
                raise ValueError('No climate data available for anomaly detection.')

            anomalies = ClimateData.get_anomalies(threshold)
            # Strip Mongo _id so the run document stays JSON-friendly
            for a in anomalies:
                a.pop('_id', None)

            doc.update({
                'status': 'completed',
                'anomalies': anomalies,
                'anomalies_found': len(anomalies),
                'critical_count': sum(
                    1 for a in anomalies
                    if max(a.get('temp_z_score') or 0, a.get('rain_z_score') or 0) > 3
                ),
            })
        except Exception as e:
            doc['error'] = str(e)

        col.insert_one(doc)
        return doc

    @staticmethod
    def get_all(limit=20):
        return list(
            get_collection('anomaly_runs').find().sort('created_at', -1).limit(limit)
        )

    @staticmethod
    def get_latest_completed():
        return get_collection('anomaly_runs').find_one(
            {'status': 'completed'}, sort=[('created_at', -1)]
        )

    @staticmethod
    def get_by_id(run_id):
        return get_collection('anomaly_runs').find_one({'id': int(run_id)})

    @staticmethod
    def delete(run_id):
        get_collection('anomaly_runs').delete_one({'id': int(run_id)})

    @staticmethod
    def get_stats():
        col = get_collection('anomaly_runs')
        return {
            'total': col.count_documents({}),
            'completed': col.count_documents({'status': 'completed'}),
            'failed': col.count_documents({'status': 'failed'}),
        }
