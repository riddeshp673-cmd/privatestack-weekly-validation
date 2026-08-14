import json
import os
import re
from http.server import BaseHTTPRequestHandler

# Vercel KV (Upstash Redis) REST API
KV_URL = os.environ.get("KV_REST_API_URL") or os.environ.get("KV_URL")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("KV_REST_API_READ_ONLY_TOKEN")

def kv_request(method, path, body=None):
    """Make request to Vercel KV REST API."""
    import urllib.request
    
    if not KV_URL or not KV_TOKEN:
        raise RuntimeError("KV environment variables not configured")
    
    url = f"{KV_URL}{path}"
    headers = {
        "Authorization": f"Bearer {KV_TOKEN}",
        "Content-Type": "application/json"
    }
    
    data = json.dumps(body).encode("utf-8") if body else None
    
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    
    with urllib.request.urlopen(req, timeout=10) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"KV error: {resp.status} {resp.read().decode()}")
        return json.loads(resp.read().decode()) if resp.length else {}

def is_valid_email(email):
    """Basic email validation."""
    pattern = r"^[^\s@]+@[^\s@]+\.[^\s@]+$"
    return bool(re.match(pattern, email))

class handler(BaseHTTPRequestHandler):
    def _set_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
    
    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors()
        self.end_headers()
    
    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                self._json_response(400, {"success": False, "error": "Empty request body"})
                return
            
            body = json.loads(self.rfile.read(content_length).decode("utf-8"))
            email = body.get("email", "").strip().lower()
            
            if not email:
                self._json_response(400, {"success": False, "error": "Email is required"})
                return
            
            if not is_valid_email(email):
                self._json_response(400, {"success": False, "error": "Invalid email format"})
                return
            
            # Check for duplicate using KV SET with NX (only if not exists)
            # Key format: signup:{email}
            key = f"signup:{email}"
            
            # Try to set only if not exists (atomic check-and-set)
            result = kv_request("POST", "/set", {
                "key": key,
                "value": json.dumps({
                    "email": email,
                    "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                    "source": "landing_page",
                    "experiment_id": "96f5a4c2-ebc8-4366-9893-8eb284c58eec"
                }),
                "nx": True,  # Only set if key doesn't exist
                "ex": 2592000  # 30 days TTL
            })
            
            # Upstash returns {"result": "OK"} on success, or error if key exists
            if result.get("result") == "OK":
                self._json_response(200, {
                    "success": True,
                    "message": "Successfully subscribed",
                    "signup_id": key
                })
            else:
                # Key already exists (duplicate)
                self._json_response(409, {"success": False, "error": "Email already subscribed"})
        
        except json.JSONDecodeError:
            self._json_response(400, {"success": False, "error": "Invalid JSON"})
        except RuntimeError as e:
            # KV configuration error
            self._json_response(500, {"success": False, "error": "Storage unavailable"})
        except Exception as e:
            self._json_response(500, {"success": False, "error": "Internal server error"})
    
    def _json_response(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._set_cors()
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))