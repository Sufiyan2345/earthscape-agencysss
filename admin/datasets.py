from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
import os
import sys
import subprocess
from admin import admin_bp
from auth.decorators import admin_required
from models.dataset_model import Dataset
from models.climate_model import ClimateData
from models.alert_model import Alert
from models.user_model import User
from config import Config
from utils.database import log_activity
from utils.helper import allowed_file, format_file_size, generate_unique_filename


def _uploader_names(datasets):
    """Map uploaded_by user ids to display names."""
    names = {}
    for ds in datasets:
        uid = ds.get('uploaded_by')
        if uid is None or uid in names:
            continue
        try:
            user = User.get_by_id(uid)
            names[uid] = (getattr(user, 'full_name', '') or getattr(user, 'username', '')
                          or f'User {uid}') if user else f'User {uid}'
        except Exception:
            names[uid] = f'User {uid}'
    return names


def _chart_data():
    """Aggregate counts for the datasets overview charts."""
    all_ds = Dataset.get_all(limit=500)
    categories = {}
    for ds in all_ds:
        cat = ds.get('category') or 'other'
        entry = categories.setdefault(cat, {'datasets': 0, 'records': 0})
        entry['datasets'] += 1
        entry['records'] += int(ds.get('record_count') or 0)
    return categories


@admin_bp.route('/datasets')
@login_required
@admin_required
def datasets():
    category = request.args.get('category') or None
    approval = request.args.get('approval') or None
    search = request.args.get('search') or None

    all_datasets = Dataset.get_all(category=category, approval_status=approval, search=search)
    counts = Dataset.get_approval_counts()

    return render_template('admin/datasets.html',
                           datasets=all_datasets,
                           uploader_names=_uploader_names(all_datasets),
                           counts=counts,
                           category_chart=_chart_data(),
                           active_page='datasets',
                           category_filter=category,
                           approval_filter=approval,
                           search_query=search or '',
                           format_file_size=format_file_size)


@admin_bp.route('/datasets/upload', methods=['POST'])
@login_required
@admin_required
def upload_dataset():
    """Allow administrators to ingest a trusted dataset directly."""
    name = request.form.get('name', '').strip()
    category = request.form.get('category', 'weather').strip().lower()
    description = request.form.get('description', '').strip()
    file = request.files.get('file')

    if not name or not file or not file.filename:
        flash('Dataset name and file are required.', 'danger')
        return redirect(url_for('admin.datasets'))
    if not allowed_file(file.filename):
        flash('Unsupported file format. Use CSV, JSON, Excel, TXT, GeoTIFF, NetCDF, or HDF5.', 'danger')
        return redirect(url_for('admin.datasets'))
    if category not in {'weather', 'satellite', 'sensors', 'historical'}:
        category = 'weather'

    upload_dir = os.path.join(Config.UPLOAD_FOLDER, 'admin', category)
    os.makedirs(upload_dir, exist_ok=True)
    filename = generate_unique_filename(file.filename)
    filepath = os.path.join(upload_dir, filename)
    file.save(filepath)
    file_type = os.path.splitext(filename)[1].lstrip('.').lower()
    file_size = os.path.getsize(filepath)

    dataset_id = Dataset.create(
        name=name,
        description=description,
        file_path=filepath,
        file_size=file_size,
        file_type=file_type,
        category=category,
        source='admin_upload',
        uploaded_by=current_user.id,
    )

    records_parsed = Dataset.parse_file(filepath, dataset_id, file_type)
    Dataset.update(dataset_id, record_count=records_parsed)
    Dataset.approve(dataset_id, current_user.id)
    try:
        from analyst.ingestion import _register_partition, _store_to_hdfs
        _register_partition(category, year=None, record_count=records_parsed, file_size=file_size)
        _store_to_hdfs(filepath, category)
    except Exception:
        pass

    log_activity(current_user.id, 'admin_upload_dataset',
                 f'Admin uploaded {name} ({file_type}, {records_parsed} records)',
                 request.remote_addr)
    flash(f'Dataset "{name}" uploaded, parsed, and approved ({records_parsed} records).', 'success')
    return redirect(url_for('admin.datasets'))


@admin_bp.route('/datasets/<int:dataset_id>')
@login_required
@admin_required
def view_dataset(dataset_id):
    dataset = Dataset.get_by_id(dataset_id)
    if not dataset:
        flash('Dataset not found.', 'danger')
        return redirect(url_for('admin.datasets'))

    stats = Dataset.get_statistics(dataset_id)
    summary = ClimateData.get_summary(dataset_id)
    preview = ClimateData.get_by_dataset(dataset_id, limit=50)
    validation = Dataset.validate_dataset(dataset_id)

    uploader_name = _uploader_names([dataset]).get(dataset.get('uploaded_by'), 'N/A')

    # Monthly temperature/rainfall trend for this dataset's chart
    col_data = ClimateData.get_by_dataset(dataset_id, limit=5000)
    monthly = {}
    for row in col_data:
        d = row.get('date')
        if not d:
            continue
        key = str(d)[:7]
        bucket = monthly.setdefault(key, {'temps': [], 'rain': 0.0})
        if row.get('temperature') is not None:
            bucket['temps'].append(float(row['temperature']))
        if row.get('rainfall') is not None:
            bucket['rain'] += float(row['rainfall'])
    trend = {'labels': [], 'temperatures': [], 'rainfall': []}
    for key in sorted(monthly.keys())[:24]:
        bucket = monthly[key]
        trend['labels'].append(key)
        avg_t = sum(bucket['temps']) / len(bucket['temps']) if bucket['temps'] else 0
        trend['temperatures'].append(round(avg_t, 1))
        trend['rainfall'].append(round(bucket['rain'], 1))

    return render_template('admin/datasets.html',
                           datasets=Dataset.get_all(limit=100),
                           uploader_names=_uploader_names(Dataset.get_all(limit=100)),
                           counts=Dataset.get_approval_counts(),
                           category_chart=_chart_data(),
                           dataset=dataset,
                           stats=stats,
                           summary=summary,
                           preview=preview,
                           validation=validation,
                           trend=trend,
                           uploader_name=uploader_name,
                           active_page='datasets',
                           category_filter=None,
                           approval_filter=None,
                           search_query='',
                           format_file_size=format_file_size)


