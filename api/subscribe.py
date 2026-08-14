import json
import os
import re
import urllib.request
import traceback
from http.server import BaseHTTPRequestHandler

# Vercel KV (Upstash Redis) REST API
# The KV_URL is the base endpoint for the REST API (e.g., https://<instance-id>.upstash.io)
# We send commands as JSON arrays: [ "command", "arg1", "arg2", ... ]
KV_URL = os.environ.get("KV_REST_API_URL") or os.environ.get("KV_URL")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("KV_REST_API_READ_ONLY_TOKEN")

def kv_request(command, *args):
    """Make request to Vercel KV REST API using command array format."""
    if not KV_URL or not KV_TOKEN:
        raise RuntimeError(f"KV env vars missing: KV_URL={bool(KV_URL)}, KV_TOKEN={bool(KV_TOKEN)}")
    
    # Build the command array: [command, arg1, arg2, ...]
    command_array = [command] + list(args)
    
    url = KV_URL  # The base URL is the endpoint
    headers = {
        "Authorization": f"Bearer {KV_TOKEN}",
        "Content-Type": "application/json"
    }
    
    data = json.dumps(command_array).encode("utf-8")
    
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status >= 400:
                error_body = resp.read().decode()
                raise RuntimeError(f"KV HTTP {resp.status}: {error_body}")
            response_data = resp.read().decode()
            # The response is typically the result of the command
            # For GET: returns the value or null
            # For SET: returns "OK"
            # For other commands, it depends.
            return json.loads(response_data) if response_data else None
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
            
            # Check for duplicate using KV GET first
            # Format: GET key -> returns value or null
            test_key = "test:connection"
            try:
                get_result = kv_request("GET", test_key)
                # If we get here, the REST API is working
            except Exception as get_error:
                # If GET fails, then the issue is with the connection or token
                self._json_response(500, {"success": False, "error": "KV connection failed", "detail": str(get_error)})
                return
            
            # Check for duplicate using KV GET first
            # Replace @ and . in email to make a safe key
            safe_email = email.replace("@", "_at_").replace(".", "_dot_")
            key = f"signup:{safe_email}"
            
            # Try to get the key
            get_result = kv_request("GET", key)
            
            # If get_result is not None, then the key exists
            if get_result is not None:
                self._json_response(409, {"success": False, "error": "Email already subscribed", "get_result": get_result})
            else:
                # Key does not exist, now set it with expiration and NX
                signup_data = {
                    "email": email,
                    "timestamp": __import__("datetime").datetime.utcnow().isoformat() + "Z",
                    "source": "landing_page",
                    "experiment_id": "96f5a4c2-ebc8-4366-9893-8eb284c58eec"
                }
                
                # Set the key with value as JSON string, with expiration (30 days) and NX (only if not exists)
                # Redis SET command: SET key value EX seconds NX
                set_result = kv_request("SET", key, json.dumps(signup_data), "EX", "2592000", "NX")
                
                # Upstash returns "OK" on success
                if set_result == "OK":
                    self._json_response(200, {
                        "success": True,
                        "message": "Successfully subscribed",
                        "signup_id": key
                    })
                else:
                    # If not OK, then the key already exists (since we used NX) or other error
                    self._json_response(409, {"success": False, "error": "Email already subscribed", "set_result": set_result})
        
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