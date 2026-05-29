"""
phase3_enrich.py
══════════════════════════════════════════════════════════════════════════════
Phase 3 — Data Cleaning & AI Enrichment
──────────────────────────────────────────────────────────────────────────────
WHAT IT DOES:
  For every row in Google Sheet "AllData", checks if the AI-enrichable columns
  are empty. If empty → uses OpenAI GPT to fill them. If already filled → skips.
  This makes the script 100% idempotent (safe to run multiple times).

TARGET COLUMNS (filled by AI):
  ┌─────────────────┬─────────────────────────────────────────────────────┐
  │ Normalized Content │ Rule-based text normalization (no AI needed)     │
  │ Category        │ AI: دسته‌بندی موضوعی پیام                           │
  │ Topic           │ AI: موضوع اصلی پیام (یک عبارت کوتاه)               │
  │ Title           │ AI: عنوان خلاصه پیام                                │
  │ Summary         │ AI: خلاصه مفید پیام                                 │
  │ Tags            │ AI: تگ‌های کلیدی با کاما                            │
  │ Priority        │ AI: اولویت (High / Medium / Low)                    │
  │ Action Items    │ AI: اقدامات لازم (اگر وجود داشت)                   │
  └─────────────────┴─────────────────────────────────────────────────────┘

USAGE:
  python phase3_enrich.py

REQUIREMENTS:
  pip install openai gspread google-auth colorama
  OPENAI_API_KEY must be set as environment variable OR in a .env file.
══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import json
import time
import logging
import gspread
from datetime import datetime
from google.oauth2.service_account import Credentials
from colorama import init, Fore, Style

# ── Force UTF-8 on Windows ────────────────────────────────────────────────
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

init(autoreset=True)

# ── Try loading .env file if python-dotenv is available ──────────────────
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ── OpenAI client ─────────────────────────────────────────────────────────
try:
    from openai import OpenAI
    openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
except ImportError:
    print(Fore.RED + "[-] openai package not found. Run: pip install openai")
    sys.exit(1)

# ── Local imports ─────────────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from normalization_layer import normalize_text
from sheet_guard import safe_worksheet, SheetWriteProtectionError

# ── Config ────────────────────────────────────────────────────────────────
CREDENTIALS_FILE  = os.path.join(BASE_DIR, "credentials.json")
SPREADSHEET_URL   = "https://docs.google.com/spreadsheets/d/19C4vdoFIlMQGhAyUmYjaoSatU-jQPy4BJIpoXbMZkEM/edit"
SHEET_NAME        = "AllData"
GPT_MODEL         = "gpt-4o-mini"       # cheap + fast + multilingual
GPT_DELAY_SECONDS = 0.5                 # polite rate-limiting between API calls
LOG_DIR           = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Columns that Phase 3 is responsible for filling
# These are checked: if ALL are empty → enrich this row
AI_TARGET_COLUMNS = ["Category", "Topic", "Title", "Summary", "Tags", "Priority", "Action Items"]
NORM_COLUMN       = "Normalized Content"   # rule-based, no AI

# ── Logging ───────────────────────────────────────────────────────────────
log_file = os.path.join(LOG_DIR, f"phase3_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("phase3")


# ══════════════════════════════════════════════════════════════════════════
# HELPER: Column mapping
# ══════════════════════════════════════════════════════════════════════════
def get_col_map(headers: list) -> dict:
    """Returns {column_name: 0-based_index} for all headers."""
    return {h.strip(): i for i, h in enumerate(headers)}


def cell(row: list, col_map: dict, col_name: str) -> str:
    """Safe cell reader — returns '' if column missing or out of bounds."""
    idx = col_map.get(col_name, -1)
    if idx == -1 or idx >= len(row):
        return ""
    return (row[idx] or "").strip()


def row_needs_enrichment(row: list, col_map: dict) -> bool:
    """
    Returns True if ALL AI target columns are empty for this row.
    Skips rows that have no meaningful content to enrich.
    """
    content = cell(row, col_map, "Raw Content") or cell(row, col_map, "Transcript")
    if not content or not content.strip():
        return False   # no content → nothing to enrich
    # Check if every AI column is empty
    return all(not cell(row, col_map, col) for col in AI_TARGET_COLUMNS)


# ══════════════════════════════════════════════════════════════════════════
# AI ENRICHMENT — single GPT call returns all fields at once
# ══════════════════════════════════════════════════════════════════════════
SYSTEM_PROMPT = """You are an AI assistant specialized in analyzing business communications
in the steel and construction materials industry (Farsi/Arabic/English mixed messages).

You will receive a WhatsApp message or voice transcript. Analyze it and respond ONLY with
valid JSON (no markdown, no code block) with these exact keys:

