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
    
    # Debug: print what we're sending
    print(f"DEBUG KV Request: {method} {url}")
    print(f"DEBUG KV Headers: {headers}")
    print(f"DEBUG KV Body: {data}")
    
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status >= 400:
                error_body = resp.read().decode()
                raise RuntimeError(f"KV HTTP {resp.status}: {error_body}")
            response_data = resp.read().decode()
            result = json.loads(response_data) if response_data else {}
            print(f"DEBUG KV Response: {resp.status} {result}")
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"DEBUG KV HTTPError: {e.code} {error_body}")
        raise RuntimeError(f"KV HTTPError {e.code}: {error_body}")
    except urllib.error.URLError as e:
        print(f"DEBUG KV URLError: {e.reason}")
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
            
            # First, test KV connection with a simple GET on a nonsense key
            test_key = f"test:connection:{__import__('uuid').uuid4()}"
            try:
                get_result = kv_request("POST", "/get", {"key": test_key})
                # If we get here, the REST API is working
                print("DEBUG: KV connection test successful")
            except Exception as get_error:
                # If GET fails, then the issue is with the connection or token
                print(f"DEBUG: KV connection test failed: {get_error}")
                self._json_response(500, {"success": False, "error": "KV connection failed", "detail": str(get_error)})
                return
            
            # Check for duplicate using KV GET first
            # Let's try a simple key format to see if the issue is with the key
            # key = f"signup:{email}"  # Original
            # Let's try replacing special characters in the email for the key
            safe_email = email.replace("@", "_at_").replace(".", "_dot_")
            key = f"signup:{safe_email}"
            
            # Try to get the key
            get_result = kv_request("POST", "/get", {"key": key})
            
            # Debug the get result
            print(f"DEBUG GET result for {key}: {get_result}")
            
            # If get_result has a result (not None), then the key exists
            if get_result.get("result") is not None:
                self._json_response(409, {"success": False, "error": "Email already subscribed", "get_result": get_result})
            else:
                # Key does not exist, now set it
                signup_data = {
                    "email": email,
                    "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                    "source": "landing_page",
                    "experiment_id": "96f5a4c2-ebc8-4366-9893-8eb284c58eec"
                }
                
                # Try setting the key with just key and value (no expiration) to see if that works
                # First, try with a simple string value to see if the issue is with the JSON
                simple_value = "test-value"
                set_result = kv_request("POST", "/set", {
                    "key": key,
                    "value": simple_value
                })
                
                print(f"DEBUG SET result (simple): {set_result}")
                
                if set_result.get("result") == "OK":
                    # Now try with the JSON data
                    set_result2 = kv_request("POST", "/set", {
                        "key": key,
                        "value": json.dumps(signup_data)
                    })
                    print(f"DEBUG SET result (JSON): {set_result2}")
                    
                    if set_result2.get("result") == "OK":
                        self._json_response(200, {
                            "success": True,
                            "message": "Successfully subscribed",
                            "signup_id": key
                        })
                    else:
                        self._json_response(500, {"success": False, "error": "Failed to set JSON key", "set_result_simple": set_result, "set_result_json": set_result2})
                else:
                    self._json_response(500, {"success": False, "error": "Failed to set simple key", "set_result": set_result})
        
        except json.JSONDecodeError as e:
            self._json_response(400, {"success": False, "error": "Invalid JSON", "detail": str(e)})
        except RuntimeError as e:
            # KV configuration error
            self._json_response(500, {"success": False, "error": "Storage unavailable", "detail": str(e)})
        except Exception as e:
            # Full traceback for debugging
            tb = traceback.format_exc()
            print(f"DEBUG: Unexpected error: {tb}")
            self._json_response(500, {"success": False, "error": "Internal server error", "detail": str(e), "traceback": tb})
    
    def _json_response(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._set_cors()
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))