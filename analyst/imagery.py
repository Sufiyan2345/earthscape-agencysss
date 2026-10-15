import os
import re
import logging
from datetime import datetime

from flask import render_template, request, redirect, url_for, flash, send_file
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename

from analyst import analyst_bp
from auth.decorators import analyst_required
from config import Config, basedir
from models.dataset_model import Dataset
from models.climate_model import ClimateData
from models.imagery_model import SatelliteImage
from utils.imagery import analyze_imagery, is_allowed_image
from utils.database import log_activity

PLATFORMS = ['LANDSAT-9', 'SENTINEL-2', 'MODIS-TERRA', 'GOES-16', 'UAV/Drone']


def _imagery_folder():
    """Store ingested imagery under static/uploads so the files live in the
    project's static tree and remain servable via the dedicated
    ``satellite_imagery_file`` route (absolute stored_path).
    """
    folder = os.path.abspath(os.path.join(basedir, 'static', 'uploads', 'satellite_imagery'))
    os.makedirs(folder, exist_ok=True)
    return folder


def _parse_float(value, default=None):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@analyst_bp.route('/satellite-imagery')
@login_required
@analyst_required
def satellite_imagery():
    """Imagery ingestion hub: upload form + gallery of ingested images."""
    images = SatelliteImage.get_all(limit=60)
    return render_template('analyst/imagery.html',
                         images=images,
                         platforms=PLATFORMS,
                         stats=SatelliteImage.get_stats(),
                         active_page='satellite_imagery')


@analyst_bp.route('/satellite-imagery/upload', methods=['POST'])
@login_required
@analyst_required
def upload_satellite_imagery():
    """Decode the uploaded image, extract indicators, persist everything."""
    file = request.files.get('image_file')
    if not file or not file.filename:
        flash('Choose an image file to ingest.', 'danger')
        return redirect(url_for('analyst.satellite_imagery'))
    if not is_allowed_image(file.filename):
        flash('Unsupported image format. Allowed: PNG, JPG, TIFF, BMP, GIF, WEBP.', 'danger')
        return redirect(url_for('analyst.satellite_imagery'))

    platform = request.form.get('platform', 'LANDSAT-9')
    if platform not in PLATFORMS:
        platform = 'LANDSAT-9'
    latitude = _parse_float(request.form.get('latitude'), 20.5937)
    longitude = _parse_float(request.form.get('longitude'), 78.9629)
    latitude = max(-90.0, min(90.0, latitude or 0.0))
    longitude = max(-180.0, min(180.0, longitude or 0.0))
    capture_date = request.form.get('capture_date') or datetime.utcnow().strftime('%Y-%m-%d')

    # Save image with absolute path
    safe_name = secure_filename(file.filename)
    stored_name = '{}_{}'.format(datetime.utcnow().strftime('%Y%m%d%H%M%S'), safe_name)
    filepath = os.path.abspath(os.path.join(_imagery_folder(), stored_name))
    file.save(filepath)

    hdfs_path = f'/climate/satellite_imagery/{stored_name}'
    try:
        from utils.ingestion_backend import verified_hdfs_upload
        from utils.webhdfs import real_hdfs
        if real_hdfs.using_real_hdfs():
            verified_hdfs_upload(filepath, hdfs_path)
    except Exception as error:
        if os.path.exists(filepath):
            os.remove(filepath)
        flash(f'Satellite image was not stored in HDFS: {error}', 'danger')
        return redirect(url_for('analyst.satellite_imagery'))

    try:
        metrics = analyze_imagery(filepath)
    except Exception as e:
        if os.path.exists(filepath):
            os.remove(filepath)
        flash(str(e), 'danger')
        return redirect(url_for('analyst.satellite_imagery'))

    file_size = os.path.getsize(filepath)
    station = 'IMG-{}'.format(re.sub(r'[^A-Za-z0-9]+', '-', safe_name)[:40]).upper()

    # Derived climate record
    record = {
        'station_name': station,
        'latitude': latitude,
        'longitude': longitude,
        'elevation': 0,
        'date': capture_date,
        'temperature': metrics['land_surface_temp'],
        'cloud_cover': metrics['cloud_cover'],
        'soil_moisture': metrics['water_cover'],
    }

    dataset_id = Dataset.create(
        name='Satellite Imagery - {} ({})'.format(platform, safe_name),
        description='Imagery-derived indicators from {} ({}x{}, {} MP). '
                    'LST est. {}C, cloud {}%, vegetation index {}.'.format(
                        platform, metrics['width'], metrics['height'],
                        metrics['megapixels'], metrics['land_surface_temp'],
                        metrics['cloud_cover'], metrics['vegetation_index']),
        file_path=filepath,
        file_size=file_size,
        file_type=metrics['format'].lower(),
        category='satellite_imagery',
        source='satellite_imagery',
        uploaded_by=current_user.id,
        record_count=1,
        column_count=len(record),
        hdfs_path=hdfs_path,
    )
    ClimateData.insert_batch([record], dataset_id)

    image_id = SatelliteImage.create({
        'filename': safe_name,
        'stored_path': filepath,
        'hdfs_path': hdfs_path,
        'platform': platform,
        'latitude': latitude,
        'longitude': longitude,
        'capture_date': capture_date,
        'station_name': station,
        'dataset_id': dataset_id,
        'file_size': file_size,
        'metrics': metrics,
        'uploaded_by': current_user.id,
        'uploaded_by_name': getattr(current_user, 'full_name', None) or current_user.username,
    })

    _register_imagery_partition(file_size)
    log_activity(current_user.id, 'ingest_satellite_imagery',
                 '1 image ({}) from {}'.format(safe_name, platform), request.remote_addr)

    flash('Image ingested: {} indicators extracted from {} ({}). '
          'Sent to Admin for approval.'.format(len(metrics) - 4, safe_name, platform), 'success')
    Dataset.notify_pending_review(dataset_id)
    return redirect(url_for('analyst.satellite_imagery'))


