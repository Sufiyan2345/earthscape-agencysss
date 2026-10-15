"""
Local Hadoop Streaming adapter (fallback) for EarthScape Climate

This adapter provides a simple local runner for mapper/reducer scripts (the ones
in hadoop/mapreduce/). It is intended as a pragmatic way to run MapReduce-style
jobs end-to-end when a Hadoop cluster (HDFS/YARN) is not available.

Limitations:
- Mapper output is sorted in-memory (lines read into a list) before feeding the
  reducer. This is acceptable for moderate-size datasets but not for very large
  ones. For massive data, replace the sort with an external merge-sort or use
  a real Hadoop cluster.
- The adapter expects mapper/reducer scripts to follow the project's
  hadoop/mapreduce/ mapper.py and reducer.py semantics (tab-separated fields,
  JSON in the reducer payloads).

API:
- run_streaming_job(records_iterable, mapper_path, reducer_path, job_type) -> (ok, result_dict)

"""

import os
import sys
import json
import tempfile
import subprocess
import shutil


def _job_type_to_mapper_type(job_type):
    if job_type == 'anomaly_detection':
        return 'anomaly'
    if job_type == 'correlation_analysis':
        return 'correlation'
    return 'climate'


def run_streaming_job(records_iterable, mapper_path, reducer_path, job_type='temperature_analysis', temp_dir=None):
    """
    Run a local streaming job using the provided mapper and reducer scripts.

    records_iterable: iterable of dict (climate records) that will be written as JSON lines
    mapper_path: path to mapper.py
    reducer_path: path to reducer.py
    job_type: logical job type (used to pick mapper/reducer modes)

    Returns: (ok: bool, result: dict)
    """
    temp_base = None
    try:
        if temp_dir:
            temp_base = tempfile.mkdtemp(dir=temp_dir)
        else:
            temp_base = tempfile.mkdtemp()

        input_path = os.path.join(temp_base, 'stream_input.jsonl')
        mapper_out = os.path.join(temp_base, 'mapper_out.txt')
        mapper_sorted = os.path.join(temp_base, 'mapper_sorted.txt')

        # Write input as JSON lines
        with open(input_path, 'w', encoding='utf-8') as inf:
            count = 0
            for rec in records_iterable:
                try:
                    inf.write(json.dumps(rec, ensure_ascii=False) + '\n')
                    count += 1
                except Exception:
                    # skip non-serializable records
                    continue

        if count == 0:
            return True, {'message': 'No input records for streaming job', 'output_records': 0}

        mapper_type = _job_type_to_mapper_type(job_type)
        reducer_type = mapper_type

        # Run mapper
        mapper_cmd = [sys.executable, mapper_path, mapper_type]
        with open(input_path, 'rb') as fin, open(mapper_out, 'wb') as mout:
            proc = subprocess.run(mapper_cmd, stdin=fin, stdout=mout, stderr=subprocess.PIPE)
            if proc.returncode != 0:
                # capture stderr and return failure
                stderr = proc.stderr.decode('utf-8', errors='replace')
                return False, {'error': 'Mapper failed', 'stderr': stderr}

        # Read mapper output and sort lines (simple in-memory sort). This is a
        # pragmatic approach for local runs; replace with external sort for big data.
        with open(mapper_out, 'r', encoding='utf-8') as mout:
            lines = [l for l in (ln.rstrip('\n') for ln in mout) if l and not l.startswith('MAPPER_ERROR')]

        if not lines:
            return True, {'message': 'Mapper produced no output', 'output_records': 0}

        lines.sort()

        with open(mapper_sorted, 'w', encoding='utf-8') as ms:
            ms.write('\n'.join(lines) + '\n')

        # Run reducer
        reducer_cmd = [sys.executable, reducer_path, reducer_type]
        proc = subprocess.run(reducer_cmd, stdin=open(mapper_sorted, 'rb'), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if proc.returncode != 0:
            stderr = proc.stderr.decode('utf-8', errors='replace')
            return False, {'error': 'Reducer failed', 'stderr': stderr}

        stdout = proc.stdout.decode('utf-8', errors='replace')
        out_lines = [ln for ln in (l.strip() for l in stdout.splitlines()) if ln]

        # Parse reducer output lines. We expect tab-separated fields with JSON payload
        aggregations = []
        anomalies = []
        correlations = []

        for line in out_lines:
            parts = line.split('\t')
            if not parts:
                continue
            try:
                if job_type in ('temperature_analysis', 'rainfall_analysis', 'data_aggregation', 'statistical_summary'):
                    # region \t metric \t json
                    if len(parts) >= 3:
                        payload = json.loads(parts[2])
                        aggregations.append(payload)
                elif job_type == 'anomaly_detection':
                    # key \t json
                    if len(parts) >= 2:
                        payload = json.loads(parts[1])
                        anomalies.append(payload)
                elif job_type == 'correlation_analysis':
                    # region \t pair \t json
                    if len(parts) >= 3:
                        payload = json.loads(parts[2])
                        correlations.append(payload)
                else:
                    # Generic: try to parse last field as JSON
                    try:
                        payload = json.loads(parts[-1])
                        aggregations.append(payload)
                    except Exception:
                        # fallback: capture raw line
                        aggregations.append({'raw': line})
            except Exception:
                # skip malformed lines
                continue

        result = {
            'job_type': job_type,
            'aggregations': aggregations,
            'anomalies': anomalies,
            'correlations': correlations,
            'output_records': len(aggregations) + len(anomalies) + len(correlations)
        }

        return True, result

    except Exception as e:
        return False, {'error': str(e)}
    finally:
        try:
            if temp_base and os.path.isdir(temp_base):
                shutil.rmtree(temp_base)
        except Exception:
            pass
