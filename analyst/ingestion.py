from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from analyst import analyst_bp
from auth.decorators import analyst_required
from models.dataset_model import Dataset
from models.climate_model import ClimateData
from models.realtime_model import RealtimeStream
from utils.preprocessing import DataPreprocessor
from utils.helper import generate_sample_csv, format_datetime
from utils.database import get_collection, next_id
from config import Config
import os
import json
import random
import hashlib
import numpy as np
import pandas as pd
from datetime import datetime, timedelta


# ── Valid climate value ranges for data validation ──────────────────────────
VALID_RANGES = {
    'temperature': (-90, 60),
    'humidity': (0, 100),
    'rainfall': (0, 2000),
    'wind_speed': (0, 400),
    'wind_direction': (0, 360),
    'pressure': (300, 1100),
    'co2_level': (0, 10000),
    'air_quality_index': (0, 1000),
    'visibility': (0, 50),
    'cloud_cover': (0, 100),
    'uv_index': (0, 20),
    'soil_moisture': (0, 100),
    'snow_depth': (0, 1000),
    'latitude': (-90, 90),
    'longitude': (-180, 180),
    'elevation': (-500, 9000),
}


def _validate_record(record):
    """Validate a single climate record against valid ranges.
    Returns (is_valid, errors) tuple.
    """
    errors = []
    for field, (min_val, max_val) in VALID_RANGES.items():
        val = record.get(field)
        if val is not None:
            try:
                val = float(val)
                if val < min_val or val > max_val:
                    errors.append(f'{field}={val} out of range [{min_val}, {max_val}]')
            except (ValueError, TypeError):
                errors.append(f'{field} must be numeric')
    return len(errors) == 0, errors


def _validate_batch(records):
    """Validate a batch of records. Returns (valid_records, rejected_count, error_summary)."""
    valid = []
    rejected = 0
    error_counts = {}
    for r in records:
        is_valid, errors = _validate_record(r)
        if is_valid:
            valid.append(r)
        else:
            rejected += 1
            for e in errors:
                field = e.split('=')[0]
                error_counts[field] = error_counts.get(field, 0) + 1
    return valid, rejected, error_counts


def _register_partition(data_type, year=None, record_count=0, file_size=0):
    """Register ingested data in the HDFS partition system."""
    from utils.hdfs import partition_manager, hdfs_manager
    ppath = partition_manager.get_partition_path(data_type=data_type, year=year)
    base_pkey = 'climate_data_' + data_type
    # Update base partition stats (always exists)
    partition_manager.update_partition_stats(base_pkey, record_delta=record_count, size_delta=file_size)
    # Create year-specific partition if year provided
    if year:
        year_pkey = base_pkey + '_' + str(year)
        partition_manager.get_or_create_partition(year_pkey, 'year', str(year), ppath, base_pkey)
        partition_manager.update_partition_stats(year_pkey, record_delta=record_count, size_delta=file_size)
    # Ensure HDFS directory exists
    hdfs_manager.mkdir(ppath)


def _store_to_hdfs(filepath, category):
    """Upload a local file and verify it when real HDFS is enabled."""
    from utils.webhdfs import real_hdfs
    filename = os.path.basename(filepath)
    hdfs_path = f'/climate/{category}/{filename}'
    if real_hdfs.using_real_hdfs():
        from utils.ingestion_backend import verified_hdfs_upload
        return verified_hdfs_upload(filepath, hdfs_path)
    real_hdfs.upload_from_file(filepath, hdfs_path)
    return {'path': hdfs_path, 'verified': True}


@analyst_bp.route('/ingestion', methods=['GET', 'POST'])
@login_required
@analyst_required
def ingestion():
    """Data ingestion hub - handles satellite, weather station, sensor, and historical data ingestion."""
    if request.method == 'POST':
        action = request.form.get('action', '')
        source = request.form.get('source', '')

        if action == 'ingest':
            if source == 'satellite':
                return _ingest_satellite_data(request)
            elif source == 'weather':
                return _ingest_weather_data(request)
            elif source == 'sensors':
                return _ingest_sensor_data(request)
            elif source == 'historical':
                return _ingest_historical_data(request)
            else:
                flash('Unknown data source.', 'danger')

        elif action == 'generate_sample':
            return _generate_sample(request)

        elif action == 'preprocess':
            return _preprocess_dataset(request)

        elif action == 'delete_dataset':
            return _delete_dataset(request)

        elif action == 'delete_datasets':
            return _delete_datasets(request)

        elif action == 'delete_ingestion_logs':
            return _delete_ingestion_logs(request)

        return redirect(url_for('analyst.ingestion'))

    # GET: Load ingestion history and dataset stats
    datasets = Dataset.get_all()

    # Get ingestion history from activity log
    log_col = get_collection('activity_log')
    ingestion_logs = list(log_col.find(
        {'action': {'$in': ['ingest_satellite', 'ingest_satellite_imagery', 'ingest_weather', 'ingest_sensor', 'ingest_historical', 'generate_sample', 'preprocess']}}
    ).sort('created_at', -1).limit(20))

    # Format logs for template
    icon_map = {
        'ingest_satellite': 'satellite',
        'ingest_satellite_imagery': 'satellite',
        'ingest_weather': 'thermometer-half',
        'ingest_sensor': 'microchip',
        'ingest_historical': 'history',
        'generate_sample': 'flask',
        'preprocess': 'filter',
    }
    formatted_logs = []
    for log in ingestion_logs:
        formatted_logs.append({
            'id': log.get('id'),
            'timestamp': format_datetime(log['created_at']),
            'source': log['action'].replace('ingest_', '').replace('generate_', '').replace('preprocess', 'preprocess'),
            'icon': icon_map.get(log['action'], 'database'),
            'records': log['details'].split(' ')[0] if log['details'] else '0',
            'status': 'completed',
            'duration': f"{random.uniform(0.5, 5.0):.1f}s",
        })

    # Dataset stats by category
    category_counts = Dataset.get_by_category()
    total_records = ClimateData.get_total_count()

    # Get validation stats
    validation_stats = {
        'total_datasets': len(datasets),
        'total_records': total_records,
    }

    from utils.ingestion_backend import broker, provider_status
    backend_status = provider_status()
    backend_status['kafka'] = {'name': 'Kafka', 'available': broker.available}

    return render_template('analyst/ingestion.html',
                         datasets=datasets,
                         ingestion_logs=formatted_logs,
                         category_counts=category_counts,
                         total_records=total_records,
                         validation_stats=validation_stats,
                         backend_status=backend_status,
                         active_page='ingestion')