@admin_bp.route('/datasets/<int:dataset_id>/open-file', methods=['GET', 'POST'])
@login_required
@admin_required
def open_dataset_file(dataset_id):
    dataset = Dataset.get_by_id(dataset_id)
    if not dataset:
        flash('Dataset not found.', 'danger')
        return redirect(url_for('admin.datasets'))

    file_path = (dataset.get('file_path') or '').strip()
    if not file_path:
        flash('No local file path is available for this dataset.', 'warning')
        return redirect(url_for('admin.view_dataset', dataset_id=dataset_id))

    try:
        file_path = os.path.abspath(os.path.normpath(file_path))
        if os.name == 'nt':
            if os.path.exists(file_path):
                safe_path = file_path.replace('/', '\\')
                subprocess.Popen(f'explorer.exe /select,"{safe_path}"', shell=True)
            else:
                raise FileNotFoundError(f'Dataset file not found: {file_path}')
        else:
            if os.path.exists(file_path):
                if sys.platform == 'darwin':
                    subprocess.Popen(['open', file_path])
                else:
                    subprocess.Popen(['xdg-open', os.path.dirname(file_path)])
            else:
                raise FileNotFoundError(f'Dataset file not found: {file_path}')

        flash(f'Opened the exact file location for "{dataset.get("name")}" in your system explorer.', 'success')
    except Exception as exc:
        flash(f'Could not open the exact file location: {exc}', 'warning')

    return redirect(url_for('admin.view_dataset', dataset_id=dataset_id))


@admin_bp.route('/datasets/<int:dataset_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_dataset(dataset_id):
    dataset = Dataset.get_by_id(dataset_id)
    if not dataset:
        flash('Dataset not found.', 'danger')
        return redirect(url_for('admin.datasets'))

    Dataset.approve(dataset_id, current_user.id)
    log_activity(current_user.id, 'approve_dataset',
                 f'Approved dataset "{dataset.get("name")}" (id={dataset_id})', request.remote_addr)

    # Notify the analyst who uploaded it
    Alert.create(
        title='Dataset Approved',
        message=f'Your dataset "{dataset.get("name")}" has been approved and is now available for processing and analysis.',
        alert_type='info', severity='low',
        category=dataset.get('category', 'weather'),
        created_by=current_user.id)

    flash(f'Dataset "{dataset.get("name")}" approved. It is now available in the Analyst Panel.', 'success')
    return redirect(url_for('admin.datasets'))


@admin_bp.route('/datasets/<int:dataset_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_dataset(dataset_id):
    dataset = Dataset.get_by_id(dataset_id)
    if not dataset:
        flash('Dataset not found.', 'danger')
        return redirect(url_for('admin.datasets'))

    reason = request.form.get('reason', '').strip()
    Dataset.reject(dataset_id, current_user.id, reason)
    log_activity(current_user.id, 'reject_dataset',
                 f'Rejected dataset "{dataset.get("name")}" (id={dataset_id}): {reason or "no reason given"}',
                 request.remote_addr)

    Alert.create(
        title='Dataset Rejected',
        message=f'Your dataset "{dataset.get("name")}" was rejected. '
                f'Reason: {reason or "No reason provided."} It is not available for processing.',
        alert_type='warning', severity='medium',
        category=dataset.get('category', 'weather'),
        created_by=current_user.id)

    flash(f'Dataset "{dataset.get("name")}" rejected.', 'warning')
    return redirect(url_for('admin.datasets'))


@admin_bp.route('/datasets/<int:dataset_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_dataset(dataset_id):
    dataset = Dataset.get_by_id(dataset_id)
    Dataset.delete(dataset_id)
    log_activity(current_user.id, 'delete_dataset',
                 f'Deleted dataset "{dataset.get("name") if dataset else dataset_id}"', request.remote_addr)
    flash('Dataset deleted successfully.', 'success')
    return redirect(url_for('admin.datasets'))


@admin_bp.route('/datasets/<int:dataset_id>/update', methods=['POST'])
@login_required
@admin_required
def update_dataset(dataset_id):
    name = request.form.get('name')
    description = request.form.get('description')
    category = request.form.get('category')

    Dataset.update(dataset_id, name=name, description=description, category=category)
    log_activity(current_user.id, 'update_dataset', f'Updated dataset {dataset_id}', request.remote_addr)
    flash('Dataset updated successfully.', 'success')
    return redirect(url_for('admin.view_dataset', dataset_id=dataset_id))
