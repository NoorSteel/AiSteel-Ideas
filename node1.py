"""
node1.py
══════════════════════════════════════════════════════════════════════════════
Node1 - Text Optimization & Team Member Name Correction
──────────────────────────────────────────────────────────────────────────────
WHAT IT DOES:
  For every row in Google Sheet "AllData", applies a specialized AI editor
  prompt to clean up transcription errors, formatting, and correct spelling
  of team members' names (محمدرضا ذاکری، محمد خشنودی، عرفان، آیدا، نگین، محمدعلی).
  Writes the optimized result to the "Transcription" column.

USAGE:
  python node1.py [--force]
══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import argparse
import time
import logging
import gspread
from google.oauth2.service_account import Credentials
from colorama import init, Fore, Style

# Force UTF-8 on Windows
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

init(autoreset=True)

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from openai import OpenAI
    openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
except ImportError:
    print(Fore.RED + "[-] openai package not found. Run: pip install openai")
    sys.exit(1)

from sheet_guard import safe_worksheet

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CREDENTIALS_FILE  = os.path.join(BASE_DIR, "credentials.json")
SPREADSHEET_URL   = "https://docs.google.com/spreadsheets/d/19C4vdoFIlMQGhAyUmYjaoSatU-jQPy4BJIpoXbMZkEM/edit"
SHEET_NAME        = "AllData"
GPT_MODEL         = "gpt-4o-mini"
GPT_DELAY_SECONDS = 0.5

# Setup local logging
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "node1.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("node1")

# The optimized system prompt containing specialized team names and metal terms
SYSTEM_PROMPT = """تو یک هوش مصنوعی ویراستار و متخصص در حوزه صنعت آهن و فولاد هستی.
متن زیر خروجی خام تبدیل گفتار به نوشتار (STT) از یک وویس واتس‌اپ یا یک پیام متنی است. 

وظیفه تو این است که بدون تغییر در معنا، مفهوم و اطلاعات اصلی پیام:
1. غلط‌های املایی ناشی از تلفظ یا اشتباهات صوتی را اصلاح کنی (مثلاً "میل گرد" به "میلگرد"، "تیر آهن" به "تیرآهن" یا اصطلاحات متالورژی).
2. اسامی خاص اعضای تیم و همکاران را شناسایی کرده و املای صحیح آن‌ها را دقیقاً مطابق با لیست زیر ثبت کنی (از ثبت املای عامیانه، صوتیِ اشتباه یا فینگلیش خودداری شود):
   - محمدرضا ذاکری
   - محمد خشنودی
   - عرفان
   - آیدا
   - نگین
   - محمدعلی
3. علائم نگارشی (نقطه، ویرگول، علامت سوال و ...) را به درستی قرار دهی تا متن کاملاً خوانا شود.
4. کلمات پرکننده عامیانه، جملات زائد و تکرارهای اضافی صحبت کردن (مانند "اممم"، "مثلا"، "در واقع"، مکث‌های بیهوده) را حذف کنی.
5. هرگونه ساختار لیست‌بندی (مانند بولِت‌پوینت، خط تیره، شماره‌گذاری و استایل‌های لیستی) را حذف کرده و کل متن را به صورت یک پاراگراف روان، پیوسته، منسجم و یک‌دست بازنویسی کنی. کل پیام باید به شکل پاراگراف متنی ارائه شود.
6. اصطلاحات انگلیسی یا استارتاپی که فینگلیش یا با املای نادرست نوشته شده‌اند را اصلاح کنی.

پاسخ تو باید فقط و فقط شامل متن اصلاح‌شده و نهایی باشد که به صورت یک پاراگراف یک‌دست است، و هیچ توضیح اضافی یا عنوان دیگری ننویسی.

متن ورودی:
" {text} "