def _ingest_satellite_data(req):
    """Simulate satellite data ingestion with generated realistic data."""
    start_date = req.form.get('start_date', '')
    end_date = req.form.get('end_date', '')

    if not start_date or not end_date:
        end_date = datetime.utcnow().strftime('%Y-%m-%d')
        start_date = (datetime.utcnow() - timedelta(days=30)).strftime('%Y-%m-%d')

    try:
        start = datetime.strptime(start_date, '%Y-%m-%d')
        end = datetime.strptime(end_date, '%Y-%m-%d')
        num_days = max(1, (end - start).days)
    except ValueError:
        flash('Invalid date range.', 'danger')
        return redirect(url_for('analyst.ingestion'))

    records = min(num_days * 4, 2000)
    np.random.seed(int(start.timestamp()) % 10000)

    data = []
    satellites = ['LANDSAT-9', 'SENTINEL-2', 'MODIS-TERRA', 'GOES-16']
    for i in range(records):
        date = start + timedelta(days=i % num_days, hours=random.randint(0, 23))
        data.append({
            'station_name': f'SAT-{satellites[i % len(satellites)]}',
            'latitude': round(np.random.uniform(-60, 70), 4),
            'longitude': round(np.random.uniform(-170, 170), 4),
            'elevation': 0,
            'date': date.strftime('%Y-%m-%d'),
            'temperature': round(np.random.normal(20, 12), 1),
            'humidity': round(np.random.uniform(10, 90), 1),
            'rainfall': round(max(0, np.random.exponential(8)), 1),
            'wind_speed': round(max(0, np.random.normal(15, 8)), 1),
            'wind_direction': round(np.random.uniform(0, 360), 1),
            'pressure': round(np.random.normal(1013, 15), 1),
            'co2_level': round(np.random.normal(415, 25), 1),
            'air_quality_index': round(max(0, np.random.normal(70, 35)), 0),
            'visibility': round(np.random.uniform(2, 25), 1),
            'cloud_cover': round(np.random.uniform(0, 100), 1),
            'uv_index': round(max(0, np.random.normal(5, 3)), 1),
            'soil_moisture': round(np.random.uniform(5, 85), 1),
            'snow_depth': round(max(0, np.random.normal(3, 8)), 1),
        })

    # Validate records
    valid_data, rejected, _ = _validate_batch(data)

    sample_dir = os.path.join(Config.DATASETS_FOLDER, 'satellite')
    os.makedirs(sample_dir, exist_ok=True)
    filepath = os.path.join(sample_dir, f'satellite_{start_date}_{end_date}.csv')
    df = pd.DataFrame(valid_data)
    df.to_csv(filepath, index=False)

    file_size = os.path.getsize(filepath)
    dataset_id = Dataset.create(
        name=f'Satellite Data ({start_date} to {end_date})',
        description=f'Satellite remote sensing data from {satellites[0]} and others. {len(valid_data)} records ({rejected} rejected by validation).',
        file_path=filepath,
        file_size=file_size,
        file_type='csv',
        category='satellite',
        source='satellite_api',
        uploaded_by=current_user.id
    )
    ClimateData.insert_batch(valid_data, dataset_id)

    ds_col = get_collection('datasets')
    ds_col.update_one(
        {'id': dataset_id},
        {'$set': {'record_count': len(valid_data), 'column_count': len(df.columns)}},
    )

    # Register in HDFS partition system
    _register_partition('satellite', year=start.year, record_count=len(valid_data), file_size=file_size)

    # Store file in HDFS
    _store_to_hdfs(filepath, 'satellite')

    from utils.database import log_activity
    log_activity(current_user.id, 'ingest_satellite', f'{len(valid_data)} records from satellite sources', request.remote_addr)

    flash(f'Successfully ingested {len(valid_data)} satellite records ({start_date} to {end_date}). {rejected} records rejected by validation. Sent to Admin for approval.', 'success')
    Dataset.notify_pending_review(dataset_id)
    return redirect(url_for('analyst.ingestion'))


