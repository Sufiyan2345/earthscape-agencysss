import json
import time
import math
import os
import numpy as np
from datetime import datetime
from collections import defaultdict
from utils.database import get_collection, next_id


def _safe_float(value):
    """Return a finite float or None for missing/invalid climate values."""
    if value is None or value == '':
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


class MapReduceManager:
    """MapReduce job manager that processes real climate data."""

    @staticmethod
    def submit_job(job_name, job_type, input_path, submitted_by,
                   mapper_code='', reducer_code='', input_params=None):
        col = get_collection('mapreduce_jobs')
        params_json = json.dumps(input_params) if input_params else '{}'
        job_id = next_id('mapreduce_jobs')
        col.insert_one({
            'id': job_id,
            'job_name': job_name,
            'job_type': job_type,
            'input_path': input_path,
            'status': 'running',
            'mapper_code': mapper_code,
            'reducer_code': reducer_code,
            'submitted_by': submitted_by,
            'started_at': datetime.utcnow().isoformat(),
            'input_params': params_json,
            'progress': 0,
            'input_records': 0,
            'output_records': 0,
            'created_at': datetime.utcnow().isoformat(),
        })
        return job_id

    @staticmethod
    def execute_job(job_id):
        """Execute a MapReduce job against real climate data using a streamed map/reduce to limit memory usage."""
        col = get_collection('mapreduce_jobs')
        job = col.find_one({'id': job_id})
        if not job:
            return False

        # Use real Hadoop Streaming when the institute environment enables it.
        try:
            from config import Config
            from utils.hadoop_mr import hadoop_bridge
            params = json.loads(job.get('input_params') or '{}')
            if Config.HDFS_USE_REAL and hadoop_bridge.is_hadoop_available():
                output_path = params.get('output_path') or f"/climate/results/{job['job_name']}"
                result = hadoop_bridge.submit_job(
                    job_name=job['job_name'], job_type=job['job_type'],
                    input_path=job['input_path'], output_path=output_path,
                    submitted_by=job.get('submitted_by'), input_params=params,
                )
                col.update_one({'id': job_id}, {'$set': {
                    'status': 'running' if result.get('success') else 'failed',
                    'progress': 10 if result.get('success') else 100,
                    'hadoop_job_id': result.get('job_id'),
                    'hdfs_output_path': output_path,
                    'error_message': None if result.get('success') else result.get('message'),
                    'started_at': datetime.utcnow().isoformat(),
                }})
                return bool(result.get('success'))
        except Exception as exc:
            col.update_one({'id': job_id}, {'$set': {'status': 'failed', 'error_message': str(exc)}})
            return False

        start_time = time.time()
        job_type = job['job_type']

        try:
            # Update progress to 5%
            col.update_one({'id': job_id}, {'$set': {'progress': 5}})

            # Fetch an iterator over input records
            records_iter = MapReduceManager._fetch_input_data(job['input_path'], job_type)

            # If caller requested Hadoop/streaming execution, delegate to the local streaming adapter
            try:
                params = json.loads(job.get('input_params') or '{}')
            except Exception:
                params = {}

            if params.get('use_hadoop'):
                # Defer to local Hadoop-streaming adapter (uses mapper/reducer scripts in hadoop/mapreduce/ by default)
                try:
                    from utils.hadoop_adapter import run_streaming_job
                    mapper_path = job.get('mapper_code') or os.path.join(os.getcwd(), 'hadoop', 'mapreduce', 'mapper.py')
                    reducer_path = job.get('reducer_code') or os.path.join(os.getcwd(), 'hadoop', 'mapreduce', 'reducer.py')
                    col.update_one({'id': job_id}, {'$set': {'progress': 12}})
                    ok, stream_result = run_streaming_job(records_iter, mapper_path, reducer_path, job_type=job_type)
                    if not ok:
                        raise RuntimeError('Streaming adapter failed: %s' % (stream_result.get('error') if isinstance(stream_result, dict) else str(stream_result)))

                    # Persist streaming result and finish
                    execution_time = time.time() - start_time
                    col.update_one({'id': job_id}, {'$set': {
                        'status': 'completed', 'progress': 100, 'output_records': stream_result.get('output_records', 0),
                        'execution_time': round(execution_time, 2), 'completed_at': datetime.utcnow().isoformat(),
                        'result': json.dumps(stream_result)
                    }})
                    return True
                except Exception as e:
                    execution_time = time.time() - start_time
                    col.update_one({'id': job_id}, {'$set': {
                        'status': 'failed', 'error_message': str(e), 'execution_time': round(execution_time, 2),
                        'completed_at': datetime.utcnow().isoformat(),
                    }})
                    return False

            # Stream through records, map on-the-fly and accumulate grouped values
            col.update_one({'id': job_id}, {'$set': {'progress': 10}})

            input_count = 0
            invalid_records = 0
            missing_values = 0
            numeric_fields = ('temperature', 'rainfall', 'humidity', 'wind_speed',
                              'pressure', 'co2_level', 'air_quality_index')
            # Choose accumulator structure depending on job_type
            if job_type in ('temperature_analysis', 'rainfall_analysis', 'data_aggregation', 'statistical_summary', 'trend_prediction', 'pattern_detection'):
                # groups: (region, metric) -> list of numeric values or list of dicts for trend/pattern
                groups = defaultdict(list)
            elif job_type == 'anomaly_detection':
                # groups: key -> list of {'value', 'date'}
                groups = defaultdict(list)
            elif job_type == 'correlation_analysis':
                # groups: (region, pair) -> {'x':[], 'y':[]}
                groups = defaultdict(lambda: {'x': [], 'y': []})
            else:
                groups = defaultdict(list)

            # Ensure records_iter is an iterator (cursor or list)
            iterator = iter(records_iter)

            for rec in iterator:
                if not isinstance(rec, dict):
                    invalid_records += 1
                    continue
                input_count += 1
                rec = dict(rec)
                record_invalid = False
                for field in numeric_fields:
                    value = rec.get(field)
                    if value is None or value == '':
                        missing_values += 1
                        continue
                    parsed = _safe_float(value)
                    if parsed is None:
                        rec[field] = None
                        record_invalid = True
                    else:
                        rec[field] = parsed
                if record_invalid:
                    invalid_records += 1
                # update progress periodically
                if input_count % 1000 == 0:
                    col.update_one({'id': job_id}, {'$set': {'input_records': input_count, 'progress': 12}})

                # Map the single record into intermediate items (reuse map logic but per-record)
                # Use the same mapping semantics as _map_phase but inline to avoid intermediate list
                region = rec.get('station_name') or rec.get('region') or 'global'
                date = rec.get('date') or rec.get('timestamp', '')

                if job_type == 'temperature_analysis':
                    temp = rec.get('temperature')
                    if temp is not None:
                        groups[(region, 'temperature')].append(float(temp))
                elif job_type == 'rainfall_analysis':
                    rain = rec.get('rainfall')
                    if rain is not None:
                        groups[(region, 'rainfall')].append(float(rain))
                elif job_type == 'anomaly_detection':
                    temp = rec.get('temperature')
                    rain = rec.get('rainfall')
                    aqi = rec.get('air_quality_index')
                    if temp is not None:
                        groups[f"{region}_temp"].append({'value': float(temp), 'date': date})
                    if rain is not None:
                        groups[f"{region}_rain"].append({'value': float(rain), 'date': date})
                    if aqi is not None:
                        groups[f"{region}_aqi"].append({'value': float(aqi), 'date': date})
                elif job_type == 'correlation_analysis':
                    temp = rec.get('temperature')
                    rain = rec.get('rainfall')
                    hum = rec.get('humidity')
                    aqi = rec.get('air_quality_index')
                    ws = rec.get('wind_speed')
                    if temp is not None and rain is not None:
                        groups[(region, 'temp_rain')]['x'].append(float(temp)); groups[(region, 'temp_rain')]['y'].append(float(rain))
                    if temp is not None and hum is not None:
                        groups[(region, 'temp_humidity')]['x'].append(float(temp)); groups[(region, 'temp_humidity')]['y'].append(float(hum))
                    if temp is not None and aqi is not None:
                        groups[(region, 'temp_aqi')]['x'].append(float(temp)); groups[(region, 'temp_aqi')]['y'].append(float(aqi))
                    if rain is not None and hum is not None:
                        groups[(region, 'rain_humidity')]['x'].append(float(rain)); groups[(region, 'rain_humidity')]['y'].append(float(hum))
                elif job_type in ('data_aggregation', 'statistical_summary', 'pattern_detection', 'trend_prediction'):
                    for metric in ('temperature', 'rainfall', 'humidity', 'wind_speed', 'pressure', 'co2_level', 'air_quality_index'):
                        v = rec.get(metric)
                        if v is not None:
                            # normalize metric key names for consistency
                            key = metric if metric != 'air_quality_index' else 'air_quality_index'
                            groups[(region, key)].append({'value': float(v), 'date': date} if job_type in ('trend_prediction', 'pattern_detection') else float(v))
                else:
                    # Generic: collect temperature/rainfall/humidity
                    for metric in ('temperature', 'rainfall', 'humidity'):
                        v = rec.get(metric)
                        if v is not None:
                            groups[(region, metric)].append(float(v))

            # Done scanning input
            col.update_one({'id': job_id}, {'$set': {'input_records': input_count, 'progress': 30}})

            if input_count == 0:
                result = {
                    'message': 'No climate data found for the specified input path.',
                    'records_processed': 0,
                    'data_quality': {'invalid_records': invalid_records, 'missing_values': missing_values},
                }
                execution_time = time.time() - start_time
                col.update_one({'id': job_id}, {'$set': {
                    'status': 'completed', 'progress': 100, 'input_records': 0,
                    'output_records': 0, 'execution_time': round(execution_time, 2),
                    'completed_at': datetime.utcnow().isoformat(), 'result': json.dumps(result)
                }})
                return True

            # Update progress before reduction
            col.update_one({'id': job_id}, {'$set': {'progress': 45}})

            # Finalize reduction directly from accumulators
            if job_type in ('temperature_analysis', 'rainfall_analysis', 'data_aggregation', 'statistical_summary'):
                result = MapReduceManager._finalize_aggregation_from_groups(groups, job_type)
            elif job_type == 'anomaly_detection':
                result = MapReduceManager._finalize_anomaly_from_groups(groups)
            elif job_type == 'correlation_analysis':
                result = MapReduceManager._finalize_correlation_from_groups(groups)
            elif job_type == 'trend_prediction':
                result = MapReduceManager._finalize_trend_from_groups(groups)
            elif job_type == 'pattern_detection':
                result = MapReduceManager._finalize_pattern_from_groups(groups)
            else:
                result = MapReduceManager._finalize_aggregation_from_groups(groups, job_type)

            result['data_quality'] = {
                'records_read': input_count,
                'invalid_records': invalid_records,
                'missing_values': missing_values,
                'records_with_usable_values': input_count - invalid_records,
            }

            col.update_one({'id': job_id}, {'$set': {'progress': 85}})

            output_records = result.get('output_records', 0)
            execution_time = time.time() - start_time

            # Store completed result
            col.update_one({'id': job_id}, {'$set': {
                'status': 'completed', 'progress': 100, 'output_records': output_records,
                'execution_time': round(execution_time, 2), 'completed_at': datetime.utcnow().isoformat(),
                'result': json.dumps(result),
            }})
            return True

        except Exception as e:
            execution_time = time.time() - start_time
            col.update_one({'id': job_id}, {'$set': {
                'status': 'failed', 'error_message': str(e), 'execution_time': round(execution_time, 2),
                'completed_at': datetime.utcnow().isoformat(),
            }})
            return False

    # ── Data fetching ─────────────────────────────────────────────────────

    @staticmethod
    def _fetch_input_data(input_path, job_type):
        """Fetch climate data from DB based on input_path and job_type.
        
        Supports:
        - /climate_data or default: batch climate_data only
        - /realtime: realtime_readings only
        - /combined: merged climate_data + realtime_readings
        - /satellite or /weather: climate_data filtered by source
        """
        climate_col = get_collection('climate_data')
        readings_col = get_collection('realtime_readings')
        streams_col = get_collection('realtime_streams')

        projection = {'station_name': 1, 'date': 1, 'temperature': 1,
                      'humidity': 1, 'rainfall': 1, 'wind_speed': 1,
                      'pressure': 1, 'co2_level': 1, 'air_quality_index': 1,
                      '_id': 0}
        value_query = {'$or': [
            {'temperature': {'$ne': None}}, {'rainfall': {'$ne': None}},
            {'humidity': {'$ne': None}}, {'air_quality_index': {'$ne': None}},
            {'soil_moisture': {'$ne': None}},
        ]}

        def _fetch_realtime_readings(limit=10000):
            """Fetch realtime readings and resolve stream names."""
            readings = list(readings_col.find({
                '$or': [
                    {'temperature': {'$ne': None}}, {'rainfall': {'$ne': None}},
                    {'humidity': {'$ne': None}}, {'air_quality_index': {'$ne': None}},
                    {'soil_moisture': {'$ne': None}},
                ]
            }).sort('timestamp', -1).limit(limit))

            if not readings:
                return []

            # Build stream_id -> stream_name lookup
            stream_ids = list(set(r['stream_id'] for r in readings if 'stream_id' in r))
            stream_map = {}
            if stream_ids:
                streams = streams_col.find({'id': {'$in': stream_ids}})
                for s in streams:
                    stream_map[s['id']] = s.get('stream_name', 'Unknown')

            rows = []
            for r in readings:
                rows.append({
                    'station_name': stream_map.get(r.get('stream_id'), 'Unknown'),
                    'date': r.get('timestamp', ''),
                    'temperature': r.get('temperature'),
                    'humidity': r.get('humidity'),
                    'rainfall': r.get('rainfall'),
                    'wind_speed': r.get('wind_speed'),
                    'pressure': r.get('pressure'),
                    'co2_level': r.get('co2_level'),
                    'air_quality_index': r.get('air_quality_index'),
                })
            return rows

        def _fetch_climate_data(limit=0, exclude_realtime=False):
            """Fetch batch climate data."""
            query_filter = {'$and': [value_query, {'data_source': {'$ne': 'realtime'}}]} \
                if exclude_realtime else value_query
            query = climate_col.find(query_filter, projection).sort('date', 1)
            if limit:
                query = query.limit(limit)
            return [dict(r) for r in query]

        if '/realtime' in (input_path or '') and '/combined' not in (input_path or ''):
            return _fetch_realtime_readings(10000)
        elif '/combined' in (input_path or ''):
            # Realtime readings are promoted into climate_data, so exclude
            # those copies before adding the source readings below.
            batch_rows = _fetch_climate_data(8000, exclude_realtime=True)
            rt_rows = _fetch_realtime_readings(2000)
            return batch_rows + rt_rows
        elif '/dataset/' in (input_path or ''):
            try:
                dataset_id = int((input_path or '').rstrip('/').rsplit('/', 1)[-1])
            except (TypeError, ValueError):
                return []
            return [dict(r) for r in climate_col.find(
                {'dataset_id': dataset_id, **value_query}, projection
            ).sort('date', 1)]
        elif '/satellite' in (input_path or ''):
            return _fetch_climate_data()
        elif '/weather' in (input_path or ''):
            return _fetch_climate_data()
        else:
            return _fetch_climate_data(10000)

    # ── MAP phase ─────────────────────────────────────────────────────────

    @staticmethod
    def _map_phase(records, job_type):
        """Map phase: transform records into intermediate key-value pairs."""
        mapped = []

        if job_type == 'temperature_analysis':
            for r in records:
                region = r.get('station_name') or 'global'
                temp = r.get('temperature')
                if temp is not None:
                    mapped.append({'key': region, 'metric': 'temperature',
                                   'value': float(temp), 'date': r.get('date', '')})

        elif job_type == 'rainfall_analysis':
            for r in records:
                region = r.get('station_name') or 'global'
                rain = r.get('rainfall')
                if rain is not None:
                    mapped.append({'key': region, 'metric': 'rainfall',
                                   'value': float(rain), 'date': r.get('date', '')})

        elif job_type == 'anomaly_detection':
            for r in records:
                region = r.get('station_name') or 'global'
                temp = r.get('temperature')
                rain = r.get('rainfall')
                aqi = r.get('air_quality_index')
                if temp is not None:
                    mapped.append({'key': region + '_temp', 'value': float(temp),
                                   'date': r.get('date', '')})
                if rain is not None:
                    mapped.append({'key': region + '_rain', 'value': float(rain),
                                   'date': r.get('date', '')})
                if aqi is not None:
                    mapped.append({'key': region + '_aqi', 'value': float(aqi),
                                   'date': r.get('date', '')})

        elif job_type == 'correlation_analysis':
            for r in records:
                region = r.get('station_name') or 'global'
                temp = r.get('temperature')
                rain = r.get('rainfall')
                hum = r.get('humidity')
                aqi = r.get('air_quality_index')
                ws = r.get('wind_speed')
                if temp is not None and rain is not None:
                    mapped.append({'key': region, 'pair': 'temp_rain',
                                   'x': float(temp), 'y': float(rain)})
                if temp is not None and hum is not None:
                    mapped.append({'key': region, 'pair': 'temp_humidity',
                                   'x': float(temp), 'y': float(hum)})
                if temp is not None and aqi is not None:
                    mapped.append({'key': region, 'pair': 'temp_aqi',
                                   'x': float(temp), 'y': float(aqi)})
                if rain is not None and hum is not None:
                    mapped.append({'key': region, 'pair': 'rain_humidity',
                                   'x': float(rain), 'y': float(hum)})

        elif job_type == 'data_aggregation':
            for r in records:
                region = r.get('station_name') or 'global'
                for metric in ['temperature', 'rainfall', 'humidity', 'wind_speed', 'pressure']:
                    val = r.get(metric)
                    if val is not None:
                        mapped.append({'key': region, 'metric': metric,
                                       'value': float(val), 'date': r.get('date', '')})

        elif job_type == 'trend_prediction':
            for r in records:
                region = r.get('station_name') or 'global'
                date = r.get('date', '')
                temp = r.get('temperature')
                co2 = r.get('co2_level')
                if temp is not None:
                    mapped.append({'key': region, 'metric': 'temperature',
                                   'value': float(temp), 'date': date})
                if co2 is not None:
                    mapped.append({'key': region, 'metric': 'co2',
                                   'value': float(co2), 'date': date})

        elif job_type == 'statistical_summary':
            for r in records:
                region = r.get('station_name') or 'global'
                for metric in ['temperature', 'rainfall', 'humidity', 'wind_speed',
                               'pressure', 'co2_level', 'air_quality_index']:
                    val = r.get(metric)
                    if val is not None:
                        mapped.append({'key': region, 'metric': metric,
                                       'value': float(val), 'date': r.get('date', '')})

        elif job_type == 'pattern_detection':
            for r in records:
                region = r.get('station_name') or 'global'
                temp = r.get('temperature')
                rain = r.get('rainfall')
                if temp is not None:
                    mapped.append({'key': region, 'metric': 'temperature',
                                   'value': float(temp), 'date': r.get('date', '')})
                if rain is not None:
                    mapped.append({'key': region, 'metric': 'rainfall',
                                   'value': float(rain), 'date': r.get('date', '')})

        else:
            # Generic: process all metrics
            for r in records:
                region = r.get('station_name') or 'global'
                for metric in ['temperature', 'rainfall', 'humidity']:
                    val = r.get(metric)
                    if val is not None:
                        mapped.append({'key': region, 'metric': metric,
                                       'value': float(val), 'date': r.get('date', '')})

        return mapped

    # ── REDUCE phase ──────────────────────────────────────────────────────

    @staticmethod
    def _reduce_phase(mapped, job_type, raw_records):
        """Reduce phase: aggregate mapped data into final results."""

        if job_type in ('temperature_analysis', 'rainfall_analysis', 'data_aggregation', 'statistical_summary'):
            return MapReduceManager._reduce_aggregation(mapped, job_type)
        elif job_type == 'anomaly_detection':
            return MapReduceManager._reduce_anomaly_detection(mapped, raw_records)
        elif job_type == 'correlation_analysis':
            return MapReduceManager._reduce_correlation(mapped)
        elif job_type == 'trend_prediction':
            return MapReduceManager._reduce_trend(mapped, raw_records)
        elif job_type == 'pattern_detection':
            return MapReduceManager._reduce_pattern_detection(mapped, raw_records)
        else:
            return MapReduceManager._reduce_aggregation(mapped, job_type)

    @staticmethod
    def _reduce_aggregation(mapped, job_type):
        """Aggregate statistics per region per metric."""
        groups = defaultdict(list)
        for item in mapped:
            group_key = (item['key'], item.get('metric', 'value'))
            groups[group_key].append(item['value'])

        results = []
        for (region, metric), values in groups.items():
            count = len(values)
            mean_val = sum(values) / count
            min_val = min(values)
            max_val = max(values)
            variance = sum((x - mean_val) ** 2 for x in values) / count if count > 1 else 0
            std_dev = math.sqrt(variance)
            sorted_vals = sorted(values)
            median_val = sorted_vals[count // 2] if count % 2 == 1 else (sorted_vals[count // 2 - 1] + sorted_vals[count // 2]) / 2

            results.append({
                'region': region,
                'metric': metric,
                'count': count,
                'mean': round(mean_val, 2),
                'min': round(min_val, 2),
                'max': round(max_val, 2),
                'std_dev': round(std_dev, 2),
                'median': round(median_val, 2),
                'sum': round(sum(values), 2),
            })

        results.sort(key=lambda x: (x['region'], x['metric']))
        return {
            'job_type': job_type,
            'phase': 'reduce',
            'aggregations': results,
            'total_groups': len(results),
            'output_records': len(results),
            'summary': {
                'total_records_processed': sum(r['count'] for r in results),
                'unique_regions': len(set(r['region'] for r in results)),
                'metrics_computed': list(set(r['metric'] for r in results)),
            }
        }

    @staticmethod
    def _reduce_anomaly_detection(mapped, raw_records):
        """Detect anomalies using Z-score method on grouped data."""
        groups = defaultdict(list)
        for item in mapped:
            groups[item['key']].append({'value': item['value'], 'date': item.get('date', '')})

        anomalies_found = []
        total_anomalies = 0
        severity_dist = {'critical': 0, 'severe': 0, 'moderate': 0, 'mild': 0}

        for key, entries in groups.items():
            values = [e['value'] for e in entries]
            if len(values) < 3:
                continue

            mean_val = sum(values) / len(values)
            variance = sum((x - mean_val) ** 2 for x in values) / len(values)
            std_dev = math.sqrt(variance)

            if std_dev == 0:
                continue

            for entry in entries:
                z_score = abs((entry['value'] - mean_val) / std_dev)
                if z_score > 2.0:
                    if z_score > 3:
                        sev = 'critical'
                    elif z_score > 2.5:
                        sev = 'severe'
                    elif z_score > 2.0:
                        sev = 'moderate'
                    else:
                        sev = 'mild'

                    severity_dist[sev] = severity_dist.get(sev, 0) + 1
                    total_anomalies += 1
                    anomalies_found.append({
                        'key': key,
                        'date': entry['date'],
                        'value': round(entry['value'], 2),
                        'z_score': round(z_score, 2),
                        'mean': round(mean_val, 2),
                        'std_dev': round(std_dev, 2),
                        'severity': sev,
                    })

        # Sort by z_score descending
        anomalies_found.sort(key=lambda x: x['z_score'], reverse=True)

        # Determine metric types with anomalies
        metric_types = defaultdict(int)
        for a in anomalies_found:
            k = a['key']
            if '_temp' in k:
                metric_types['temperature'] += 1
            elif '_rain' in k:
                metric_types['rainfall'] += 1
            elif '_aqi' in k:
                metric_types['air_quality'] += 1

        most_common = max(metric_types, key=metric_types.get) if metric_types else 'none'

        return {
            'job_type': 'anomaly_detection',
            'phase': 'reduce',
            'total_anomalies': total_anomalies,
            'severity_distribution': severity_dist,
            'most_common_type': most_common,
            'anomalies': anomalies_found[:200],
            'output_records': total_anomalies,
            'summary': {
                'method': 'Z-score (threshold=2.0)',
                'groups_analyzed': len(groups),
                'anomaly_rate': round(total_anomalies / max(1, sum(len(v) for v in groups.values())) * 100, 2),
            },
            'recommendation': 'Review detected anomalies and verify data quality. '
                              'Critical anomalies may indicate sensor malfunction or extreme weather events.'
        }

    @staticmethod
    def _reduce_correlation(mapped):
        """Compute Pearson correlation coefficients between variable pairs."""
        groups = defaultdict(lambda: {'x': [], 'y': []})
        for item in mapped:
            pair_key = (item['key'], item['pair'])
            groups[pair_key]['x'].append(item['x'])
            groups[pair_key]['y'].append(item['y'])

        results = []
        for (region, pair_type), data in groups.items():
            x_vals = data['x']
            y_vals = data['y']
            n = min(len(x_vals), len(y_vals))
            if n < 3:
                continue

            x = x_vals[:n]
            y = y_vals[:n]

            # Pearson correlation
            sum_x = sum(x)
            sum_y = sum(y)
            sum_xy = sum(a * b for a, b in zip(x, y))
            sum_x2 = sum(a ** 2 for a in x)
            sum_y2 = sum(b ** 2 for b in y)

            numerator = n * sum_xy - sum_x * sum_y
            denom_x = n * sum_x2 - sum_x ** 2
            denom_y = n * sum_y2 - sum_y ** 2
            denominator = math.sqrt(max(0, denom_x) * max(0, denom_y))

            r = numerator / denominator if denominator != 0 else 0
            r = max(-1, min(1, r))

            # Classify
            abs_r = abs(r)
            if abs_r >= 0.8:
                strength = 'very strong'
            elif abs_r >= 0.6:
                strength = 'strong'
            elif abs_r >= 0.4:
                strength = 'moderate'
            elif abs_r >= 0.2:
                strength = 'weak'
            else:
                strength = 'very weak'

            direction = 'positive' if r > 0 else 'negative'

            # P-value estimation
            if n > 2 and abs_r < 1:
                t = r * math.sqrt((n - 2) / (1 - r ** 2))
                p_value = 2 * math.exp(-0.717 * abs(t) - 0.416 * t ** 2)
                p_value = max(0.0001, min(1.0, p_value))
            else:
                p_value = 0.001 if abs_r >= 1 else 1.0

            results.append({
                'region': region,
                'pair': pair_type,
                'correlation': round(r, 4),
                'p_value': round(p_value, 4),
                'significant': p_value < 0.05,
                'strength': strength,
                'direction': direction,
                'sample_size': n,
                'interpretation': f"A {strength} {direction} correlation exists between {pair_type.replace('_', ' and ')}.",
            })

        results.sort(key=lambda x: abs(x['correlation']), reverse=True)

        return {
            'job_type': 'correlation_analysis',
            'phase': 'reduce',
            'correlations': results,
            'total_pairs': len(results),
            'significant_pairs': sum(1 for r in results if r['significant']),
            'output_records': len(results),
            'summary': {
                'method': 'Pearson correlation coefficient',
                'regions_analyzed': len(set(r['region'] for r in results)),
                'variable_pairs': list(set(r['pair'] for r in results)),
            }
        }

    @staticmethod
    def _reduce_trend(mapped, raw_records):
        """Compute trend analysis using linear regression on time series."""
        groups = defaultdict(list)
        for item in mapped:
            groups[(item['key'], item['metric'])].append({
                'value': item['value'], 'date': item.get('date', '')
            })

        trends = []
        for (region, metric), entries in groups.items():
            # Sort by date
            entries.sort(key=lambda x: x['date'])
            values = [e['value'] for e in entries]
            n = len(values)
            if n < 3:
                continue

            # Linear regression: y = a + b*x
            x_vals = list(range(n))
            mean_x = sum(x_vals) / n
            mean_y = sum(values) / n

            num = sum((x_vals[i] - mean_x) * (values[i] - mean_y) for i in range(n))
            den = sum((x_vals[i] - mean_x) ** 2 for i in range(n))

            slope = num / den if den != 0 else 0
            intercept = mean_y - slope * mean_x

            # R-squared
            predicted = [slope * x + intercept for x in x_vals]
            ss_res = sum((values[i] - predicted[i]) ** 2 for i in range(n))
            ss_tot = sum((values[i] - mean_y) ** 2 for i in range(n))
            r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

            # Trend per decade (extrapolate slope over ~3650 data points)
            trend_per_period = slope
            direction = 'increasing' if slope > 0.01 else ('decreasing' if slope < -0.01 else 'stable')

            trends.append({
                'region': region,
                'metric': metric,
                'slope_per_record': round(slope, 6),
                'trend_direction': direction,
                'r_squared': round(max(0, r_squared), 4),
                'mean_value': round(mean_y, 2),
                'min_value': round(min(values), 2),
                'max_value': round(max(values), 2),
                'data_points': n,
                'first_date': entries[0]['date'],
                'last_date': entries[-1]['date'],
            })

        return {
            'job_type': 'trend_prediction',
            'phase': 'reduce',
            'trends': trends,
            'total_trends': len(trends),
            'output_records': len(trends),
            'summary': {
                'method': 'Linear regression (OLS)',
                'regions_analyzed': len(set(t['region'] for t in trends)),
                'metrics_analyzed': list(set(t['metric'] for t in trends)),
            }
        }

    @staticmethod
    def _reduce_pattern_detection(mapped, raw_records):
        """Detect climate patterns: seasonal, trend, cyclical."""
        groups = defaultdict(list)
        for item in mapped:
            groups[(item['key'], item['metric'])].append({
                'value': item['value'], 'date': item.get('date', '')
            })

        patterns = []
        for (region, metric), entries in groups.items():
            entries.sort(key=lambda x: x['date'])
            values = [e['value'] for e in entries]
            n = len(values)
            if n < 4:
                continue

            mean_val = sum(values) / n
            variance = sum((x - mean_val) ** 2 for x in values) / n
            std_dev = math.sqrt(variance)

            # Detect seasonal pattern: compare monthly averages
            monthly = defaultdict(list)
            for e in entries:
                if e['date'] and len(e['date']) >= 7:
                    month = e['date'][5:7]
                    monthly[month].append(e['value'])

            seasonal_strength = 0
            monthly_means = {}
            if len(monthly) >= 3:
                for m, vals in monthly.items():
                    monthly_means[m] = sum(vals) / len(vals)
                monthly_vals = list(monthly_means.values())
                if len(monthly_vals) >= 3:
                    month_variance = sum((v - mean_val) ** 2 for v in monthly_vals) / len(monthly_vals)
                    seasonal_strength = min(1.0, math.sqrt(month_variance) / std_dev) if std_dev > 0 else 0

            # Detect trend
            x_vals = list(range(n))
            slope = 0
            if n >= 3:
                mean_x = sum(x_vals) / n
                num = sum((x_vals[i] - mean_x) * (values[i] - mean_val) for i in range(n))
                den = sum((x_vals[i] - mean_x) ** 2 for i in range(n))
                slope = num / den if den != 0 else 0

            trend_direction = 'increasing' if slope > 0.01 else ('decreasing' if slope < -0.01 else 'stable')

            # Detect outliers (potential extreme events)
            outlier_count = 0
            if std_dev > 0:
                for v in values:
                    z = abs((v - mean_val) / std_dev)
                    if z > 2.0:
                        outlier_count += 1

            # Classify overall pattern
            if seasonal_strength > 0.5:
                pattern_type = 'seasonal'
            elif abs(slope) > 0.05:
                pattern_type = 'trend'
            elif outlier_count > n * 0.05:
                pattern_type = 'extreme_events'
            else:
                pattern_type = 'stable'

            patterns.append({
                'region': region,
                'metric': metric,
                'pattern_type': pattern_type,
                'seasonal_strength': round(seasonal_strength, 4),
                'trend_direction': trend_direction,
                'trend_slope': round(slope, 6),
                'outlier_count': outlier_count,
                'mean': round(mean_val, 2),
                'std_dev': round(std_dev, 2),
                'data_points': n,
                'monthly_averages': {k: round(v, 2) for k, v in sorted(monthly_means.items())},
            })

        return {
            'job_type': 'pattern_detection',
            'phase': 'reduce',
            'patterns': patterns,
            'total_patterns': len(patterns),
            'output_records': len(patterns),
            'summary': {
                'method': 'Seasonal decomposition + trend analysis + outlier detection',
                'regions_analyzed': len(set(p['region'] for p in patterns)),
                'pattern_types_found': list(set(p['pattern_type'] for p in patterns)),
            }
        }

    @staticmethod
    def _finalize_aggregation_from_groups(groups, job_type):
        """Finalize aggregation results directly from grouped values."""
        results = []
        for (region, metric), vals in groups.items():
            # vals may be list of numbers
            if not vals:
                continue
            # if stored as dict entries (from trend/pattern), extract numeric values
            if isinstance(vals[0], dict):
                values = [v['value'] for v in vals]
            else:
                values = list(vals)
            count = len(values)
            mean_val = sum(values) / count
            min_val = min(values)
            max_val = max(values)
            variance = sum((x - mean_val) ** 2 for x in values) / count if count > 1 else 0
            std_dev = math.sqrt(variance)
            sorted_vals = sorted(values)
            median_val = sorted_vals[count // 2] if count % 2 == 1 else (sorted_vals[count // 2 - 1] + sorted_vals[count // 2]) / 2
            results.append({
                'region': region,
                'metric': metric,
                'count': count,
                'mean': round(mean_val, 2),
                'min': round(min_val, 2),
                'max': round(max_val, 2),
                'std_dev': round(std_dev, 2),
                'median': round(median_val, 2),
                'sum': round(sum(values), 2),
            })
        results.sort(key=lambda x: (x['region'], x['metric']))
        return {
            'job_type': job_type,
            'phase': 'reduce',
            'aggregations': results,
            'total_groups': len(results),
            'output_records': len(results),
            'summary': {
                'total_records_processed': sum(r['count'] for r in results),
                'unique_regions': len(set(r['region'] for r in results)),
                'metrics_computed': list(set(r['metric'] for r in results)),
            }
        }

    @staticmethod
    def _finalize_anomaly_from_groups(groups):
        """Finalize anomaly detection from grouped time series (value/date)."""
        anomalies_found = []
        total_anomalies = 0
        severity_dist = {'critical': 0, 'severe': 0, 'moderate': 0, 'mild': 0}
        for key, entries in groups.items():
            values = [e['value'] for e in entries]
            if len(values) < 3:
                continue
            mean_val = sum(values) / len(values)
            variance = sum((x - mean_val) ** 2 for x in values) / len(values)
            std_dev = math.sqrt(variance)
            if std_dev == 0:
                continue
            for entry in entries:
                z_score = abs((entry['value'] - mean_val) / std_dev)
                if z_score > 2.0:
                    if z_score > 3:
                        sev = 'critical'
                    elif z_score > 2.5:
                        sev = 'severe'
                    else:
                        sev = 'moderate'
                    severity_dist[sev] = severity_dist.get(sev, 0) + 1
                    total_anomalies += 1
                    anomalies_found.append({
                        'key': key,
                        'date': entry.get('date', ''),
                        'value': round(entry['value'], 2),
                        'z_score': round(z_score, 2),
                        'mean': round(mean_val, 2),
                        'std_dev': round(std_dev, 2),
                        'severity': sev,
                    })
        anomalies_found.sort(key=lambda x: x['z_score'], reverse=True)
        # metric type heuristic
        metric_types = defaultdict(int)
        for a in anomalies_found:
            k = a['key']
            if '_temp' in k:
                metric_types['temperature'] += 1
            elif '_rain' in k:
                metric_types['rainfall'] += 1
            elif '_aqi' in k:
                metric_types['air_quality'] += 1
        most_common = max(metric_types, key=metric_types.get) if metric_types else 'none'
        return {
            'job_type': 'anomaly_detection',
            'phase': 'reduce',
            'total_anomalies': total_anomalies,
            'severity_distribution': severity_dist,
            'most_common_type': most_common,
            'anomalies': anomalies_found[:200],
            'output_records': total_anomalies,
            'summary': {
                'method': 'Z-score (threshold=2.0)',
                'groups_analyzed': len(groups),
                'anomaly_rate': round(total_anomalies / max(1, sum(len(v) for v in groups.values())) * 100, 2),
            },
            'recommendation': 'Review detected anomalies and verify data quality. Critical anomalies may indicate sensor malfunction or extreme weather events.'
        }

    @staticmethod
    def _finalize_correlation_from_groups(groups):
        """Finalize correlation results from grouped x/y arrays."""
        results = []
        for (region, pair_type), data in groups.items():
            x_vals = data.get('x', [])
            y_vals = data.get('y', [])
            n = min(len(x_vals), len(y_vals))
            if n < 3:
                continue
            x = x_vals[:n]
            y = y_vals[:n]
            sum_x = sum(x)
            sum_y = sum(y)
            sum_xy = sum(a * b for a, b in zip(x, y))
            sum_x2 = sum(a ** 2 for a in x)
            sum_y2 = sum(b ** 2 for b in y)
            numerator = n * sum_xy - sum_x * sum_y
            denom_x = n * sum_x2 - sum_x ** 2
            denom_y = n * sum_y2 - sum_y ** 2
            denominator = math.sqrt(max(0, denom_x) * max(0, denom_y))
            r = numerator / denominator if denominator != 0 else 0
            r = max(-1, min(1, r))
            abs_r = abs(r)
            if abs_r >= 0.8:
                strength = 'very strong'
            elif abs_r >= 0.6:
                strength = 'strong'
            elif abs_r >= 0.4:
                strength = 'moderate'
            elif abs_r >= 0.2:
                strength = 'weak'
            else:
                strength = 'very weak'
            direction = 'positive' if r > 0 else 'negative'
            if n > 2 and abs_r < 1:
                t = r * math.sqrt((n - 2) / (1 - r ** 2))
                p_value = 2 * math.exp(-0.717 * abs(t) - 0.416 * t ** 2)
                p_value = max(0.0001, min(1.0, p_value))
            else:
                p_value = 0.001 if abs_r >= 1 else 1.0
            results.append({
                'region': region,
                'pair': pair_type,
                'correlation': round(r, 4),
                'p_value': round(p_value, 4),
                'significant': p_value < 0.05,
                'strength': strength,
                'direction': direction,
                'sample_size': n,
                'interpretation': f"A {strength} {direction} correlation exists between {pair_type.replace('_', ' and ') }.",
            })
        results.sort(key=lambda x: abs(x['correlation']), reverse=True)
        return {
            'job_type': 'correlation_analysis',
            'phase': 'reduce',
            'correlations': results,
            'total_pairs': len(results),
            'significant_pairs': sum(1 for r in results if r['significant']),
            'output_records': len(results),
            'summary': {
                'method': 'Pearson correlation coefficient',
                'regions_analyzed': len(set(r['region'] for r in results)),
                'variable_pairs': list(set(r['pair'] for r in results)),
            }
        }

    @staticmethod
    def _finalize_trend_from_groups(groups):
        """Compute trends from grouped time series data."""
        trends = []
        for (region, metric), entries in groups.items():
            # entries may be list of dicts with 'value' and 'date'
            if not entries:
                continue
            entries_sorted = sorted(entries, key=lambda x: x.get('date', ''))
            values = [e['value'] for e in entries_sorted]
            n = len(values)
            if n < 3:
                continue
            x_vals = list(range(n))
            mean_x = sum(x_vals) / n
            mean_y = sum(values) / n
            num = sum((x_vals[i] - mean_x) * (values[i] - mean_y) for i in range(n))
            den = sum((x_vals[i] - mean_x) ** 2 for i in range(n))
            slope = num / den if den != 0 else 0
            intercept = mean_y - slope * mean_x
            predicted = [slope * x + intercept for x in x_vals]
            ss_res = sum((values[i] - predicted[i]) ** 2 for i in range(n))
            ss_tot = sum((values[i] - mean_y) ** 2 for i in range(n))
            r_squared = 1 - (ss_res / ss_tot) if ss_tot != 0 else 0
            trends.append({
                'region': region,
                'metric': metric,
                'slope_per_record': round(slope, 6),
                'trend_direction': 'increasing' if slope > 0.01 else ('decreasing' if slope < -0.01 else 'stable'),
                'r_squared': round(max(0, r_squared), 4),
                'mean_value': round(mean_y, 2),
                'min_value': round(min(values), 2),
                'max_value': round(max(values), 2),
                'data_points': n,
                'first_date': entries_sorted[0].get('date', ''),
                'last_date': entries_sorted[-1].get('date', ''),
            })
        return {
            'job_type': 'trend_prediction',
            'phase': 'reduce',
            'trends': trends,
            'total_trends': len(trends),
            'output_records': len(trends),
            'summary': {
                'method': 'Linear regression (OLS)',
                'regions_analyzed': len(set(t['region'] for t in trends)),
                'metrics_analyzed': list(set(t['metric'] for t in trends)),
            }
        }

    @staticmethod
    def _finalize_pattern_from_groups(groups):
        """Finalize pattern detection from grouped series data."""
        patterns = []
        for (region, metric), entries in groups.items():
            entries_sorted = sorted(entries, key=lambda x: x.get('date', ''))
            values = [e['value'] for e in entries_sorted]
            n = len(values)
            if n < 4:
                continue
            mean_val = sum(values) / n
            variance = sum((x - mean_val) ** 2 for x in values) / n
            std_dev = math.sqrt(variance)
            monthly = defaultdict(list)
            for e in entries_sorted:
                if e.get('date') and len(e.get('date')) >= 7:
                    month = e['date'][5:7]
                    monthly[month].append(e['value'])
            seasonal_strength = 0
            monthly_means = {}
            if len(monthly) >= 3:
                for m, vals in monthly.items():
                    monthly_means[m] = sum(vals) / len(vals)
                monthly_vals = list(monthly_means.values())
                if len(monthly_vals) >= 3:
                    month_variance = sum((v - mean_val) ** 2 for v in monthly_vals) / len(monthly_vals)
                    seasonal_strength = min(1.0, math.sqrt(month_variance) / std_dev) if std_dev > 0 else 0
            x_vals = list(range(n))
            slope = 0
            if n >= 3:
                mean_x = sum(x_vals) / n
                num = sum((x_vals[i] - mean_x) * (values[i] - mean_val) for i in range(n))
                den = sum((x_vals[i] - mean_x) ** 2 for i in range(n))
                slope = num / den if den != 0 else 0
            trend_direction = 'increasing' if slope > 0.01 else ('decreasing' if slope < -0.01 else 'stable')
            outlier_count = 0
            if std_dev > 0:
                for v in values:
                    z = abs((v - mean_val) / std_dev)
                    if z > 2.0:
                        outlier_count += 1
            if seasonal_strength > 0.5:
                pattern_type = 'seasonal'
            elif abs(slope) > 0.05:
                pattern_type = 'trend'
            elif outlier_count > n * 0.05:
                pattern_type = 'extreme_events'
            else:
                pattern_type = 'stable'
            patterns.append({
                'region': region,
                'metric': metric,
                'pattern_type': pattern_type,
                'seasonal_strength': round(seasonal_strength, 4),
                'trend_direction': trend_direction,
                'trend_slope': round(slope, 6),
                'outlier_count': outlier_count,
                'mean': round(mean_val, 2),
                'std_dev': round(std_dev, 2),
                'data_points': n,
                'monthly_averages': {k: round(v, 2) for k, v in sorted(monthly_means.items())},
            })
        return {
            'job_type': 'pattern_detection',
            'phase': 'reduce',
            'patterns': patterns,
            'total_patterns': len(patterns),
            'output_records': len(patterns),
            'summary': {
                'method': 'Seasonal decomposition + trend analysis + outlier detection',
                'regions_analyzed': len(set(p['region'] for p in patterns)),
                'pattern_types_found': list(set(p['pattern_type'] for p in patterns)),
            }
        }

    # ── Query methods ─────────────────────────────────────────────────────

    @staticmethod
    def get_all_jobs(limit=50):
        col = get_collection('mapreduce_jobs')
        docs = list(col.find().sort('created_at', -1).limit(limit))
        return [dict(d) for d in docs]

    @staticmethod
    def get_jobs_by_user(submitted_by, limit=50):
        """Jobs submitted by a specific user (used by the Analyst panel so
        each analyst tracks their own processing workloads)."""
        col = get_collection('mapreduce_jobs')
        docs = list(col.find({'submitted_by': submitted_by}).sort('created_at', -1).limit(limit))
        return [dict(d) for d in docs]

    @staticmethod
    def get_job_stats(jobs=None):
        """Aggregate monitoring statistics across the given job list."""
        if jobs is None:
            jobs = MapReduceManager.get_all_jobs()
        completed = [j for j in jobs if j.get('status') == 'completed']
        durations = [j.get('execution_time') or 0 for j in completed]
        return {
            'total': len(jobs),
            'running': sum(1 for j in jobs if j.get('status') == 'running'),
            'pending': sum(1 for j in jobs if j.get('status') == 'pending'),
            'completed': len(completed),
            'failed': sum(1 for j in jobs if j.get('status') == 'failed'),
            'cancelled': sum(1 for j in jobs if j.get('status') == 'cancelled'),
            'avg_execution_time': round(sum(durations) / len(durations), 2) if durations else 0,
            'input_records': sum(j.get('input_records') or 0 for j in jobs),
            'output_records': sum(j.get('output_records') or 0 for j in jobs),
        }

    @staticmethod
    def get_job(job_id):
        col = get_collection('mapreduce_jobs')
        doc = col.find_one({'id': job_id})
        return dict(doc) if doc else None

    @staticmethod
    def get_running_jobs():
        col = get_collection('mapreduce_jobs')
        docs = list(col.find({'status': 'running'}))
        return [dict(d) for d in docs]

    @staticmethod
    def get_job_count():
        col = get_collection('mapreduce_jobs')
        return col.count_documents({})

    @staticmethod
    def get_job_types():
        return [
            {'value': 'temperature_analysis', 'label': 'Temperature Analysis'},
            {'value': 'rainfall_analysis', 'label': 'Rainfall Analysis'},
            {'value': 'anomaly_detection', 'label': 'Anomaly Detection'},
            {'value': 'correlation_analysis', 'label': 'Correlation Analysis'},
            {'value': 'data_aggregation', 'label': 'Data Aggregation'},
            {'value': 'trend_prediction', 'label': 'Trend Prediction'},
            {'value': 'pattern_detection', 'label': 'Pattern Detection'},
            {'value': 'statistical_summary', 'label': 'Statistical Summary'},
        ]

    @staticmethod
    def cancel_job(job_id):
        """Cancel a running job. Returns True only if a running job was
        actually transitioned to cancelled."""
        col = get_collection('mapreduce_jobs')
        res = col.update_one(
            {'id': job_id, 'status': 'running'},
            {'$set': {'status': 'cancelled', 'completed_at': datetime.utcnow().isoformat()}},
        )
        return res.modified_count > 0

    @staticmethod
    def update_job(job_id, job_name, job_type, input_path, output_path, num_reducers, mapper_code='', reducer_code='', use_hadoop=False):
        """Update a finished job's parameters and reset it for a fresh run.

        Returns the job_id if the job was found and was in a final state,
        otherwise None (running/pending jobs must be cancelled first).
        """
        col = get_collection('mapreduce_jobs')
        input_params = {
            'input_path': input_path,
            'output_path': output_path,
            'num_reducers': max(1, min(int(num_reducers or 2), 10)),
            'job_type': job_type,
            'use_hadoop': bool(use_hadoop),
        }
        res = col.update_one(
            {'id': job_id, 'status': {'$in': ['completed', 'failed', 'cancelled']}},
            {'$set': {
                'job_name': job_name,
                'job_type': job_type,
                'input_path': input_path,
                'mapper_code': mapper_code or '',
                'reducer_code': reducer_code or '',
                'input_params': json.dumps(input_params),
                'status': 'running',
                'progress': 0,
                'input_records': 0,
                'output_records': 0,
                'execution_time': 0,
                'result': None,
                'error_message': None,
                'started_at': datetime.utcnow().isoformat(),
                'completed_at': None,
                'updated_at': datetime.utcnow().isoformat(),
            }},
        )
        return job_id if res.modified_count > 0 else None


    @staticmethod
    def delete_job(job_id, submitted_by=None):
        """Atomically delete a finished shared job record.

        The optional owner constraint lets the Analyst endpoint enforce
        ownership in the same database operation that performs the delete.
        """
        col = get_collection('mapreduce_jobs')
        query = {'id': job_id, 'status': {'$in': ['completed', 'failed', 'cancelled']}}
        if submitted_by is not None:
            query['submitted_by'] = submitted_by
        res = col.delete_one(
            query
        )
        return res.deleted_count > 0
