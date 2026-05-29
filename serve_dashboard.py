import os
import sys
import json
import http.server
import socketserver
import webbrowser
import gspread
from threading import Timer
from google.oauth2.service_account import Credentials

PORT = 8000
DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard")
CREDENTIALS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "credentials.json")
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/19C4vdoFIlMQGhAyUmYjaoSatU-jQPy4BJIpoXbMZkEM/edit"
SHEET_NAME = "AllData"

def fetch_sheet_records_via_api():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_url(SPREADSHEET_URL).worksheet(SHEET_NAME)
    records = sheet.get_all_records()
    return records

class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        # Serve from the dashboard folder
        super().__init__(*args, directory=DIRECTORY, **kwargs)

    def do_GET(self):
        # Support serving the standalone preview from root folder if requested
        if self.path in ("/", "/local_preview.html"):
            root_preview = os.path.join(os.path.dirname(DIRECTORY), "local_preview.html")
            if os.path.exists(root_preview):
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                with open(root_preview, "rb") as f:
                    self.wfile.write(f.read())
                return

        # Serve the Google Sheet records securely as JSON
        if self.path == "/api/records":
            try:
                records = fetch_sheet_records_via_api()
                self.send_response(200)
                self.send_header("Content-type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")  # Support dev CORS
                self.end_headers()
                self.wfile.write(json.dumps(records, ensure_ascii=False).encode("utf-8"))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                error_response = {"error": str(e)}
                self.wfile.write(json.dumps(error_response).encode("utf-8"))
            return

        # Support Vite path mapping in fallback mode
        if self.path.startswith("/src/") or self.path.startswith("/assets/"):
            pass
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
