from flask import render_template, request, redirect, url_for, flash, Response
from flask_login import login_required, current_user
from analyst import analyst_bp
from auth.decorators import analyst_required
from models.report_model import Report
from models.climate_model import ClimateData
from models.dataset_model import Dataset
import json
import re


def _enrich_report(report):
    """Add display-only fields (generated_at, region) to a report doc."""
    report['generated_at'] = report.get('created_at', 'N/A')
    report['region'] = 'All Regions'
    # Extract region from description if present (stored as "Region: <name>")
    match = re.search(r'region:\s*(.+)', report.get('description', '') or '', re.IGNORECASE)
    if match:
        report['region'] = match.group(1).strip()
    return report


@analyst_bp.route('/reports')
@login_required
@analyst_required
def reports():
    all_reports = Report.get_all()
    datasets = Dataset.get_approved()

    # Get available regions from climate data
    regional = ClimateData.get_regional_data()
    regions = sorted(
        {str(r.get('station_name')).strip() for r in regional if r.get('station_name') is not None and str(r.get('station_name')).strip()},
        key=str.casefold,
    ) if regional else [
        'North Station', 'South Station', 'East Station', 'West Station', 'Central Station'
    ]

    # Parse report data for display
    parsed_reports = [_enrich_report(dict(r)) for r in all_reports]

    return render_template('analyst/reports.html',
                         reports=parsed_reports,
                         regions=regions,
                         datasets=datasets,
                         active_page='reports')


@analyst_bp.route('/reports/generate', methods=['POST'])
@login_required
@analyst_required
def generate_report():
    title = request.form.get('title', '').strip()
    description = request.form.get('description', '')
    report_type = request.form.get('report_type', 'climate_summary')
    category = request.form.get('category', 'climate')
    region = request.form.get('region', 'all')
    start_date = request.form.get('start_date', '')
    end_date = request.form.get('end_date', '')

    if not title:
        # Auto-generate title based on type
        type_names = {
            'climate_summary': 'Climate Summary Report',
            'anomaly_report': 'Anomaly Detection Report',
            'trend_analysis': 'Trend Analysis Report',
            'regional_analysis': 'Regional Analysis Report',
            'prediction_report': 'Prediction Results Report',
        }
        title = type_names.get(report_type, 'Climate Analysis Report')

    # Gather summary data
    summary_data = ClimateData.get_summary()
    total_records = summary_data.get('total_records', 0)
    avg_temp = round(summary_data.get('avg_temp', 0) or 0, 2)
    avg_humidity = round(summary_data.get('avg_humidity', 0) or 0, 2)
    avg_rainfall = round(summary_data.get('avg_rainfall', 0) or 0, 2)

    summary = f"Report Type: {report_type.replace('_', ' ').title()}\n"
    summary += f"Total Records Analyzed: {total_records}\n"
    summary += f"Average Temperature: {avg_temp}°C\n"
    summary += f"Average Humidity: {avg_humidity}%\n"
    summary += f"Average Rainfall: {avg_rainfall}mm\n"

    if region and region != 'all':
        summary += f"Region: {region}\n"
    if start_date:
        summary += f"Date Range: {start_date} to {end_date or 'present'}\n"

    # Get additional stats based on report type
    if report_type == 'anomaly_report':
        anomalies = ClimateData.get_anomalies()
        summary += f"Anomalies Detected: {len(anomalies)}\n"
    elif report_type == 'regional_analysis':
        regional = ClimateData.get_regional_data()
        summary += f"Regions Covered: {len(regional)}\n"
    elif report_type == 'prediction_report':
        from models.prediction_model import Prediction
        predictions = Prediction.get_all(limit=100)
        summary += f"Total Predictions: {len(predictions)}\n"

    description_full = description or ''
    if region and region != 'all':
        description_full += f"\nRegion: {region}"
    if start_date:
        description_full += f"\nDate Range: {start_date} to {end_date or 'present'}"

    Report.create(
        title=title,
        description=description_full,
        report_type=report_type,
        category=category,
        generated_by=current_user.id,
        summary=summary
    )

    flash(f'Report "{title}" generated successfully with {total_records} records.', 'success')
    return redirect(url_for('analyst.reports'))


@analyst_bp.route('/reports/<int:report_id>')
@login_required
@analyst_required
def view_report(report_id):
    report = Report.get_by_id(report_id)
    if not report:
        flash('Report not found.', 'danger')
        return redirect(url_for('analyst.reports'))

    # Parse report data
    report = _enrich_report(dict(report))

    all_reports = Report.get_all()
    parsed_reports = [_enrich_report(dict(r)) for r in all_reports]

    datasets = Dataset.get_approved()
    regional = ClimateData.get_regional_data()
    regions = sorted(
        {str(r.get('station_name')).strip() for r in regional if r.get('station_name') is not None and str(r.get('station_name')).strip()},
        key=str.casefold,
    ) if regional else []

    return render_template('analyst/reports.html',
                         report=report,
                         reports=parsed_reports,
                         regions=regions,
                         datasets=datasets,
                         active_page='reports')


@analyst_bp.route('/reports/<int:report_id>/download')
@login_required
@analyst_required
def download_report(report_id):
    """Render the report as a text file and send it as a download."""
    report = Report.get_by_id(report_id)
    if not report:
        flash('Report not found.', 'danger')
        return redirect(url_for('analyst.reports'))

    lines = [
        '=' * 60,
        report.get('title', 'Climate Report'),
        '=' * 60,
        f"Report ID: {report.get('id')}",
        f"Type: {report.get('report_type', '').replace('_', ' ').title()}",
        f"Category: {report.get('category', '')}",
        f"Status: {report.get('status', '')}",
        f"Generated: {report.get('created_at', '')}",
        '',
        '--- Summary ---',
        report.get('summary', '') or 'No summary available.',
        '',
        '--- Description ---',
        report.get('description', '') or 'No description provided.',
    ]
    return Response(
        '\n'.join(lines),
        mimetype='text/plain',
        headers={'Content-Disposition': f'attachment; filename=report_{report_id}.txt'}
    )


@analyst_bp.route('/reports/<int:report_id>/delete', methods=['POST'])
@login_required
@analyst_required
def delete_report(report_id):
    report = Report.get_by_id(report_id)
    if not report:
        flash('Report not found.', 'danger')
        return redirect(url_for('analyst.reports'))

    Report.delete(report_id)
    flash(f'Report "{report.get("title", "")}" deleted successfully.', 'success')
    return redirect(url_for('analyst.reports'))
