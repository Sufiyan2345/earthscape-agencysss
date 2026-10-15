"""Analyst MapReduce panel — DATA PROCESSING.

The Analyst role processes large climate datasets with Hadoop MapReduce:
submit analysis jobs against real climate collections, track their own
jobs live and inspect the produced results. Monitoring of ALL cluster
jobs happens in the Admin panel.
"""
import json
import threading

from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user

from analyst import analyst_bp
from auth.decorators import analyst_required
from utils.mapreduce import MapReduceManager


def _safe_json(val):
    """Safely parse a JSON string."""
    if not val:
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return None


def _prepare(job):
    """Derive display fields from the stored job document."""
    job = dict(job)
    params = _safe_json(job.get('input_params')) or {}
    job['input_path'] = params.get('input_path', job.get('input_path', '/climate_data'))
    job['output_path'] = params.get('output_path', job.get('output_path', '/output/'))
    job['num_reducers'] = params.get('num_reducers', 2)
    job['parsed_result'] = _safe_json(job.get('result'))
    # Expose optional streaming/hadoop flags and custom mapper/reducer paths
    job['use_hadoop'] = params.get('use_hadoop', False) if isinstance(params, dict) else False
    job['mapper_code'] = job.get('mapper_code', '')
    job['reducer_code'] = job.get('reducer_code', '')
    return job


@analyst_bp.route('/mapreduce', methods=['GET', 'POST'])
@login_required
@analyst_required
def mapreduce():
    # Handle job submission via POST
    if request.method == 'POST':
        action = request.form.get('action', '')

        if action == 'submit_job':
            job_name = request.form.get('job_name', '').strip()
            job_type = request.form.get('job_type', 'temperature_analysis')
            input_path = request.form.get('input_path', '/climate_data')
            output_path = request.form.get('output_path', '/output/')
            num_reducers = request.form.get('num_reducers', 2, type=int)

            if not job_name:
                flash('Job name is required.', 'danger')
                return redirect(url_for('analyst.mapreduce'))

            from config import Config
            use_hadoop = Config.HDFS_USE_REAL or request.form.get('use_hadoop') in ('1', 'true', 'on', 'yes')
            mapper_code = request.form.get('mapper_code', '').strip() or ''
            reducer_code = request.form.get('reducer_code', '').strip() or ''

            input_params = {
                'input_path': input_path,
                'output_path': output_path,
                'num_reducers': max(1, min(num_reducers or 2, 10)),
                'job_type': job_type,
                'use_hadoop': use_hadoop,
            }
            job_id = MapReduceManager.submit_job(job_name, job_type, input_path, current_user.id,
                                                 mapper_code=mapper_code, reducer_code=reducer_code, input_params=input_params)
            # Execute the job asynchronously without blocking the page
            thread = threading.Thread(target=MapReduceManager.execute_job, args=(job_id,))
            thread.daemon = True
            thread.start()

            flash(f'Job "{job_name}" submitted successfully (Job #{job_id}). Processing started.', 'success')
            return redirect(url_for('analyst.mapreduce'))

        if action == 'edit_job':
            try:
                job_id = int(request.form.get('job_id'))
            except (TypeError, ValueError):
                flash('Invalid job reference.', 'danger')
                return redirect(url_for('analyst.mapreduce'))
            job = MapReduceManager.get_job(job_id)
            if not job or job.get('submitted_by') != current_user.id:
                flash('Job not found.', 'danger')
                return redirect(url_for('analyst.mapreduce'))
            if job.get('status') in ('running', 'pending'):
                flash(f'Job #{job_id} is still running — cancel it before editing.', 'warning')
                return redirect(url_for('analyst.mapreduce'))

            job_name = request.form.get('job_name', '').strip() or job.get('job_name', 'Job')
            job_type = request.form.get('job_type', job.get('job_type', 'temperature_analysis'))
            input_path = request.form.get('input_path', '/climate_data')
            output_path = request.form.get('output_path', '/output/')
            num_reducers = request.form.get('num_reducers', 2, type=int)
            use_hadoop = True if request.form.get('use_hadoop') in ('1', 'true', 'on', 'yes') else False
            mapper_code = request.form.get('mapper_code', '').strip() or ''
            reducer_code = request.form.get('reducer_code', '').strip() or ''

            updated = MapReduceManager.update_job(job_id, job_name, job_type, input_path,
                                                  output_path, num_reducers, mapper_code=mapper_code, reducer_code=reducer_code, use_hadoop=use_hadoop)
            if updated is None:
                flash(f'Job #{job_id} could not be edited (still running?).', 'warning')
                return redirect(url_for('analyst.mapreduce'))

            # Re-run the job with the updated parameters so the analysis panel refreshes
            thread = threading.Thread(target=MapReduceManager.execute_job, args=(job_id,))
            thread.daemon = True
            thread.start()

            flash(f'Job #{job_id} updated and re-processing started.', 'success')
            return redirect(url_for('analyst.mapreduce', action='view', id=job_id))

    jobs = MapReduceManager.get_jobs_by_user(current_user.id)
    stats = MapReduceManager.get_job_stats(jobs)
    job_types = MapReduceManager.get_job_types()
    from utils.hadoop_mr import hadoop_bridge
    hadoop_status = hadoop_bridge.get_cluster_info()
    view_job = None

    # Check if viewing a specific job (must belong to this analyst)
    if request.args.get('action') == 'view' and request.args.get('id'):
        job_id = request.args.get('id', type=int)
        for j in jobs:
            if j.get('id') == job_id:
                view_job = _prepare(j)
                break

    parsed_jobs = [_prepare(j) for j in jobs]

    return render_template('analyst/mapreduce.html',
                         jobs=parsed_jobs,
                         job_types=job_types,
                         job=view_job,
                         stats=stats,
                         hadoop_status=hadoop_status,
                         active_page='mapreduce')


