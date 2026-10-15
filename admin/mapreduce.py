"""Admin MapReduce panel — MONITORING ONLY.

The Admin role monitors Hadoop MapReduce jobs submitted by analysts:
cluster-wide statistics, status filtering, live progress, per-job detail
and cancellation of stuck jobs. Analysts are the ones who process climate
data (submit jobs) in the Analyst panel.
"""
import json

from flask import render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required

from admin import admin_bp
from auth.decorators import admin_required
from utils.mapreduce import MapReduceManager
from utils.database import get_collection

VALID_FILTERS = ('all', 'running', 'completed', 'failed', 'cancelled')


def _safe_json(val):
    """Safely parse a JSON string, returning None on failure."""
    if not val:
        return None
    if isinstance(val, (dict, list)):
        return val
    try:
        return json.loads(val)
    except (json.JSONDecodeError, TypeError):
        return None


def _attach_submitter_names(jobs):
    """Resolve submitted_by user ids to usernames for display."""
    ids = list({j.get('submitted_by') for j in jobs if j.get('submitted_by') is not None})
    name_map = {}
    if ids:
        for u in get_collection('users').find({'id': {'$in': ids}}):
            name_map[u['id']] = u.get('full_name') or u.get('username') or f"User #{u['id']}"
    for j in jobs:
        j['submitter_name'] = name_map.get(j.get('submitted_by'), f"User #{j.get('submitted_by')}")
    return jobs


def _prepare(jobs):
    """Parse result/params JSON and resolve submitter names for display."""
    for j in jobs:
        j['parsed_result'] = _safe_json(j.get('result'))
        j['parsed_params'] = _safe_json(j.get('input_params'))
    return _attach_submitter_names(jobs)


@admin_bp.route('/mapreduce')
@login_required
@admin_required
def mapreduce():
    all_jobs = MapReduceManager.get_all_jobs()
    stats = MapReduceManager.get_job_stats(all_jobs)
    from utils.hadoop_mr import hadoop_bridge
    hadoop_status = hadoop_bridge.get_cluster_info()

    status_filter = request.args.get('filter', 'all')
    if status_filter not in VALID_FILTERS:
        status_filter = 'all'
    jobs = all_jobs if status_filter == 'all' else [j for j in all_jobs if j.get('status') == status_filter]

    _prepare(all_jobs)  # stats computed on raw docs, prepare the filtered view
    _prepare(jobs)
    return render_template('admin/mapreduce.html',
                         jobs=jobs, stats=stats, status_filter=status_filter,
                         hadoop_status=hadoop_status,
                         job_types=MapReduceManager.get_job_types(),
                         active_page='mapreduce')


@admin_bp.route('/mapreduce/<int:job_id>')
@login_required
@admin_required
def view_job(job_id):
    job = MapReduceManager.get_job(job_id)
    if not job:
        flash('Job not found.', 'danger')
        return redirect(url_for('admin.mapreduce'))
    _prepare([job])
    from utils.hadoop_mr import hadoop_bridge
    return render_template('admin/mapreduce.html',
                         job=job,
                         jobs=_prepare(MapReduceManager.get_all_jobs()),
                         stats=MapReduceManager.get_job_stats(),
                         hadoop_status=hadoop_bridge.get_cluster_info(),
                         status_filter='all',
                         job_types=MapReduceManager.get_job_types(),
                         active_page='mapreduce')


@admin_bp.route('/mapreduce/<int:job_id>/cancel', methods=['POST'])
@login_required
@admin_required
def cancel_job(job_id):
    if MapReduceManager.cancel_job(job_id):
        flash(f'Job #{job_id} cancelled.', 'success')
    else:
        flash(f'Job #{job_id} is not running and could not be cancelled.', 'warning')
    return redirect(request.referrer or url_for('admin.mapreduce'))


@admin_bp.route('/mapreduce/<int:job_id>/status')
@login_required
@admin_required
def job_status(job_id):
    """JSON status endpoint used by the live monitor polling."""
    job = MapReduceManager.get_job(job_id)
    if job:
        return jsonify({
            'status': job['status'],
            'progress': job.get('progress', 0),
            'input_records': job.get('input_records', 0),
            'output_records': job.get('output_records', 0),
            'execution_time': job.get('execution_time', 0),
            'result': _safe_json(job.get('result')),
        })
    return jsonify({'error': 'Job not found'}), 404
