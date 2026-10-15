from flask import render_template, request, jsonify, redirect, url_for, flash
from flask_login import login_required
from analyst import analyst_bp
from auth.decorators import analyst_required
from models.climate_model import ClimateData
from models.dataset_model import Dataset
from utils.database import get_collection
import math

PER_PAGE = 20


def _build_match(dataset_id=None, region='', year=None):
    """Mongo match clause for the selected dataset / location / year filters."""
    match = {}
    if dataset_id:
        match['dataset_id'] = int(dataset_id)
    if region:
        match['station_name'] = region
    if year:
        match['date'] = {'$regex': f'^{int(year)}'}
    return match


def _scoped_summary(match):
    """Aggregate summary stats over exactly the filtered records."""
    col = get_collection('climate_data')
    pipeline = []
    if match:
        pipeline.append({'$match': match})
    pipeline.append({
        '$group': {
            '_id': None,
            'total_records': {'$sum': 1},
            'avg_temp': {'$avg': '$temperature'},
            'avg_rainfall': {'$avg': '$rainfall'},
            'avg_humidity': {'$avg': '$humidity'},
            'avg_pressure': {'$avg': '$pressure'},
            'avg_wind': {'$avg': '$wind_speed'},
            'avg_co2': {'$avg': '$co2_level'},
            'avg_aqi': {'$avg': '$air_quality_index'},
            'avg_visibility': {'$avg': '$visibility'},
            'avg_uv_index': {'$avg': '$uv_index'},
            'avg_soil_moisture': {'$avg': '$soil_moisture'},
        }
    })
    result = list(col.aggregate(pipeline))
    summary = result[0] if result else {}
    summary.pop('_id', None)
    for key in ('total_records',):
        summary.setdefault(key, 0)
    for key in ('avg_temp', 'avg_rainfall', 'avg_humidity', 'avg_wind', 'avg_co2',
                'avg_pressure', 'avg_aqi', 'avg_visibility', 'avg_uv_index',
                'avg_soil_moisture'):
        summary[key] = round(summary[key], 1) if summary.get(key) is not None else 0
    return summary


def _scoped_regions(dataset_id=None):
    """Real station/location list for the dropdown (scoped to the dataset)."""
    col = get_collection('climate_data')
    match = {'station_name': {'$ne': None, '$exists': True}}
    if dataset_id:
        match['dataset_id'] = int(dataset_id)
    pipeline = [
        {'$match': match},
        {'$group': {'_id': '$station_name'}},
        {'$sort': {'_id': 1}},
    ]
    return [d['_id'] for d in col.aggregate(pipeline) if d['_id']]


def _scoped_years(dataset_id=None):
    """Real year list derived from stored record dates (scoped to the dataset)."""
    col = get_collection('climate_data')
    match = {'date': {'$ne': None, '$exists': True}}
    if dataset_id:
        match['dataset_id'] = int(dataset_id)
    pipeline = [
        {'$match': match},
        {'$addFields': {'year': {'$substrCP': ['$date', 0, 4]}}},
        {'$group': {'_id': '$year'}},
        {'$sort': {'_id': -1}},
    ]
    years = []
    for d in col.aggregate(pipeline):
        try:
            years.append(int(d['_id']))
        except (TypeError, ValueError):
            continue
    return years


def _monthly_series(match, year=None):
    """Monthly series for every chart variable (filtered).

    Rainfall is summed, all other metrics are averaged. Missing values stay
    None so the frontend can span gaps instead of drawing false zeros."""
    col = get_collection('climate_data')
    pipeline = []
    if match:
        pipeline.append({'$match': match})
    pipeline.append({'$addFields': {'month': {'$substrCP': ['$date', 0, 7]}}})
    pipeline.append({
        '$group': {
            '_id': '$month',
            'avg_temp': {'$avg': '$temperature'},
            'total_rainfall': {'$sum': '$rainfall'},
            'avg_humidity': {'$avg': '$humidity'},
            'avg_wind_speed': {'$avg': '$wind_speed'},
            'avg_pressure': {'$avg': '$pressure'},
            'avg_co2_level': {'$avg': '$co2_level'},
            'avg_air_quality_index': {'$avg': '$air_quality_index'},
            'avg_visibility': {'$avg': '$visibility'},
            'avg_uv_index': {'$avg': '$uv_index'},
            'avg_soil_moisture': {'$avg': '$soil_moisture'},
        }
    })
    if year:
        # Single year: full month range ascending
        pipeline.append({'$sort': {'_id': 1}})
    else:
        # All years: most recent 24 months, then flip to ascending
        pipeline.append({'$sort': {'_id': -1}})
        pipeline.append({'$limit': 24})

    rows = list(col.aggregate(pipeline))
    if not year:
        rows.reverse()

    series = {'labels': [], 'temperatures': [], 'rainfall': [], 'humidity': [],
              'wind_speed': [], 'pressure': [], 'co2_level': [],
              'air_quality_index': [], 'visibility': [], 'uv_index': [],
              'soil_moisture': []}
    # group key in the aggregation -> output series key
    key_map = {'avg_temp': 'temperatures', 'total_rainfall': 'rainfall',
               'avg_humidity': 'humidity', 'avg_wind_speed': 'wind_speed',
               'avg_pressure': 'pressure', 'avg_co2_level': 'co2_level',
               'avg_air_quality_index': 'air_quality_index',
               'avg_visibility': 'visibility', 'avg_uv_index': 'uv_index',
               'avg_soil_moisture': 'soil_moisture'}
    for r in rows:
        if not r.get('_id'):
            continue
        series['labels'].append(r['_id'])
        for agg_key, out_key in key_map.items():
            val = r.get(agg_key)
            series[out_key].append(round(val, 1) if val is not None else None)
    return series


