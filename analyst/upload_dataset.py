from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from analyst import analyst_bp
from auth.decorators import analyst_required
from models.dataset_model import Dataset
from models.climate_model import ClimateData
from utils.helper import allowed_file, generate_unique_filename, format_file_size
from utils.database import log_activity
from config import Config
import os
import json


@analyst_bp.route('/upload-dataset', methods=['GET', 'POST'])
@login_required
@analyst_required
def upload_dataset():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        description = request.form.get('description', '')
        category = request.form.get('category', 'weather')
        file = request.files.get('file')

        if not name:
            flash('Dataset name is required.', 'danger')
            return redirect(url_for('analyst.upload_dataset'))

        if not file or file.filename == '':
            flash('No file selected.', 'danger')
            return redirect(url_for('analyst.upload_dataset'))

        if not allowed_file(file.filename):
            flash('File type not allowed. Supported: CSV, JSON, XLSX, XLS, TXT, TIF, TIFF, NC, HDF5', 'danger')
            return redirect(url_for('analyst.upload_dataset'))

        # Save file
        filename = generate_unique_filename(file.filename)
        category_dir = os.path.join(Config.UPLOAD_FOLDER, category)
        os.makedirs(category_dir, exist_ok=True)
        filepath = os.path.join(category_dir, filename)
        file.save(filepath)

        file_size = os.path.getsize(filepath)
        file_type = file.filename.rsplit('.', 1)[1].lower()

        # Create dataset record
        dataset_id = Dataset.create(
            name=name,
            description=description,
            file_path=filepath,
            file_size=file_size,
            file_type=file_type,
            category=category,
            source='upload',
            uploaded_by=current_user.id
        )

        # Parse file based on format using multi-format parser
        records_parsed = 0
        parseable_types = ['csv', 'txt', 'json', 'xlsx', 'xls', 'nc', 'hdf5', 'h5', 'tif', 'tiff']
        if file_type in parseable_types:
            records_parsed = Dataset.parse_file(filepath, dataset_id, file_type)

        # Log activity
        log_activity(current_user.id, 'upload_dataset',
                     f'Uploaded {name} ({file_type}, {file_size} bytes, {records_parsed} records)',
                     request.remote_addr)

        # Register in HDFS partition system and upload file to HDFS
        try:
            from utils.hdfs import partition_manager, hdfs_manager
            ppath = partition_manager.get_partition_path(data_type=category)
            pkey = 'climate_data_' + category
            partition_manager.get_or_create_partition(pkey, 'type', category, ppath, 'climate_data')
            partition_manager.update_partition_stats(pkey, record_delta=records_parsed, size_delta=file_size)
            hdfs_manager.mkdir(ppath)
        except Exception:
            pass

        # Upload the original file to HDFS and retain its verified path.
        from utils.webhdfs import real_hdfs
        hdfs_path = f'/climate/{category}/{filename}'
        if real_hdfs.using_real_hdfs():
            from utils.ingestion_backend import verified_hdfs_upload
            verified_hdfs_upload(filepath, hdfs_path)
        else:
            real_hdfs.upload_from_file(filepath, hdfs_path)
        Dataset.update(dataset_id, hdfs_path=hdfs_path)

        # Notify admins that a new dataset awaits review
        Dataset.notify_pending_review(dataset_id)

        format_info = {
            'csv': 'CSV', 'json': 'JSON', 'xlsx': 'Excel', 'xls': 'Excel',
            'txt': 'Text', 'tif': 'GeoTIFF', 'tiff': 'GeoTIFF',
            'nc': 'NetCDF', 'hdf5': 'HDF5', 'h5': 'HDF5'
        }
        fmt = format_info.get(file_type, file_type.upper())

        if records_parsed > 0:
            flash(f'Dataset "{name}" uploaded and parsed successfully ({records_parsed} records ingested from {fmt} file). Sent to Admin for review and approval.', 'success')
        elif file_type in parseable_types:
            flash(f'Dataset "{name}" uploaded ({fmt} format) but contained no parseable climate records. Sent to Admin for review.', 'warning')
        else:
            flash(f'Dataset "{name}" uploaded ({fmt} format). Sent to Admin for review and approval.', 'info')

        return redirect(url_for('analyst.upload_dataset'))

    datasets = Dataset.get_for_owner(current_user.id)

    # Compute format stats
    format_counts = {}
    for ds in datasets:
        ft = ds.get('file_type', 'unknown')
        format_counts[ft] = format_counts.get(ft, 0) + 1

    return render_template('analyst/upload_dataset.html', datasets=datasets,
                         format_file_size=format_file_size,
                         format_counts=format_counts,
                         active_page='upload_dataset')


@analyst_bp.route('/upload-dataset/<int:dataset_id>/view')
@login_required
@analyst_required
def view_uploaded_data(dataset_id):
    """View parsed data from an uploaded dataset."""
    dataset = Dataset.get_owned_by_id(dataset_id, current_user.id)
    if not dataset:
        flash('Dataset not found.', 'danger')
        return redirect(url_for('analyst.upload_dataset'))

    # Get data records
    data = ClimateData.get_by_dataset(dataset_id, limit=200)
    summary = ClimateData.get_summary(dataset_id)
    validation = Dataset.validate_dataset(dataset_id)

    return render_template('analyst/upload_dataset.html',
                         dataset=dataset,
                         data=data,
                         summary=summary,
                         validation=validation,
                         datasets=Dataset.get_for_owner(current_user.id),
                         format_file_size=format_file_size,
                         active_page='upload_dataset')


@analyst_bp.route('/upload-dataset/<int:dataset_id>/delete', methods=['POST'])
@login_required
@analyst_required
def delete_dataset(dataset_id):
    """Delete a dataset the current user uploaded."""
    dataset = Dataset.get_by_id(dataset_id)
    if not dataset:
        flash('Dataset not found.', 'danger')
        return redirect(url_for('analyst.upload_dataset'))

    if str(dataset.get('uploaded_by', '')) != str(current_user.id):
        flash('You can only delete datasets you uploaded yourself.', 'warning')
        return redirect(url_for('analyst.upload_dataset'))

    # Remove the physical file if it exists
    try:
        path = dataset.get('file_path', '')
        if path and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

    deleted = Dataset.delete(dataset_id)
    if not deleted:
        flash('Dataset was already deleted or is no longer active.', 'warning')
        return redirect(url_for('analyst.upload_dataset'))
    log_activity(current_user.id, 'delete_dataset',
                 f'Deleted dataset "{dataset.get("name", dataset_id)}"', request.remote_addr)
    flash(f'Dataset "{dataset.get("name", "")}" deleted successfully.', 'success')
    return redirect(url_for('analyst.upload_dataset'))
