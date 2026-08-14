import json
import os
import re
import traceback
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
        try:
            # Debug: check env vars
            kv_url = os.environ.get("KV_REST_API_URL") or os.environ.get("KV_URL")
            kv_token = os.environ.get("KV_REST_API_TOKEN") or os.environ.get("KV_REST_API_READ_ONLY_TOKEN")
            
            # Return debug info for now
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self._set_cors()
            self.end_headers()
            self.wfile.write(json.dumps({
                "debug": True,
                "kv_url_set": bool(kv_url),
                "kv_token_set": bool(kv_token),
                "all_env_keys": [k for k in os.environ.keys() if "KV" in k or "REDIS" in k]
            }).encode())
            return
        
        except Exception as e:
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self._set_cors()
            self.end_headers()
            self.wfile.write(json.dumps({
                "success": False,
                "error": str(e),
                "traceback": traceback.format_exc()
            }).encode())