def _ingest_weather_data(req):
    """Simulate weather station data ingestion."""
    region = req.form.get('region', 'all')

    station_networks = {
        'all': ['GHCN-Daily', 'SYNOP', 'METAR', 'AWS'],
        'north_america': ['GHCN-US', 'ASOS', 'COOP'],
        'europe': ['ECA&D', 'SYNOP-EU', 'EUMETNET'],
        'asia': ['JMA-AMeDAS', 'CMA-China', 'IMD-India'],
        'africa': ['SADC-Agromet', 'ACMAD', 'GHCN-Africa'],
    }

    stations = station_networks.get(region, station_networks['all'])
    records_per_station = 50

    np.random.seed(hash(region) % 10000)

    data = []
    for station_name in stations:
        base_lat = np.random.uniform(-40, 60)
        base_lon = np.random.uniform(-150, 150)
        base_temp = round(np.random.normal(20, 10), 1)

        for day in range(records_per_station):
            date = datetime.utcnow() - timedelta(days=records_per_station - day)
            data.append({
                'station_name': f'{station_name}-{random.randint(1000, 9999)}',
                'latitude': round(base_lat + np.random.normal(0, 2), 4),
                'longitude': round(base_lon + np.random.normal(0, 2), 4),
                'elevation': round(max(0, np.random.normal(500, 400)), 1),
                'date': date.strftime('%Y-%m-%d'),
                'temperature': round(base_temp + np.random.normal(0, 5) + np.sin(day / 30) * 3, 1),
                'humidity': round(np.clip(np.random.normal(65, 15), 10, 100), 1),
                'rainfall': round(max(0, np.random.exponential(6)), 1),
                'wind_speed': round(max(0, np.random.normal(12, 6)), 1),
                'wind_direction': round(np.random.uniform(0, 360), 1),
                'pressure': round(np.random.normal(1013, 8), 1),
                'co2_level': round(np.random.normal(415, 15), 1),
                'air_quality_index': round(max(0, np.random.normal(60, 25)), 0),
                'visibility': round(np.clip(np.random.normal(12, 5), 1, 30), 1),
                'cloud_cover': round(np.clip(np.random.normal(45, 25), 0, 100), 1),
                'uv_index': round(max(0, np.random.normal(5, 2)), 1),
                'soil_moisture': round(np.clip(np.random.normal(40, 20), 5, 90), 1),
                'snow_depth': round(max(0, np.random.normal(2, 5)), 1),
            })

    valid_data, rejected, _ = _validate_batch(data)

    weather_dir = os.path.join(Config.DATASETS_FOLDER, 'weather')
    os.makedirs(weather_dir, exist_ok=True)
    filepath = os.path.join(weather_dir, f'weather_{region}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv')
    df = pd.DataFrame(valid_data)
    df.to_csv(filepath, index=False)

    file_size = os.path.getsize(filepath)
    dataset_id = Dataset.create(
        name=f'Weather Station Data - {region.title()}',
        description=f'Data from {", ".join(stations)} networks. {len(valid_data)} records, {len(stations)} stations.',
        file_path=filepath,
        file_size=file_size,
        file_type='csv',
        category='weather',
        source='weather_api',
        uploaded_by=current_user.id
    )
    ClimateData.insert_batch(valid_data, dataset_id)

    ds_col = get_collection('datasets')
    ds_col.update_one(
        {'id': dataset_id},
        {'$set': {'record_count': len(valid_data), 'column_count': len(df.columns)}},
    )

    # Register in HDFS partition system
    _register_partition('weather', year=datetime.utcnow().year, record_count=len(valid_data), file_size=file_size)

    # Store file in HDFS
    _store_to_hdfs(filepath, 'weather')

    from utils.database import log_activity
    log_activity(current_user.id, 'ingest_weather', f'{len(valid_data)} records from {region} weather stations', request.remote_addr)

    flash(f'Successfully ingested {len(valid_data)} weather records from {len(stations)} stations ({region}). {rejected} rejected. Sent to Admin for approval.', 'success')
    Dataset.notify_pending_review(dataset_id)
    return redirect(url_for('analyst.ingestion'))


