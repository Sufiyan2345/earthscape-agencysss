#!/usr/bin/env python3
"""
MapReduce Reducer for Climate Data Processing
Aggregates mapper output to compute statistics per region and metric.
"""

import sys
import json
import math
from collections import defaultdict


def climate_reducer():
    """
    Reducer function for climate data aggregation.
    Input: Key-value pairs from mapper (region, metric, value, date)
    Output: Aggregated statistics per region per metric
    """
    current_region = None
    current_metric = None
    values = []
    dates = []

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        parts = line.split('\t')
        if len(parts) < 3:
            continue

        region = parts[0]
        metric = parts[1]
        try:
            value = float(parts[2])
        except (TypeError, ValueError):
            continue
        date = parts[3] if len(parts) > 3 else ''

        if current_region == region and current_metric == metric:
            values.append(value)
            if date:
                dates.append(date)
        else:
            if current_region and current_metric and values:
                emit_result(current_region, current_metric, values, dates)
            current_region = region
            current_metric = metric
            values = [value]
            dates = [date] if date else []

    # Emit last group
    if current_region and current_metric and values:
        emit_result(current_region, current_metric, values, dates)


def emit_result(region, metric, values, dates):
    """Compute and emit aggregated statistics."""
    count = len(values)
    total = sum(values)
    mean = total / count
    min_val = min(values)
    max_val = max(values)

    # Standard deviation
    variance = sum((x - mean) ** 2 for x in values) / count
    std_dev = math.sqrt(variance)

    # Median
    sorted_vals = sorted(values)
    if count % 2 == 0:
        median = (sorted_vals[count // 2 - 1] + sorted_vals[count // 2]) / 2
    else:
        median = sorted_vals[count // 2]

    result = {
        'region': region,
        'metric': metric,
        'count': count,
        'sum': round(total, 2),
        'mean': round(mean, 2),
        'min': round(min_val, 2),
        'max': round(max_val, 2),
        'std_dev': round(std_dev, 2),
        'median': round(median, 2),
        'date_range': {
            'start': min(dates) if dates else '',
            'end': max(dates) if dates else ''
        }
    }

    print(f"{region}\t{metric}\t{json.dumps(result)}")


def anomaly_reducer():
    """
    Reducer for anomaly detection using Z-score method.
    Identifies data points that deviate significantly from the mean.
    """
    current_key = None
    values = []
    date_values = []

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        parts = line.split('\t')
        if len(parts) < 2:
            continue

        key = parts[0]
        value = float(parts[1])
        date = parts[2] if len(parts) > 2 else ''

        if current_key == key:
            values.append(value)
            date_values.append((date, value))
        else:
            if current_key and values:
                detect_anomalies(current_key, values, date_values)
            current_key = key
            values = [value]
            date_values = [(date, value)] if date else []

    if current_key and values:
        detect_anomalies(current_key, values, date_values)


def detect_anomalies(key, values, date_values):
    """Detect anomalies using Z-score method (threshold = 2 standard deviations)."""
    mean = sum(values) / len(values)
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    std_dev = math.sqrt(variance)

    if std_dev == 0:
        return

    threshold = 2.0
    anomalies = []

    for date, value in date_values:
        z_score = abs((value - mean) / std_dev)
        if z_score > threshold:
            anomalies.append({
                'date': date,
                'value': value,
                'z_score': round(z_score, 2),
                'mean': round(mean, 2),
                'std_dev': round(std_dev, 2)
            })

    if anomalies:
        result = {
            'key': key,
            'total_records': len(values),
            'anomaly_count': len(anomalies),
            'anomalies': anomalies
        }
        print(f"{key}\t{json.dumps(result)}")


def correlation_reducer():
    """
    Reducer for computing Pearson correlation coefficients between variable pairs.
    """
    current_key = None
    current_pair = None
    x_values = []
    y_values = []

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        parts = line.split('\t')
        if len(parts) < 3:
            continue

        region = parts[0]
        pair_type = parts[1]
        pair_values = parts[2].split(',')

        if len(pair_values) != 2:
            continue

        if current_key == region and current_pair == pair_type:
            x_values.append(float(pair_values[0]))
            y_values.append(float(pair_values[1]))
        else:
            if current_key and current_pair and x_values:
                compute_correlation(current_key, current_pair, x_values, y_values)
            current_key = region
            current_pair = pair_type
            x_values = [float(pair_values[0])]
            y_values = [float(pair_values[1])]

    if current_key and current_pair and x_values:
        compute_correlation(current_key, current_pair, x_values, y_values)


def compute_correlation(region, pair_type, x_vals, y_vals):
    """Compute Pearson correlation coefficient."""
    n = len(x_vals)
    if n < 2:
        return

    sum_x = sum(x_vals)
    sum_y = sum(y_vals)
    sum_xy = sum(x * y for x, y in zip(x_vals, y_vals))
    sum_x2 = sum(x ** 2 for x in x_vals)
    sum_y2 = sum(y ** 2 for y in y_vals)

    numerator = n * sum_xy - sum_x * sum_y
    denominator = math.sqrt((n * sum_x2 - sum_x ** 2) * (n * sum_y2 - sum_y ** 2))

    if denominator == 0:
        correlation = 0
    else:
        correlation = numerator / denominator

    result = {
        'region': region,
        'pair': pair_type,
        'correlation': round(correlation, 4),
        'sample_size': n,
        'interpretation': interpret_correlation(correlation)
    }
    print(f"{region}\t{pair_type}\t{json.dumps(result)}")


def interpret_correlation(r):
    """Interpret correlation coefficient."""
    abs_r = abs(r)
    direction = "positive" if r > 0 else "negative"
    if abs_r >= 0.8:
        strength = "very strong"
    elif abs_r >= 0.6:
        strength = "strong"
    elif abs_r >= 0.4:
        strength = "moderate"
    elif abs_r >= 0.2:
        strength = "weak"
    else:
        strength = "very weak"
    return f"{strength} {direction} correlation"


if __name__ == '__main__':
    reducer_type = sys.argv[1] if len(sys.argv) > 1 else 'climate'

    if reducer_type == 'anomaly':
        anomaly_reducer()
    elif reducer_type == 'correlation':
        correlation_reducer()
    else:
        climate_reducer()
