"""Shared anomaly checks for realtime readings."""


def detect_latest_reading(detector, reading):
    """Return normalized anomaly flags for one realtime reading."""
    flags = []
    if not reading:
        return flags

    temperature = reading.get('temperature')
    if temperature is not None:
        result = detector.detect_temperature_anomaly(temperature)
        if result.get('is_anomaly'):
            flags.append({
                'type': result.get('type', 'unknown'),
                'severity': result.get('severity', 'unknown'),
                'z_score': result.get('z_score', 0),
                'value': temperature,
            })

    aqi = reading.get('air_quality_index')
    if aqi is not None:
        result = detector.detect_air_quality_anomaly(aqi)
        if result.get('is_anomaly'):
            flags.append({
                'type': 'air_quality',
                'severity': result.get('severity', 'unknown'),
                'category': result.get('category', ''),
                'value': aqi,
            })

    rainfall = reading.get('rainfall')
    humidity = reading.get('humidity')
    if rainfall is not None and humidity is not None:
        result = detector.detect_flood_risk(rainfall, humidity, reading.get('wind_speed'))
        if result.get('risk_level') in ('high', 'critical'):
            flags.append({
                'type': 'flood_risk',
                'severity': result.get('risk_level', 'unknown'),
                'risk_score': result.get('risk_score', 0),
                'factors': result.get('factors', []),
            })

    return flags
