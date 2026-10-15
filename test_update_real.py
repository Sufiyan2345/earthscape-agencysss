import sys, os
sys.path.insert(0, r'C:\Users\IQRACOM\OneDrive\Desktop\Earthscape Climate')
os.environ['FLASK_ENV'] = 'testing'

from app import create_app
from models.imagery_model import SatelliteImage

app = create_app()

with app.test_client() as client:
    client.post('/auth/login', data={'username': 'analyst', 'password': 'analyst123'}, follow_redirects=True)
    
    # Find images uploaded by analyst (user ID 2)
    images = SatelliteImage.get_all(limit=60)
    analyst_images = [img for img in images if img.get('uploaded_by') == 2]
    print(f'Total images: {len(images)}')
    print(f'Images by analyst (ID 2): {len(analyst_images)}')
    
    if analyst_images:
        test_img = analyst_images[0]
        print(f'Testing with image ID: {test_img["id"]}')
        
        resp = client.post(f'/analyst/satellite-imagery/{test_img["id"]}/update',
            data={
                'platform': 'SENTINEL-2',
                'latitude': '28.6139',
                'longitude': '77.2090',
                'capture_date': '2024-01-15',
                'station_name': 'UPDATED-STATION'
            },
            follow_redirects=True)
        
        html = resp.data.decode('utf-8')
        
        # Verify DB updated
        updated = SatelliteImage.get_by_id(test_img['id'])
        print(f'After update platform: {updated.get("platform")}')
        print(f'After update station_name: {updated.get("station_name")}')
        print(f'After update latitude: {updated.get("latitude")}')
        print(f'After update updated_at: {updated.get("updated_at")}')
        
        if updated.get('platform') == 'SENTINEL-2':
            print('SUCCESS: Data updated correctly!')
        else:
            print('FAIL: Data not updated')
    else:
        print('No images uploaded by analyst user - cannot test update')
        print('Images in DB:')
        for img in images[:5]:
            print(f'  ID {img["id"]}: uploaded_by={img.get("uploaded_by")}, platform={img.get("platform")}')
