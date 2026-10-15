"""End-to-end test for MongoDB + HDFS + Hadoop integration."""
import sys
import os
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
        failed += 1

with app.app_context():
    # ── MongoDB Module ──
    print("=== MongoDB Module ===")
    
    def t_mongo_status():
        from utils.mongo import mongo_status, is_mongo_available
        s = mongo_status()
        assert 'status' in s
        assert 'backend' in s
        print(f"    status={s['status']}, backend={s['backend']}")
    test("mongo_status()", t_mongo_status)

    def t_mongo_collection_crud():
        from utils.mongo import get_collection
        col = get_collection('test_integration')
        # insert
        doc_id = col.insert_one({'name': 'alpha', 'value': 10})
        assert doc_id is not None
        # find
        found = col.find_one({'name': 'alpha'})
        assert found is not None
        assert found['value'] == 10
        # update
        col.update_one({'name': 'alpha'}, {'$set': {'value': 99}})
        updated = col.find_one({'name': 'alpha'})
        assert updated['value'] == 99
        # count
        assert col.count_documents({}) >= 1
        # delete
        col.delete_one({'name': 'alpha'})
        assert col.find_one({'name': 'alpha'}) is None
        # cleanup
        col.delete_many({})
    test("Collection CRUD (insert/find/update/delete)", t_mongo_collection_crud)

    def t_mongo_insert_many():
        from utils.mongo import get_collection
        col = get_collection('test_integration')
        result = col.insert_many([{'x': 1}, {'x': 2}, {'x': 3}])
        assert len(result.inserted_ids) == 3
        assert col.count_documents({}) >= 3
        col.delete_many({})
    test("insert_many()", t_mongo_insert_many)

    def t_mongo_query_operators():
        from utils.mongo import get_collection
        col = get_collection('test_integration')
        col.insert_many([{'v': 1}, {'v': 5}, {'v': 10}, {'v': 20}])
        # $gt
        results = col.find({'v': {'$gt': 5}})
        assert len(results) == 2
        # $lte
        results = col.find({'v': {'$lte': 5}})
        assert len(results) == 2
        # $in
        results = col.find({'v': {'$in': [1, 20]}})
        assert len(results) == 2
        col.delete_many({})
    test("Query operators ($gt, $lte, $in)", t_mongo_query_operators)

    def t_mongo_aggregate():
        from utils.mongo import get_collection
        col = get_collection('test_integration')
        col.insert_many([
            {'cat': 'A', 'val': 10},
            {'cat': 'A', 'val': 20},
            {'cat': 'B', 'val': 30},
        ])
        result = col.aggregate([
            {'$match': {'cat': 'A'}},
            {'$group': {'_id': '$cat', 'total': {'$sum': '$val'}}}
        ])
        assert len(result) == 1
        assert result[0]['total'] == 30
        col.delete_many({})
    test("Aggregate ($match, $group, $sum)", t_mongo_aggregate)

    # ── WebHDFS Client ──
    print("\n=== WebHDFS Client ===")

    def t_hdfs_status():
        from utils.webhdfs import real_hdfs
        s = real_hdfs.status()
        assert 'status' in s
        assert 'backend' in s
        print(f"    status={s['status']}, backend={s['backend']}")
    test("HDFS status()", t_hdfs_status)

    def t_hdfs_mkdir():
        from utils.webhdfs import real_hdfs
        real_hdfs.mkdir('/test_integration/subdir')
        # Verify directory exists via list_directory
        listing = real_hdfs.list_directory('/test_integration')
        assert listing is not None
        assert len(listing) >= 1
    test("HDFS mkdir + list_directory", t_hdfs_mkdir)

    def t_hdfs_file_ops():
        from utils.webhdfs import real_hdfs
        test_content = 'Hello HDFS integration test'
        real_hdfs.store_file('/test_integration/test.txt', test_content)
        # Read it back
        content = real_hdfs.read_file('/test_integration/test.txt')
        assert content is not None
        assert 'Hello HDFS' in content
        # Delete
        real_hdfs.delete('/test_integration/test.txt')
    test("HDFS file store/read/delete", t_hdfs_file_ops)

    # ── Hadoop MapReduce Bridge ──
    print("\n=== Hadoop MapReduce Bridge ===")

    def t_hadoop_cluster():
        from utils.hadoop_mr import hadoop_bridge
        info = hadoop_bridge.get_cluster_info()
        assert 'backend' in info
        print(f"    backend={info['backend']}")
    test("Hadoop cluster_info()", t_hadoop_cluster)

    def t_hadoop_submit():
        from utils.hadoop_mr import hadoop_bridge
        result = hadoop_bridge.submit_job(
            job_name='test_job',
            job_type='temperature_analysis',
            input_path='/climate/test.csv',
            output_path='/climate_output/test',
        )
        assert result is not None
        assert 'submitted_to' in result
    test("Hadoop submit_job", t_hadoop_submit)

    # ── Climate Model MongoDB writes ──
    print("\n=== Climate Model MongoDB Integration ===")

    def t_climate_insert_batch():
        from models.climate_model import ClimateData
        from models.dataset_model import Dataset
        from utils.mongo import get_collection
        # Create a real dataset first to satisfy FK constraint
        ds_id = Dataset.create(
            name='MongoDB Integration Test',
            description='Test dataset for MongoDB integration',
            file_path='test_mongo.csv',
            file_size=0,
            file_type='csv',
            category='weather',
            source='test',
            uploaded_by=1
        )
        records = [
            {
                'station_name': 'TestMongoDB-001', 'latitude': 40.0, 'longitude': -74.0,
                'elevation': 10, 'date': '2026-08-01',
                'temperature': 28.5, 'humidity': 65.0, 'rainfall': 0.0,
                'wind_speed': 10.0, 'wind_direction': 180.0,
                'pressure': 1013.0, 'co2_level': 415.0, 'air_quality_index': 50.0,
                'visibility': 15.0, 'cloud_cover': 30.0,
                'uv_index': 6.0, 'soil_moisture': 40.0, 'snow_depth': 0.0,
            }
        ]
        ClimateData.insert_batch(records, dataset_id=ds_id)
        # Check MongoDB received the data
        col = get_collection('climate_data')
        found = col.find({'station_name': 'TestMongoDB-001'})
        assert len(found) >= 1
        # Cleanup
        col.delete_many({'station_name': 'TestMongoDB-001'})
        Dataset.delete(ds_id)
    test("ClimateData.insert_batch() -> MongoDB", t_climate_insert_batch)

    # ── Summary ──
    print(f"\n{'='*50}")
    print(f"RESULTS: {passed} passed, {failed} failed out of {passed + failed}")
    if failed == 0:
        print("ALL TESTS PASSED!")
    else:
        print(f"WARNING: {failed} test(s) failed")
        sys.exit(1)
