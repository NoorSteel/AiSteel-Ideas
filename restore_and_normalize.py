import os
import sys
import re
import json
import gspread
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
BACKUP_FILE = os.path.join(BASE_DIR, "backup_sheet_20260529_172817.json")

def extract_audio_filename(content: str) -> str:
    """Extracts the audio filename if the message represents an attached audio file."""
    if not content:
        return None
    content_lower = content.strip().lower()
    audio_extensions = ['.opus', '.wav', '.m4a', '.mp3', '.ogg', '.amr']
    attached_match = re.search(r"<attached:\s*(?:voice\s+mail\s+)?([^>]+)>", content, re.IGNORECASE)
    if attached_match:
        return attached_match.group(1).strip()
    android_match = re.search(r"^([\w-]+\.(?:opus|wav|m4a|mp3|ogg|amr))\s*\(file\s+attached\)$", content.strip(), re.IGNORECASE)
    if android_match:
        return android_match.group(1).strip()
    if any(content_lower.endswith(ext) for ext in audio_extensions):
        if len(content.split()) == 1:
            return content.strip()
    return None

def should_skip_message_refined(content: str) -> bool:
    """
    Refined, extremely safe filter. Only filters out:
    1. WhatsApp system notifications
    2. Bot domain counts (e.g. AiSteel.it.com 55)
    3. Standalone URLs
    4. WhatsApp media omitted logs
    5. Single name questions (e.g. عرفان ؟؟)
    Keeps all other valid conversational short messages (e.g. 38 درهم, بخرم؟, این خوبه).
    """
    if not content:
        return True
        
    # Standardize spaces and remove directional marks
    content_clean = content.strip().replace('\u200e', '').replace('\u200f', '').replace('\u202f', ' ').replace('\u200b', '')
    content_norm = re.sub(r'[\s\xa0]+', ' ', content_clean).strip().lower()
    
    # If it is a voice note/audio file, do NOT skip it!
    if extract_audio_filename(content) is not None:
        return False
        
    # 1. Skip WhatsApp system notifications
    system_keywords = [
        "added you", "created this group", "joined using an invite link",
        "changed this group's icon", "changed the subject", "left", "invited",
        "changed their phone number", "turned on messages", "waiting for this message",
        "changed the group description", "messages and calls are end-to-end encrypted"
    ]
    if any(keyword in content_norm for keyword in system_keywords):
        return True
        
    # 2. Skip bot count statistics (e.g. AiSteel.it.com 55)
    # Only skips if it matches domain followed by counts/numbers
    if re.search(r"aisteel\s*\.\s*[a-z0-9]+([\.-][a-z0-9]+)*\s+\d+", content_norm, re.IGNORECASE):
        return True
        
    # 3. Skip standalone URLs
    if re.match(r"^https?://[^\s]+$", content_norm, re.IGNORECASE):
        return True
        
    # 4. Skip standard WhatsApp media omitted placeholders
    skip_keywords = [
        "image omitted", "photo omitted", "video omitted", "sticker omitted", "gif omitted",
        "document omitted", "contact card omitted", "audio omitted",
        "تصویر ضمیمه نشد", "ویدیو ضمیمه نشد", "استیکر ضمیمه نشد", "عکس ضمیمه نشد",
        "تصویر حذف شد", "ویدیو حذف شد", "استیکر حذف شد", "سند ضمیمه نشد"
    ]
    if any(keyword in content_norm for keyword in skip_keywords):
        return True
        
    # Check for non-audio attached attached files
    if re.search(r"<attached:\s*([^>]+)>", content_norm):
        return True
        
    # 5. Skip single name/short filler questions (e.g. "عرفان ؟؟" or "محمد خوشنودي ؟؟")
    # If it ends with a question mark and is short, check if it has trade context
    if '؟' in content_clean or '?' in content_clean:
        stripped = re.sub(r'[؟\?\s]', '', content_clean).strip()
        steel_keywords = [
            "تیرآهن", "تیر آهن", "ميلگرد", "میلگرد", "میل گرد", "استیل", "آهن", "پروفیل", "لوله", 
            "نبشی", "خرید", "فروش", "قیمت", "تن", "بار", "ورق", "قوطی", "شمش", "ناودانی", "هاش", 
            "سپری", "سیم", "مفتول", "تسمه", "زانو", "اتصالات", "شیرآلات", "فولاد", "سفارش", "تخفیف",
            "درهم", "درم", "تومان", "ریال", "موجود", "موجوده", "بخر", "بخرم"
        ]
        has_steel = any(kw in content_norm for kw in steel_keywords)
        if len(stripped) < 12 and not has_steel:
            return True
            
    return False