{
  "Category": "one of: [سفارش خرید | استعلام قیمت | پیام تیمی | مالی | پشتیبانی | عمومی | نامشخص]",
  "Topic":    "a 3-8 word phrase describing the core topic (in Farsi if message is Farsi)",
  "Title":    "a concise title for the message (max 60 chars)",
  "Summary":  "a 1-3 sentence neutral summary of what this message is about",
  "Tags":     "comma-separated keywords relevant to this message (max 5 tags)",
  "Priority": "one of: [High | Medium | Low] — High if urgent/financial/order, Low if social",
  "Action Items": "bullet list of action items if any, else empty string"
}

Rules:
- If the message is meaningless/system/very short → set all fields to empty string ""
- Keep Farsi text in Farsi, don't translate unnecessarily
- Be concise and factual
"""

def enrich_with_ai(content: str, sender: str, source: str) -> dict:
    """
    Calls OpenAI GPT and returns a dict with all AI-enriched fields.
    Returns empty-string dict on failure.
    """
    empty = {k: "" for k in AI_TARGET_COLUMNS}

    if not content or len(content.strip()) < 5:
        return empty

    user_message = f"""Sender: {sender}
Source: {source}
Message:
{content}"""

    try:
        response = openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_message},
            ],
            temperature=0.2,
            max_tokens=400,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content.strip()
        result = json.loads(raw)

        # Validate and sanitize — ensure all expected keys exist
        enriched = {}
        for col in AI_TARGET_COLUMNS:
            enriched[col] = str(result.get(col, "")).strip()
        return enriched

    except json.JSONDecodeError as e:
        logger.warning(f"  JSON parse error: {e} | raw: {raw[:100]}")
        return empty
    except Exception as e:
        logger.error(f"  OpenAI API error: {e}")
        return empty


# ══════════════════════════════════════════════════════════════════════════
# MAIN PHASE 3 PIPELINE
# ══════════════════════════════════════════════════════════════════════════
def run_phase3():
    print(Fore.CYAN + Style.BRIGHT + "\n" + "═" * 62)
    print(Fore.CYAN + Style.BRIGHT + "   Phase 3 — Data Cleaning & AI Enrichment")
    print(Fore.CYAN + Style.BRIGHT + "═" * 62 + "\n")

    # ── 0. API key check ─────────────────────────────────────────────────
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key or api_key.startswith("sk-..."):
        print(Fore.RED + "[-] OPENAI_API_KEY not set.")
        print(Fore.YELLOW + "    Set it with:  $env:OPENAI_API_KEY = 'sk-...'")
        print(Fore.YELLOW + "    Or add it to a .env file in this directory.")
        sys.exit(1)
    print(Fore.GREEN + f"[+] OpenAI API key loaded (model: {GPT_MODEL})")

    # ── 1. Connect to Google Sheets ───────────────────────────────────────
    if not os.path.exists(CREDENTIALS_FILE):
        print(Fore.RED + f"[-] credentials.json not found at {CREDENTIALS_FILE}")
        sys.exit(1)

    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds  = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_url(SPREADSHEET_URL)
        sheet = safe_worksheet(spreadsheet, SHEET_NAME)
        print(Fore.GREEN + f"[+] Connected to: '{spreadsheet.title}' → '{SHEET_NAME}' [PROTECTED]")
    except Exception as e:
        print(Fore.RED + f"[-] Google Sheets connection failed: {e}")
        sys.exit(1)

    # ── 2. Fetch all rows ─────────────────────────────────────────────────
    try:
        all_values = sheet.get_all_values()
        print(Fore.GREEN + f"[+] Fetched {len(all_values)} rows from sheet.")
    except Exception as e:
        print(Fore.RED + f"[-] Failed to fetch sheet data: {e}")
        sys.exit(1)

    if len(all_values) < 2:
        print(Fore.YELLOW + "[!] Sheet has no data rows. Exiting.")
        return

    headers = [h.strip() for h in all_values[0]]
    col_map = get_col_map(headers)
    print(f"[*] Columns detected: {headers}\n")

    # ── 3. Ensure all target columns exist in headers ─────────────────────
    all_target_cols = AI_TARGET_COLUMNS + [NORM_COLUMN]
    missing_cols = [c for c in all_target_cols if c not in col_map]
    if missing_cols:
        print(Fore.YELLOW + f"[!] Missing columns in sheet: {missing_cols}")
        print(Fore.YELLOW + "    Add these columns to the sheet header first.")
        sys.exit(1)

    # ── 4. Identify rows that need enrichment ─────────────────────────────
    # Skip row 0 (header) and row 1 if it's a blank spacer
    start_idx = 1
    if len(all_values) > 1 and all(not c.strip() for c in all_values[1]):
        start_idx = 2
        print("[*] Detected blank spacer row 2 — skipping it.")

    rows_to_process = []
    rows_already_done = 0

    for i in range(start_idx, len(all_values)):
        row = all_values[i]
        if not any(c.strip() for c in row):
            continue  # skip fully empty rows
        if row_needs_enrichment(row, col_map):
            rows_to_process.append((i, row))
        else:
            rows_already_done += 1

    print(Fore.CYAN + f"[*] Rows already enriched   : {rows_already_done}")
    print(Fore.CYAN + f"[*] Rows to process (Phase 3): {len(rows_to_process)}")

    if not rows_to_process:
        print(Fore.GREEN + "\n[+] All rows are already enriched. Nothing to do!")
        return

    print()

    # ── 5. Process each row ───────────────────────────────────────────────
    success_count  = 0
    skip_count     = 0
    error_count    = 0

    for idx, (sheet_row_idx, row) in enumerate(rows_to_process):
        sheet_row_num = sheet_row_idx + 1  # 1-based for gspread

        sender  = cell(row, col_map, "Created By") or "Unknown"
        source  = cell(row, col_map, "Source")     or "Text"
        raw     = cell(row, col_map, "Raw Content")
        transcript = cell(row, col_map, "Transcript")

        # Choose best content: prefer transcript for voice messages
        content = transcript if source == "Voice" and transcript else raw

        print(Fore.YELLOW + f"[{idx+1}/{len(rows_to_process)}] Row {sheet_row_num} | {sender} | {source}")
        print(f"  Content preview: {repr(content[:80])}")

        # ── 5a. Rule-based Normalization (no AI cost) ──────────────────
        norm_val = normalize_text(raw) if raw else ""
        norm_col_letter = gspread.utils.rowcol_to_a1(sheet_row_num, col_map[NORM_COLUMN] + 1)[:-1]
        if norm_val and not cell(row, col_map, NORM_COLUMN):
            try:
                sheet.update(
                    f"{norm_col_letter}{sheet_row_num}",
                    [[norm_val]],
                    value_input_option="USER_ENTERED"
                )
                print(Fore.CYAN + f"  ✔ Normalized Content written.")
            except Exception as e:
                logger.error(f"  Failed to write Normalized Content: {e}")

        # ── 5b. AI Enrichment ──────────────────────────────────────────
        if not content or len(content.strip()) < 5:
            print(Fore.MAGENTA + "  ⊘ Skipped (no meaningful content for AI)")
            skip_count += 1
            print()
            continue

        enriched = enrich_with_ai(content, sender, source)
        time.sleep(GPT_DELAY_SECONDS)

        # ── 5c. Write each enriched field to its cell ──────────────────
        write_errors = 0
        for col_name in AI_TARGET_COLUMNS:
            value = enriched.get(col_name, "")
            if not value:
                continue  # don't overwrite with empty
            col_idx = col_map.get(col_name, -1)
            if col_idx == -1:
                continue
            col_letter = gspread.utils.rowcol_to_a1(sheet_row_num, col_idx + 1)[:-1]
            try:
                sheet.update(
                    f"{col_letter}{sheet_row_num}",
                    [[value]],
                    value_input_option="USER_ENTERED"
                )
            except Exception as e:
                logger.error(f"  Error writing '{col_name}': {e}")
                write_errors += 1

        if write_errors == 0:
            print(Fore.GREEN  + f"  ✔ AI fields written: Category={enriched.get('Category','-')} | Priority={enriched.get('Priority','-')}")
            print(Fore.WHITE  + f"    Topic   : {enriched.get('Topic','')}")
            print(Fore.WHITE  + f"    Summary : {enriched.get('Summary','')[:80]}")
            success_count += 1
        else:
            print(Fore.RED + f"  ✘ {write_errors} write error(s) — check log.")
            error_count += 1

        print()

    # ── 6. Summary ────────────────────────────────────────────────────────
    print("═" * 62)
    print(Fore.GREEN  + f"[+] Phase 3 complete!")
    print(Fore.GREEN  + f"    ✔ Enriched   : {success_count}")
    print(Fore.YELLOW + f"    ⊘ Skipped    : {skip_count}")
    print(Fore.CYAN   + f"    — Already done: {rows_already_done}")
    if error_count:
        print(Fore.RED + f"    ✘ Errors     : {error_count}  (see {log_file})")
    print("═" * 62)
    print(Fore.CYAN + f"\n[*] Full log saved to: {log_file}")


if __name__ == "__main__":
    run_phase3()
