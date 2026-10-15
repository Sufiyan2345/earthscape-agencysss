import sys, os, io
sys.path.insert(0, r'C:\Users\IQRACOM\OneDrive\Desktop\Earthscape Climate')
os.environ['FLASK_ENV'] = 'testing'

from app import create_app
from models.imagery_model import SatelliteImage

app = create_app()

# Pick a small valid image for upload test
test_src = r'C:\Users\IQRACOM\OneDrive\Desktop\Earthscape Climate\static\images\sidebar_admin.jpg'
assert os.path.exists(test_src), 'test source missing'

with app.test_client() as client:
    r = client.post('/auth/login', data={'username': 'analyst', 'password': 'analyst123'}, follow_redirects=True)
    print('login', r.status_code)

    # Upload an image as analyst
    with open(test_src, 'rb') as f:
        r = client.post('/analyst/satellite-imagery/upload',
            data={'platform': 'LANDSAT-9', 'latitude': '20.5', 'longitude': '78.9',
                  'capture_date': '2024-01-15', 'image_file': (f, 'test_upload.jpg')},
            follow_redirects=True)
    print('upload', r.status_code)

    images = SatelliteImage.get_all(limit=60)
    owned = [i for i in images if i.get('uploaded_by') == 2]
    assert owned, 'no owned image'
    img = owned[0]
    print('TARGET image id', img['id'], 'path', img.get('stored_path'), 'exists', os.path.exists(img.get('stored_path','')))

    # EDIT 1: metadata only (no new file)
    r = client.post('/analyst/satellite-imagery/%d/update' % img['id'],
        data={'platform': 'SENTINEL-2', 'latitude': '28.6', 'longitude': '77.2',
              'capture_date': '2025-05-20', 'station_name': 'EDITED-STATION'},
        follow_redirects=True)
    print('edit1', r.status_code, 'flash-updated' , 'updated successfully' in r.data.decode())

    upd = SatelliteImage.get_by_id(img['id'])
    print('  platform', upd.get('platform'), 'station', upd.get('station_name'),
          'lat', upd.get('latitude'), 'path_exists', os.path.exists(upd.get('stored_path','')))

    # Check image still serves
    r = client.get('/analyst/satellite-imagery/%d/image' % img['id'])
    print('  image GET', r.status_code)

    # EDIT 2: with new image file
    with open(test_src, 'rb') as f:
        r = client.post('/analyst/satellite-imagery/%d/update' % img['id'],
            data={'platform': 'MODIS-TERRA', 'latitude': '10.0', 'longitude': '20.0',
                  'capture_date': '2023-03-03', 'station_name': 'RE-IMG',
                  'image_file': (f, 'new_image.jpg')},
            follow_redirects=True)
    print('edit2', r.status_code, 'flash-updated', 'updated successfully' in r.data.decode())

    upd = SatelliteImage.get_by_id(img['id'])
    print('  platform', upd.get('platform'), 'station', upd.get('station_name'),
          'path_exists', os.path.exists(upd.get('stored_path','')))
    r = client.get('/analyst/satellite-imagery/%d/image' % img['id'])
    print('  image GET', r.status_code)
