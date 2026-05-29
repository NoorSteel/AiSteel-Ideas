"""
classify_categories.py
══════════════════════════════════════════════════════════════════════════════
Category Classification & AI Structuring Pipeline
──────────────────────────────────────────────────────────────────────────────
WHAT IT DOES:
  For every row in Google Sheet "AllData", uses OpenAI GPT to categorize
  the message content.
  - Primary Category: Selects exactly ONE from the user-specified 20 categories.
  - Secondary Category: Optionally generates 1-2 secondary categories.
  Writes these back to the 'Category' and a new 'Secondary Category' column.

USAGE:
  python classify_categories.py [--force]
══════════════════════════════════════════════════════════════════════════════
"""

import os
import sys
import json
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
        logging.FileHandler(os.path.join(LOG_DIR, "classification.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("classification")

# Categories requested by user
VALID_CATEGORIES = [
    "Vision & Business Concept",
    "Business Model",
    "Strategy",
    "Product",
    "Services",
    "AI Solutions",
    "Steel Industry Applications",
    "Market Research",
    "Sales",
    "Marketing",
    "Operations",
    "Technology & Infrastructure",
    "Finance",
    "Legal & DIFC",
    "Partnerships",
    "Investment & Fundraising",
    "Risk Assessment",
    "Decisions",
    "Tasks & Action Items",
    "Meetings & Discussions"
]

SYSTEM_PROMPT = """You are an AI specialized in business analysis and categorizing communications in the steel and construction materials industry (AiSteel startup).

Analyze the WhatsApp message or transcription text and categorize it according to the classification rules.

You MUST select exactly ONE Primary Category from the list below:
- Vision & Business Concept (for high-level vision, startup idea, goals, identity)
- Business Model (for how the startup makes money, value proposition)
- Strategy (for planning, roadmap, next steps)
- Product (for software product development, features, design, UI/UX, website)
- Services (for business services, consulting, solutions offered)
- AI Solutions (for specific AI models, systems, training, Whisper, GPT integration)
- Steel Industry Applications (for metallurgical terms, raw materials, steel trade)
- Market Research (for researching competitors, market sizes, opportunities)
- Sales (for customer orders, inquiries, price quotes, commercial terms)
- Marketing (for social media, branding, campaigns, Instagram, logo design)
- Operations (for company day-to-day operations, office locations, setup)
- Technology & Infrastructure (for servers, APIs, hosting, databases, codebase)
- Finance (for payments, bank private accounts, funding, capital)
- Legal & DIFC (for Dubai International Financial Centre, regulations, licenses, registration)
- Partnerships (for accenture, vendor relations, strategic alliances)
- Investment & Fundraising (for private equity, seeking investors)
- Risk Assessment (for security, sheet protection, audit, error checking)
- Decisions (for final strategic decisions and executive choices)
- Tasks & Action Items (for concrete TODOs, work delegations)
- Meetings & Discussions (for summaries of meetings or open-ended discussions)

Additionally, you can optionally generate 1 to 2 Secondary Categories from the same list if the message covers multiple topics.

Your response must be ONLY a valid JSON object (no markdown, no code block) with these exact keys:
{
  "Primary": "exactly one value from the list above",
  "Secondary": "comma-separated list of secondary categories from the list above, or empty string \"\" if none apply"
}

Rules:
- Be precise and objective
- If the message is meaningless/too short/deleted -> set both categories to empty string ""
- Respond ONLY with the JSON object
"""

def call_ai_classifier(text: str) -> dict:
    """Calls OpenAI GPT to classify the message into Primary and Secondary categories."""
    default_result = {"Primary": "", "Secondary": ""}
    if not text or len(text.strip()) < 2:
        return default_result
    
    try:
        response = openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f'Message Content:\n"{text}"'},
            ],
            temperature=0.1,
            max_tokens=150,
            response_format={"type": "json_object"}
        )
        raw = response.choices[0].message.content.strip()
        res = json.loads(raw)
        
        # Verify and clean the AI response
        primary = str(res.get("Primary", "")).strip()
        secondary = str(res.get("Secondary", "")).strip()
        
        if primary not in VALID_CATEGORIES:
            primary = ""
            
        return {"Primary": primary, "Secondary": secondary}
    except Exception as e:
        logger.error(f"  OpenAI API Error: {e}")
        return default_result

def cell_val(row: list, col_map: dict, col_name: str) -> str:
    idx = col_map.get(col_name, -1)
    if idx == -1 or idx >= len(row):
        return ""
    return (row[idx] or "").strip()

