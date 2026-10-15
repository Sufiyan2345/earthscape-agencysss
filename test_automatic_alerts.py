#!/usr/bin/env python3
"""
Test script to verify AUTOMATIC HIGH ALERT is working
when real-time data exceeds threshold
"""
import sys
sys.path.insert(0, '.')

from models.realtime_model import RealtimeStream
from models.alert_model import Alert
from utils.notifications import get_thresholds
from datetime import datetime

print("=" * 80)
print("TESTING AUTOMATIC HIGH ALERT SYSTEM")
print("=" * 80)

# Get current thresholds
thresholds = get_thresholds()
print(f"\n1️⃣ CURRENT THRESHOLDS:")
print(f"  Temperature Max: {thresholds.get('temperature_max', 'N/A')}°C")
print(f"  Rainfall Max: {thresholds.get('rainfall_max', 'N/A')}mm")

# Count alerts before test
alerts_before = Alert.get_count()
high_alerts_before = len(Alert.get_all(severity='high'))

print(f"\n2️⃣ ALERTS BEFORE TEST:")
print(f"  Total Alerts: {alerts_before}")
print(f"  High Severity Alerts: {high_alerts_before}")

# Create real-time reading with EXCEEDING temperature (should trigger alert)
print(f"\n3️⃣ INSERTING REAL-TIME DATA WITH HIGH TEMPERATURE:")

temp_threshold = thresholds.get('temperature_max', 35.0)
test_temperature = temp_threshold + 10  # 10 degrees over threshold

print(f"  Temperature: {test_temperature}°C (Threshold: {temp_threshold}°C)")
print(f"  Expected: HIGH ALERT SHOULD BE CREATED AUTOMATICALLY ✓")

try:
    RealtimeStream.add_reading(
        stream_id=1,
        temperature=test_temperature,
        humidity=50.0,
        rainfall=100.0,
        wind_speed=30.0,
        co2_level=400.0,
        air_quality_index=80.0,
        publish=False
    )
    print(f"  ✓ Real-time reading added successfully")
except Exception as e:
    print(f"  ✗ ERROR creating real-time data: {e}")
    sys.exit(1)

# Count alerts after test
import time
time.sleep(1)  # Give database time to process

alerts_after = Alert.get_count()
high_alerts_after = len(Alert.get_all(severity='high'))

print(f"\n4️⃣ ALERTS AFTER TEST:")
print(f"  Total Alerts: {alerts_after}")
print(f"  High Severity Alerts: {high_alerts_after}")
print(f"  New Alerts Created: {alerts_after - alerts_before}")
print(f"  New High Alerts Created: {high_alerts_after - high_alerts_before}")

# Check if automatic alert was created
if high_alerts_after > high_alerts_before:
    print(f"\n✓ SUCCESS: AUTOMATIC HIGH ALERT IS WORKING!")
    print(f"  Found {high_alerts_after - high_alerts_before} new high alert(s)")
    
    # Show the alert details
    new_alerts = Alert.get_all(severity='high', limit=3)
    for alert in new_alerts:
        if 'temperature' in alert.get('category', '').lower():
            print(f"\n  Alert Details:")
            print(f"    - Title: {alert['title']}")
            print(f"    - Severity: {alert['severity']}")
            print(f"    - Message: {alert['message']}")
            print(f"    - Source: {alert['source']}")
            print(f"    - Created: {alert['created_at']}")
            break
else:
    print(f"\n✗ PROBLEM: AUTOMATIC HIGH ALERT IS NOT WORKING")
    print(f"  No high alerts were created when temperature exceeded threshold")
    print(f"  This means check_and_create_alerts() may not be called or has an issue")

print("\n" + "=" * 80)
print("TEST COMPLETE")
print("=" * 80)
