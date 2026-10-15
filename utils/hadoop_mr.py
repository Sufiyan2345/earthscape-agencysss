"""
Real Hadoop MapReduce job submitter for EarthScape Climate System.

Submits MapReduce jobs to a real Hadoop cluster via the Hadoop REST API / YARN.
Falls back to local Python-based MapReduce simulation when Hadoop is unavailable.

Set environment variables:
  HDFS_USE_REAL=true
  HADOOP_HOME=/path/to/hadoop  (for local job submission)
  HADOOP_RESOURCE_MANAGER=http://resourcemanager:8088
"""

import os
import glob
import json
import subprocess
import requests
from datetime import datetime
from config import Config


class HadoopJobSubmitter:
    """Submit real MapReduce jobs to Hadoop/YARN."""

    def __init__(self):
        self.rm_url = os.environ.get(
            'HADOOP_RESOURCE_MANAGER',
            'http://localhost:8088'
        )
        self.hadoop_home = os.environ.get('HADOOP_HOME', '')
        self.hadoop_jar = os.path.join(
            self.hadoop_home, 'bin', 'hadoop'
        ) if self.hadoop_home else ''

    def is_available(self):
        """Check if Hadoop/YARN is reachable."""
        try:
            r = requests.get(
                f"{self.rm_url}/ws/v1/cluster/info",
                timeout=3
            )
            return r.status_code == 200
        except Exception:
            return False

    def get_cluster_info(self):
        """Get YARN cluster info."""
        try:
            r = requests.get(
                f"{self.rm_url}/ws/v1/cluster/info",
                timeout=1
            )
            if r.status_code == 200:
                return r.json().get('clusterMetrics', {})
        except Exception:
            pass
        return None

    def get_cluster_metrics(self):
        """Get YARN cluster metrics."""
        try:
            r = requests.get(
                f"{self.rm_url}/ws/v1/cluster/metrics",
                timeout=1
            )
            if r.status_code == 200:
                return r.json().get('clusterMetrics', {})
        except Exception:
            pass
        return None

    def submit_jar_job(self, jar_path, main_class, input_path, output_path,
                       mapper_class=None, reducer_class=None, args=None):
        """
        Submit a real Hadoop MapReduce job via `hadoop jar` command.
        Returns (success, job_id, message).
        """
        if not self.hadoop_home or not os.path.exists(self.hadoop_jar):
            return False, None, 'HADOOP_HOME not set or hadoop binary not found'

        cmd = [self.hadoop_jar, 'jar', jar_path, main_class]
        cmd.extend([input_path, output_path])
        if mapper_class:
            cmd.extend(['-mapper', mapper_class])
        if reducer_class:
            cmd.extend(['-reducer', reducer_class])
        if args:
            cmd.extend(args)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300
            )
            if result.returncode == 0:
                # Extract job ID from output
                job_id = self._extract_job_id(result.stdout + result.stderr)
                return True, job_id, 'Job submitted successfully'
            else:
                return False, None, f'Job failed: {result.stderr[:500]}'
        except subprocess.TimeoutExpired:
            return False, None, 'Job submission timed out (300s)'
        except Exception as e:
            return False, None, str(e)

    def submit_streaming_job(self, input_path, output_path, job_type='climate',
                             num_reducers=1, mapper_path=None, reducer_path=None):
        """Submit the repository mapper/reducer to a real Hadoop cluster."""
        streaming_jar = os.environ.get('HADOOP_STREAMING_JAR', '')
        if '*' in streaming_jar:
            streaming_jar = next(iter(glob.glob(streaming_jar)), '')
        if not streaming_jar or not os.path.exists(streaming_jar):
            return False, None, 'Set HADOOP_STREAMING_JAR to hadoop-streaming.jar'
        hadoop_cmd = self.hadoop_jar if self.hadoop_jar and os.path.exists(self.hadoop_jar) else os.path.join(self.hadoop_home, 'bin', 'hadoop.cmd')
        if not os.path.exists(hadoop_cmd):
            return False, None, 'HADOOP_HOME does not contain hadoop or hadoop.cmd'
        mapper_path = mapper_path or os.path.join(os.getcwd(), 'hadoop', 'mapreduce', 'mapper.py')
        reducer_path = reducer_path or os.path.join(os.getcwd(), 'hadoop', 'mapreduce', 'reducer.py')
        mapper_mode = 'anomaly' if job_type == 'anomaly_detection' else ('correlation' if job_type == 'correlation_analysis' else 'climate')
        cmd = [hadoop_cmd, 'jar', streaming_jar,
               '-input', input_path, '-output', output_path,
               '-mapper', f'python3 mapper.py {mapper_mode}',
               '-reducer', f'python3 reducer.py {mapper_mode}',
               '-file', mapper_path, '-file', reducer_path,
               '-numReduceTasks', str(max(1, int(num_reducers or 1)))]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            output = result.stdout + result.stderr
            return (True, self._extract_job_id(output), 'Streaming job submitted successfully') if result.returncode == 0 else (False, None, output[-1000:])
        except subprocess.TimeoutExpired:
            return False, None, 'Streaming job submission timed out (300s)'
        except Exception as exc:
            return False, None, str(exc)

    def submit_yarn_job(self, jar_path, main_class, input_path, output_path,
                        job_name='EarthScape_MR', queues='default',
                        mapper_class=None, reducer_class=None,
                        num_reducers=1, extra_args=None):
        """
        Submit job via YARN REST API (if available).
        """
        try:
            # Try submitting via REST API
            job_config = {
                'application-name': job_name,
                'type': 'MAPREDUCE',
            }
            r = requests.post(
                f"{self.rm_url}/ws/v1/cluster/apps",
                json=job_config,
                timeout=10
            )
            if r.status_code in (200, 202):
                app_id = r.json().get('id', '')
                return True, app_id, 'Job submitted via YARN REST API'
        except Exception:
            pass

        # Fallback to hadoop jar command
        return self.submit_jar_job(
            jar_path, main_class, input_path, output_path,
            mapper_class, reducer_class
        )

    def get_job_status(self, job_id):
        """Get status of a YARN job."""
        try:
            r = requests.get(
                f"{self.rm_url}/ws/v1/cluster/apps/{job_id}",
                timeout=5
            )
            if r.status_code == 200:
                app = r.json().get('app', {})
                return {
                    'id': app.get('id', job_id),
                    'name': app.get('name', ''),
                    'state': app.get('state', 'UNKNOWN'),
                    'status': app.get('finalStatus', 'UNDEFINED'),
                    'progress': app.get('progress', 0),
                    'start_time': app.get('startedTime', 0),
                    'finish_time': app.get('finishedTime', 0),
                    'user': app.get('user', ''),
                    'queue': app.get('queue', 'default'),
                }
        except Exception:
            pass
        return None

    def get_running_jobs(self):
        """Get list of running YARN applications."""
        try:
            r = requests.get(
                f"{self.rm_url}/ws/v1/cluster/apps",
                params={'states': 'RUNNING,ACCEPTED,NEW'},
                timeout=5
            )
            if r.status_code == 200:
                apps = r.json().get('apps', {}).get('app', [])
                return [
                    {
                        'id': a.get('id', ''),
                        'name': a.get('name', ''),
                        'state': a.get('state', ''),
                        'progress': a.get('progress', 0),
                        'user': a.get('user', ''),
                    }
                    for a in apps
                ]
        except Exception:
            pass
        return []

    def kill_job(self, job_id):
        """Kill a running YARN job."""
        try:
            r = requests.put(
                f"{self.rm_url}/ws/v1/cluster/apps/{job_id}/state",
                json={'state': 'KILLED'},
                timeout=5
            )
            return r.status_code == 200
        except Exception:
            return False

    def _extract_job_id(self, output):
        """Extract Hadoop job ID from command output."""
        import re
        match = re.search(r'job_\d+_\d+', output)
        if match:
            return match.group(0)
        match = re.search(r'application_\d+_\d+', output)
        if match:
            return match.group(0)
        return None


