import os
import sys
import re
import json
import shutil
import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials
from colorama import init, Fore, Style

# Force stdout and stderr to use UTF-8 on Windows to prevent UnicodeEncodeError in cmd/powershell
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Initialize colorama
init(autoreset=True)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/19C4vdoFIlMQGhAyUmYjaoSatU-jQPy4BJIpoXbMZkEM/edit"
SHEET_NAME = "AllData"

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

def should_skip_message(content: str) -> bool:
    """
    Upgraded bulletproof filter to detect meaningless, short, system, and bot messages.
    Supports robust space-normalization and unicode cleaning.
    """
    if not content:
        return True
        
    # Standardize spaces and remove directional marks
    content_clean = content.strip().replace('\u200e', '').replace('\u200f', '').replace('\u202f', ' ').replace('\u200b', '')
    # Replace any multi-spaces/tabs/newlines with a single space for uniform checks
    content_norm = re.sub(r'[\s\xa0]+', ' ', content_clean).strip().lower()
    
    # If it is a voice note/audio file, do NOT skip it!
    if extract_audio_filename(content) is not None:
        return False
        
    # 1. Skip WhatsApp system notifications
    system_keywords = [
        "added you", "created this group", "joined using an invite link",
        "changed this group's icon", "changed the subject", "left", "invited",
        "changed their phone number", "turned on messages", "waiting for this message",
        "changed the group description"
    ]
    if any(keyword in content_norm for keyword in system_keywords):
        return True
        
    # 2. Skip bot stats, domain queries, or lists of domains
    # e.g., aisteel.it.com 55, aisteel.ae 125, aisteel.ai 719
    if re.search(r"aisteel\s*\.\s*[a-z0-9]+([\.-][a-z0-9]+)*", content_norm, re.IGNORECASE):
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
        
    # Check for non-audio attached files (e.g. PDF, Images) and skip them
    if re.search(r"<attached:\s*([^>]+)>", content_norm):
        return True
        
    # 5. Skip very short filler/meaningless expressions (Persian and English)
    normalized_content = re.sub(r'[^\w\s\u0600-\u06FF]', ' ', content_norm)
    words = [w for w in normalized_content.split() if w]
    
    fillers = {
        "بله", "چشم", "حتما", "باشه", "سلام", "ممنون", "تشکر", "خوبید", "مرسی", "سپاس", "اوکی", "حله", "آره",
        "خوبم", "ممنونم", "مرسی ممنون", "انشالله", "انشأالله", "انشاالله", "یاعلی", "یا علی", "خب", "خوب",
        "شما", "من", "ما", "آنها", "او", "ایشان", "این", "آن", "چه", "چطور", "چرا", "کی", "کجا", "کیه",
        "yes", "ok", "okey", "sure", "thanks", "thank you", "hello", "hi", "deal", "yep", "yup"
    }
    
    if len(words) == 1 and words[0] in fillers:
        return True
        
    # 6. Skip short/meaningless messages lacking steel industry keywords
    steel_keywords = [
        "تیرآهن", "تیر آهن", "ميلگرد", "میلگرد", "میل گرد", "استیل", "آهن", "پروفیل", "لوله", 
        "نبشی", "خرید", "فروش", "قیمت", "تن", "بار", "ورق", "قوطی", "شمش", "ناودانی", "هاش", 
        "سپری", "سیم", "مفتول", "تسمه", "زانو", "اتصالات", "شیرآلات", "فولاد", "سفارش", "تخفیف",
        "پیش‌فاکتور", "فاکتور", "وزن", "ضخامت", "ابعاد", "سایز", "شاخه", "کیلو", "کیلوگرم", "آهن‌آلات"
    ]
    has_steel_keyword = any(kw in content_norm for kw in steel_keywords)
    
    # Count characters (excluding spaces and punctuation)
    alphanumeric_only = re.sub(r'[^\w\u0600-\u06FF]', '', content_norm).strip()
    
    if not has_steel_keyword:
        # Match questions consisting of name/short text only (e.g. عرفان ؟؟)
        if '؟' in content_clean or '?' in content_clean:
            return True
        if len(alphanumeric_only) < 12:
            return True
        if len(words) <= 2:
            return True
            
    return False

