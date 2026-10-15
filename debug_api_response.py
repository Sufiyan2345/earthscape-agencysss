#!/usr/bin/env python
"""Debug script to check the complete forecast API response."""
from models.climate_model import ClimateData
from models.prediction_model import Prediction
import json

# Replicate the analytics_forecast_data() function logic
predictions = Prediction.get_all(limit=100)
monthly = ClimateData.get_monthly_trends()
live_forecast = Prediction.get_live_forecast(list(reversed(monthly)))

print(f"Live forecast before overlay (count={len(live_forecast)}):")
print(json.dumps(live_forecast[:2], indent=2))

# Overlay latest ML
latest_records = ClimateData.get_latest_readings(limit=1)
latest_data_ts = latest_records[0].get('created_at', '') if latest_records else ''
live_forecast = Prediction.overlay_latest_ml(live_forecast, predictions, latest_data_ts)

print(f"\nLive forecast after overlay (count={len(live_forecast)}):")
print(json.dumps(live_forecast[:2], indent=2))

# Check what extractRainPredictions would get
def liveToPreds(liveForecast, key):
    out = []
    for f in (liveForecast or []):
        if f:
            v = f.get(key) if isinstance(f, dict) else getattr(f, key, None)
            if v is not None and v is not None:
                try:
                    float_v = float(v)
                    if not __import__('math').isnan(float_v):
                        out.append({'label': f.get('period') if isinstance(f, dict) else f.period, 'value': round(float_v * 10) / 10, 'confidence': 0.8})
                except:
                    pass
    return out

rainfall_preds = liveToPreds(live_forecast, 'predicted_rainfall_mm')
print(f"\nRainfall predictions extracted (count={len(rainfall_preds)}):")
print(json.dumps(rainfall_preds, indent=2))
