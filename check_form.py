import sys, os, re
sys.path.insert(0, r'C:\Users\IQRACOM\OneDrive\Desktop\Earthscape Climate')
os.environ['FLASK_ENV'] = 'testing'

from app import create_app
app = create_app()

with app.test_client() as client:
    client.post('/auth/login', data={'username': 'analyst', 'password': 'analyst123'}, follow_redirects=True)
    resp = client.get('/analyst/satellite-imagery')
    html = resp.data.decode('utf-8')
    
    match = re.search(r'<form[^>]*update_satellite_imagery[^>]*>(.*?)</form>', html, re.DOTALL)
    if match:
        form_inner = match.group(1)
        print('Form inner HTML length:', len(form_inner))
        fields = ['platform', 'latitude', 'longitude', 'capture_date', 'station_name']
        for field in fields:
            present = 'name="' + field + '"' in form_inner
            print('Field ' + field + ': ' + ('present' if present else 'MISSING'))
        print('Contains submit button:', 'type="submit"' in form_inner)
        print('Contains CSRF:', 'csrf' in form_inner.lower())
    else:
        print('Update form not found in HTML')
