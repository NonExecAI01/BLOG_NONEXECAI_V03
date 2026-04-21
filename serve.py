#!/usr/bin/env python3
"""
serve.py — Local development server for Non-Exec AI Blog
Run with: python serve.py
Opens http://localhost:3000/ in your default browser.
"""

import http.server
import os
import webbrowser
from functools import partial

from dotenv import load_dotenv
load_dotenv()

PORT = 3000
DIRECTORY = os.path.dirname(os.path.abspath(__file__))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def log_message(self, format, *args):
        print(f"  {self.address_string()} — {format % args}")


if __name__ == "__main__":
    with http.server.HTTPServer(("", PORT), Handler) as httpd:
        url = f"http://localhost:{PORT}/"
        print(f"\n  Non-Exec AI Blog — local server")
        print(f"  Serving at {url}")
        print(f"  Press Ctrl+C to stop\n")
        webbrowser.open(url)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  Server stopped.")