class MapReduceBridge:
    """
    Bridge between the EarthScape MapReduce system and real Hadoop.
    Routes jobs to real Hadoop when available, otherwise uses local simulation.
    """

    def __init__(self):
        self.hadoop = HadoopJobSubmitter()

    def is_hadoop_available(self):
        return self.hadoop.is_available()

    def get_cluster_info(self):
        info = self.hadoop.get_cluster_info()
        if info:
            return {
                'status': 'connected',
                'backend': 'Real Hadoop/YARN',
                'resource_manager': self.hadoop.rm_url,
                'total_mb': info.get('totalMB', 0),
                'reserved_mb': info.get('reservedMB', 0),
                'available_mb': info.get('availableMB', 0),
                'total_vcores': info.get('totalVirtualCores', 0),
                'apps_running': info.get('appsRunning', 0),
                'nodes_active': info.get('activeNodes', 0),
            }
        return {
            'status': 'connected',
            'backend': 'Local simulation',
            'message': 'Set HDFS_USE_REAL=true and configure HADOOP_HOME for real Hadoop.',
        }

    def submit_job(self, job_name, job_type, input_path, output_path=None,
                   submitted_by=None, mapper_code='', reducer_code='',
                   input_params=None):
        """
        Submit a MapReduce job.
        If real Hadoop is available, submit to YARN.
        Otherwise, use local Python simulation.
        """
        if self.is_hadoop_available() and output_path:
            success, job_id, msg = self.hadoop.submit_streaming_job(
                input_path=input_path,
                output_path=output_path or f'/climate/results/{job_name}',
                job_type=job_type,
                num_reducers=(input_params or {}).get('num_reducers', 1),
            )
            return {
                'submitted_to': 'real_hadoop',
                'job_id': job_id,
                'success': success,
                'message': msg,
            }

        # Fallback: local simulation
        return {
            'submitted_to': 'local_simulation',
            'job_id': None,
            'success': True,
            'message': 'Using local Python MapReduce simulation.',
        }

    def _build_mapper_script(self, job_type, custom_code=''):
        """Generate a Hadoop streaming mapper script."""
        return f"#!/usr/bin/env python3\n# EarthScape Climate Mapper - {job_type}\n{custom_code or self._default_mapper(job_type)}"

    def _build_reducer_script(self, job_type, custom_code=''):
        """Generate a Hadoop streaming reducer script."""
        return f"#!/usr/bin/env python3\n# EarthScape Climate Reducer - {job_type}\n{custom_code or self._default_reducer(job_type)}"

    def _default_mapper(self, job_type):
        return '''
import sys
for line in sys.stdin:
    line = line.strip()
    parts = line.split(',')
    if len(parts) >= 3:
        print(f"{parts[0]}\\t{parts[2]}")
'''

    def _default_reducer(self, job_type):
        return '''
import sys
current_key = None
values = []
for line in sys.stdin:
    key, value = line.strip().split('\\t', 1)
    if key == current_key:
        values.append(float(value))
    else:
        if current_key:
            print(f"{current_key}\\t{sum(values)/len(values):.2f}")
        current_key = key
        values = [float(value)]
if current_key:
    print(f"{current_key}\\t{sum(values)/len(values):.2f}")
'''


# Global instance
hadoop_bridge = MapReduceBridge()
