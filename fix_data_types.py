"""
One-time repair script: converts numeric climate fields stored as STRINGS
in MongoDB into real floats.

Some uploaded files inserted values like "12.5" (text) instead of 12.5.
Strings break the "%.1f"|format() table rendering on /analyst/climate-data
and are silently skipped by chart aggregations ($avg / $sum).

Run ONCE while MongoDB is running:
    python fix_data_types.py
"""
from utils.database import get_collection

NUMERIC_FIELDS = [
    'latitude', 'longitude', 'elevation', 'temperature', 'humidity',
    'rainfall', 'wind_speed', 'wind_direction', 'pressure', 'co2_level',
    'air_quality_index', 'visibility', 'cloud_cover', 'uv_index',
    'soil_moisture', 'snow_depth',
]


def main():
    col = get_collection('climate_data')
    # Documents where at least one numeric field is a string
    query = {'$or': [{f: {'$type': 'string'}} for f in NUMERIC_FIELDS]}
    candidates = list(col.find(query))
    print('Found {} record(s) with string numeric fields.'.format(len(candidates)))

    fixed_docs = 0
    fixed_values = 0
    for doc in candidates:
        updates = {}
        for f in NUMERIC_FIELDS:
            v = doc.get(f)
            if isinstance(v, str):
                s = v.strip()
                if not s:
                    updates[f] = None
                    fixed_values += 1
                    continue
                try:
                    updates[f] = float(s)
                    fixed_values += 1
                except ValueError:
                    updates[f] = None  # unparseable junk -> treated as missing
                    fixed_values += 1
        if updates:
            col.update_one({'_id': doc['_id']}, {'$set': updates})
            fixed_docs += 1

    print('Repaired {} record(s), {} field value(s) converted to numbers.'.format(
        fixed_docs, fixed_values))
    if fixed_docs:
        print('Refresh the pages (Ctrl+F5) - charts and tables will use the fixed data.')
    else:
        print('Nothing to repair - all numeric fields are already real numbers.')


if __name__ == '__main__':
    main()
