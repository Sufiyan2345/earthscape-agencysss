import sys, os
sys.path.insert(0, r'C:\Users\IQRACOM\OneDrive\Desktop\Earthscape Climate')
os.environ['FLASK_ENV'] = 'testing'

from app import create_app
from models.imagery_model import SatelliteImage

app = create_app()

with app.test_client() as client:
    client.post('/auth/login', data={'username': 'analyst', 'password': 'analyst123'}, follow_redirects=True)
    images = SatelliteImage.get_all(limit=200)
    print('Total images in DB:', len(images))
    missing = 0
    for img in images:
        p = img.get('stored_path')
        exists = bool(p) and os.path.exists(p)
        if not exists:
            missing += 1
            print('  MISSING file for image', img.get('id'), '| path:', repr(p), '| uploaded_by:', img.get('uploaded_by'))
    print('Images with missing files:', missing)
