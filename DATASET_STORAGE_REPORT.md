================================================================================
DATASET UPLOAD & APPROVAL FLOW - FILE STORAGE LOCATIONS
================================================================================

QUESTION: When analyst uploads dataset and admin approves it, are files saved in:
  1. myuploads folder?
  2. HDFS?

ANSWER: ✓ YES - Both locations!

================================================================================
HOW IT WORKS:
================================================================================

STEP 1: ANALYST UPLOADS FILE
   └─ File saved to: uploads/{category}/ folder
      Example: uploads/historical/

STEP 2: ADMIN APPROVES DATASET
   └─ File is ALSO copied to HDFS mock storage
      Example: uploads/hdfs/climate/historical/

================================================================================
ABU DHABI CLIMATE RECORD - APPROVED DATASET (ID: 75)
================================================================================

Status: ✓ APPROVED

Local Upload Folder:
   Path: uploads\historical\20260827155338_70a01f28.csv
   Size: 120,431 bytes
   Status: ✓ EXISTS

HDFS Storage (Mock):
   Path: uploads\hdfs\climate\historical\20260827155338_70a01f28.csv
   Size: 120,431 bytes
   Status: ✓ EXISTS

Database Entry (MongoDB):
   - Name: Abu Dhabi Climate Record
   - ID: 75
   - Category: historical
   - File Type: CSV
   - Approval Status: APPROVED
   - Created: 2026-08-27 15:38:54
   - HDFS Path: /climate/historical/20260827155338_70a01f28.csv

================================================================================
FILE NAMING CONVENTION:
================================================================================

Original file name NOT preserved in uploads folder.
Instead, files are renamed to: {TIMESTAMP}_{UNIQUE_HASH}.{extension}

Example: 20260827155338_70a01f28.csv
   ├─ Timestamp: 2026-08-27 15:53:38
   └─ Unique Hash: 70a01f28

This prevents name conflicts when multiple files are uploaded.

================================================================================
OTHER ABU DHABI DATASETS IN SYSTEM:
================================================================================

1. Abu Dhabi_United Arab Emirates (ID: 71)
   Status: ✓ APPROVED
   Category: weather
   File: uploads\weather\20260827152228_6052050a.csv ✓
   HDFS: /climate/weather/20260827152228_6052050a.csv

2. Abu Dhabi_United Arab Emirates (ID: 72)
   Status: ⏳ PENDING (waiting for admin approval)
   Category: weather
   File: uploads\weather\20260827152830_fc9000fc.csv ✓
   HDFS: (empty - not copied until approved)

3. Abu Dhabi Climate Record (ID: 73)
   Status: ⏳ PENDING (waiting for admin approval)
   Category: historical
   File: MISSING (file was deleted)
   HDFS: /climate/historical/20260827153854_41491dfa.csv

4. Abu Dhabi Climate Record (ID: 75) ← MAIN APPROVED VERSION
   Status: ✓ APPROVED
   Category: historical
   File: uploads\historical\20260827155338_70a01f28.csv ✓
   HDFS: /climate/historical/20260827155338_70a01f28.csv ✓

================================================================================
FOLDER STRUCTURE:
================================================================================

uploads/
├── weather/              (Weather data uploads)
│   ├── 20260824184554_7e0a9454.csv
│   ├── 20260824184554_7e0a9454_cleaned.csv
│   ├── 20260825114446_3fa7bb3a.csv
│   ├── 20260827152228_6052050a.csv ← Abu Dhabi (APPROVED)
│   └── 20260827152830_fc9000fc.csv ← Abu Dhabi (PENDING)
│
├── historical/          (Historical data uploads)
│   └── 20260827155338_70a01f28.csv ← Abu Dhabi Climate Record (APPROVED)
│
├── sensors/
│   └── 20260825142304_0cca18be.csv
│
├── satellite/
├── realtime/
├── test_flow/
│
└── hdfs/                (HDFS mock storage - backup copy after approval)
    └── climate/
        ├── weather/     (HDFS copy of approved weather datasets)
        ├── historical/  (HDFS copy of approved historical datasets)
        ├── satellite/
        └── sensors/

================================================================================
SUMMARY:
================================================================================

✓ Files ARE saved in uploads/{category}/ folder when uploaded by analyst
✓ Files ARE COPIED to uploads/hdfs/climate/{category}/ when ADMIN APPROVES
✓ Metadata is stored in MongoDB (datasets collection)
✓ Original filename NOT preserved (replaced with timestamp_hash format)
✓ Abu Dhabi Climate Record (ID: 75) IS APPROVED and EXISTS in BOTH locations

Two-Stage Storage:
  1. Upload Stage → uploads/{category}/ folder
  2. Approval Stage → ALSO copies to uploads/hdfs/climate/{category}/ folder
