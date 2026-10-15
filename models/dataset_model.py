from utils.database import get_collection, next_id
from utils.helper import get_cached_value
from datetime import datetime
import json
import os
import pandas as pd
import numpy as np


class Dataset:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    @staticmethod
    def get_all(category=None, status='active', approval_status=None, search=None, limit=100):
        col = get_collection('datasets')
        query = {'status': status}
        if category:
            query['category'] = category
        if approval_status:
            if approval_status == 'approved':
                # Legacy datasets without an approval_status are treated as approved
                query['$or'] = [{'approval_status': 'approved'}, {'approval_status': {'$exists': False}}]
            else:
                query['approval_status'] = approval_status
        if search:
            query['name'] = {'$regex': search, '$options': 'i'}
        return list(col.find(query).sort('created_at', -1).limit(limit))

    @staticmethod
    def get_approved(category=None, limit=100):
        """Datasets available to analysts for processing (approved only)."""
        return Dataset.get_all(category=category, approval_status='approved', limit=limit)

    @staticmethod
    def get_for_owner(owner_id, limit=100):
        """Return active datasets uploaded by one analyst."""
        return list(get_collection('datasets').find({
            'status': 'active',
            'uploaded_by': owner_id,
        }).sort('created_at', -1).limit(limit))

    @staticmethod
    def get_owned_by_id(dataset_id, owner_id):
        """Return a dataset only when it belongs to the requesting analyst."""
        return get_collection('datasets').find_one({
            'id': int(dataset_id),
            'status': 'active',
            'uploaded_by': owner_id,
        })

    @staticmethod
    def get_by_id(dataset_id):
        return get_collection('datasets').find_one({'id': int(dataset_id)})

    @staticmethod
    def create(name, description, file_path, file_size, file_type, category,
               source, uploaded_by, hdfs_path='', record_count=0, column_count=0,
               columns_info='[]', tags='[]'):
        col = get_collection('datasets')
        ds_id = next_id('datasets')
        now = datetime.utcnow().isoformat()
        col.insert_one({
            'id': ds_id,
            'name': name,
            'description': description,
            'file_path': file_path,
            'file_size': file_size,
            'file_type': file_type,
            'category': category,
            'source': source,
            'uploaded_by': uploaded_by,
            'hdfs_path': hdfs_path,
            'record_count': record_count,
            'column_count': column_count,
            'columns_info': columns_info,
            'tags': tags,
            'status': 'active',
            'approval_status': 'pending',
            'reviewed_by': None,
            'reviewed_at': None,
            'rejection_reason': '',
            'is_public': 1,
            'created_at': now,
            'updated_at': now,
        })
        return ds_id

    @staticmethod
    def update(dataset_id, **kwargs):
        allowed = ['name', 'description', 'category', 'status', 'hdfs_path', 'tags',
                    'is_public', 'record_count', 'column_count', 'columns_info',
                    'approval_status', 'reviewed_by', 'reviewed_at', 'rejection_reason',
                    'file_path', 'file_size', 'file_type', 'source']
        updates = {}
        for key, value in kwargs.items():
            if key in allowed:
                updates[key] = value
        if updates:
            updates['updated_at'] = datetime.utcnow().isoformat()
            get_collection('datasets').update_one(
                {'id': int(dataset_id)}, {'$set': updates}
            )

    @staticmethod
    def delete(dataset_id):
        dataset_id = int(dataset_id)
        result = get_collection('datasets').update_one(
            {'id': dataset_id, 'status': 'active'},
            {'$set': {'status': 'deleted', 'updated_at': datetime.utcnow().isoformat()}}
        )
        if result.modified_count:
            get_collection('climate_data').delete_many({'dataset_id': dataset_id})
        return result.modified_count

    @staticmethod
    def delete_many(dataset_ids):
        """Soft-delete selected active datasets and return the count."""
        ids = []
        for dataset_id in dataset_ids:
            try:
                ids.append(int(dataset_id))
            except (TypeError, ValueError):
                continue
        if not ids:
            return 0
        result = get_collection('datasets').update_many(
            {'id': {'$in': ids}, 'status': 'active'},
            {'$set': {'status': 'deleted', 'updated_at': datetime.utcnow().isoformat()}}
        )
        if result.modified_count:
            get_collection('climate_data').delete_many({'dataset_id': {'$in': ids}})
        return result.modified_count

    # ── Approval workflow ────────────────────────────────────────────────

    @staticmethod
    def approve(dataset_id, reviewer_id):
        get_collection('datasets').update_one(
            {'id': int(dataset_id)},
            {'$set': {
                'approval_status': 'approved',
                'reviewed_by': reviewer_id,
                'reviewed_at': datetime.utcnow().isoformat(),
                'rejection_reason': '',
                'updated_at': datetime.utcnow().isoformat(),
            }}
        )

    @staticmethod
    def reject(dataset_id, reviewer_id, reason=''):
        get_collection('datasets').update_one(
            {'id': int(dataset_id)},
            {'$set': {
                'approval_status': 'rejected',
                'reviewed_by': reviewer_id,
                'reviewed_at': datetime.utcnow().isoformat(),
                'rejection_reason': reason,
                'updated_at': datetime.utcnow().isoformat(),
            }}
        )

    @staticmethod
    def get_approval_counts():
        """Counts of datasets by approval status (legacy docs count as approved)."""
        col = get_collection('datasets')
        base = {'status': 'active'}
        pending = col.count_documents({**base, 'approval_status': 'pending'})
        rejected = col.count_documents({**base, 'approval_status': 'rejected'})
        approved = col.count_documents({
            **base,
            '$or': [{'approval_status': 'approved'}, {'approval_status': {'$exists': False}}]
        })
        return {'pending': pending, 'approved': approved, 'rejected': rejected,
                'total': pending + approved + rejected}

    @staticmethod
    def notify_pending_review(dataset_id):
        """Create an alert so admins see a new dataset awaiting review."""
        try:
            from models.alert_model import Alert
            doc = Dataset.get_by_id(dataset_id)
            if doc:
                Alert.create(
                    title='New Dataset Pending Review',
                    message=f'Dataset "{doc.get("name")}" ({doc.get("record_count") or 0} records, '
                            f'{(doc.get("category") or "other")}) was uploaded and awaits approval.',
                    alert_type='info', severity='low',
                    category=doc.get('category', 'weather'))
        except Exception:
            pass

    @staticmethod
    def get_count():
        return get_cached_value('datasets:active_count', lambda: get_collection('datasets').count_documents({'status': 'active'}), ttl_seconds=60)

    @staticmethod
    def get_by_category():
        pipeline = [
            {'$match': {'status': 'active'}},
            {'$group': {'_id': '$category', 'count': {'$sum': 1}}},
        ]
        return {doc['_id']: doc['count']
                for doc in get_collection('datasets').aggregate(pipeline)
                if doc['_id']}

    # ── Multi-format file parsers ─────────────────────────────────────────

    @staticmethod
    def parse_file(file_path, dataset_id, file_type=None):
        """Auto-detect format and parse any supported climate data file."""
        if file_type is None:
            file_type = os.path.splitext(file_path)[1].lstrip('.').lower()

        parsers = {
            'csv': Dataset.parse_csv,
            'txt': Dataset.parse_csv,
            'json': Dataset.parse_json,
            'xlsx': Dataset.parse_excel,
            'xls': Dataset.parse_excel,
            'nc': Dataset.parse_netcdf,
            'hdf5': Dataset.parse_hdf5,
            'h5': Dataset.parse_hdf5,
            'hdf': Dataset.parse_hdf5,
            'tif': Dataset.parse_geotiff,
            'tiff': Dataset.parse_geotiff,
        }

        parser = parsers.get(file_type)
        if parser is None:
            print(f"No parser for file type: {file_type}")
            return 0

        return parser(file_path, dataset_id)

    @staticmethod
    def parse_csv(file_path, dataset_id):
        try:
            df = pd.read_csv(file_path)
            records = Dataset._normalize_climate_records(df)
            Dataset._insert_records(records, dataset_id, df)
            return len(records)
        except Exception as e:
            print(f"Error parsing CSV: {e}")
            return 0

    @staticmethod
    def parse_json(file_path, dataset_id):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                raw = json.load(f)

            if isinstance(raw, list):
                records = raw
            elif isinstance(raw, dict):
                if 'data' in raw:
                    records = raw['data']
                elif 'features' in raw:
                    records = []
                    for feature in raw['features']:
                        props = feature.get('properties', {})
                        geom = feature.get('geometry', {})
                        if geom.get('type') == 'Point':
                            coords = geom.get('coordinates', [0, 0])
                            props.setdefault('longitude', coords[0])
                            props.setdefault('latitude', coords[1])
                        records.append(props)
                elif 'observations' in raw:
                    records = raw['observations']
                elif 'stations' in raw:
                    records = []
                    for station in raw['stations']:
                        for obs in station.get('observations', []):
                            obs['station_name'] = station.get('name', '')
                            obs.setdefault('latitude', station.get('latitude', 0))
                            obs.setdefault('longitude', station.get('longitude', 0))
                            records.append(obs)
                else:
                    records = [raw]
            else:
                print("Unsupported JSON structure")
                return 0

            df = pd.DataFrame(records)
            records = Dataset._normalize_climate_records(df)
            Dataset._insert_records(records, dataset_id, df)
            return len(records)
        except Exception as e:
            print(f"Error parsing JSON: {e}")
            return 0

    @staticmethod
    def parse_excel(file_path, dataset_id):
        try:
            xl = pd.ExcelFile(file_path)
            sheets = []
            for sheet in xl.sheet_names:
                sheet_df = pd.read_excel(file_path, sheet_name=sheet)
                if not sheet_df.empty:
                    sheet_df['source_sheet'] = sheet
                    sheets.append(sheet_df)
            df = pd.concat(sheets, ignore_index=True) if sheets else pd.DataFrame()

            records = Dataset._normalize_climate_records(df)
            Dataset._insert_records(records, dataset_id, df)
            return len(records)
        except Exception as e:
            print(f"Error parsing Excel: {e}")
            return 0

    @staticmethod
    def parse_netcdf(file_path, dataset_id):
        try:
            try:
                import xarray as xr
                with xr.open_dataset(file_path) as ds:
                    df = ds.to_dataframe().reset_index()
                column_mapping = {
                    'time': 'date', 't': 'date', 'datetime': 'date',
                    'temp': 'temperature', 'tas': 'temperature', 't2m': 'temperature',
                    'rh': 'humidity', 'r': 'humidity', 'relative_humidity': 'humidity',
                    'pr': 'rainfall', 'precip': 'rainfall', 'precipitation': 'rainfall',
                    'u10': 'wind_speed', 'wind': 'wind_speed', 'ws': 'wind_speed',
                    'sp': 'pressure', 'slp': 'pressure', 'mslp': 'pressure',
                    'lat': 'latitude', 'y': 'latitude',
                    'lon': 'longitude', 'x': 'longitude',
                    'alt': 'elevation', 'z': 'elevation', 'height': 'elevation',
                }
                df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})
                if 'date' in df.columns:
                    df['date'] = pd.to_datetime(df['date'], errors='coerce').dt.strftime('%Y-%m-%d')
                df = df.dropna(axis=0, how='all')
                records = Dataset._normalize_climate_records(df)
                Dataset._insert_records(records, dataset_id, df)
                return len(records)
            except ImportError:
                file_size = os.path.getsize(file_path)
                print(f"NetCDF file detected ({file_size} bytes). Install 'xarray' for full parsing.")
                get_collection('datasets').update_one(
                    {'id': int(dataset_id)},
                    {'$set': {
                        'description': f'NetCDF file: {os.path.basename(file_path)} ({file_size} bytes). '
                                       f'Install xarray package for full data extraction.',
                        'columns_info': json.dumps(['Install xarray for NetCDF parsing']),
                    }}
                )
                return 0
        except Exception as e:
            print(f"Error parsing NetCDF: {e}")
            return 0

    @staticmethod
    def parse_hdf5(file_path, dataset_id):
        try:
            try:
                import h5py
                with h5py.File(file_path, 'r') as f:
                    arrays = {}
                    def extract_datasets(name, obj):
                        if isinstance(obj, h5py.Dataset) and obj.ndim == 1:
                            try:
                                values = np.asarray(obj[:], dtype=float)
                                if values.size:
                                    arrays[name.split('/')[-1]] = values
                            except (TypeError, ValueError):
                                pass
                    f.visititems(extract_datasets)

                aliases = {
                    'temp': 'temperature', 'temperature': 'temperature', 'tas': 'temperature',
                    'rain': 'rainfall', 'precip': 'rainfall', 'precipitation': 'rainfall',
                    'rh': 'humidity', 'humidity': 'humidity', 'wind': 'wind_speed',
                    'wind_speed': 'wind_speed', 'pressure': 'pressure', 'slp': 'pressure',
                    'co2': 'co2_level', 'aqi': 'air_quality_index', 'lat': 'latitude',
                    'latitude': 'latitude', 'lon': 'longitude', 'longitude': 'longitude',
                    'time': 'date', 'datetime': 'date', 'date': 'date',
                }
                columns = {}
                for name, values in arrays.items():
                    key = aliases.get(name.lower())
                    if key:
                        columns[key] = values
                if not columns:
                    columns = {'temperature': next(iter(arrays.values()))} if arrays else {}
                length = min(len(values) for values in columns.values()) if columns else 0
                records = []
                for index in range(min(length, 50000)):
                    record = {key: values[index].item() for key, values in columns.items()}
                    record.setdefault('date', datetime.utcnow().strftime('%Y-%m-%d'))
                    record.setdefault('station_name', os.path.basename(file_path))
                    records.append(record)

                if records:
                    df = pd.DataFrame(records)
                    records = Dataset._normalize_climate_records(df)
                    Dataset._insert_records(records, dataset_id, df)
                    return len(records)
            except ImportError:
                file_size = os.path.getsize(file_path)
                print(f"HDF5 file detected ({file_size} bytes). Install 'h5py' for full parsing.")
                get_collection('datasets').update_one(
                    {'id': int(dataset_id)},
                    {'$set': {
                        'description': f'HDF5 file: {os.path.basename(file_path)} ({file_size} bytes). '
                                       f'Install h5py package for full data extraction.',
                        'columns_info': json.dumps(['Install h5py for HDF5 parsing']),
                    }}
                )
                return 0
        except Exception as e:
            print(f"Error parsing HDF5: {e}")
            return 0

    @staticmethod
    def parse_geotiff(file_path, dataset_id):
        try:
            try:
                import rasterio
                records = []
                with rasterio.open(file_path) as src:
                    meta = src.meta
                    transform = src.transform
                    for band_idx in range(1, min(src.count + 1, 5)):
                        band_data = src.read(band_idx)
                        step = max(1, int(np.sqrt(band_data.size / 1000)))
                        for row in range(0, band_data.shape[0], step):
                            for col in range(0, band_data.shape[1], step):
                                val = band_data[row, col]
                                if val != src.nodata and not np.isnan(val):
                                    lon, lat = transform * (col, row)
                                    records.append({
                                        'station_name': f'GeoTIFF-B{band_idx}',
                                        'latitude': round(lat, 4),
                                        'longitude': round(lon, 4),
                                        'date': datetime.utcnow().strftime('%Y-%m-%d'),
                                        'temperature': round(float(val), 1) if band_idx == 1 else None,
                                    })
                    if records:
                        df = pd.DataFrame(records)
                        records = Dataset._normalize_climate_records(df)
                        Dataset._insert_records(records, dataset_id, df)
                        return len(records)
            except ImportError:
                file_size = os.path.getsize(file_path)
                print(f"GeoTIFF file detected ({file_size} bytes). Install 'rasterio' for full parsing.")
                get_collection('datasets').update_one(
                    {'id': int(dataset_id)},
                    {'$set': {
                        'description': f'GeoTIFF file: {os.path.basename(file_path)} ({file_size} bytes). '
                                       f'Install rasterio package for full raster data extraction.',
                        'columns_info': json.dumps(['Install rasterio for GeoTIFF parsing']),
                    }}
                )
                return 0
        except Exception as e:
            print(f"Error parsing GeoTIFF: {e}")
            return 0

    # ── Internal helpers ──────────────────────────────────────────────────

    @staticmethod
    def _normalize_climate_records(df):
        column_mapping = {
            'Station': 'station_name', 'StationName': 'station_name', 'station': 'station_name',
            'Name': 'station_name', 'Location': 'station_name',
            'Station.City': 'station_name', 'Station.Code': 'station_code',
            'Lat': 'latitude', 'LAT': 'latitude', 'lat': 'latitude',
            'Lon': 'longitude', 'LONG': 'longitude', 'LON': 'longitude', 'lng': 'longitude',
            'Long': 'longitude', 'lon': 'longitude',
            'Elev': 'elevation', 'Alt': 'elevation', 'alt': 'elevation', 'height': 'elevation',
            'Date': 'date', 'DATE': 'date', 'Timestamp': 'date', 'timestamp': 'date',
            'Time': 'date', 'time': 'date', 'DateTime': 'date',
            'Date.Full': 'date',
            'Temp': 'temperature', 'TEMP': 'temperature', 'temp': 'temperature',
            'Temperature_C': 'temperature', 'temp_c': 'temperature',
            'Data.Temperature.Avg Temp': 'temperature',
            'Hum': 'humidity', 'HUM': 'humidity', 'hum': 'humidity',
            'RH': 'humidity', 'Relative_Humidity': 'humidity',
            'Rain': 'rainfall', 'RAIN': 'rainfall', 'rain': 'rainfall',
            'Precipitation': 'rainfall', 'precip': 'rainfall',
            'Data.Precipitation': 'rainfall',
            'Wind': 'wind_speed', 'WIND': 'wind_speed', 'wind_spd': 'wind_speed',
            'WindSpeed': 'wind_speed', 'wind_dir': 'wind_direction',
            'Wind_Direction': 'wind_direction', 'wdir': 'wind_direction',
            'Data.Wind.Speed': 'wind_speed', 'Data.Wind.Direction': 'wind_direction',
            'Pres': 'pressure', 'PRES': 'pressure', 'pres': 'pressure',
            'Pressure': 'pressure', 'Barometric': 'pressure',
            'CO2': 'co2_level', 'co2': 'co2_level', 'CO2_ppm': 'co2_level',
            'AQI': 'air_quality_index', 'aqi': 'air_quality_index',
            'Vis': 'visibility', 'visibility_km': 'visibility',
            'Cloud': 'cloud_cover', 'clouds': 'cloud_cover', 'cloud_pct': 'cloud_cover',
            'UV': 'uv_index', 'uv': 'uv_index', 'UV_Index': 'uv_index',
            'Soil': 'soil_moisture', 'soil_m': 'soil_moisture',
            'Snow': 'snow_depth', 'snow_cm': 'snow_depth',
        }
        df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})
        records = df.where(pd.notnull(df), None).to_dict('records')
        return records

    @staticmethod
    def _insert_records(records, dataset_id, df):
        from models.climate_model import ClimateData
        ClimateData.insert_batch(records, dataset_id)

        get_collection('datasets').update_one(
            {'id': int(dataset_id)},
            {'$set': {
                'record_count': len(records),
                'column_count': len(df.columns),
                'columns_info': json.dumps(list(df.columns)),
                'updated_at': datetime.utcnow().isoformat(),
            }}
        )

    @staticmethod
    def get_statistics(dataset_id):
        doc = get_collection('datasets').find_one(
            {'id': int(dataset_id)},
            {'record_count': 1, 'column_count': 1, 'file_size': 1, 'columns_info': 1}
        )
        if doc:
            doc.pop('_id', None)
        return doc or {}

    @staticmethod
    def validate_dataset(dataset_id):
        VALID_RANGES = {
            'temperature': (-90, 60), 'humidity': (0, 100),
            'rainfall': (0, 2000), 'wind_speed': (0, 400),
            'pressure': (300, 1100), 'co2_level': (0, 10000),
            'air_quality_index': (0, 1000), 'visibility': (0, 50),
            'cloud_cover': (0, 100), 'uv_index': (0, 20),
            'soil_moisture': (0, 100), 'snow_depth': (0, 1000),
        }
        rows = list(get_collection('climate_data').find({'dataset_id': int(dataset_id)}))
        total = len(rows)
        invalid = 0
        issues = {}
        missing = {field: 0 for field in VALID_RANGES}
        for row in rows:
            for field, (min_val, max_val) in VALID_RANGES.items():
                val = row.get(field)
                if val is None:
                    missing[field] += 1
                    continue
                try:
                    v = float(val)
                    if v < min_val or v > max_val:
                        invalid += 1
                        issues[field] = issues.get(field, 0) + 1
                except (ValueError, TypeError):
                    invalid += 1
                    issues[field] = issues.get(field, 0) + 1

        return {
            'total_records': total,
            'valid_records': total - invalid,
            'invalid_records': invalid,
            'issues': issues,
            'missing': missing,
            'missing_total': sum(missing.values()),
            'completeness_percent': round(
                100 * (1 - sum(missing.values()) / max(1, total * len(VALID_RANGES))), 1
            ),
        }
