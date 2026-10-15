"""Admin satellite imagery monitoring & management.

Admin monitors all imagery ingested by analysts (platform mix, extracted
indicators, derived datasets) and can remove invalid entries.
"""
import os

from flask import render_template, redirect, url_for, flash, send_file
from flask_login import login_required
from auth.decorators import admin_required
from admin import admin_bp
from models.imagery_model import SatelliteImage


@admin_bp.route('/satellite-imagery')
@login_required
@admin_required
def satellite_imagery():
    """Monitor all ingested satellite imagery across the system."""
    images = SatelliteImage.get_all(limit=60)
    return render_template('admin/imagery.html',
                         images=images,
                         stats=SatelliteImage.get_stats(),
                         active_page='satellite_imagery')


@admin_bp.route('/satellite-imagery/<int:image_id>/image')
@login_required
@admin_required
def satellite_imagery_file(image_id):
    """Serve the stored image for gallery thumbnails."""
    img = SatelliteImage.get_by_id(image_id)
    stored_path = SatelliteImage.resolve_file_path(img)
    if not stored_path:
        return 'Image not found', 404
    return send_file(stored_path)


@admin_bp.route('/satellite-imagery/<int:image_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_satellite_imagery(image_id):
    """Remove an ingested imagery record (management action)."""
    img = SatelliteImage.get_by_id(image_id)
    if not img:
        flash('Image not found.', 'danger')
        return redirect(url_for('admin.satellite_imagery'))
    SatelliteImage.delete(image_id)
    try:
        if img.get('stored_path') and os.path.exists(img['stored_path']):
            os.remove(img['stored_path'])
    except OSError:
        pass
    flash('Satellite image #{} removed.'.format(image_id), 'success')
    return redirect(url_for('admin.satellite_imagery'))
