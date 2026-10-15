"""
One-time sample data seeder for EarthScape Climate.

Run ONCE while MongoDB is running:
    python seed_sample_data.py

It creates ONE approved sample dataset ("Sample Climate Data - Demo")
with ~224 daily records (2026-01-01 .. 2026-08-12) across 3 stations,
inserted through the exact same models the web app uses
(Dataset.create + ClimateData.insert_batch), so every chart
(analytics, forecast, dashboard, correlation) shows data immediately.
"""
import os
import numpy as np
import pandas as pd

from config import Config
from models.dataset_model import Dataset
from models.climate_model import ClimateData
from utils.database import get_collection

DATASET_NAME = 'Sample Climate Data - Demo'


def _find_uploader_id():
    """Prefer the analyst demo user, fall back to any user, else id 1."""
    users = get_collection('users')
    for query in ({'username': 'analyst'}, {'username': 'admin'}, {}):
        u = users.find_one(query)
        if u:
            return u.get('id', 1)
    return 1


def build_records():
    np.random.seed(2026)
    dates = pd.date_range('2026-01-01', '2026-08-12', freq='D')
    stations = [
        ('Station_Alpha', 12.97, 77.59, 920.0),
        ('Station_Beta', 19.07, 72.87, 14.0),
        ('Station_Gamma', 28.61, 77.20, 216.0),
    ]
    records = []
    for i, date in enumerate(dates):
        name, lat, lon, elev = stations[i % len(stations)]
        day_of_year = date.timetuple().tm_yday
        # Gentle seasonal curve: cooler in Jan, warmer mid-year
        seasonal = 6.0 * np.sin((day_of_year - 20) / 365.0 * 2 * np.pi)
        records.append({
            'station_name': name,
            'latitude': lat,
            'longitude': lon,
            'elevation': elev,
            'date': date.strftime('%Y-%m-%d'),
            'temperature': round(float(np.random.normal(24 + seasonal, 3)), 1),
            'humidity': round(float(np.clip(np.random.normal(62, 12), 25, 98)), 1),
            'rainfall': round(float(max(0, np.random.exponential(8))), 1),
            'wind_speed': round(float(max(0, np.random.normal(14, 6))), 1),
            'wind_direction': round(float(np.random.uniform(0, 360)), 1),
            'pressure': round(float(np.random.normal(1013, 8)), 1),
            'co2_level': round(float(np.random.normal(418, 12)), 1),
            'air_quality_index': round(float(max(5, np.random.normal(72, 22))), 0),
            'visibility': round(float(np.random.uniform(4, 20)), 1),
            'cloud_cover': round(float(np.random.uniform(0, 100)), 1),
            'uv_index': round(float(max(0, np.random.normal(6, 2))), 1),
            'soil_moisture': round(float(np.random.uniform(15, 75)), 1),
            'snow_depth': 0.0,
        })
    return records


def main():
    # Idempotency: do not duplicate the sample dataset on re-runs
    existing = get_collection('datasets').find_one(
        {'name': DATASET_NAME, 'status': 'active'})
    if existing:
        print('Sample dataset already exists (id {}). Nothing to do.'.format(existing.get('id')))
        return

    records = build_records()
    df = pd.DataFrame(records)

    # Persist the CSV alongside other generated datasets
    sample_dir = os.path.join(Config.DATASETS_FOLDER, 'sample')
    os.makedirs(sample_dir, exist_ok=True)
    filepath = os.path.join(sample_dir, 'sample_climate_demo.csv')
    df.to_csv(filepath, index=False)

    dataset_id = Dataset.create(
        name=DATASET_NAME,
        description='Demo sample data: {} daily records, 3 stations, Jan-Aug 2026.'.format(len(records)),
        file_path=filepath,
        file_size=os.path.getsize(filepath),
        file_type='csv',
        category='weather',
        source='generated',
        uploaded_by=_find_uploader_id(),
    )

    ClimateData.insert_batch(records, dataset_id)

    # Finalize counts and mark approved so it shows as a ready dataset
    Dataset.update(
        dataset_id,
        record_count=len(records),
        column_count=len(df.columns),
        approval_status='approved',
        reviewed_by=1,
    )

    total = ClimateData.get_total_count()
    print('Sample dataset created: id {}, {} records.'.format(dataset_id, len(records)))
    print('CSV file saved at: {}'.format(filepath))
    print('climate_data collection now holds {} total records.'.format(total))
    print('Restart/refresh the app pages - charts will show the data.')


if __name__ == '__main__':
    main()
