#!/usr/bin/env python
"""Debug script to check rainfall forecast data."""
from models.climate_model import ClimateData
from models.prediction_model import Prediction
import json

# Get monthly trends
monthly = ClimateData.get_monthly_trends()
print(f"Monthly data count: {len(monthly)}")

# Reverse to get oldest-first order
monthly_asc = list(reversed(monthly))
print(f"First month (oldest): {monthly_asc[0].get('month')} - rainfall: {monthly_asc[0].get('total_rainfall')}")
print(f"Last month (newest): {monthly_asc[-1].get('month')} - rainfall: {monthly_asc[-1].get('total_rainfall')}")

# Get live forecast
live_forecast = Prediction.get_live_forecast(monthly_asc)
print(f"\nLive forecast count: {len(live_forecast)}")
print(f"Live forecast data:\n{json.dumps(live_forecast, indent=2)}")

# Get predictions
predictions = Prediction.get_all(limit=5)
print(f"\nPredictions count: {len(predictions)}")
for p in predictions:
    result_str = p.get('prediction_result', '{}')
    try:
        result = json.loads(result_str) if isinstance(result_str, str) else result_str
        has_rain = 'predicted_rainfall' in result or 'predicted_rainfall_mm' in result
        print(f"  - ID {p.get('id')}: type={p.get('model_type')}, has_rainfall={has_rain}, keys={list(result.keys())[:5]}")
    except:
        print(f"  - ID {p.get('id')}: Failed to parse result")
