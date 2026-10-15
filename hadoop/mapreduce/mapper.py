#!/usr/bin/env python3
"""
MapReduce Mapper for Climate Data Processing
Processes climate records and emits key-value pairs for reducer aggregation.
"""

import sys
import json
import csv
from datetime import datetime


def climate_mapper():
    """
    Mapper function for climate data processing.
    Input: Climate records (CSV or JSON format)
    Output: Key-value pairs keyed by (region, metric_type)
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            # Try parsing as JSON first
            try:
                record = json.loads(line)
                process_json_record(record)
            except json.JSONDecodeError:
                # Parse as CSV
                process_csv_line(line)
        except Exception as e:
            # Log error and skip malformed records
            print(f"MAPPER_ERROR: {str(e)}", file=sys.stderr)
            continue


def process_json_record(record):
    """Process a JSON-formatted climate record."""
    region = record.get('station_name') or record.get('region') or 'unknown'
    date = record.get('date', '')
    temperature = record.get('temperature')
    rainfall = record.get('rainfall')
    humidity = record.get('humidity')
    wind_speed = record.get('wind_speed')
    pressure = record.get('pressure')
    air_quality = record.get('air_quality_index')

    # Emit temperature data
    if temperature is not None:
        print(f"{region}\ttemperature\t{temperature}\t{date}")

    # Emit rainfall data
    if rainfall is not None:
        print(f"{region}\trainfall\t{rainfall}\t{date}")

    # Emit humidity data
    if humidity is not None:
        print(f"{region}\thumidity\t{humidity}\t{date}")

    # Emit wind speed data
    if wind_speed is not None:
        print(f"{region}\twind_speed\t{wind_speed}\t{date}")

    # Emit pressure data
    if pressure is not None:
        print(f"{region}\tpressure\t{pressure}\t{date}")

    # Emit air quality data
    if air_quality is not None:
        print(f"{region}\tair_quality\t{air_quality}\t{date}")


def process_csv_line(line):
    """Process a CSV-formatted climate record."""
    try:
        reader = csv.reader([line])
        fields = next(reader)
        if len(fields) < 7:
            return

        date = fields[0]
        region = fields[1]
        temperature = fields[2]
        rainfall = fields[3]
        humidity = fields[4]
        wind_speed = fields[5]
        pressure = fields[6]
        air_quality = fields[7] if len(fields) > 7 else None

        # Emit each metric
        if temperature:
            print(f"{region}\ttemperature\t{temperature}\t{date}")
        if rainfall:
            print(f"{region}\trainfall\t{rainfall}\t{date}")
        if humidity:
            print(f"{region}\thumidity\t{humidity}\t{date}")
        if wind_speed:
            print(f"{region}\twind_speed\t{wind_speed}\t{date}")
        if pressure:
            print(f"{region}\tpressure\t{pressure}\t{date}")
        if air_quality:
            print(f"{region}\tair_quality\t{air_quality}\t{date}")
    except Exception:
        pass


def anomaly_mapper():
    """
    Specialized mapper for anomaly detection.
    Emits records formatted for statistical anomaly analysis.
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            region = record.get('station_name') or record.get('region') or 'unknown'
            date = record.get('date', '')
            temperature = record.get('temperature')
            rainfall = record.get('rainfall')

            # Emit for z-score calculation
            if temperature not in (None, ''):
                print(f"{region}_temp\t{float(temperature)}\t{date}")
            if rainfall not in (None, ''):
                print(f"{region}_rain\t{float(rainfall)}\t{date}")
        except Exception:
            continue


def correlation_mapper():
    """
    Mapper for correlation analysis between climate variables.
    Emits paired values for correlation coefficient calculation.
    """
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
            region = record.get('station_name') or record.get('region') or 'unknown'
            temp = record.get('temperature', '')
            rain = record.get('rainfall', '')
            humidity = record.get('humidity', '')
            aqi = record.get('air_quality_index', '')

            if temp not in (None, '') and rain not in (None, ''):
                print(f"{region}\ttemp_rain\t{temp},{rain}")
            if temp not in (None, '') and humidity not in (None, ''):
                print(f"{region}\ttemp_humidity\t{temp},{humidity}")
            if temp not in (None, '') and aqi not in (None, ''):
                print(f"{region}\ttemp_aqi\t{temp},{aqi}")
        except Exception:
            continue


if __name__ == '__main__':
    mapper_type = sys.argv[1] if len(sys.argv) > 1 else 'climate'

    if mapper_type == 'anomaly':
        anomaly_mapper()
    elif mapper_type == 'correlation':
        correlation_mapper()
    else:
        climate_mapper()
