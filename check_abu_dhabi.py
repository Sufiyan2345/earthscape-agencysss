#!/usr/bin/env python
from utils.database import get_collection

print("=" * 80)
print("SEARCHING FOR 'ABU DHABI CLIMATE RECORD' DATASET")
print("=" * 80)

ds_col = get_collection('datasets')
records = list(ds_col.find({'name': {'$regex': 'Abu Dhabi', '$options': 'i'}}))

if not records:
    print("\n❌ No dataset found with 'Abu Dhabi' in the name")
    print("\nAll datasets in database:")
    all_datasets = list(ds_col.find().limit(20))
    for ds in all_datasets:
        print(f"  - {ds.get('name')} (ID: {ds.get('id')})")
else:
    for r in records:
        print(f"\n✓ Found Dataset:")
        print(f"  Name: {r.get('name')}")
        print(f"  ID: {r.get('id')}")
        print(f"  Category: {r.get('category')}")
        print(f"  File Path: {r.get('file_path')}")
        print(f"  HDFS Path: {r.get('hdfs_path')}")
        print(f"  Approval Status: {r.get('approval_status')}")
        print(f"  File Size: {r.get('file_size')} bytes")
        print(f"  File Type: {r.get('file_type')}")
        print(f"  Created At: {r.get('created_at')}")
        
        # Check if file exists
        import os
        if r.get('file_path'):
            exists = os.path.exists(r.get('file_path'))
            print(f"  File Exists: {'✓ YES' if exists else '✗ NO'}")
        print()

# Now check uploads folder structure
print("\n" + "=" * 80)
print("UPLOADS FOLDER STRUCTURE")
print("=" * 80)
import os
uploads_dir = "uploads"
for category in os.listdir(uploads_dir):
    cat_path = os.path.join(uploads_dir, category)
    if os.path.isdir(cat_path):
        files = [f for f in os.listdir(cat_path) if not f.startswith('.')]
        print(f"\n{category}/")
        for f in files:
            file_path = os.path.join(cat_path, f)
            size = os.path.getsize(file_path)
            print(f"  - {f} ({size} bytes)")

print("\n" + "=" * 80)
print("HDFS PARTITION INFO")
print("=" * 80)
try:
    from utils.hdfs import partition_manager
    partitions = partition_manager.get_all_partitions()
    for pkey, p in partitions.items():
        print(f"\n{pkey}:")
        print(f"  Type: {p.get('type')}")
        print(f"  Value: {p.get('value')}")
        print(f"  HDFS Path: {p.get('hdfs_path')}")
        print(f"  Records: {p.get('record_count', 0)}")
        print(f"  Size: {p.get('total_size', 0)} bytes")
except Exception as e:
    print(f"Error reading HDFS partitions: {e}")