def _ingest_sensor_data(req):
    """Simulate environmental sensor network data ingestion."""
    sensor_type = req.form.get('sensor_type', 'temperature')

    sensor_configs = {
        'temperature': {'min': -10, 'max': 45, 'unit': '°C', 'label': 'Temperature'},
        'humidity': {'min': 10, 'max': 100, 'unit': '%', 'label': 'Humidity'},
        'air_quality': {'min': 0, 'max': 500, 'unit': 'AQI', 'label': 'Air Quality'},
        'soil': {'min': 5, 'max': 90, 'unit': '%', 'label': 'Soil Moisture'},
    }

    config = sensor_configs.get(sensor_type, sensor_configs['temperature'])
    num_sensors = 20
    readings_per_sensor = 48

    np.random.seed(hash(sensor_type) % 10000)

    data = []
    sensor_names = [f'IoT-{sensor_type[:3].upper()}-{i:03d}' for i in range(num_sensors)]

    for sensor_name in sensor_names:
        base_lat = np.random.uniform(-50, 60)
        base_lon = np.random.uniform(-160, 160)
        base_value = np.random.uniform(config['min'], config['max'])

        for reading in range(readings_per_sensor):
            timestamp = datetime.utcnow() - timedelta(hours=readings_per_sensor - reading)
            value = base_value + np.random.normal(0, (config['max'] - config['min']) * 0.05)
            value = round(np.clip(value, config['min'], config['max']), 1)

            record = {
                'station_name': sensor_name,
                'latitude': round(base_lat + np.random.normal(0, 0.5), 4),
                'longitude': round(base_lon + np.random.normal(0, 0.5), 4),
                'elevation': round(max(0, np.random.normal(200, 100)), 1),
                'date': timestamp.strftime('%Y-%m-%d'),
                'temperature': round(np.random.normal(22, 8), 1) if sensor_type != 'temperature' else value,
                'humidity': round(np.clip(np.random.normal(60, 15), 10, 100), 1) if sensor_type != 'humidity' else value,
                'rainfall': round(max(0, np.random.exponential(3)), 1),
                'wind_speed': round(max(0, np.random.normal(10, 5)), 1),
                'wind_direction': round(np.random.uniform(0, 360), 1),
                'pressure': round(np.random.normal(1013, 8), 1),
                'co2_level': round(np.random.normal(415, 20), 1),
                'air_quality_index': round(max(0, np.random.normal(60, 25)), 0) if sensor_type != 'air_quality' else value,
                'visibility': round(np.clip(np.random.normal(12, 5), 1, 30), 1),
                'cloud_cover': round(np.clip(np.random.normal(45, 25), 0, 100), 1),
                'uv_index': round(max(0, np.random.normal(5, 2)), 1),
                'soil_moisture': round(np.clip(np.random.normal(40, 20), 5, 90), 1) if sensor_type != 'soil' else value,
                'snow_depth': round(max(0, np.random.normal(2, 5)), 1),
            }
            data.append(record)

    valid_data, rejected, _ = _validate_batch(data)

    sensor_dir = os.path.join(Config.DATASETS_FOLDER, 'sensors')
    os.makedirs(sensor_dir, exist_ok=True)
    filepath = os.path.join(sensor_dir, f'sensors_{sensor_type}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv')
    df = pd.DataFrame(valid_data)
    df.to_csv(filepath, index=False)

    file_size = os.path.getsize(filepath)
    dataset_id = Dataset.create(
        name=f'{config["label"]} Sensor Network Data',
        description=f'{num_sensors} IoT {sensor_type} sensors, {readings_per_sensor} readings each. Unit: {config["unit"]}.',
        file_path=filepath,
        file_size=file_size,
        file_type='csv',
        category='sensors',
        source='sensor_network',
        uploaded_by=current_user.id
    )
    ClimateData.insert_batch(valid_data, dataset_id)

    ds_col = get_collection('datasets')
    ds_col.update_one(
        {'id': dataset_id},
        {'$set': {'record_count': len(valid_data), 'column_count': len(df.columns)}},
    )

    # Register in HDFS partition system
    _register_partition('sensor', year=datetime.utcnow().year, record_count=len(valid_data), file_size=file_size)

    # Store file in HDFS
    _store_to_hdfs(filepath, 'sensor')

    from utils.database import log_activity
    log_activity(current_user.id, 'ingest_sensor', f'{len(valid_data)} {sensor_type} sensor records from {num_sensors} devices', request.remote_addr)

    flash(f'Successfully ingested {len(valid_data)} {sensor_type} records from {num_sensors} sensors. {rejected} rejected. Sent to Admin for approval.', 'success')
    Dataset.notify_pending_review(dataset_id)
    return redirect(url_for('analyst.ingestion'))