def clean_google_sheets():
    print(Fore.CYAN + Style.BRIGHT + "\n==============================================")
    print(Fore.CYAN + Style.BRIGHT + "    GOOGLE SHEETS DUST & CLEANUP PIPELINE     ")
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
        
    # Read all sheet values
    try:
        print("[*] Fetching spreadsheet rows...")
        all_values = sheet.get_all_values()
        print(Fore.GREEN + f"[+] Fetched {len(all_values)} rows successfully.")
    except Exception as e:
        print(Fore.RED + f"[-] Failed to fetch values: {e}")
        return
        
    if len(all_values) < 2:
        print(Fore.YELLOW + "[!] Spreadsheet has too few rows to clean.")
        return
        
    headers = all_values[0]
    print(f"[*] Sheet Headers: {headers}")
    
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
    
    # Create a local backup of spreadsheet data
    backup_file = os.path.join(BASE_DIR, f"backup_sheet_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(backup_file, 'w', encoding='utf-8') as f:
        json.dump(all_values, f, ensure_ascii=False, indent=2)
    print(Fore.GREEN + f"[+] Safely backed up spreadsheet data to: {os.path.basename(backup_file)}")
    
    # Filter rows
    kept_rows = []
    kept_rows.append(all_values[0])  # Keep header row
    
    # Check if second row is spacer or header helper
    # Often, a blank row exists under headers, keep it to protect spreadsheet layout
    if len(all_values) > 1:
        second_row = all_values[1]
        is_blank = all(not cell.strip() for cell in second_row)
        if is_blank:
            kept_rows.append(second_row)
            start_row_idx = 2
            print("[*] Detected and preserved blank spacer row 2.")
        else:
            start_row_idx = 1
            
    deleted_count = 0
    print(Fore.YELLOW + "\n[*] Starting Row Classification and Filtering:")
    print("--------------------------------------------------------------------------------")
    
    for row_num in range(start_row_idx, len(all_values)):
        row = all_values[row_num]
        
        # If the entire row is empty, skip/clean it out
        if all(not cell.strip() for cell in row):
            deleted_count += 1
            print(f"Row {row_num + 1:<4} | [EMPTY ROW] -> REMOVED")
            continue
            
        # Get content
        content = ""
        if raw_content_idx < len(row):
            content = row[raw_content_idx]
            
        # Check matching
        if should_skip_message(content):
            deleted_count += 1
            sender = row[headers.index("Created By")] if "Created By" in headers and headers.index("Created By") < len(row) else "Unknown"
            print(f"Row {row_num + 1:<4} | Sender: {sender:<20} | Content: {repr(content):<50} -> REMOVED")
        else:
            kept_rows.append(row)
            
    print("--------------------------------------------------------------------------------")
    print(Fore.GREEN + f"[+] Filtering complete. Total rows classified: {len(all_values)}")
    print(Fore.YELLOW + f"[+] Kept: {len(kept_rows)} rows | Deleted/Cleaned: {deleted_count} rows.")
    
    if deleted_count == 0:
        print(Fore.GREEN + "\n[+] Congratulations! The Google Sheet is already fully clean. No edits needed.")
        return
        
    # Write back clean data
    try:
        print("\n[*] Uploading clean data set to Google Sheets...")
        # Clear sheet first
        sheet.clear()
        
        # Write back the kept rows
        # Use gspread update with dynamic range e.g. A1:Z[len]
        col_end_letter = gspread.utils.rowcol_to_a1(1, len(headers))[1:] # Get column letter, like 'Z'
        range_to_update = f"A1:{col_end_letter}{len(kept_rows)}"
        
        sheet.update(range_to_update, kept_rows, value_input_option='USER_ENTERED')
        print(Fore.GREEN + f"[+] Safely synchronized Google Sheets! {deleted_count} meaningless rows deleted.")
    except Exception as e:
        print(Fore.RED + f"[-] Error writing back to sheet: {e}")
        print(Fore.YELLOW + f"[!] Please restore from backup file: {backup_file}")

if __name__ == "__main__":
    clean_google_sheets()