متن اصلاح‌شده و نهایی برای ثبت در گوگل شیت:"""

def call_ai_editor(text: str) -> str:
    """Calls OpenAI GPT with the optimized Node1 system prompt to clean the text."""
    if not text or len(text.strip()) < 2:
        return ""
    
    try:
        response = openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {"role": "user", "content": SYSTEM_PROMPT.format(text=text)},
            ],
            temperature=0.1,
            max_tokens=500,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"  OpenAI API Error: {e}")
        return ""

def cell_val(row: list, col_map: dict, col_name: str) -> str:
    idx = col_map.get(col_name, -1)
    if idx == -1 or idx >= len(row):
        return ""
    return (row[idx] or "").strip()

def run_node1(force: bool = False):
    print(Fore.CYAN + Style.BRIGHT + "\n" + "═" * 62)
    print(Fore.CYAN + Style.BRIGHT + "   Node1 — Text Optimization & Name Correction Pipeline")
    print(Fore.CYAN + Style.BRIGHT + "═" * 62 + "\n")

    # 1. API key check
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print(Fore.RED + "[-] OPENAI_API_KEY not found in environment or .env file.")
        sys.exit(1)

    # 2. Google Sheets Authentication
    if not os.path.exists(CREDENTIALS_FILE):
        print(Fore.RED + f"[-] credentials.json not found at {CREDENTIALS_FILE}")
        sys.exit(1)

    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_url(SPREADSHEET_URL)
        sheet = safe_worksheet(spreadsheet, SHEET_NAME)
        print(Fore.GREEN + f"[+] Connected to Google Sheets: '{spreadsheet.title}' -> '{SHEET_NAME}'")
    except Exception as e:
        print(Fore.RED + f"[-] Google Sheets connection failed: {e}")
        sys.exit(1)

    # 3. Fetch all values
    try:
        all_values = sheet.get_all_values()
        print(Fore.GREEN + f"[+] Fetched {len(all_values)} rows successfully.")
    except Exception as e:
        print(Fore.RED + f"[-] Failed to fetch spreadsheet values: {e}")
        sys.exit(1)

    if len(all_values) < 2:
        print(Fore.YELLOW + "[!] Sheet has no data rows.")
        return

    headers = [h.strip() for h in all_values[0]]
    col_map = {h: idx for idx, h in enumerate(headers)}
    
    # 4. Handle Transcription column addition
    target_col = "Transcription"
    if target_col not in col_map:
        print(Fore.YELLOW + f"[*] Column '{target_col}' not found. Adding as a new column...")
        try:
            # Safely expand grid by adding 1 new column
            print(Fore.YELLOW + "[*] Expanding sheet grid by adding 1 new column...")
            sheet.add_cols(1)
            print(Fore.GREEN + "[+] Expanded columns successfully.")
            
            new_col_idx = len(headers) + 1
            new_cell_a1 = gspread.utils.rowcol_to_a1(1, new_col_idx)
            
            # Safely write the header to the single new cell (avoids full sheet overwrite blocks)
            sheet.update(new_cell_a1, [[target_col]])
            headers.append(target_col)
            col_map[target_col] = len(headers) - 1
            print(Fore.GREEN + f"[+] Created column '{target_col}' at position {new_cell_a1}")
        except Exception as e:
            print(Fore.RED + f"[-] Failed to create header cell '{target_col}': {e}")
            sys.exit(1)
    else:
        print(Fore.GREEN + f"[+] Column '{target_col}' exists at column number {col_map[target_col] + 1}")

    trans_col_idx = col_map[target_col]

    # Detect blank spacer row 2
    start_row_idx = 1
    if len(all_values) > 1 and all(not c.strip() for c in all_values[1]):
        start_row_idx = 2
        print("[*] Skipped blank spacer row 2.")

    # 5. Process rows
    success_count = 0
    skip_count = 0
    error_count = 0
    rows_to_process = []

    for idx in range(start_row_idx, len(all_values)):
        row = all_values[idx]
        if not any(c.strip() for c in row):
            continue # skip empty rows
        
        existing_val = cell_val(row, col_map, target_col)
        # We need raw text: prioritize Transcript column, then Raw Content
        raw_text = cell_val(row, col_map, "Transcript") or cell_val(row, col_map, "Raw Content")
        
        if not raw_text or len(raw_text.strip()) < 2:
            continue
            
        if existing_val and not force:
            skip_count += 1
            continue
            
        rows_to_process.append((idx + 1, raw_text, existing_val))

    print(Fore.CYAN + f"[*] Total rows to process : {len(rows_to_process)}")
    print(Fore.CYAN + f"[*] Already optimized      : {skip_count}")

    if not rows_to_process:
        print(Fore.GREEN + "\n[+] No rows need optimization. All done!")
        return

    print()

    for idx, (row_num, raw_text, old_val) in enumerate(rows_to_process):
        print(Fore.YELLOW + f"[{idx+1}/{len(rows_to_process)}] Row {row_num}")
        print(f"  Input  : {repr(raw_text[:80])}")

        optimized = call_ai_editor(raw_text)
        time.sleep(GPT_DELAY_SECONDS)

        if optimized:
            cell_address = gspread.utils.rowcol_to_a1(row_num, trans_col_idx + 1)
            try:
                sheet.update(cell_address, [[optimized]])
                print(Fore.GREEN + f"  ✔ Optimized : {repr(optimized[:80])}")
                
                # Update Status to "node1"
                if "Status" in col_map:
                    status_col_idx = col_map["Status"]
                    status_address = gspread.utils.rowcol_to_a1(row_num, status_col_idx + 1)
                    sheet.update(status_address, [["node1"]])
                    print(Fore.CYAN + f"  ✔ Status updated to 'node1'")
                    
                success_count += 1
            except Exception as e:
                logger.error(f"  Failed to write to row {row_num}: {e}")
                error_count += 1
        else:
            logger.warning(f"  Failed to get optimized text for row {row_num}")
            error_count += 1
        
        print()

    print("═" * 62)
    print(Fore.GREEN + "[+] Node1 complete!")
    print(Fore.GREEN + f"    ✔ Optimized  : {success_count}")
    print(Fore.YELLOW + f"    ⊘ Skipped    : {skip_count}")
    if error_count:
        print(Fore.RED + f"    ✘ Errors     : {error_count}")
    print("═" * 62)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Node1 Text Optimization Pipeline")
    parser.add_argument("--force", action="store_true", help="Force re-run on all rows even if already processed")
    args = parser.parse_args()

    run_node1(force=args.force)