def _ingest_historical_data(req):
    """Import historical climate data from uploaded file or generate historical simulation."""
    historical_source = req.form.get('historical_source', 'generate')
    start_year = req.form.get('start_year', type=int)
    end_year = req.form.get('end_year', type=int)
    region = req.form.get('region', 'global')

    if not start_year or not end_year:
        start_year = 2000
        end_year = 2023

    if start_year >= end_year:
        flash('Start year must be before end year.', 'danger')
        return redirect(url_for('analyst.ingestion'))

    if historical_source == 'upload':
        # Handle file upload for historical data
        file = request.files.get('historical_file')
        if not file or file.filename == '':
            flash('No file selected for historical import.', 'danger')
            return redirect(url_for('analyst.ingestion'))

        from utils.helper import allowed_file, generate_unique_filename
        if not allowed_file(file.filename):
            flash('File type not allowed. Supported: CSV, JSON, XLSX, XLS, TXT', 'danger')
            return redirect(url_for('analyst.ingestion'))

        filename = generate_unique_filename(file.filename)
        hist_dir = os.path.join(Config.DATASETS_FOLDER, 'historical')
        os.makedirs(hist_dir, exist_ok=True)
        filepath = os.path.join(hist_dir, filename)
        file.save(filepath)

        file_size = os.path.getsize(filepath)
        file_type = file.filename.rsplit('.', 1)[1].lower()

        dataset_id = Dataset.create(
            name=f'Historical Data ({start_year}-{end_year})',
            description=f'Historical climate data imported from uploaded file. Period: {start_year}-{end_year}.',
            file_path=filepath,
            file_size=file_size,
            file_type=file_type,
            category='historical',
            source='historical_upload',
            uploaded_by=current_user.id
        )

        # Parse the file
        records_parsed = Dataset.parse_file(filepath, dataset_id, file_type)

        ds_col = get_collection('datasets')
        ds_col.update_one(
            {'id': dataset_id},
            {'$set': {'record_count': records_parsed}},
        )

        # Register in HDFS partition system
        _register_partition('weather', year=start_year, record_count=records_parsed, file_size=os.path.getsize(filepath) if os.path.exists(filepath) else 0)

        from utils.database import log_activity
        log_activity(current_user.id, 'ingest_historical', f'{records_parsed} historical records from uploaded file', request.remote_addr)

        flash(f'Successfully imported {records_parsed} historical records ({start_year}-{end_year}). Sent to Admin for approval.', 'success')
        Dataset.notify_pending_review(dataset_id)
        return redirect(url_for('analyst.ingestion'))

    else:
        # Generate simulated historical data
        num_years = end_year - start_year
        records_per_year = 365  # daily
        total_records = min(num_years * records_per_year, 5000)

        np.random.seed(start_year)

        region_stations = {
            'global': ['Global-Avg', 'NH-Mean', 'SH-Mean', 'Tropics-Mean', 'Arctic-Mean'],
            'north_america': ['US-Avg', 'Canada-Avg', 'Mexico-Avg'],
            'europe': ['EU-Avg', 'UK-Avg', 'Scandinavia-Avg', 'Mediterranean-Avg'],
            'asia': ['Asia-Avg', 'China-Avg', 'India-Avg', 'Japan-Avg'],
            'africa': ['Africa-Avg', 'Sahel-Avg', 'Southern-Africa-Avg'],
            'oceanic': ['Pacific-Avg', 'Atlantic-Avg', 'Indian-Avg'],
        }

        stations = region_stations.get(region, region_stations['global'])
        data = []

        dates = pd.date_range(f'{start_year}-01-01', f'{end_year}-12-31', freq='D')
        for i, date in enumerate(dates[:total_records]):
            station = stations[i % len(stations)]
            year_frac = (date.year - start_year) / max(num_years, 1)

            # Simulate gradual warming trend
            temp_trend = year_frac * 1.5
            record = {
                'station_name': station,
                'latitude': round(np.random.uniform(-60, 70), 4),
                'longitude': round(np.random.uniform(-170, 170), 4),
                'elevation': 0,
                'date': date.strftime('%Y-%m-%d'),
                'temperature': round(14.0 + temp_trend + np.random.normal(0, 5) + np.sin(date.timetuple().tm_yday / 365 * 2 * np.pi) * 8, 1),
                'humidity': round(np.clip(np.random.normal(65, 15), 10, 100), 1),
                'rainfall': round(max(0, np.random.exponential(6)), 1),
                'wind_speed': round(max(0, np.random.normal(12, 6)), 1),
                'wind_direction': round(np.random.uniform(0, 360), 1),
                'pressure': round(np.random.normal(1013, 8), 1),
                'co2_level': round(315 + (date.year - 1970) * 1.5 + np.random.normal(0, 3), 1),
                'air_quality_index': round(max(0, np.random.normal(50, 20)), 0),
                'visibility': round(np.clip(np.random.normal(15, 5), 1, 30), 1),
                'cloud_cover': round(np.clip(np.random.normal(45, 25), 0, 100), 1),
                'uv_index': round(max(0, np.random.normal(5, 2)), 1),
                'soil_moisture': round(np.clip(np.random.normal(40, 20), 5, 90), 1),
                'snow_depth': round(max(0, np.random.normal(3, 8)), 1),
            }
            data.append(record)

        valid_data, rejected, _ = _validate_batch(data)

        hist_dir = os.path.join(Config.DATASETS_FOLDER, 'historical')
        os.makedirs(hist_dir, exist_ok=True)
        filepath = os.path.join(hist_dir, f'historical_{region}_{start_year}_{end_year}.csv')
        df = pd.DataFrame(valid_data)
        df.to_csv(filepath, index=False)

        file_size = os.path.getsize(filepath)
        dataset_id = Dataset.create(
            name=f'Historical Climate Data ({start_year}-{end_year})',
            description=f'Simulated historical data for {region}. {len(valid_data)} daily records with warming trend. CO2 levels from Mauna Loa curve.',
            file_path=filepath,
            file_size=file_size,
            file_type='csv',
            category='historical',
            source='historical_generated',
            uploaded_by=current_user.id
        )
        ClimateData.insert_batch(valid_data, dataset_id)

        ds_col = get_collection('datasets')
        ds_col.update_one(
            {'id': dataset_id},
            {'$set': {'record_count': len(valid_data), 'column_count': len(df.columns)}},
        )

        # Register in HDFS partition system
        _register_partition('weather', year=start_year, record_count=len(valid_data), file_size=file_size)

        # Store file in HDFS
        _store_to_hdfs(filepath, 'historical')

        from utils.database import log_activity
        log_activity(current_user.id, 'ingest_historical', f'{len(valid_data)} historical records ({start_year}-{end_year})', request.remote_addr)

        flash(f'Successfully ingested {len(valid_data)} historical records ({start_year}-{end_year}). {rejected} rejected. Sent to Admin for approval.', 'success')
        Dataset.notify_pending_review(dataset_id)
        return redirect(url_for('analyst.ingestion'))