@analyst_bp.route('/climate-data')
@login_required
@analyst_required
def climate_data():
    """Climate records explorer — only Admin-approved datasets are selectable."""
    datasets = Dataset.get_approved()
    dataset_id = request.args.get('dataset_id', type=int)
    region = request.args.get('region', '')
    year = request.args.get('year', type=int)
    page = request.args.get('page', 1, type=int)

    # The selected dataset must exist and be approved
    if dataset_id and not any(dataset.get('id') == dataset_id for dataset in datasets):
        dataset_id = None

    match = _build_match(dataset_id, region, year)
    col = get_collection('climate_data')

    total_records = col.count_documents(match)
    pages = max(1, math.ceil(total_records / PER_PAGE))
    page = min(max(1, page), pages)
    data = list(col.find(match).sort('date', -1)
                .skip((page - 1) * PER_PAGE).limit(PER_PAGE))

    summary = _scoped_summary(match)
    regions = _scoped_regions(dataset_id)
    years = _scoped_years(dataset_id)
    monthly_trends = _monthly_series(match, year)

    pagination = {
        'page': page,
        'pages': pages,
        'total': total_records,
        'has_prev': page > 1,
        'has_next': page < pages,
        'prev_num': page - 1,
        'next_num': page + 1,
    }

    return render_template('analyst/climate_data.html',
                         datasets=datasets,
                         data=data,
                         summary=summary,
                         regions=regions,
                         years=years,
                         monthly_trends=monthly_trends,
                         pagination=pagination,
                         selected_dataset=dataset_id,
                         selected_region=region,
                         selected_year=year,
                         active_page='climate_data')


@analyst_bp.route('/climate-data/correlation')
@login_required
@analyst_required
def correlation():
    """Return computed correlation analysis using real algorithms."""
    results = ClimateData.get_correlation_results()
    return jsonify(results)


@analyst_bp.route('/climate-data/<int:record_id>/update', methods=['POST'])
@login_required
@analyst_required
def update_climate_record(record_id):
    """Update a single climate data record."""
    col = get_collection('climate_data')
    record = col.find_one({'id': record_id})
    if not record:
        flash('Record not found.', 'danger')
        return redirect(url_for('analyst.climate_data'))

    updates = {}
    float_fields = ['temperature', 'humidity', 'rainfall', 'wind_speed', 'wind_direction',
                    'pressure', 'co2_level', 'air_quality_index', 'visibility',
                    'cloud_cover', 'uv_index', 'soil_moisture', 'snow_depth',
                    'latitude', 'longitude', 'elevation']
    str_fields = ['station_name', 'date']

    for f in float_fields:
        val = request.form.get(f)
        if val is not None and val != '':
            try:
                updates[f] = float(val)
            except (ValueError, TypeError):
                pass
    for f in str_fields:
        val = request.form.get(f, '').strip()
        if val:
            updates[f] = val

    if updates:
        col.update_one({'id': record_id}, {'$set': updates})
        flash('Record updated successfully.', 'success')
    else:
        flash('No valid fields to update.', 'warning')

    dataset_id = request.form.get('dataset_id', type=int)
    return redirect(url_for('analyst.climate_data', dataset_id=dataset_id))


@analyst_bp.route('/climate-data/<int:record_id>/delete', methods=['POST'])
@login_required
@analyst_required
def delete_climate_record(record_id):
    """Delete a single climate data record."""
    col = get_collection('climate_data')
    record = col.find_one({'id': record_id})
    if not record:
        flash('Record not found.', 'danger')
        return redirect(url_for('analyst.climate_data'))

    dataset_id = record.get('dataset_id')
    col.delete_one({'id': record_id})
    flash('Record deleted successfully.', 'success')
    return redirect(url_for('analyst.climate_data', dataset_id=dataset_id))


@analyst_bp.route('/climate-data/delete-many', methods=['POST'])
@login_required
@analyst_required
def delete_climate_records():
    """Delete selected climate records from the current explorer view."""
    raw_ids = request.form.getlist('record_ids')
    try:
        record_ids = [int(record_id) for record_id in raw_ids]
    except (TypeError, ValueError):
        record_ids = []
    deleted = get_collection('climate_data').delete_many({'id': {'$in': record_ids}}).deleted_count if record_ids else 0
    if deleted:
        flash(f'{deleted} climate record(s) deleted successfully.', 'success')
    else:
        flash('Select at least one climate record to delete.', 'warning')
    return redirect(url_for('analyst.climate_data',
                            dataset_id=request.form.get('dataset_id', type=int),
                            region=request.form.get('region', ''),
                            year=request.form.get('year', type=int)))
