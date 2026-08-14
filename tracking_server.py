#!/usr/bin/env python3
"""
Local signup tracking system for PrivateStack Weekly validation.
File-based storage, no external dependencies, runs locally.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import threading
import time

# Configuration
DATA_DIR = Path(__file__).parent / "data"
SIGNUPS_FILE = DATA_DIR / "signups.jsonl"
METRICS_FILE = DATA_DIR / "metrics.json"

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

def load_signups():
    """Load all signups from JSONL file."""
    if not SIGNUPS_FILE.exists():
        return []
    signups = []
    with open(SIGNUPS_FILE, 'r') as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    signups.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return signups

def save_signup(email, metadata=None):
    """Save a new signup to JSONL file."""
    signup = {
        "email": email,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "source": "landing_page",
        "experiment_id": "96f5a4c2-ebc8-4366-9893-8eb284c58eec",
        "metadata": metadata or {}
    }
    
    with open(SIGNUPS_FILE, 'a') as f:
        f.write(json.dumps(signup, separators=(',', ':')) + '\n')
    
    # Update metrics
    update_metrics()
    
    return signup

def update_metrics():
    """Update aggregated metrics file."""
    signups = load_signups()
    metrics = {
        "total_signups": len(signups),
        "last_signup": signups[-1]["timestamp"] if signups else None,
        "signups_by_date": {},
        "experiment_id": "96f5a4c2-ebc8-4366-9893-8eb284c58eec",
        "updated_at": datetime.utcnow().isoformat() + "Z"
    }
    
    # Count by date
    for s in signups:
        date = s["timestamp"][:10]  # YYYY-MM-DD
        metrics["signups_by_date"][date] = metrics["signups_by_date"].get(date, 0) + 1
    
    with open(METRICS_FILE, 'w') as f:
        json.dump(metrics, f, indent=2)
    
    return metrics

def get_metrics():
    """Get current metrics."""
    if METRICS_FILE.exists():
        with open(METRICS_FILE, 'r') as f:
            return json.load(f)
    return update_metrics()

class SignupHandler(BaseHTTPRequestHandler):
    """HTTP request handler for signup API."""
    
    def _set_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
    
    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()
    
    def do_POST(self):
        parsed = urlparse(self.path)
        
        if parsed.path == '/api/subscribe':
            self.handle_subscribe()
        else:
            self.send_response(404)
            self.end_headers()
    
    def handle_subscribe(self):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            self.send_error_response(400, "Empty request body")
            return
        
        try:
            body = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(body)
        except json.JSONDecodeError:
            self.send_error_response(400, "Invalid JSON")
            return
        
        email = data.get('email', '').strip().lower()
        
        if not email:
            self.send_error_response(400, "Email is required")
            return
        
        # Basic email validation
        if '@' not in email or '.' not in email.split('@')[-1]:
            self.send_error_response(400, "Invalid email format")
            return
        
        # Check for duplicates
        signups = load_signups()
        if any(s['email'] == email for s in signups):
            self.send_error_response(409, "Email already subscribed")
            return
        
        # Save signup
        metadata = {
            "user_agent": self.headers.get('User-Agent', ''),
            "referer": self.headers.get('Referer', ''),
            "ip": self.client_address[0]
        }
        
        signup = save_signup(email, metadata)
        
        self.send_success_response({
            "success": True,
            "message": "Successfully subscribed",
            "signup_id": signup["timestamp"]
        })
    
    def send_success_response(self, data):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
    
    def send_error_response(self, status, message):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps({"success": False, "error": message}).encode('utf-8'))
    
    def log_message(self, format, *args):
        # Suppress default log messages
        pass

def run_server(port=8080):
    """Run the local signup tracking server."""
    server = HTTPServer(('localhost', port), SignupHandler)
    print(f"📡 Signup tracking server running on http://localhost:{port}")
    print(f"   POST /api/subscribe - Submit email signup")
    print(f"   Data stored in: {DATA_DIR}")
    print(f"   Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Server stopped")
        server.shutdown()

def serve_landing_page(port=8080):
    """Serve the landing page and API on the same port."""
    import http.server
    import socketserver
    
    class CombinedHandler(SignupHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            
            if parsed.path in ('/', '/index.html'):
                self.serve_landing_page()
            else:
                self.send_response(404)
                self.end_headers()
        
        def serve_landing_page(self):
            landing_file = Path(__file__).parent / "index.html"
            if landing_file.exists():
                with open(landing_file, 'r') as f:
                    content = f.read()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
            else:
                self.send_response(404)
                self.end_headers()
    
    server = HTTPServer(('localhost', port), CombinedHandler)
    print(f"🌐 Landing page + API server running on http://localhost:{port}")
    print(f"   GET  /              - Landing page")
    print(f"   POST /api/subscribe - Submit email signup")
    print(f"   Data stored in: {DATA_DIR}")
    print(f"   Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Server stopped")
        server.shutdown()

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='PrivateStack Weekly - Local Signup Tracking')
    parser.add_argument('--port', type=int, default=8080, help='Port to run server on')
    parser.add_argument('--api-only', action='store_true', help='Run only API server (no landing page)')
    parser.add_argument('--metrics', action='store_true', help='Print current metrics and exit')
    parser.add_argument('--signups', action='store_true', help='Print all signups and exit')
    
    args = parser.parse_args()
    
    if args.metrics:
        metrics = get_metrics()
        print(json.dumps(metrics, indent=2))
    elif args.signups:
        signups = load_signups()
        for s in signups:
            print(f"{s['timestamp']} - {s['email']}")
        print(f"\nTotal: {len(signups)} signups")
    elif args.api_only:
        run_server(args.port)
    else:
        serve_landing_page(args.port)