import sys, os, re
sys.path.insert(0, r'C:\Users\IQRACOM\OneDrive\Desktop\Earthscape Climate')
os.environ['FLASK_ENV'] = 'testing'
from app import create_app
app = create_app()
with app.test_client() as client:
    client.post('/auth/login', data={'username':'analyst','password':'analyst123'}, follow_redirects=True)
    html = client.get('/analyst/satellite-imagery').data.decode()
    m = re.search(r'<form[^>]*update_satellite_imagery[^>]*>(.*?)</form>', html, re.DOTALL)
    if m:
        form = m.group(1)
        act = re.search(r'action="([^"]+)"', form)
        print('FORM ACTION:', act.group(1) if act else 'NOT FOUND')
        print('METHOD POST:', 'method="POST"' in form)
        print('ENCTYPE:', 'multipart/form-data' in form)
        for f in ['platform','latitude','longitude','capture_date','station_name','image_file']:
            print('  field', f, 'PRESENT' if ('name="'+f+'"') in form else 'MISSING')
        print('  submit btn:', 'type="submit"' in form)
    else:
        print('NO EDIT FORM FOUND')
    print('image url present:', (('/analyst/satellite-imagery/1/image' in html) or ('/analyst/satellite-imagery/2/image' in html)))
    print('toggleEdit count:', html.count('toggleEdit'))
