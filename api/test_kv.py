import json
import os
import urllib.request
import traceback
from http.server import BaseHTTPRequestHandler

# Vercel KV (Upstash Redis) REST API
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
            if not response_data:
                return None
            result = json.loads(response_data)
            # Upstash returns a JSON object with a "result" field
            if isinstance(result, dict) and "result" in result:
                return result["result"]
            # Fallback: return the whole result (should not happen)
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        raise RuntimeError(f"KV HTTPError {e.code}: {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"KV URLError: {e.reason}")

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
            # Generate a random key for testing
            import uuid
            test_key = f"test:{uuid.uuid4()}"
            
            # Test GET (should return null for non-existent key)
            get_before = kv_request("GET", test_key)
            
            # Test SET with value, EX, NX
            set_result = kv_request("SET", test_key, "test-value", "EX", "10", "NX")
            
            # Test GET after SET
            get_after = kv_request("GET", test_key)
            
            # Test SET again with NX (should return nil/null because key exists)
            set_again = kv_request("SET", test_key, "another-value", "EX", "10", "NX")
            
            # Clean up: delete the test key
            delete_result = kv_request("DEL", test_key)
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._set_cors()
            self.end_headers()
            self.wfile.write(json.dumps({
                "test_key": test_key,
                "get_before": get_before,  # should be None
                "set_result": set_result,  # should be "OK"
                "get_after": get_after,    # should be "test-value"
                "set_again": set_again,    # should be None (because NX and key exists)
                "delete_result": delete_result  # should be 1
            }).encode())
        except Exception as e:
            tb = traceback.format_exc()
            self._json_response(500, {"success": False, "error": "Internal server error", "detail": str(e), "traceback": tb})
    
    def _json_response(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self._set_cors()
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))