def _register_imagery_partition(file_size):
    """Register ingested imagery in the HDFS partition system (best-effort)."""
    try:
        from utils.hdfs import partition_manager, hdfs_manager
        partition_manager.update_partition_stats('climate_data_satellite',
                                                   record_delta=1, size_delta=file_size)
        hdfs_manager.mkdir('/climate/satellite')
    except Exception:
        pass


@analyst_bp.route('/satellite-imagery/<int:image_id>/image')
@login_required
@analyst_required
def satellite_imagery_file(image_id):
    """Serve the stored image with fallback diagnostics and path verification."""
    img = SatelliteImage.get_by_id(image_id)
    if not img:
        logging.warning(f"[SatelliteImagery] Image record #{image_id} not found in database.")
        return 'Image record not found', 404

    stored_path = SatelliteImage.resolve_file_path(img)
    if not stored_path:
        logging.error(f"[SatelliteImagery] Target path does not exist for image #{image_id}: {img.get('stored_path')}")
        return 'File missing from server storage', 404

    return send_file(stored_path)


@analyst_bp.route('/satellite-imagery/<int:image_id>/delete', methods=['POST'])
@login_required
@analyst_required
def delete_satellite_imagery(image_id):
    """Delete an imagery record the analyst uploaded."""
    img = SatelliteImage.get_by_id(image_id)
    if not img:
        flash('Image not found.', 'danger')
        return redirect(url_for('analyst.satellite_imagery'))
    if img.get('uploaded_by') != current_user.id:
        flash('You can only delete images you uploaded.', 'danger')
        return redirect(url_for('analyst.satellite_imagery'))
    
    SatelliteImage.delete(image_id)
    
    dataset_id = img.get('dataset_id')
    if dataset_id:
        try:
            ClimateData.delete_by_dataset(dataset_id)
            Dataset.delete(dataset_id)
        except Exception:
            pass
            
    try:
        stored_path = img.get('stored_path')
        if stored_path and os.path.exists(stored_path):
            os.remove(stored_path)
    except OSError:
        pass

    log_activity(current_user.id, 'delete_satellite_imagery',
                 'image #{} ({})'.format(image_id, img.get('filename', '')),
                 request.remote_addr)
    flash('Satellite image #{} deleted.'.format(image_id), 'success')
    return redirect(url_for('analyst.satellite_imagery'))