@analyst_bp.route('/mapreduce/<int:job_id>/cancel', methods=['POST'])
@login_required
@analyst_required
def cancel_job(job_id):
    """Cancel one of this analyst's running jobs."""
    job = MapReduceManager.get_job(job_id)
    if not job or job.get('submitted_by') != current_user.id:
        flash('Job not found.', 'danger')
        return redirect(url_for('analyst.mapreduce'))
    if MapReduceManager.cancel_job(job_id):
        flash(f'Job #{job_id} cancelled.', 'success')
    else:
        flash(f'Job #{job_id} is not running and could not be cancelled.', 'warning')
    return redirect(url_for('analyst.mapreduce'))


@analyst_bp.route('/mapreduce/<int:job_id>/delete', methods=['POST'])
@login_required
@analyst_required
def delete_job(job_id):
    """Delete one of this analyst's finished jobs (completed/failed/cancelled)."""
    job = MapReduceManager.get_job(job_id)
    if not job or job.get('submitted_by') != current_user.id:
        flash('Job not found.', 'danger')
        return redirect(url_for('analyst.mapreduce'))
    if MapReduceManager.delete_job(job_id, submitted_by=current_user.id):
        flash(f'Job #{job_id} deleted.', 'success')
    else:
        flash(f'Job #{job_id} is still running — cancel it before deleting.', 'warning')
    return redirect(url_for('analyst.mapreduce'))


@analyst_bp.route('/mapreduce/<int:job_id>/status')
@login_required
@analyst_required
def job_status(job_id):
    """JSON status endpoint used by the live progress polling."""
    job = MapReduceManager.get_job(job_id)
    if job and job.get('submitted_by') == current_user.id:
        return jsonify({
            'status': job['status'],
            'progress': job.get('progress', 0),
            'input_records': job.get('input_records', 0),
            'output_records': job.get('output_records', 0),
            'execution_time': job.get('execution_time', 0),
            'result': _safe_json(job.get('result')),
        })
    return jsonify({'error': 'Job not found'}), 404
