"""Test all routes by logging in as admin and analyst, then visiting every page."""
import urllib.request
import urllib.parse
import http.cookiejar
import re
import ssl

BASE = 'http://127.0.0.1:5000'

def make_opener():
    """Create a URL opener with cookie jar for session management."""
    cj = http.cookiejar.CookieJar()
    handler = urllib.request.HTTPCookieProcessor(cj)
    opener = urllib.request.build_opener(handler)
    return opener

def login(opener, username, password):
    """Login and store session cookie."""
    data = urllib.parse.urlencode({'username': username, 'password': password}).encode()
    req = urllib.request.Request(f'{BASE}/auth/login', data=data, method='POST')
    try:
        resp = opener.open(req)
        return resp.getcode(), resp.url
    except urllib.error.HTTPError as e:
        return e.code, e.url
    except urllib.error.URLError as e:
        return 0, str(e)

def test_route(opener, route):
    """Test a single route."""
    try:
        req = urllib.request.Request(f'{BASE}{route}')
        resp = opener.open(req)
        code = resp.getcode()
        body = resp.read().decode('utf-8', errors='replace')
        if code >= 400:
            return code, extract_error(body)
        return code, 'OK'
    except urllib.error.HTTPError as e:
        body = ''
        try:
            body = e.read().decode('utf-8', errors='replace')
        except:
            pass
        if e.code == 500:
            return e.code, extract_error(body)
        return e.code, str(e.reason)
    except Exception as e:
        return 0, str(e)

def extract_error(html):
    """Extract error message from HTML."""
    # Try to find traceback
    m = re.search(r'<div class="traceback">(.*?)</div>', html, re.DOTALL)
    if m:
        text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        return text[:300]
    # Try debugger error
    m = re.search(r'class="errormsg"[^>]*>(.*?)<', html, re.DOTALL)
    if m:
        return m.group(1)[:300]
    # Try plain traceback
    m = re.search(r'(\w+Error:.*?)</(?:div|pre|p)', html, re.DOTALL)
    if m:
        text = re.sub(r'<[^>]+>', '', m.group(1)).strip()
        return text[:300]
    if 'Internal Server Error' in html:
        return 'Internal Server Error'
    return 'Unknown error'

def test_panel(opener, username, password, routes, panel_name):
    """Login and test all routes."""
    print(f"\n{'='*60}")
    print(f"Testing {panel_name}")
    print(f"{'='*60}")
    
    code, url = login(opener, username, password)
    print(f"Login: {code} -> {url}")
    
    errors = []
    for route in routes:
        code, msg = test_route(opener, route)
        if code == 200:
            print(f"  [ OK ] {route}: 200")
        elif code in (301, 302):
            print(f"  [ OK ] {route}: {code} redirect")
        else:
            print(f"  [FAIL] {route}: {code} - {msg}")
            errors.append((route, code, msg))
    
    return errors

# Admin GET routes
admin_routes = [
    '/admin/',
    '/admin/dashboard',
    '/admin/users',
    '/admin/datasets',
    '/admin/satellite-imagery',
    '/admin/hdfs',
    '/admin/hdfs/partitions',
    '/admin/mapreduce',
    '/admin/analytics',
    '/admin/analytics/anomalies',
    '/admin/analytics/forecast',
    '/admin/realtime',
    '/admin/machine-learning',
    '/admin/machine-learning/correlation',
    '/admin/reports',
    '/admin/alerts',
    '/admin/alerts/rules',
    '/admin/alerts/preferences',
    '/admin/knowledge',
    '/admin/feedback',
    '/admin/settings',
    '/admin/profile',
]

# Analyst GET routes
analyst_routes = [
    '/analyst/',
    '/analyst/dashboard',
    '/analyst/climate-data',
    '/analyst/upload-dataset',
    '/analyst/ingestion',
    '/analyst/satellite-imagery',
    '/analyst/hdfs',
    '/analyst/hdfs/partitions',
    '/analyst/mapreduce',
    '/analyst/analytics',
    '/analyst/analytics/anomalies',
    '/analyst/analytics/forecast',
    '/analyst/machine-learning',
    '/analyst/machine-learning/correlation',
    '/analyst/realtime',
    '/analyst/visualization',
    '/analyst/alerts',
    '/analyst/alerts/preferences',
    '/analyst/reports',
    '/analyst/feedback',
    '/analyst/help',
    '/analyst/profile',
]

admin_errors = test_panel(make_opener(), 'admin', 'admin123', admin_routes, 'Admin Panel')
analyst_errors = test_panel(make_opener(), 'analyst', 'analyst123', analyst_routes, 'Analyst Panel')

print(f"\n{'='*60}")
print(f"SUMMARY")
print(f"{'='*60}")
print(f"Admin errors: {len(admin_errors)}")
for route, code, msg in admin_errors:
    print(f"  {route}: {code} - {msg}")
print(f"Analyst errors: {len(analyst_errors)}")
for route, code, msg in analyst_errors:
    print(f"  {route}: {code} - {msg}")

total = len(admin_errors) + len(analyst_errors)
if total == 0:
    print("\nAll pages working!")
else:
    print(f"\nTotal issues: {total}")