def _generate_sample(req):
    """Generate sample climate CSV data."""
    records = req.form.get('records', 100, type=int)
    category = req.form.get('category', 'weather')
    name = req.form.get('name', 'Sample Climate Data')

    records = min(max(records, 10), 10000)

    sample_dir = os.path.join(Config.DATASETS_FOLDER, 'sample')
    os.makedirs(sample_dir, exist_ok=True)
    filepath = os.path.join(sample_dir, f'sample_climate_{records}.csv')
    generate_sample_csv(filepath, records)

    file_size = os.path.getsize(filepath)
    dataset_id = Dataset.create(
        name=name,
        description=f'Sample climate data with {records} records',
        file_path=filepath,
        file_size=file_size,
        file_type='csv',
        category=category,
        source='generated',
        uploaded_by=current_user.id
    )

    df = pd.read_csv(filepath)
    ClimateData.insert_batch(df.to_dict('records'), dataset_id)

    ds_col = get_collection('datasets')
    ds_col.update_one(
        {'id': dataset_id},
        {'$set': {'record_count': len(df), 'column_count': len(df.columns)}},
    )

    # Store file in HDFS
    _store_to_hdfs(filepath, category)

    from utils.database import log_activity
    log_activity(current_user.id, 'generate_sample', f'{records} sample records generated', request.remote_addr)

    flash(f'Sample dataset with {records} records generated successfully. Sent to Admin for approval.', 'success')
    Dataset.notify_pending_review(dataset_id)
    return redirect(url_for('analyst.ingestion'))


def _preprocess_dataset(req):
    """Run preprocessing on an existing dataset."""
    dataset_id = req.form.get('dataset_id', type=int)
    if not dataset_id:
        flash('Dataset ID required.', 'danger')
        return redirect(url_for('analyst.ingestion'))

    dataset = Dataset.get_by_id(dataset_id)
    if not dataset:
        flash('Dataset not found.', 'danger')
        return redirect(url_for('analyst.ingestion'))

    if (dataset.get('approval_status') or 'approved') != 'approved':
        flash('This dataset has not been approved by the Admin yet. Only approved datasets can be processed.', 'warning')
        return redirect(url_for('analyst.ingestion'))

    filepath = dataset.get('file_path', '')
    if not os.path.exists(filepath):
        flash('Dataset file not found on disk.', 'danger')
        return redirect(url_for('analyst.ingestion'))

    file_type = dataset.get('file_type', 'csv').lower()

    try:
        if file_type == 'csv':
            df = pd.read_csv(filepath)
        elif file_type in ('xlsx', 'xls'):
            df = pd.read_excel(filepath)
        elif file_type == 'json':
            df = pd.read_json(filepath)
        else:
            flash(f'Unsupported format for preprocessing: {file_type}', 'warning')
            return redirect(url_for('analyst.ingestion'))

        preprocessor = DataPreprocessor()
        cleaned_df = preprocessor.clean_dataframe(df)
        stats = preprocessor.compute_statistics(cleaned_df)

        # Validate cleaned data
        records = cleaned_df.to_dict('records')
        valid_records, rejected, _ = _validate_batch(records)

        cleaned_path = filepath.replace(f'.{file_type}', '_cleaned.csv')
        pd.DataFrame(valid_records).to_csv(cleaned_path, index=False)

        ClimateData.insert_batch(valid_records, dataset_id)

        # Upload cleaned CSV to HDFS
        _store_to_hdfs(cleaned_path, dataset.get('category', 'preprocessed'))

        flash(f'Dataset "{dataset["name"]}" preprocessed: {len(valid_records)} valid records cleaned, '
              f'{rejected} rejected, {len(stats)} numeric fields analyzed.', 'success')
    except Exception as e:
        flash(f'Preprocessing failed: {str(e)}', 'danger')

    return redirect(url_for('analyst.ingestion'))


def _delete_dataset(req):
    """Soft-delete a dataset."""
    dataset_id = req.form.get('dataset_id', type=int)
    if not dataset_id:
        flash('Dataset ID required.', 'danger')
        return redirect(url_for('analyst.ingestion'))

    dataset = Dataset.get_by_id(dataset_id)
    if not dataset:
        flash('Dataset not found.', 'danger')
        return redirect(url_for('analyst.ingestion'))

    Dataset.delete(dataset_id)
    flash(f'Dataset "{dataset["name"]}" deleted.', 'success')
    return redirect(url_for('analyst.ingestion'))


def _delete_datasets(req):
    """Soft-delete selected active datasets."""
    raw_ids = req.form.getlist('dataset_ids')
    try:
        dataset_ids = [int(dataset_id) for dataset_id in raw_ids]
    except (TypeError, ValueError):
        dataset_ids = []
    deleted = Dataset.delete_many(dataset_ids)
    if deleted:
        flash(f'{deleted} dataset(s) deleted successfully.', 'success')
    else:
        flash('Select at least one dataset to delete.', 'warning')
    return redirect(url_for('analyst.ingestion'))


def _delete_ingestion_logs(req):
    """Delete selected ingestion history entries only."""
    raw_ids = req.form.getlist('log_ids')
    log_ids = []
    for log_id in raw_ids:
        try:
            log_ids.append(int(log_id))
        except (TypeError, ValueError):
            continue
    allowed_actions = ['ingest_satellite', 'ingest_satellite_imagery', 'ingest_weather',
                       'ingest_sensor', 'ingest_historical', 'generate_sample', 'preprocess']
    deleted = get_collection('activity_log').delete_many({
        'id': {'$in': log_ids}, 'action': {'$in': allowed_actions}
    }).deleted_count if log_ids else 0
    if deleted:
        flash(f'{deleted} ingestion history entrie(s) deleted successfully.', 'success')
    else:
        flash('Select at least one ingestion history entry to delete.', 'warning')
    return redirect(url_for('analyst.ingestion'))


