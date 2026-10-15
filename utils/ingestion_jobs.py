"""Background batch ingestion jobs."""

import json
import os
import threading
from datetime import datetime

import pandas as pd

from config import Config
from models.climate_model import ClimateData
from models.dataset_model import Dataset
from utils.database import get_collection
from utils.helper import generate_unique_filename


def submit_batch(dataset_name, category, records, uploaded_by=1):
    jobs = get_collection('ingestion_jobs')
    job_id = __import__('utils.database', fromlist=['next_id']).next_id('ingestion_jobs')
    jobs.insert_one({'id': job_id, 'status': 'queued', 'dataset_name': dataset_name,
                     'category': category, 'total_records': len(records),
                     'records_ingested': 0, 'error': None,
                     'created_at': datetime.utcnow().isoformat()})

    def worker():
        try:
            jobs.update_one({'id': job_id}, {'$set': {'status': 'running'}})
            category_dir = os.path.join(Config.DATASETS_FOLDER, category)
            os.makedirs(category_dir, exist_ok=True)
            filename = generate_unique_filename(dataset_name + '.csv')
            filepath = os.path.join(category_dir, filename)
            pd.DataFrame(records).to_csv(filepath, index=False)
            dataset_id = Dataset.create(
                name=dataset_name, description=f'Background API import: {len(records)} records',
                file_path=filepath, file_size=os.path.getsize(filepath), file_type='csv',
                category=category, source='api_batch_background', uploaded_by=uploaded_by,
            )
            ClimateData.insert_batch(records, dataset_id)
            Dataset.update(dataset_id, record_count=len(records), column_count=len(records[0]) if records else 0)
            jobs.update_one({'id': job_id}, {'$set': {
                'status': 'completed', 'dataset_id': dataset_id,
                'records_ingested': len(records),
                'completed_at': datetime.utcnow().isoformat(),
            }})
        except Exception as error:
            jobs.update_one({'id': job_id}, {'$set': {
                'status': 'failed', 'error': str(error),
                'completed_at': datetime.utcnow().isoformat(),
            }})

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    return job_id


def get_job(job_id):
    return get_collection('ingestion_jobs').find_one({'id': int(job_id)}, {'_id': 0})
