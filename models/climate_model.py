from utils.database import get_collection, next_id, next_ids
from utils.helper import get_cached_value
from datetime import datetime
import json
import numpy as np


class ClimateData:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    @staticmethod
    def get_by_dataset(dataset_id, limit=1000, offset=0):
        col = get_collection('climate_data')
        docs = col.find({'dataset_id': int(dataset_id)}).sort('date', -1).skip(offset).limit(limit)
        return list(docs)

    @staticmethod
    def get_summary(dataset_id=None):
        key = 'climate:summary:{}'.format(dataset_id or 'all')
        return get_cached_value(key, lambda: ClimateData._compute_summary(dataset_id), ttl_seconds=60)

    @staticmethod
    def get_visualization_state(start_date=None, end_date=None, region=None):
        """Return filter-scoped summary, anomalies, and mappable stations."""
        match = {}
        if start_date or end_date:
            match['date'] = {}
            if start_date:
                match['date']['$gte'] = start_date
            if end_date:
                match['date']['$lte'] = end_date
        if region:
            match['station_name'] = region
        rows = list(get_collection('climate_data').find(match).sort('date', -1).limit(50000))

        def numeric(value):
            try:
                value = float(value)
                return value if value == value else None
            except (TypeError, ValueError):
                return None

        def numbers(field):
            return [value for r in rows if (value := numeric(r.get(field))) is not None]

        summary = {'total_records': len(rows)}
        for field, key in [('temperature', 'avg_temp'), ('rainfall', 'avg_rainfall'),
                           ('humidity', 'avg_humidity'), ('wind_speed', 'avg_wind'),
                           ('co2_level', 'avg_co2'), ('air_quality_index', 'avg_aqi'),
                           ('pressure', 'avg_pressure')]:
            values = numbers(field)
            summary[key] = round(sum(values) / len(values), 2) if values else None

        anomalies = []
        for field, output in [('temperature', 'temp_z_score'), ('rainfall', 'rain_z_score')]:
            values = numbers(field)
            if len(values) < 2:
                continue
            mean = sum(values) / len(values)
            std = (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5 or 1
            for row in rows:
                value = row.get(field)
                value = numeric(value)
                if value is None:
                    continue
                score = abs((value - mean) / std)
                if score > 2:
                    item = next((a for a in anomalies if a.get('id') == row.get('id')), None)
                    if not item:
                        item = {'id': row.get('id'), 'date': row.get('date'),
                                'station_name': row.get('station_name'),
                                'temperature': row.get('temperature'), 'rainfall': row.get('rainfall')}
                        anomalies.append(item)
                    item[output] = round(score, 3)

        stations = []
        seen = set()
        for row in rows:
            lat, lng = row.get('latitude'), row.get('longitude')
            name = row.get('station_name') or 'Unknown station'
            lat, lng = numeric(lat), numeric(lng)
            if lat is not None and lng is not None and name not in seen:
                stations.append({
                    'station_name': name, 'latitude': lat, 'longitude': lng,
                    'temperature': row.get('temperature'), 'rainfall': row.get('rainfall'),
                    'humidity': row.get('humidity'), 'wind_speed': row.get('wind_speed'),
                    'pressure': row.get('pressure'), 'co2_level': row.get('co2_level'),
                    'air_quality_index': row.get('air_quality_index'),
                    'visibility': row.get('visibility'), 'uv_index': row.get('uv_index'),
                    'soil_moisture': row.get('soil_moisture'),
                    'date': row.get('date'),
                })
                seen.add(name)
        return {'summary': summary, 'anomalies': anomalies[:100], 'stations': stations}

    @staticmethod
    def _compute_summary(dataset_id=None):
        col = get_collection('climate_data')
        match = {'dataset_id': int(dataset_id)} if dataset_id else {}
        pipeline = []
        if match:
            pipeline.append({'$match': match})
        pipeline.append({
            '$group': {
                '_id': None,
                'total_records': {'$sum': 1},
                'avg_temp': {'$avg': '$temperature'},
                'min_temp': {'$min': '$temperature'},
                'max_temp': {'$max': '$temperature'},
                'avg_humidity': {'$avg': '$humidity'},
                'avg_rainfall': {'$avg': '$rainfall'},
                'avg_wind': {'$avg': '$wind_speed'},
                'avg_co2': {'$avg': '$co2_level'},
                'avg_aqi': {'$avg': '$air_quality_index'},
                'avg_pressure': {'$avg': '$pressure'},
                'avg_visibility': {'$avg': '$visibility'},
                'avg_uv_index': {'$avg': '$uv_index'},
                'avg_soil_moisture': {'$avg': '$soil_moisture'},
            }
        })
        result = list(col.aggregate(pipeline))
        if result:
            d = result[0]
            d.pop('_id', None)
            return d
        return {}

    @staticmethod
    def get_monthly_trends(year=None):
        key = 'climate:monthly_trends:{}'.format(year or 'all')
        return get_cached_value(key, lambda: ClimateData._compute_monthly_trends(year), ttl_seconds=60)

    @staticmethod
    def _compute_monthly_trends(year=None):
        col = get_collection('climate_data')
        pipeline = []
        if year:
            pipeline.append({'$match': {'date': {'$regex': f'^{str(year)}'}}})

        pipeline.append({
            '$addFields': {
                'month': {'$substrCP': ['$date', 0, 7]},
            }
        })
        pipeline.append({
            '$group': {
                '_id': '$month',
                'avg_temp': {'$avg': '$temperature'},
                'avg_humidity': {'$avg': '$humidity'},
                'total_rainfall': {'$sum': '$rainfall'},
                'avg_wind': {'$avg': '$wind_speed'},
                'avg_co2': {'$avg': '$co2_level'},
                'avg_aqi': {'$avg': '$air_quality_index'},
                'avg_pressure': {'$avg': '$pressure'},
                'avg_visibility': {'$avg': '$visibility'},
                'avg_uv': {'$avg': '$uv_index'},
                'avg_soil_moisture': {'$avg': '$soil_moisture'},
                'record_count': {'$sum': 1},
            }
        })
        if year:
            pipeline.append({'$sort': {'_id': 1}})
        else:
            pipeline.append({'$sort': {'_id': -1}})
            pipeline.append({'$limit': 24})

        results = []
        for doc in col.aggregate(pipeline):
            doc['month'] = doc.pop('_id')
            results.append(doc)
        return results

    @staticmethod
    def get_regional_data():
        return get_cached_value('climate:regional_data', ClimateData._compute_regional_data, ttl_seconds=300)

    @staticmethod
    def _compute_regional_data():
        col = get_collection('climate_data')
        pipeline = [
            {'$match': {'station_name': {'$ne': None}}},
            {
                '$group': {
                    '_id': '$station_name',
                    'latitude': {'$avg': '$latitude'},
                    'longitude': {'$avg': '$longitude'},
                    'avg_temp': {'$avg': '$temperature'},
                    'avg_humidity': {'$avg': '$humidity'},
                    'total_rainfall': {'$sum': '$rainfall'},
                    'avg_aqi': {'$avg': '$air_quality_index'},
                    'avg_wind': {'$avg': '$wind_speed'},
                    'avg_pressure': {'$avg': '$pressure'},
                    'avg_co2': {'$avg': '$co2_level'},
                    'avg_visibility': {'$avg': '$visibility'},
                    'avg_uv': {'$avg': '$uv_index'},
                    'avg_soil_moisture': {'$avg': '$soil_moisture'},
                    'readings': {'$sum': 1},
                }
            },
            {'$sort': {'_id': 1}},
        ]
        results = []
        for doc in col.aggregate(pipeline):
            doc['station_name'] = doc.pop('_id')
            results.append(doc)
        return results

    @staticmethod
    def get_anomalies(threshold=2.0):
        key = 'climate:anomalies:v2:{}'.format(threshold)
        return get_cached_value(key, lambda: ClimateData._compute_anomalies(threshold), ttl_seconds=120)

    @staticmethod
    def _compute_anomalies(threshold=2.0):
        col = get_collection('climate_data')
        try:
            temp_stats = next(col.aggregate([
                {'$match': {'temperature': {'$ne': None}}},
                {'$group': {
                    '_id': None,
                    'mean': {'$avg': '$temperature'},
                    'stddev': {'$stdDevPop': '$temperature'},
                }},
            ]))
        except Exception:
            temp_stats = None
        try:
            rain_stats = next(col.aggregate([
                {'$match': {'rainfall': {'$ne': None}}},
                {'$group': {
                    '_id': None,
                    'mean': {'$avg': '$rainfall'},
                    'stddev': {'$stdDevPop': '$rainfall'},
                }},
            ]))
        except Exception:
            rain_stats = None

        if not temp_stats and not rain_stats:
            return []

        t_mean = (temp_stats or {}).get('mean') or 0
        t_std = (temp_stats or {}).get('stddev') or 1
        r_mean = (rain_stats or {}).get('mean') or 0
        r_std = (rain_stats or {}).get('stddev') or 1

        pipeline = [
            {
                '$match': {
                    '$or': [
                        {'temperature': {'$ne': None}},
                        {'rainfall': {'$ne': None}},
                    ]
                }
            },
            {
                '$addFields': {
                    'temp_z': {
                        '$cond': [
                            {'$and': [
                                {'$ne': ['$temperature', None]},
                                {'$ne': [t_std, 0]},
                            ]},
                            {'$abs': {'$divide': [{'$subtract': ['$temperature', t_mean]}, t_std]}},
                            0,
                        ]
                    },
                    'rain_z': {
                        '$cond': [
                            {'$and': [
                                {'$ne': ['$rainfall', None]},
                                {'$ne': [r_std, 0]},
                            ]},
                            {'$abs': {'$divide': [{'$subtract': ['$rainfall', r_mean]}, r_std]}},
                            0,
                        ]
                    },
                }
            },
            {
                '$match': {
                    '$expr': {
                    '$or': [
                        {'$gt': ['$temp_z', threshold]},
                        {'$gt': ['$rain_z', threshold]},
                    ]
                    }
                }
            },
            {'$sort': {'date': -1}},
            {'$limit': 100},
            {
                '$project': {
                    'temperature': 1,
                    'rainfall': 1,
                    'date': 1,
                    'station_name': 1,
                    'humidity': 1,
                    'wind_speed': 1,
                    'dataset_id': 1,
                    'temp_z_score': '$temp_z',
                    'rain_z_score': '$rain_z',
                }
            },
        ]
        return list(col.aggregate(pipeline))

    @staticmethod
    def get_correlation_data(variables=None):
        """Fetch rows containing the selected correlation variables."""
        variables = variables or [
            'temperature', 'rainfall', 'humidity', 'wind_speed',
            'pressure', 'co2_level', 'air_quality_index'
        ]
        key = 'climate:correlation_data:' + ','.join(sorted(variables))
        return get_cached_value(
            key,
            lambda: ClimateData._fetch_correlation_data(variables),
            ttl_seconds=300,
        )

    @staticmethod
    def _fetch_correlation_data(variables=None):
        variables = variables or [
            'temperature', 'rainfall', 'humidity', 'wind_speed',
            'pressure', 'co2_level', 'air_quality_index'
        ]
        query = {field: {'$ne': None} for field in variables}
        projection = {field: 1 for field in variables}
        return list(get_collection('climate_data').find(
            query, projection
        ).limit(5000))

    @staticmethod
    def align_correlation_rows(raw, variables):
        """Keep row-aligned numeric values for the selected variables."""
        def _num(value):
            if value is None or value == '':
                return None
            try:
                number = float(value)
            except (TypeError, ValueError):
                return None
            return number if number == number else None

        data = {var: [] for var in variables}
        aligned = 0
        for record in raw:
            row = {var: _num(record.get(var)) for var in variables}
            if any(value is None for value in row.values()):
                continue
            for var in variables:
                data[var].append(row[var])
            aligned += 1
        return {var: values for var, values in data.items() if len(values) > 2}, aligned

    @staticmethod
    def get_correlation_results():
        """Compute correlation results using the current climate data."""
        return get_cached_value(
            'climate:correlation_results',
            ClimateData._compute_correlation_results,
            ttl_seconds=60,
        )

    @staticmethod
    def _compute_correlation_results():
        from ml_models.correlation_analysis import CorrelationAnalyzer

        variables = [
            'temperature', 'rainfall', 'humidity', 'wind_speed',
            'pressure', 'co2_level', 'air_quality_index'
        ]
        raw = ClimateData.get_correlation_data(variables)
        if not raw:
            return {'error': 'No data available for correlation analysis', 'correlations': []}
        data, aligned = ClimateData.align_correlation_rows(raw, variables)
        if len(data) < 2:
            return {'error': 'Not enough numeric records to compute correlations. '
                             'Upload climate data (or run fix_data_types.py) first.', 'correlations': []}
        analyzer = CorrelationAnalyzer()
        analyzer.load_data(data)
        pairwise = analyzer.compute_pairwise_correlations()
        matrix = analyzer.compute_correlation_matrix()

        def _convert(obj):
            if isinstance(obj, dict):
                return {key: _convert(value) for key, value in obj.items()}
            if isinstance(obj, list):
                return [_convert(value) for value in obj]
            if isinstance(obj, np.bool_):
                return bool(obj)
            if isinstance(obj, np.integer):
                return int(obj)
            if isinstance(obj, np.floating):
                return float(obj)
            if isinstance(obj, np.ndarray):
                return _convert(obj.tolist())
            return obj

        return _convert({
            'pairwise_correlations': pairwise,
            'correlation_matrix': matrix,
            'total_records': aligned,
        })

    @staticmethod
    def insert_batch(records, dataset_id):
        col = get_collection('climate_data')

        def _to_float(value):
            """Coerce uploaded values (possibly strings) to float; None if invalid."""
            if value is None or value == '':
                return None
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        numeric_fields = ('latitude', 'longitude', 'elevation', 'temperature',
                          'humidity', 'rainfall', 'wind_speed', 'wind_direction',
                          'pressure', 'co2_level', 'air_quality_index', 'visibility',
                          'cloud_cover', 'uv_index', 'soil_moisture', 'snow_depth')
        docs = []
        ids = next_ids('climate_data', len(records))
        for record_id, r in zip(ids, records):
            doc = {
            'id': record_id,
                'dataset_id': int(dataset_id),
                'station_name': r.get('station_name'),
                'date': r.get('date'),
                'data_source': 'batch',
                'created_at': datetime.utcnow().isoformat(),
            }
            for f in numeric_fields:
                doc[f] = _to_float(r.get(f))
            docs.append(doc)
        if docs:
            col.insert_many(docs)
            ClimateData.invalidate_caches()
            ClimateData._maybe_submit_large_dataset_job(dataset_id)

    @staticmethod
    def _maybe_submit_large_dataset_job(dataset_id):
        """Start one automatic summary job when a dataset becomes large."""
        try:
            from config import Config
            threshold = max(1, int(Config.MAPREDUCE_AUTO_THRESHOLD))
            dataset_id = int(dataset_id)
            climate_col = get_collection('climate_data')
            record_count = climate_col.count_documents({'dataset_id': dataset_id})
            if record_count < threshold:
                return None

            input_path = f'/dataset/{dataset_id}'
            jobs = get_collection('mapreduce_jobs')
            existing = jobs.find_one({
                'input_path': input_path,
                'job_type': 'statistical_summary',
                'auto_generated': True,
            })
            if existing:
                return existing.get('id')

            dataset = get_collection('datasets').find_one({'id': dataset_id}) or {}
            from utils.mapreduce import MapReduceManager
            job_id = MapReduceManager.submit_job(
                job_name=f'Automatic summary - Dataset #{dataset_id}',
                job_type='statistical_summary',
                input_path=input_path,
                submitted_by=dataset.get('uploaded_by'),
                input_params={
                    'input_path': input_path,
                    'output_path': f'/climate/results/dataset_{dataset_id}',
                    'num_reducers': 2,
                    'job_type': 'statistical_summary',
                    'use_hadoop': Config.HDFS_USE_REAL,
                    'auto_generated': True,
                },
            )
            jobs.update_one({'id': job_id}, {'$set': {
                'auto_generated': True,
                'trigger_record_count': record_count,
            }})
            import threading
            worker = threading.Thread(
                target=MapReduceManager.execute_job, args=(job_id,), daemon=True
            )
            worker.start()
            return job_id
        except Exception:
            return None

    @staticmethod
    def delete_by_dataset(dataset_id):
        """Remove every reading tied to a dataset (used when re-syncing an upload)."""
        result = get_collection('climate_data').delete_many({'dataset_id': int(dataset_id)})
        ClimateData.invalidate_caches()
        return getattr(result, 'deleted_count', 0)

    @staticmethod
    def delete_by_stations(station_names):
        """Remove every reading belonging to selected station names."""
        names = [name for name in station_names if name]
        if not names:
            return 0
        result = get_collection('climate_data').delete_many({'station_name': {'$in': names}})
        ClimateData.invalidate_caches()
        return getattr(result, 'deleted_count', 0)

    @staticmethod
    def invalidate_caches():
        """Clear cached aggregates so analysis panels reflect the newest data."""
        try:
            from utils.helper import invalidate_cache
            invalidate_cache('climate:')
        except Exception:
            pass

    @staticmethod
    def get_total_count():
        return get_cached_value('climate:total_count', lambda: get_collection('climate_data').count_documents({}), ttl_seconds=120)

    @staticmethod
    def get_latest_readings(limit=20):
        key = 'climate:latest_readings:{}'.format(limit)
        return get_cached_value(key, lambda: list(get_collection('climate_data').find().sort('created_at', -1).limit(limit)), ttl_seconds=10)

    @staticmethod
    def get_chart_data(variables=None, start_date=None, end_date=None, region=None, group_by='month'):
        """Flexible chart data query supporting multiple variables and filters."""
        if variables is None:
            variables = ['temperature', 'rainfall']

        cache_key = 'climate:chart:{}:{}:{}:{}:{}'.format(
            ','.join(sorted(variables)), start_date or '', end_date or '',
            region or '', group_by
        )
        return get_cached_value(cache_key, lambda: ClimateData._compute_chart_data(
            variables, start_date, end_date, region, group_by), ttl_seconds=120)

    @staticmethod
    def _compute_chart_data(variables, start_date, end_date, region, group_by):
        col = get_collection('climate_data')
        match = {}
        if start_date:
            match['date'] = {'$gte': start_date}
        if end_date:
            match.setdefault('date', {})['$lte'] = end_date
        if region:
            match['station_name'] = region

        pipeline = []
        if match:
            pipeline.append({'$match': match})

        if group_by == 'month':
            group_expr = {'$substrCP': ['$date', 0, 7]}
        elif group_by == 'year':
            group_expr = {'$substrCP': ['$date', 0, 4]}
        else:
            group_expr = '$date'

        safe_vars = ['temperature', 'humidity', 'rainfall', 'wind_speed', 'pressure',
                      'co2_level', 'air_quality_index', 'visibility', 'cloud_cover',
                      'uv_index', 'soil_moisture', 'snow_depth']

        group_stage = {'_id': group_expr, 'count': {'$sum': 1}}
        for v in variables:
            if v in safe_vars:
                agg = '$sum' if v == 'rainfall' else '$avg'
                group_stage[v] = {agg: f'${v}'}

        if not any(v in safe_vars for v in variables):
            group_stage['temperature'] = {'$avg': '$temperature'}

        pipeline.append({'$group': group_stage})
        pipeline.append({'$sort': {'_id': 1}})

        results = []
        for doc in col.aggregate(pipeline):
            doc['period'] = doc.pop('_id')
            results.append(doc)
        return results

    @staticmethod
    def get_available_years():
        return get_cached_value('climate:available_years', ClimateData._compute_available_years, ttl_seconds=300)

    @staticmethod
    def _compute_available_years():
        col = get_collection('climate_data')
        pipeline = [
            {'$match': {'date': {'$ne': None}}},
            {'$addFields': {'year': {'$substrCP': ['$date', 0, 4]}}},
            {'$group': {'_id': '$year'}},
            {'$sort': {'_id': -1}},
        ]
        return [doc['_id'] for doc in col.aggregate(pipeline) if doc['_id']]

    @staticmethod
    def get_regions():
        return get_cached_value('climate:regions', ClimateData._compute_regions, ttl_seconds=300)

    @staticmethod
    def _compute_regions():
        col = get_collection('climate_data')
        pipeline = [
            {'$match': {'station_name': {'$ne': None}}},
            {'$group': {'_id': '$station_name'}},
            {'$sort': {'_id': 1}},
        ]
        return [doc['_id'] for doc in col.aggregate(pipeline) if doc['_id']]