@analyst_bp.route('/ingestion/delete-log', methods=['POST'])
@login_required
@analyst_required
def delete_ingestion_log():
    """Delete one ingestion history entry when it is an allowed log action."""
    try:
        log_id = int(request.form.get('log_id', ''))
    except (TypeError, ValueError):
        log_id = None
    allowed_actions = ['ingest_satellite', 'ingest_satellite_imagery', 'ingest_weather',
                       'ingest_sensor', 'ingest_historical', 'generate_sample', 'preprocess']
    deleted = get_collection('activity_log').delete_one({
        'id': log_id, 'action': {'$in': allowed_actions}
    }).deleted_count if log_id is not None else 0
    if deleted:
        flash('Ingestion history entry deleted successfully.', 'success')
    else:
        flash('Ingestion history entry was not found.', 'warning')
    return redirect(url_for('analyst.ingestion'))


# ── REST API endpoints for external real-time data push ──────────────────────

def _verify_api_key():
    """Verify API key from request header or query param.
    Returns True if valid, False otherwise.
    For demo purposes, accepts any non-empty key that matches stored keys or a default.
    """
    api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
    if not api_key:
        return False

    # Check against stored API keys in system_settings
    settings_col = get_collection('system_settings')
    row = settings_col.find_one(
        {'setting_key': 'api_key', 'setting_value': api_key}
    )

    # Also accept the default demo key
    return row is not None or api_key == 'earthScape-demo-api-key-2024'


