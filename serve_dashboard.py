import os
import sys
import http.server
import socketserver
import webbrowser
from threading import Timer

PORT = 8000
DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard")

class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Serve from the dashboard folder
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        # Support Vite path mapping in fallback mode
        if self.path.startswith("/src/") or self.path.startswith("/assets/"):
            pass
        elif self.path == "/":
            self.path = "/local_preview.html"
        super().do_GET()

def open_browser():
    webbrowser.open_new_tab(f"http://localhost:{PORT}")

def run_server():
    # Force UTF-8 stream output for Farsi characters
    if sys.platform.startswith("win"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass

    print("\n==============================================")
    print("      AISTEEL SMART WEB DASHBOARD SERVER       ")
    print("==============================================\n")
    print(f"[*] Serving dashboard directory: {DIRECTORY}")
    print(f"[*] Server running at: http://localhost:{PORT}")
    print("[*] Press Ctrl+C to stop the server.\n")
    
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), CustomHTTPRequestHandler) as httpd:
        # Launch default browser automatically in 1 second
        Timer(1.0, open_browser).start()
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n[!] Server stopped by user.")
            sys.exit(0)

if __name__ == "__main__":
    run_server()
