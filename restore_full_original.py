import os
import sys
import json
import gspread
from google.oauth2.service_account import Credentials
from colorama import init, Fore, Style
from normalization_layer import normalize_text

# Initialize colorama
init(autoreset=True)

# Force stdout/stderr to UTF-8
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/19C4vdoFIlMQGhAyUmYjaoSatU-jQPy4BJIpoXbMZkEM/edit"
SHEET_NAME = "AllData"
BACKUP_FILE = os.path.join(BASE_DIR, "backup_sheet_20260529_172817.json")

def restore_full():
    print(Fore.CYAN + Style.BRIGHT + "\n==============================================")
    print(Fore.CYAN + Style.BRIGHT + "   FULL UNFILTERED DATABASE RESTORE PIPELINE  ")
    print(Fore.CYAN + Style.BRIGHT + "==============================================\n")
    
    if not os.path.exists(BACKUP_FILE):
        print(Fore.RED + f"[-] Error: Backup file {BACKUP_FILE} not found!")
        return
        
    print(f"[*] Reading full backup data from: {os.path.basename(BACKUP_FILE)}")
    with open(BACKUP_FILE, 'r', encoding='utf-8') as f:
        backup_rows = json.load(f)
    print(Fore.GREEN + f"[+] Loaded {len(backup_rows)} total rows from backup.")
    
    headers = [h.strip() for h in backup_rows[0]]
    
    # Ensure 'Normalized Content' column is in headers
    norm_col_name = "Normalized Content"
    if norm_col_name not in headers:
        headers.append(norm_col_name)
        
    norm_col_idx = headers.index(norm_col_name)
    raw_content_idx = -1
    raw_content_aliases = ["raw content", "message content", "rawcontent", "متن پیام", "raw_content"]
    for idx, h in enumerate(headers):
        if h.lower() in raw_content_aliases:
            raw_content_idx = idx
            break
            
    final_rows = []
    final_rows.append(headers)
    
    # Process rows (without any deletion)
    second_row = backup_rows[1]
    is_spacer = all(not cell.strip() for cell in second_row)
    if is_spacer:
        final_rows.append([""] * len(headers))
        start_idx = 2
    else:
        start_idx = 1
        
    print("[*] Processing and normalising all rows for full restoration...")
    for row_num in range(start_idx, len(backup_rows)):
        row = backup_rows[row_num]
        
        # Keep empty rows completely intact
        if all(not cell.strip() for cell in row):
            final_rows.append([""] * len(headers))
            continue
            
        content = row[raw_content_idx] if raw_content_idx < len(row) else ""
        
        new_row = list(row)
        while len(new_row) < len(headers):
            new_row.append("")
            
        # Normalize the content and store in Normalized Content column
        new_row[norm_col_idx] = normalize_text(content)
        final_rows.append(new_row)
        
    try:
        print("\n[*] Connecting to Google Sheets API...")
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_url(SPREADSHEET_URL)
        sheet = spreadsheet.worksheet(SHEET_NAME)
        
        print("[*] Clearing the spreadsheet...")
        sheet.clear()
        
        print(f"[*] Restoring all {len(final_rows)} unfiltered rows back to Google Sheets...")
        col_end_letter = gspread.utils.rowcol_to_a1(1, len(headers))[0:-1]
        range_to_update = f"A1:{col_end_letter}{len(final_rows)}"
        
        sheet.update(range_to_update, final_rows, value_input_option='USER_ENTERED')
        print(Fore.GREEN + f"[+] SUCCESS! The Google Sheet was restored to its complete, unfiltered state ({len(final_rows)} rows)!")
    except Exception as e:
        print(Fore.RED + f"[-] Error writing back to sheet: {e}")

if __name__ == "__main__":
    restore_full()