def run_classification(force: bool = False):
    print(Fore.CYAN + Style.BRIGHT + "\n" + "═" * 62)
    print(Fore.CYAN + Style.BRIGHT + "   AI Category Classification Pipeline")
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
    
    # 4. Handle Secondary Category column addition
    sec_col = "Secondary Category"
    if sec_col not in col_map:
        print(Fore.YELLOW + f"[*] Column '{sec_col}' not found. Adding as a new column...")
        try:
            print(Fore.YELLOW + "[*] Expanding sheet grid by adding 1 new column...")
            sheet.add_cols(1)
            print(Fore.GREEN + "[+] Expanded columns successfully.")
            
            new_col_idx = len(headers) + 1
            new_cell_a1 = gspread.utils.rowcol_to_a1(1, new_col_idx)
            
            # Safely write the header cell
            sheet.update(new_cell_a1, [[sec_col]])
            headers.append(sec_col)
            col_map[sec_col] = len(headers) - 1
            print(Fore.GREEN + f"[+] Created column '{sec_col}' at position {new_cell_a1}")
        except Exception as e:
            print(Fore.RED + f"[-] Failed to create header cell '{sec_col}': {e}")
            sys.exit(1)
    else:
        print(Fore.GREEN + f"[+] Column '{sec_col}' exists at column number {col_map[sec_col] + 1}")

    prim_col_idx = col_map.get("Category", -1)
    sec_col_idx = col_map[sec_col]

    if prim_col_idx == -1:
        print(Fore.RED + "[-] Error: 'Category' column not found in Google Sheets headers.")
        sys.exit(1)

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
        
        # We need raw text: prioritize Transcription, then Transcript, then Raw Content
        raw_text = cell_val(row, col_map, "Transcription") or cell_val(row, col_map, "Transcript") or cell_val(row, col_map, "Raw Content")
        existing_prim = cell_val(row, col_map, "Category")
        
        if not raw_text or len(raw_text.strip()) < 2:
            continue
            
        # If Category already has a valid classification and force is False, skip
        if existing_prim in VALID_CATEGORIES and not force:
            skip_count += 1
            continue
            
        rows_to_process.append((idx + 1, raw_text))

    print(Fore.CYAN + f"[*] Total rows to process : {len(rows_to_process)}")
    print(Fore.CYAN + f"[*] Already classified     : {skip_count}")

    if not rows_to_process:
        print(Fore.GREEN + "\n[+] No rows need classification. All done!")
        return

    print()

    for idx, (row_num, raw_text) in enumerate(rows_to_process):
        print(Fore.YELLOW + f"[{idx+1}/{len(rows_to_process)}] Row {row_num}")
        print(f"  Content: {repr(raw_text[:80])}")

        res = call_ai_classifier(raw_text)
        time.sleep(GPT_DELAY_SECONDS)

        if res["Primary"]:
            prim_cell = gspread.utils.rowcol_to_a1(row_num, prim_col_idx + 1)
            sec_cell = gspread.utils.rowcol_to_a1(row_num, sec_col_idx + 1)
            
            try:
                sheet.update(prim_cell, [[res["Primary"]]])
                sheet.update(sec_cell, [[res["Secondary"]]])
                print(Fore.GREEN + f"  ✔ Primary   : {res['Primary']}")
                if res["Secondary"]:
                    print(Fore.GREEN + f"  ✔ Secondary : {res['Secondary']}")
                
                # Also set Status to "node2" to denote classification step complete
                if "Status" in col_map:
                    status_col_idx = col_map["Status"]
                    status_cell = gspread.utils.rowcol_to_a1(row_num, status_col_idx + 1)
                    sheet.update(status_cell, [["node2"]])
                
                success_count += 1
            except Exception as e:
                logger.error(f"  Failed to write to row {row_num}: {e}")
                error_count += 1
        else:
            logger.warning(f"  Failed to classify row {row_num}")
            error_count += 1
        
        print()

    print("═" * 62)
    print(Fore.GREEN + "[+] AI Category Classification complete!")
    print(Fore.GREEN + f"    ✔ Classified : {success_count}")
    print(Fore.YELLOW + f"    ⊘ Skipped    : {skip_count}")
    if error_count:
        print(Fore.RED + f"    ✘ Errors     : {error_count}")
    print("═" * 62)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="AI Category Classification Pipeline")
    parser.add_argument("--force", action="store_true", help="Force re-classification on all rows even if already classified")
    args = parser.parse_args()

    run_classification(force=args.force)
