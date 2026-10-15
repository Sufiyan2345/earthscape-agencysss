"""Test: CSV file -> HDFS + MongoDB dual storage verification."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from app import create_app
app = create_app()

passed = 0
failed = 0

def test(name, fn):
    global passed, failed
    try:
        fn()
        print(f"  PASS: {name}")
        passed += 1
    except Exception as e:
        print(f"  FAIL: {name} -> {e}")
        import traceback; traceback.print_exc()
        failed += 1

with app.app_context():
    print("=" * 60)
    print("FULL DATA FLOW TEST: CSV -> HDFS + MongoDB")
    print("=" * 60)

    # 1. Create a test CSV file
    print("\n--- Step 1: Create test CSV file ---")
    import pandas as pd
    from datetime import datetime

    test_dir = os.path.join('uploads', 'test_flow')
    os.makedirs(test_dir, exist_ok=True)
    csv_path = os.path.join(test_dir, 'test_climate_flow.csv')

    records = [
        {'station_name': 'FlowTest-001', 'latitude': 40.0, 'longitude': -74.0,
         'elevation': 10, 'date': '2026-07-01', 'temperature': 28.5,
         'humidity': 65.0, 'rainfall': 0.0, 'wind_speed': 10.0,
         'wind_direction': 180.0, 'pressure': 1013.0, 'co2_level': 415.0,
         'air_quality_index': 50.0, 'visibility': 15.0, 'cloud_cover': 30.0,
         'uv_index': 6.0, 'soil_moisture': 40.0, 'snow_depth': 0.0},
        {'station_name': 'FlowTest-002', 'latitude': 51.5, 'longitude': -0.1,
         'elevation': 20, 'date': '2026-07-02', 'temperature': 22.0,
         'humidity': 70.0, 'rainfall': 5.0, 'wind_speed': 15.0,
         'wind_direction': 270.0, 'pressure': 1010.0, 'co2_level': 412.0,
         'air_quality_index': 45.0, 'visibility': 12.0, 'cloud_cover': 50.0,
         'uv_index': 4.0, 'soil_moisture': 55.0, 'snow_depth': 0.0},
    ]
    df = pd.DataFrame(records)
    df.to_csv(csv_path, index=False)
    file_size = os.path.getsize(csv_path)
    print(f"  Created CSV: {csv_path} ({file_size} bytes, {len(records)} records)")

    # 2. Upload CSV file to HDFS
    print("\n--- Step 2: Upload CSV to HDFS ---")
    def t_hdfs_upload():
        from utils.webhdfs import real_hdfs
        hdfs_path = '/climate/test/test_climate_flow.csv'
        result = real_hdfs.upload_from_file(csv_path, hdfs_path)
        assert result is not None
        # Verify file exists in HDFS
        exists = real_hdfs.exists(hdfs_path)
        assert exists, "File not found in HDFS after upload!"
        # Read back and verify
        content = real_hdfs.read_file(hdfs_path)
        assert content is not None
        assert 'FlowTest-001' in content
        print(f"    HDFS path: {hdfs_path}")
        print(f"    File exists in HDFS: {exists}")
        print(f"    Content verified: contains FlowTest-001")
    test("CSV file uploaded to HDFS", t_hdfs_upload)

    # 3. Save parsed records to MongoDB (via ClimateData.insert_batch)
    print("\n--- Step 3: Save records to MongoDB ---")
    def t_mongo_records():
        from models.dataset_model import Dataset
        from models.climate_model import ClimateData
        from utils.mongo import get_collection

        # Create dataset first (FK constraint)
        ds_id = Dataset.create(
            name='Flow Test Dataset',
            description='Test for CSV->HDFS+MongoDB flow',
            file_path=csv_path,
            file_size=file_size,
            file_type='csv',
            category='test',
            source='test_flow',
            uploaded_by=1
        )

        # Insert batch (this dual-writes to SQLite + MongoDB)
        ClimateData.insert_batch(records, ds_id)

        # Verify records in MongoDB
        col = get_collection('climate_data')
        found = col.find({'station_name': {'$in': ['FlowTest-001', 'FlowTest-002']}})
        assert len(found) == 2, f"Expected 2 records in MongoDB, found {len(found)}"
        print(f"    Records in MongoDB climate_data: {len(found)}")
        for r in found:
            print(f"      - {r.get('station_name')}: temp={r.get('temperature')}, date={r.get('date')}")

        # Cleanup
        col.delete_many({'station_name': {'$in': ['FlowTest-001', 'FlowTest-002']}})
        Dataset.delete(ds_id)
    test("Records saved to MongoDB", t_mongo_records)

    # 4. Verify dataset metadata in MongoDB
    print("\n--- Step 4: Verify dataset in MongoDB ---")
    def t_mongo_dataset():
        from models.dataset_model import Dataset
        from utils.mongo import get_collection
        import time; time.sleep(0.2)  # avoid sqlite locking

        ds_id = Dataset.create(
            name='Dataset Meta Test',
            description='Testing dataset metadata in MongoDB',
            file_path='test_meta.csv',
            file_size=100,
            file_type='csv',
            category='weather',
            source='test',
            uploaded_by=1
        )
        col = get_collection('datasets')
        found = col.find_one({'dataset_id': ds_id})
        assert found is not None, "Dataset not found in MongoDB!"
        assert found['name'] == 'Dataset Meta Test'
        assert found['category'] == 'weather'
        print(f"    Dataset in MongoDB: {found['name']} (id={ds_id})")
        Dataset.delete(ds_id)
        col.delete_many({'dataset_id': ds_id})
    test("Dataset metadata in MongoDB", t_mongo_dataset)

    # 5. Verify user registration in MongoDB
    print("\n--- Step 5: Verify user in MongoDB ---")
    def t_mongo_user():
        from models.user_model import User
        from utils.mongo import get_collection

        import time
        ts = str(int(time.time()))
        uid = User.create(f'flowtest_{ts}', f'flowtest_{ts}@test.com', 'password123',
                          'Flow Test User', 'analyst')
        col = get_collection('users')
        found = col.find_one({'user_id': uid})
        assert found is not None, "User not found in MongoDB!"
        assert found['role'] == 'analyst'
        print(f"    User in MongoDB: {found['username']} (id={uid}, role={found['role']})")

        # Test login recording
        user = User.get_by_id(uid)
        user.record_login()
        updated = col.find_one({'user_id': uid})
        assert 'last_login' in updated
        assert 'login_history' in updated
        print(f"    Login recorded: last_login={updated['last_login']}")
        print(f"    Login history entries: {len(updated['login_history'])}")

        # Cleanup
        col.delete_many({'user_id': uid})
        # Don't delete SQLite user (FK constraints from feedback/alerts)
        # Just deactivate instead
        User.toggle_active(uid)
    test("User registration + login in MongoDB", t_mongo_user)

    # 6. Verify alert in MongoDB
    print("\n--- Step 6: Verify alert in MongoDB ---")
    def t_mongo_alert():
        from models.alert_model import Alert
        from utils.mongo import get_collection
        import time; time.sleep(0.2)  # avoid SQLite locking

        aid = Alert.create('HDFS Test Alert', 'Data stored in HDFS successfully',
                           'info', 'low', 'system')
        col = get_collection('alerts')
        found = col.find_one({'alert_id': aid})
        assert found is not None, "Alert not found in MongoDB!"
        print(f"    Alert in MongoDB: {found['title']} (severity={found['severity']})")
        col.delete_many({'alert_id': aid})
    test("Alert in MongoDB", t_mongo_alert)

    # 7. Verify feedback in MongoDB
    print("\n--- Step 7: Verify feedback in MongoDB ---")
    def t_mongo_feedback():
        from models.feedback_model import Feedback
        from utils.mongo import get_collection
        import time; time.sleep(0.2)  # avoid sqlite locking

        fid = Feedback.create('HDFS Storage', 'Please check HDFS storage', 'feature', 'low', 1)
        col = get_collection('feedback')
        found = col.find_one({'feedback_id': fid})
        assert found is not None, "Feedback not found in MongoDB!"
        print(f"    Feedback in MongoDB: {found['subject']} (status={found['status']})")
        col.delete_many({'feedback_id': fid})
    test("Feedback in MongoDB", t_mongo_feedback)

    # 8. Full HDFS directory listing
    print("\n--- Step 8: HDFS directory listing ---")
    def t_hdfs_listing():
        from utils.webhdfs import real_hdfs
        listing = real_hdfs.list_directory('/climate_data')
        print(f"    /climate_data contents: {len(listing)} items")
        for item in listing:
            print(f"      - {item['name']} ({item['type']}, {item['length']} bytes)")
    test("HDFS directory listing", t_hdfs_listing)

    # Cleanup test file
    try:
        os.remove(csv_path)
    except Exception:
        pass

    # Summary
    print(f"\n{'=' * 60}")
    print(f"RESULTS: {passed} passed, {failed} failed out of {passed + failed}")
    print(f"{'=' * 60}")
    if failed == 0:
        print("ALL DATA FLOW TESTS PASSED!")
        print("\nData is saved to BOTH:")
        print("  -> MongoDB: All records (users, climate, alerts, feedback, datasets)")
        print("  -> HDFS:    All CSV files (via WebHDFS REST API)")
    else:
        print(f"WARNING: {failed} test(s) failed")
        sys.exit(1)
