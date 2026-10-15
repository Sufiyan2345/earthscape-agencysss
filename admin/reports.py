from flask import render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from admin import admin_bp
from auth.decorators import admin_required
from models.report_model import Report
from models.dataset_model import Dataset
from models.climate_model import ClimateData
import json


@admin_bp.route('/reports')
@login_required
@admin_required
def reports():
    all_reports = Report.get_all()
    return render_template('admin/reports.html', reports=all_reports, active_page='reports')


@admin_bp.route('/reports/generate', methods=['POST'])
@login_required
@admin_required
def generate_report():
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '')
    report_type = request.form.get('report_type', 'analysis')
    category = request.form.get('category', 'climate')

    if not title:
        flash('Report title is required.', 'danger')
        return redirect(url_for('admin.reports'))

    summary_data = ClimateData.get_summary()
    monthly = ClimateData.get_monthly_trends()

    summary = f"Report generated with {summary_data.get('total_records', 0)} total records. "
    summary += f"Average temperature: {summary_data.get('avg_temp', 'N/A')}°C. "
    summary += f"Average humidity: {summary_data.get('avg_humidity', 'N/A')}%. "
    summary += f"Average rainfall: {summary_data.get('avg_rainfall', 'N/A')}mm."

    report_id = Report.create(
        title=title,
        description=description,
        report_type=report_type,
        category=category,
        generated_by=current_user.id,
        summary=summary
    )

    flash(f'Report "{title}" generated successfully.', 'success')
    return redirect(url_for('admin.reports'))


@admin_bp.route('/reports/<int:report_id>')
@login_required
@admin_required
def view_report(report_id):
    report = Report.get_by_id(report_id)
    if not report:
        flash('Report not found.', 'danger')
        return redirect(url_for('admin.reports'))
    return render_template('admin/reports.html', report=report, reports=Report.get_all(), active_page='reports')


@admin_bp.route('/reports/<int:report_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_report(report_id):
    Report.delete(report_id)
    flash('Report deleted.', 'success')
    return redirect(url_for('admin.reports'))