@analyst_bp.route('/satellite-imagery/<int:image_id>/update', methods=['POST'])
@login_required
@analyst_required
def update_satellite_imagery(image_id):
    """Update metadata and optionally replace the file for an imagery record."""
    img = SatelliteImage.get_by_id(image_id)
    if not img:
        flash('Image not found.', 'danger')
        return redirect(url_for('analyst.satellite_imagery'))
    if img.get('uploaded_by') != current_user.id:
        flash('You can only update images you uploaded.', 'danger')
        return redirect(url_for('analyst.satellite_imagery'))

    platform = request.form.get('platform', img.get('platform', 'LANDSAT-9'))
    if platform not in PLATFORMS:
        platform = img.get('platform', 'LANDSAT-9')

    latitude = _parse_float(request.form.get('latitude'), img.get('latitude'))
    longitude = _parse_float(request.form.get('longitude'), img.get('longitude'))
    if latitude is not None:
        latitude = max(-90.0, min(90.0, latitude))
    if longitude is not None:
        longitude = max(-180.0, min(180.0, longitude))

    capture_date = request.form.get('capture_date') or img.get('capture_date') or datetime.utcnow().strftime('%Y-%m-%d')
    station_name = request.form.get('station_name', img.get('station_name', '')).strip()
    if not station_name:
        station_name = img.get('station_name', 'IMG-DEFAULT')

    updates = {
        'platform': platform,
        'latitude': latitude if latitude is not None else img.get('latitude', 0.0),
        'longitude': longitude if longitude is not None else img.get('longitude', 0.0),
        'capture_date': capture_date,
        'station_name': station_name,
        'stored_path': img.get('stored_path')
    }

    metrics = img.get('metrics') or {}
    filepath = img.get('stored_path')
    file_size = img.get('file_size', 0)
    safe_name = img.get('filename', 'image')
    image_replaced = False

    file = request.files.get('image_file')
    if file and file.filename:
        if not is_allowed_image(file.filename):
            flash('Unsupported image format. Allowed: PNG, JPG, TIFF, BMP, GIF, WEBP.', 'danger')
            return redirect(url_for('analyst.satellite_imagery'))

        old_path = img.get('stored_path')
        safe_name = secure_filename(file.filename)
        stored_name = '{}_{}'.format(datetime.utcnow().strftime('%Y%m%d%H%M%S'), safe_name)
        filepath = os.path.abspath(os.path.join(_imagery_folder(), stored_name))
        file.save(filepath)

        try:
            metrics = analyze_imagery(filepath)
        except Exception as e:
            if os.path.isfile(filepath):
                os.remove(filepath)
            flash(str(e), 'danger')
            return redirect(url_for('analyst.satellite_imagery'))

        file_size = os.path.getsize(filepath)
        updates['stored_path'] = filepath
        updates['filename'] = safe_name
        updates['metrics'] = metrics
        updates['file_size'] = file_size
        image_replaced = True

        try:
            if old_path and old_path != filepath and os.path.exists(old_path):
                os.remove(old_path)
        except OSError:
            pass

    # Update database record
    SatelliteImage.update(image_id, **updates)

    # Synchronize dataset & climate records
    dataset_id = img.get('dataset_id')
    if dataset_id:
        record = {
            'station_name': updates['station_name'],
            'latitude': updates['latitude'],
            'longitude': updates['longitude'],
            'elevation': 0,
            'date': updates['capture_date'],
            'temperature': metrics.get('land_surface_temp'),
            'cloud_cover': metrics.get('cloud_cover'),
            'soil_moisture': metrics.get('water_cover'),
        }
        ClimateData.delete_by_dataset(dataset_id)
        ClimateData.insert_batch([record], dataset_id)

        dataset_updates = {
            'name': 'Satellite Imagery - {} ({})'.format(platform, safe_name),
            'description': 'Imagery-derived indicators from {} ({}x{}, {} MP). '
                           'LST est. {}C, cloud {}%, vegetation index {}.'.format(
                               platform, metrics.get('width', 0), metrics.get('height', 0),
                               metrics.get('megapixels', 0), metrics.get('land_surface_temp', 0),
                               metrics.get('cloud_cover', 0), metrics.get('vegetation_index', 0)),
            'file_path': filepath,
            'file_size': file_size,
            'record_count': 1,
            'column_count': len(record),
        }
        if metrics.get('format'):
            dataset_updates['file_type'] = str(metrics['format']).lower()
        if image_replaced:
            dataset_updates['approval_status'] = 'pending'
            dataset_updates['reviewed_by'] = None
            dataset_updates['reviewed_at'] = None
            dataset_updates['rejection_reason'] = ''
        Dataset.update(dataset_id, **dataset_updates)
        if image_replaced:
            try:
                Dataset.notify_pending_review(dataset_id)
            except Exception:
                pass

    if image_replaced:
        _register_imagery_partition(file_size)

    log_activity(current_user.id, 'update_satellite_imagery',
                 'image #{} ({}) on {}'.format(image_id, safe_name, platform),
                 request.remote_addr)

    if image_replaced:
        flash('Satellite image #{} updated with a new file: {} indicators re-extracted, '
              'sent to Admin for approval.'.format(image_id, max(len(metrics) - 4, 0)), 'success')
    else:
        flash('Satellite image #{} metadata updated successfully.'.format(image_id), 'success')
    return redirect(url_for('analyst.satellite_imagery'))