def restore_and_normalize():
    print(Fore.CYAN + Style.BRIGHT + "\n==============================================")
    print(Fore.CYAN + Style.BRIGHT + "    SPREADSHEET RESTORE & SAFE NORMALIZATION  ")
    print(Fore.CYAN + Style.BRIGHT + "==============================================\n")
    
    if not os.path.exists(BACKUP_FILE):
        print(Fore.RED + f"[-] Error: Backup file {BACKUP_FILE} not found!")
        return
        
    # Load backup data
    print(f"[*] Reading full backup data from: {os.path.basename(BACKUP_FILE)}")
    with open(BACKUP_FILE, 'r', encoding='utf-8') as f:
        backup_rows = json.load(f)
    print(Fore.GREEN + f"[+] Loaded {len(backup_rows)} total rows from backup.")
    
    if len(backup_rows) < 2:
        print(Fore.RED + "[-] Error: Backup data is corrupted or empty.")
        return
        
    headers = [h.strip() for h in backup_rows[0]]
    print(f"[*] Original Headers: {headers}")
    
    # Ensure 'Normalized Content' is in headers
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
            
    if raw_content_idx == -1:
        print(Fore.RED + "[-] Error: 'Raw Content' column not found in headers.")
        return
        
    print(Fore.GREEN + f"[+] Raw Content Column: {raw_content_idx + 1} | Normalized Column: {norm_col_idx + 1}")
    
    # Process backup rows with refined filter and normalization
    kept_rows = []
    
    # Append header row
    kept_rows.append(headers)
    
    # Process blank spacer row
    second_row = backup_rows[1]
    is_spacer = all(not cell.strip() for cell in second_row)
    if is_spacer:
        # Match lengths
        spacer_row = [""] * len(headers)
        kept_rows.append(spacer_row)
        start_idx = 2
    else:
        start_idx = 1
        
    restored_count = 0
    skipped_count = 0
    
    print(Fore.YELLOW + "\n[*] Re-evaluating rows with REFINED safe filter:")
    print("--------------------------------------------------------------------------------")
    
    for row_num in range(start_idx, len(backup_rows)):
        row = backup_rows[row_num]
        
        # Skip empty row
        if all(not cell.strip() for cell in row):
            skipped_count += 1
            print(f"Row {row_num + 1:<4} | [EMPTY ROW] -> SKIPPED")
            continue
            
        content = row[raw_content_idx] if raw_content_idx < len(row) else ""
        
        # Check refined filter
        if should_skip_message_refined(content):
            skipped_count += 1
            sender = row[headers.index("Created By")] if "Created By" in headers and headers.index("Created By") < len(row) else "Unknown"
            print(f"Row {row_num + 1:<4} | [SKIP] Sender: {sender:<18} | Content: {repr(content):<50}")
        else:
            restored_count += 1
            sender = row[headers.index("Created By")] if "Created By" in headers and headers.index("Created By") < len(row) else "Unknown"
            print(f"Row {row_num + 1:<4} | [KEEP] Sender: {sender:<18} | Content: {repr(content):<50}")
            
            # Pad row values if needed
            new_row = list(row)
            while len(new_row) < len(headers):
                new_row.append("")
                
            # Normalize and set
            normalized_val = normalize_text(content)
            new_row[norm_col_idx] = normalized_val
            kept_rows.append(new_row)
            
    print("--------------------------------------------------------------------------------")
    print(Fore.GREEN + f"[+] Safe filtration complete. Kept: {restored_count} rows | Skipped: {skipped_count} rows.")
    
    # Upload back to sheet
    try:
        print("\n[*] Connecting to Google Sheets API to perform restoration...")
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_url(SPREADSHEET_URL)
        sheet = spreadsheet.worksheet(SHEET_NAME)
        
        print("[*] Clearing the spreadsheet...")
        sheet.clear()
        
        print(f"[*] Uploading {len(kept_rows)} clean, normalized records back to Google Sheets...")
        col_end_letter = gspread.utils.rowcol_to_a1(1, len(headers))[0:-1]
        range_to_update = f"A1:{col_end_letter}{len(kept_rows)}"
        
        sheet.update(range_to_update, kept_rows, value_input_option='USER_ENTERED')
        print(Fore.GREEN + f"[+] SUCCESS! The Google Sheet was restored successfully with {restored_count} normalized records!")
    except Exception as e:
        print(Fore.RED + f"[-] Error writing back to sheet: {e}")

if __name__ == "__main__":
    restore_and_normalize()
