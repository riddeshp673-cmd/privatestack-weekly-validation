import json
import os
import re
import urllib.request
import traceback
import sys
from http.server import BaseHTTPRequestHandler

# Vercel KV (Upstash Redis) REST API
KV_URL = os.environ.get("KV_REST_API_URL") or os.environ.get("KV_URL")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("KV_REST_API_READ_ONLY_TOKEN")

def kv_request(method, path, body=None):
    """Make request to Vercel KV REST API."""
    if not KV_URL or not KV_TOKEN:
        raise RuntimeError(f"KV env vars missing: KV_URL={bool(KV_URL)}, KV_TOKEN={bool(KV_TOKEN)}")
    
    url = f"{KV_URL}{path}"
    headers = {
        "Authorization": f"Bearer {KV_TOKEN}",
        "Content-Type": "application/json"
    }
    
    data = json.dumps(body).encode("utf-8") if body else None
    
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status >= 400:
                error_body = resp.read().decode()
                raise RuntimeError(f"KV HTTP {resp.status}: {error_body}")
            response_data = resp.read().decode()
            return json.loads(response_data) if response_data else {}
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        raise RuntimeError(f"KV HTTPError {e.code}: {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"KV URLError: {e.reason}")

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
            
            raw_body = self.rfile.read(content_length).decode("utf-8")
            body = json.loads(raw_body)
            email = body.get("email", "").strip().lower()
            
            if not email:
                self._json_response(400, {"success": False, "error": "Email is required"})
                return
            
            if not is_valid_email(email):
                self._json_response(400, {"success": False, "error": "Invalid email format"})
                return
            
            # Check for duplicate using KV SET with NX (only if not exists)
            key = f"signup:{email}"
            
            signup_data = {
                "email": email,
                "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                "source": "landing_page",
                "experiment_id": "96f5a4c2-ebc8-4366-9893-8eb284c58eec"
            }
            
            # Upstash REST API SET command format:
            # POST /set with body: {"key": "...", "value": "...", "ex": 2592000, "nx": true}
            # The ex parameter should be in seconds, nx should be boolean
            # But the error suggests wrong number of arguments - let's try without nx first
            # and check if key exists manually, or use the correct Upstash format
            
            # Let's use the proper Upstash REST API format
            # According to Upstash docs, the SET command takes: key, value, [EX seconds] [PX milliseconds] [NX|XX] [GET]
            # In REST API, it might be: {"key": "k", "value": "v", "ex": 3600, "nx": true}
            # Let's try with simpler parameters first
            
            result = kv_request("POST", "/set", {
                "key": key,
                "value": json.dumps(signup_data),
                "ex": 2592000,
                "nx": True
            })
            
            # Upstash returns {"result": "OK"} on success
            if result.get("result") == "OK":
                self._json_response(200, {
                    "success": True,
                    "message": "Successfully subscribed",
                    "signup_id": key
                })
            else:
                # Key already exists (duplicate) or other error
                self._json_response(409, {"success": False, "error": "Email already subscribed", "kv_result": result})
        
        except json.JSONDecodeError as e:
            self._json_response(400, {"success": False, "error": "Invalid JSON", "detail": str(e)})
        except RuntimeError as e:
            # KV configuration error
            self._json_response(500, {"success": False, "error": "Storage unavailable", "detail": str(e)})
        except Exception as e:
            # Full traceback for debugging
            tb = traceback.format_exc()
            self._json_response(500, {"success": False, "error": "Internal server error", "detail": str(e), "traceback": tb})
    
    def _json_response(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._set_cors()
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))