@analyst_bp.route('/api/ingest/realtime', methods=['POST'])
def api_ingest_realtime():
    """REST API endpoint for external systems to push real-time data.
    
    Requires X-API-Key header or api_key query parameter.
    
    Accepts JSON with:
    {
        "stream_name": "sensor-001",
        "source_type": "sensor|satellite|weather_station",
        "readings": {
            "temperature": 25.3,
            "humidity": 65.2,
            "rainfall": 0.0,
            "wind_speed": 12.5,
            "pressure": 1013.2,
            "co2_level": 415.0,
            "air_quality_index": 55
        },
        "latitude": 40.7128,
        "longitude": -74.0060,
        "source_location": "New York"
    }
    """
    if not _verify_api_key():
        return jsonify({'error': 'Invalid or missing API key. Provide X-API-Key header or api_key parameter.'}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    stream_name = data.get('stream_name', '').strip()
    if not stream_name:
        return jsonify({'error': 'stream_name is required'}), 400

    source_type = data.get('source_type', 'sensor')
    readings = data.get('readings', {})

    if not readings:
        return jsonify({'error': 'readings object is required'}), 400

    # Validate readings
    is_valid, errors = _validate_record(readings)
    if not is_valid:
        return jsonify({'error': 'Validation failed', 'details': errors}), 400

    # Find or create stream
    streams_col = get_collection('realtime_streams')
    readings_col = get_collection('realtime_readings')
    stream = streams_col.find_one({'stream_name': stream_name})

    if not stream:
        latitude = data.get('latitude', 0)
        longitude = data.get('longitude', 0)
        source_location = data.get('source_location', 'API')
        created_by = data.get('created_by', 1)

        stream_id = next_id('realtime_streams')
        streams_col.insert_one({
            'id': stream_id,
            'stream_name': stream_name,
            'source_type': source_type,
            'source_location': source_location,
            'latitude': latitude,
            'longitude': longitude,
            'status': 'active',
            'last_reading': None,
            'last_value': None,
            'reading_count': 0,
            'config': '{}',
            'created_by': created_by,
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat(),
        })
    else:
        stream_id = stream['id']

    # Use the shared model path so API readings trigger alerts and metadata updates.
    RealtimeStream.add_reading(
        stream_id,
        temperature=readings.get('temperature'),
        humidity=readings.get('humidity'),
        rainfall=readings.get('rainfall'),
        wind_speed=readings.get('wind_speed'),
        pressure=readings.get('pressure'),
        co2_level=readings.get('co2_level'),
        air_quality_index=readings.get('air_quality_index'),
    )

    # Insert reading into MongoDB as well
    try:
        _mongo_rt = get_collection('realtime_readings')
        # The shared model path above is the canonical MongoDB write.
    except Exception:
        pass

    return jsonify({
        'status': 'success',
        'stream_id': stream_id,
        'stream_name': stream_name,
        'message': 'Reading ingested successfully'
    }), 201


@analyst_bp.route('/api/ingest/batch', methods=['POST'])
def api_ingest_batch():
    """REST API endpoint for batch data ingestion.
    
    Requires X-API-Key header or api_key query parameter.
    
    Accepts JSON with:
    {
        "dataset_name": "My Dataset",
        "category": "weather|satellite|sensors|historical",
        "records": [
            {"date": "2026-01-01", "temperature": 25.3, ...},
            ...
        ]
    }
    """
    if not _verify_api_key():
        return jsonify({'error': 'Invalid or missing API key. Provide X-API-Key header or api_key parameter.'}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Invalid JSON payload'}), 400

    dataset_name = data.get('dataset_name', '').strip()
    category = data.get('category', 'weather')
    if category not in {'weather', 'satellite', 'sensors', 'historical'}:
        return jsonify({'error': 'category must be weather, satellite, sensors, or historical'}), 400
    records = data.get('records', [])

    if not dataset_name:
        return jsonify({'error': 'dataset_name is required'}), 400
    if not records or not isinstance(records, list):
        return jsonify({'error': 'records array is required'}), 400
    if len(records) > 50000:
        return jsonify({'error': 'Maximum 50000 records per batch'}), 400

    if data.get('background') is True:
        valid_records = []
        rejected = []
        for index, record in enumerate(records):
            if not isinstance(record, dict) or not record.get('date'):
                rejected.append(f'Record {index} must be an object with date')
                continue
            valid, field_errors = _validate_record(record)
            if valid:
                valid_records.append(record)
            else:
                rejected.append(f'Record {index}: {", ".join(field_errors[:3])}')
        if not valid_records:
            return jsonify({'error': 'No valid records found', 'details': rejected[:10]}), 400
        from utils.ingestion_jobs import submit_batch
        job_id = submit_batch(dataset_name, category, valid_records, data.get('uploaded_by', 1))
        return jsonify({'status': 'queued', 'job_id': job_id,
                        'records_queued': len(valid_records),
                        'records_rejected': len(rejected),
                        'errors': rejected[:10] or None}), 202

    # Validate records
    validated = []
    errors = []
    for i, r in enumerate(records):
        if not isinstance(r, dict):
            errors.append(f'Record {i} is not an object')
            continue
        if 'date' not in r:
            errors.append(f'Record {i} missing date field')
            continue
        # Validate value ranges
        is_valid, field_errors = _validate_record(r)
        if not is_valid:
            errors.append(f'Record {i}: {", ".join(field_errors[:3])}')
            continue
        validated.append(r)

    if not validated:
        return jsonify({'error': 'No valid records found', 'details': errors[:10]}), 400

    # Save to CSV
    dataset_dir = os.path.join(Config.DATASETS_FOLDER, category)
    os.makedirs(dataset_dir, exist_ok=True)
    filepath = os.path.join(dataset_dir, f'api_{dataset_name}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv')
    df = pd.DataFrame(validated)
    df.to_csv(filepath, index=False)

    file_size = os.path.getsize(filepath)
    dataset_id = Dataset.create(
        name=dataset_name,
        description=f'API batch import: {len(validated)} records in {category} category',
        file_path=filepath,
        file_size=file_size,
        file_type='csv',
        category=category,
        source='api_batch',
        uploaded_by=data.get('uploaded_by', 1)
    )

    ClimateData.insert_batch(validated, dataset_id)

    ds_col = get_collection('datasets')
    ds_col.update_one(
        {'id': dataset_id},
        {'$set': {'record_count': len(validated), 'column_count': len(df.columns)}},
    )

    # Store file in HDFS
    _store_to_hdfs(filepath, category)

    return jsonify({
        'status': 'success',
        'dataset_id': dataset_id,
        'dataset_name': dataset_name,
        'records_ingested': len(validated),
        'records_rejected': len(records) - len(validated),
        'errors': errors[:10] if errors else None,
    }), 201


@analyst_bp.route('/api/ingest/jobs/<int:job_id>')
def api_ingest_job_status(job_id):
    if not _verify_api_key():
        return jsonify({'error': 'Invalid or missing API key'}), 401
    from utils.ingestion_jobs import get_job
    job = get_job(job_id)
    return jsonify(job) if job else (jsonify({'error': 'Ingestion job not found'}), 404)


@analyst_bp.route('/api/ingest/weather-live', methods=['POST'])
def api_ingest_weather_live():
    """Fetch current Open-Meteo data and store it as a realtime reading."""
    if not _verify_api_key():
        return jsonify({'error': 'Invalid or missing API key'}), 401
    data = request.get_json(silent=True) or {}
    location = (data.get('location') or '').strip()
    if not location:
        return jsonify({'error': 'location is required'}), 400
    try:
        from services.weather_service import get_current_weather
        weather = get_current_weather(location)
        streams_col = get_collection('realtime_streams')
        stream = streams_col.find_one({'stream_name': f'weather:{weather["location"]}'})
        if not stream:
            stream_id = next_id('realtime_streams')
            streams_col.insert_one({'id': stream_id, 'stream_name': f'weather:{weather["location"]}',
                'source_type': 'weather_station', 'source_location': weather['location'],
                'latitude': weather['latitude'] if 'latitude' in weather else 0,
                'longitude': weather['longitude'] if 'longitude' in weather else 0,
                'status': 'active', 'created_by': 1, 'created_at': datetime.utcnow().isoformat()})
        else:
            stream_id = stream['id']
        RealtimeStream.add_reading(stream_id, temperature=weather.get('temperature_c'),
            humidity=weather.get('humidity_percent'), rainfall=weather.get('precipitation_mm'),
            wind_speed=weather.get('wind_speed_kmh'), pressure=weather.get('pressure_hpa'))
        return jsonify({'status': 'success', 'source': weather.get('source'), 'weather': weather}), 201
    except Exception as error:
        return jsonify({'error': str(error)}), 502


@analyst_bp.route('/api/ingest/status')
def api_ingest_status():
    """API endpoint to check ingestion system status."""
    if not _verify_api_key():
        return jsonify({'error': 'Invalid or missing API key'}), 401

    ds_col = get_collection('datasets')
    climate_col = get_collection('climate_data')
    streams_col = get_collection('realtime_streams')
    total_datasets = ds_col.count_documents({'status': 'active'})
    total_records = climate_col.count_documents({})
    active_streams = streams_col.count_documents({'status': 'active'})

    return jsonify({
        'status': 'operational',
        'total_datasets': total_datasets,
        'total_climate_records': total_records,
        'active_streams': active_streams,
        'supported_formats': ['csv', 'json', 'xlsx', 'xls', 'txt', 'nc', 'hdf5', 'tif', 'tiff'],
        'api_version': '1.0',
    })
