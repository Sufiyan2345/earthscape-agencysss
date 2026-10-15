import sys, os, re
sys.path.insert(0, r'C:\Users\IQRACOM\OneDrive\Desktop\Earthscape Climate')
os.environ['FLASK_ENV'] = 'testing'

from app import create_app
from models.imagery_model import SatelliteImage

app = create_app()

with app.test_client() as client:
    client.post('/auth/login', data={'username': 'analyst', 'password': 'analyst123'}, follow_redirects=True)
    
    resp = client.get('/analyst/satellite-imagery')
    html = resp.data.decode('utf-8')
    
    forms = re.findall(r'<form[^>]*update_satellite_imagery[^>]*>.*?</form>', html, re.DOTALL)
    print('Update forms found:', len(forms))
    
    if forms:
        form = forms[0]
        action = re.search(r'action="([^"]+)"', form)
        print('First form action:', action.group(1) if action else 'NOT FOUND')
        print('Has enctype:', 'enctype' in form)
        print('Has method POST:', 'method="POST"' in form)
        
        fields = ['platform', 'latitude', 'longitude', 'capture_date', 'station_name']
        for field in fields:
            if 'name="' + field + '"' in form:
                print('Field ' + field + ': present')
            else:
                print('Field ' + field + ': MISSING')
    
    print('toggleEdit function:', 'present' if 'toggleEdit' in html else 'MISSING')
