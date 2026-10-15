#!/usr/bin/env python3
"""
Test script to verify High Alert thresholds are working correctly
"""
import sys
sys.path.insert(0, '.')

from utils.notifications import get_thresholds, get_threshold_value, check_and_create_alerts
from models.alert_model import Alert

print("=" * 80)
print("TESTING HIGH ALERT THRESHOLD SYSTEM")
print("=" * 80)

# 1. Test Threshold Retrieval
print("\n1️⃣ CHECKING THRESHOLD VALUES:")
print("-" * 80)
thresholds = get_thresholds()
for key, value in sorted(thresholds.items()):
    if 'max' in key or 'min' in key:
        print(f"  ✓ {key:25s} = {value}")

# Test individual threshold lookup
print("\n2️⃣ TESTING THRESHOLD LOOKUP:")
print("-" * 80)
test_keys = ['temperature_max', 'rainfall_max', 'wind_speed_max', 'air_quality_max']
for key in test_keys:
    val = get_threshold_value(key)
    status = "✓" if val is not None else "✗"
    print(f"  {status} {key:25s} = {val}")

# 2. Test Alert Creation with High Temperature
print("\n3️⃣ TESTING HIGH ALERT CREATION (Temperature > threshold):")
print("-" * 80)
test_data = {
    'temperature': 50.0,  # Exceeds 45.0 threshold → HIGH ALERT
    'rainfall': 100.0,     # Below 200.0 threshold → OK
    'wind_speed': 50.0,    # Below 120.0 threshold → OK
    'air_quality_index': 150.0  # Below 300.0 threshold → OK
}

print(f"  Test Data: temperature={test_data['temperature']}°C (threshold=45.0°C)")
print(f"  Expected: HIGH Alert should be created ✓")

alerts_created = check_and_create_alerts(test_data, source='test', location='Test Location')
print(f"  Result: {len(alerts_created)} alert(s) created - IDs: {alerts_created}")

if alerts_created:
    for alert_id in alerts_created:
        alert = Alert.get_by_id(alert_id)
        if alert:
            print(f"\n  Alert Details:")
            print(f"    - ID: {alert['id']}")
            print(f"    - Title: {alert['title']}")
            print(f"    - Severity: {alert['severity']} (Expected: 'high')")
            print(f"    - Threshold: {alert['threshold_value']}°C")
            print(f"    - Actual: {alert['actual_value']}°C")
            print(f"    - Message: {alert['message']}")
            status = "✓ PASS" if alert['severity'] == 'high' else "✗ FAIL"
            print(f"    Status: {status}")

# 3. Test Alert Creation with High Rainfall
print("\n4️⃣ TESTING HIGH ALERT CREATION (Rainfall > threshold):")
print("-" * 80)
test_data2 = {
    'temperature': 25.0,   # OK
    'rainfall': 250.0,      # Exceeds 200.0 threshold → HIGH ALERT
    'wind_speed': 50.0,    # OK
    'air_quality_index': 150.0  # OK
}

print(f"  Test Data: rainfall={test_data2['rainfall']}mm (threshold=200.0mm)")
print(f"  Expected: HIGH Alert should be created ✓")

alerts_created2 = check_and_create_alerts(test_data2, source='test', location='Test Location')
print(f"  Result: {len(alerts_created2)} alert(s) created - IDs: {alerts_created2}")

if alerts_created2:
    for alert_id in alerts_created2:
        alert = Alert.get_by_id(alert_id)
        if alert:
            print(f"\n  Alert Details:")
            print(f"    - ID: {alert['id']}")
            print(f"    - Title: {alert['title']}")
            print(f"    - Severity: {alert['severity']} (Expected: 'high')")
            print(f"    - Threshold: {alert['threshold_value']}mm")
            print(f"    - Actual: {alert['actual_value']}mm")
            status = "✓ PASS" if alert['severity'] == 'high' else "✗ FAIL"
            print(f"    Status: {status}")

# 4. Check Alert Display in Admin Panel
print("\n5️⃣ CHECKING ALERTS IN DATABASE:")
print("-" * 80)
high_alerts = Alert.get_all(severity='high', limit=10)
print(f"  Total HIGH severity alerts in DB: {len(high_alerts)}")
for alert in high_alerts[:3]:
    print(f"\n  - {alert['title']}")
    print(f"    Severity: {alert['severity']} | Category: {alert['category']}")
    print(f"    Created: {alert['created_at']}")

# 5. Check Severity Counts
print("\n6️⃣ ALERT SEVERITY BREAKDOWN:")
print("-" * 80)
try:
    severity_counts = Alert.get_by_severity()
    for count_doc in severity_counts:
        if isinstance(count_doc, dict):
            severity = count_doc.get('_id', 'unknown')
            count = count_doc.get('count', 0)
            print(f"  {str(severity).upper():10s} : {count} alert(s)")
except Exception as e:
    print(f"  Error retrieving severity counts: {e}")

print("\n" + "=" * 80)
print("✓ TEST COMPLETE")
print("=" * 80)
