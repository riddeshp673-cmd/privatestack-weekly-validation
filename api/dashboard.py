import json
import os
import urllib.request
from http.server import BaseHTTPRequestHandler

# Vercel KV (Upstash Redis) REST API
KV_URL = os.environ.get("KV_REST_API_URL") or os.environ.get("KV_URL")
KV_TOKEN = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("KV_REST_API_READ_ONLY_TOKEN")

def kv_request(command, *args):
    """Make request to Vercel KV REST API using command array format."""
    if not KV_URL or not KV_TOKEN:
        raise RuntimeError(f"KV env vars missing: KV_URL={bool(KV_URL)}, KV_TOKEN={bool(KV_TOKEN)}")
    
    command_array = [command] + list(args)
    url = KV_URL
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
            if isinstance(result, dict) and "result" in result:
                return result["result"]
            return result
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        raise RuntimeError(f"KV HTTPError {e.code}: {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"KV URLError: {e.reason}")

class handler(BaseHTTPRequestHandler):
    def _set_cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
    
    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors()
        self.end_headers()
    
    def do_GET(self):
        try:
            # Get all signup keys using KEYS pattern
            keys_result = kv_request("KEYS", "signup:*")
            
            signups = []
            if keys_result:
                # keys_result should be a list of keys
                for key in keys_result:
                    if isinstance(key, bytes):
                        key = key.decode()
                    # Get the value for each key
                    value = kv_request("GET", key)
                    if value:
                        signups.append({
                            "key": key,
                            "data": value
                        })
            
            # Sort by timestamp (newest first)
            signups.sort(key=lambda x: x["data"].get("timestamp", ""), reverse=True)
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._set_cors()
            self.end_headers()
            self.wfile.write(json.dumps({
                "total_signups": len(signups),
                "signups": signups
            }).encode())
            
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self._set_cors()
            self.end_headers()
            self.wfile.write(json.dumps({"error": str(e), "traceback": tb}).encode())