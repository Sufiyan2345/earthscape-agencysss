from flask import render_template, request, jsonify
from flask_login import login_required
from analyst import analyst_bp
from auth.decorators import analyst_required
from models.climate_model import ClimateData
from utils.database import get_collection
import json


@analyst_bp.route('/visualization')
@login_required
@analyst_required
def visualization():
    """Climate data visualization explorer with filters and date ranges."""
    # Get available regions and years for filters
    regions = ClimateData.get_regions()
    years = ClimateData.get_available_years()

    # Get filter parameters
    selected_region = request.args.get('region', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    selected_vars = request.args.getlist('variables') or ['temperature', 'rainfall']
    group_by = request.args.get('group_by', 'month')

    # Fetch chart data with filters
    chart_data = ClimateData.get_chart_data(
        variables=selected_vars,
        start_date=start_date or None,
        end_date=end_date or None,
        region=selected_region or None,
        group_by=group_by,
    )

    labels = [d.get('period', '') for d in chart_data]
    series = {}
    for var in selected_vars:
        series[var] = [round(d[var], 2) if d.get(var) is not None else None for d in chart_data]

    # Get anomaly data for scatter plot
    anomalies = ClimateData.get_anomalies(threshold=2.0)

    # Summary stats
    summary = ClimateData.get_summary()
    summary.setdefault('avg_temp', 0)
    summary.setdefault('avg_rainfall', 0)
    summary.setdefault('avg_humidity', 0)
    summary.setdefault('total_records', 0)

    return render_template('analyst/visualization.html',
                         regions=regions,
                         years=years,
                         selected_region=selected_region,
                         start_date=start_date,
                         end_date=end_date,
                         selected_vars=selected_vars,
                         group_by=group_by,
                         labels=json.dumps(labels),
                         series=json.dumps(series),
                         anomalies_count=len(anomalies),
                         summary=summary,
                         active_page='visualization')
