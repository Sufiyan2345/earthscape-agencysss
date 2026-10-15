from app import create_app
import traceback

app = create_app()
app.config['TESTING'] = True

with app.test_client() as c:
    # Login
    r = c.post("/auth/login", data={"username": "analyst", "password": "analyst123"}, follow_redirects=False)
    print("Login:", r.status_code, r.headers.get('Location', ''))
    
    # Try dashboard
    r = c.get("/analyst/dashboard", follow_redirects=False)
    print("Dashboard:", r.status_code)
    if r.status_code == 500:
        # In TESTING mode, Flask should re-raise the exception
        print("ERROR - checking response text...")
        text = r.data.decode('utf-8', errors='replace')
        # Look for error details
        if 'Traceback' in text or 'Error' in text:
            # Extract relevant parts
            import re
            # Try to find the error type and message
            m = re.search(r'(\w+Error):\s*([^\n<]+)', text)
            if m:
                print(f"Error type: {m.group(1)}: {m.group(2)}")
            # Print first meaningful content
            lines = text.split('\n')
            for line in lines:
                line = line.strip()
                if line and not line.startswith('<') and not line.startswith('/*') and len(line) > 10:
                    print("  ", line[:200])
