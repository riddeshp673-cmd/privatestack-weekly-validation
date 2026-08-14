import json
import os
from http.server import BaseHTTPRequestHandler

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
        kv_url = os.environ.get("KV_REST_API_URL") or os.environ.get("KV_URL")
        kv_token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("KV_REST_API_READ_ONLY_TOKEN")
        
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self._set_cors()
        self.end_headers()
        self.wfile.write(json.dumps({
            "kv_url": kv_url[:20] if kv_url else None,
            "kv_token": kv_token[:20] if kv_token else None,
            "kv_url_set": bool(kv_url),
            "kv_token_set": bool(kv_token),
            "all_env_keys": [k for k in os.environ.keys() if "KV" in k or "REDIS" in k]
        }).encode())