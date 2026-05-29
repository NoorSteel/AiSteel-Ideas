import os
import sys
import json
import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials
from colorama import init, Fore, Style
from normalization_layer import normalize_text

# Initialize colorama
init(autoreset=True)

# Force stdout/stderr to UTF-8 to prevent Farsi UnicodeEncodeError in cmd/powershell
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

def run_backfill():
    print(Fore.CYAN + Style.BRIGHT + "\n==============================================")
    print(Fore.CYAN + Style.BRIGHT + "    AISTEEL TEXT NORMALIZATION BACKFILLER      ")
    print(Fore.CYAN + Style.BRIGHT + "==============================================\n")
    
    if not os.path.exists(CREDENTIALS_FILE):
        print(Fore.RED + f"[-] Error: credentials.json missing at {CREDENTIALS_FILE}")
        return
        
    try:
        print("[*] Connecting to Google Sheets API...")
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_url(SPREADSHEET_URL)
        sheet = spreadsheet.worksheet(SHEET_NAME)
        print(Fore.GREEN + f"[+] Connected to: {spreadsheet.title} -> {sheet.title}")
    except Exception as e:
        print(Fore.RED + f"[-] Connection failed: {e}")
        return
        
    # Read all values
    try:
        print("[*] Fetching spreadsheet values...")
        all_values = sheet.get_all_values()
        print(Fore.GREEN + f"[+] Fetched {len(all_values)} rows successfully.")
    except Exception as e:
        print(Fore.RED + f"[-] Failed to fetch values: {e}")
        return
        
    if len(all_values) < 2:
        print(Fore.YELLOW + "[!] Spreadsheet has too few rows to process.")
        return
        
    headers = [h.strip() for h in all_values[0]]
    print(f"[*] Current Headers: {headers}")
    
    # 1. Ensure 'Normalized Content' column exists
    norm_col_name = "Normalized Content"
    norm_col_idx = -1
    
    if norm_col_name in headers:
        norm_col_idx = headers.index(norm_col_name)
        print(Fore.GREEN + f"[+] '{norm_col_name}' column already exists at index: {norm_col_idx + 1}")
    else:
        # Append 'Normalized Content' to headers
        headers.append(norm_col_name)
        norm_col_idx = len(headers) - 1
        
        # Write back the new headers to row 1
        try:
            print(f"[*] Adding new header column '{norm_col_name}' to Google Sheets...")
            col_end_letter = gspread.utils.rowcol_to_a1(1, len(headers))[0:-1]
            sheet.update(f"A1:{col_end_letter}1", [headers])
            print(Fore.GREEN + f"[+] Successfully created '{norm_col_name}' column in the sheet.")
        except Exception as e:
            print(Fore.RED + f"[-] Failed to create new header column: {e}")
            return
            
    # Find Raw Content column index
    raw_content_aliases = ["raw content", "message content", "rawcontent", "متن پیام", "raw_content"]
    raw_content_idx = -1
    for idx, h in enumerate(headers):
        if h.strip().lower() in raw_content_aliases:
            raw_content_idx = idx
            break
            
    if raw_content_idx == -1:
        print(Fore.RED + "[-] Error: 'Raw Content' column not found in headers.")
        return
        
    print(Fore.GREEN + f"[+] Found 'Raw Content' at index: {raw_content_idx + 1}")
    
    # Create a local backup of the spreadsheet data before updating
    backup_file = os.path.join(BASE_DIR, f"backup_sheet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(backup_file, 'w', encoding='utf-8') as f:
        json.dump(all_values, f, ensure_ascii=False, indent=2)
    print(Fore.GREEN + f"[+] Safely backed up spreadsheet data to: {os.path.basename(backup_file)}")
    
    # Determine the starting row index (skip headers and spacer row if present)
    second_row = all_values[1]
    is_blank_spacer = all(not cell.strip() for cell in second_row)
    start_row_idx = 2 if is_blank_spacer else 1
    
    # We will prepare a list of single-item lists to upload to the Normalized Content column
    # Row 2 (or 3) through end of spreadsheet
    normalized_values = []
    
    # If there is a blank spacer row at row 2, add an empty string for it
    if is_blank_spacer:
        normalized_values.append([""])
        
    total_processed = 0
    total_original_len = 0
    total_cleaned_len = 0
    
    print(Fore.YELLOW + "\n[*] Processing and Normalizing Rows:")
    print("--------------------------------------------------------------------------------")
    
    for row_num in range(start_row_idx, len(all_values)):
        row = all_values[row_num]
        
        # Get raw content
        raw_content = ""
        if raw_content_idx < len(row):
            raw_content = row[raw_content_idx]
            
        # Normalize
        normalized = normalize_text(raw_content)
        normalized_values.append([normalized])
        
        # Stats
        orig_len = len(raw_content)
        clean_len = len(normalized)
        total_original_len += orig_len
        total_cleaned_len += clean_len
        total_processed += 1
        
        # Log difference
        diff = orig_len - clean_len
        sender = row[headers.index("Created By")] if "Created By" in headers and headers.index("Created By") < len(row) else "Unknown"
        print(f"Row {row_num + 1:<4} | Sender: {sender:<18} | Orig: {orig_len:<3} | Cleaned: {clean_len:<3} | Cleaned characters: {diff}")
        
    print("--------------------------------------------------------------------------------")
    print(Fore.GREEN + f"[+] Classification complete. Total records normalized: {total_processed}")
    print(Fore.YELLOW + f"[+] Total characters: Original: {total_original_len} | Cleaned: {total_cleaned_len} | Cleaned out: {total_original_len - total_cleaned_len}")
    
    # Upload the Normalized column to the sheet
    try:
        norm_col_letter = gspread.utils.rowcol_to_a1(1, norm_col_idx + 1)[0:-1]
        range_to_update = f"{norm_col_letter}2:{norm_col_letter}{len(all_values)}"
        print(f"\n[*] Batch uploading normalized column to range: {range_to_update}...")
        
        sheet.update(range_to_update, normalized_values, value_input_option='USER_ENTERED')
        print(Fore.GREEN + f"[+] Successfully backfilled and synchronized Google Sheets! {total_processed} rows updated.")
    except Exception as e:
        print(Fore.RED + f"[-] Error writing normalized column to sheet: {e}")
        print(Fore.YELLOW + f"[!] Please restore from backup file: {backup_file}")

if __name__ == "__main__":
    run_backfill()
