import os
import re
import uuid
import shutil
import hashlib
import logging
import zipfile
import sys
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from colorama import init, Fore, Style
from normalization_layer import normalize_text
from sheet_guard import safe_worksheet, SheetWriteProtectionError
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from openai import OpenAI
    openai_client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
except ImportError:
    openai_client = None

# Force stdout and stderr to use UTF-8 on Windows to prevent UnicodeEncodeError in cmd/powershell
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add FFmpeg bin path to PATH to guarantee whisper/ffmpeg works immediately on Windows
ffmpeg_bin = r"C:\Users\HP\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin"
if os.path.exists(ffmpeg_bin) and ffmpeg_bin not in os.environ["PATH"]:
    os.environ["PATH"] = ffmpeg_bin + os.path.pathsep + os.environ["PATH"]

# Gracefully import whisper to avoid import errors if dependencies are not yet installed
try:
    import whisper
except ImportError:
    whisper = None

# Initialize colorama for beautiful console outputs on Windows
init(autoreset=True)

# Configuration and Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.path.join(BASE_DIR, "input")
PROCESSED_DIR = os.path.join(BASE_DIR, "processed")
FAILED_DIR = os.path.join(BASE_DIR, "failed")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
TEMP_AUDIO_DIR = os.path.join(BASE_DIR, "temp_audio")

# Whisper Local Model Selection (Options: "tiny", "base", "small", "medium", "large")
# We use the highly accurate "small" model which is excellent for Farsi speech-to-text.
WHISPER_MODEL_NAME = "small"

# Google Sheets Configuration
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/19C4vdoFIlMQGhAyUmYjaoSatU-jQPy4BJIpoXbMZkEM/edit"
SHEET_NAME = "AllData"
CREDENTIALS_FILE = os.path.join(BASE_DIR, "credentials.json")

# Ensure directories exist
for folder in [INPUT_DIR, PROCESSED_DIR, FAILED_DIR, LOGS_DIR, TEMP_AUDIO_DIR]:
    os.makedirs(folder, exist_ok=True)

# Set up logging - write INFO/DEBUG to file, but stream only WARNING/ERROR to console during execution to keep the progress bar clean
log_filename = f"import_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
log_filepath = os.path.join(LOGS_DIR, log_filename)

file_handler = logging.FileHandler(log_filepath, encoding="utf-8")
file_handler.setLevel(logging.DEBUG)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.WARNING) # Set console to WARNING to prevent logs clashing with progress bar

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[file_handler, console_handler]
)
logger = logging.getLogger("WhatsAppImporter")

def convert_farsi_digits(text: str) -> str:
    """Converts Farsi/Arabic digits to English digits for consistent parsing."""
    farsi_digits = '۰۱۲۳۴۵۶۷۸۹'
    arabic_digits = '٠١٢٣٤٥٦٧٨٩'
    english_digits = '0123456789'
    translation_table = str.maketrans(farsi_digits + arabic_digits, english_digits * 2)
    return text.translate(translation_table)

def generate_message_hash(date_str: str, time_str: str, sender: str, content: str) -> str:
    """Generates a unique SHA-256 hash representing a unique message."""
    raw_str = f"{date_str.strip()}_{time_str.strip()}_{sender.strip()}_{content.strip()}"
    return hashlib.sha256(raw_str.encode('utf-8')).hexdigest()

def correct_steel_terminology(text: str) -> str:
    """
    Applies the same spelling standards as the voice prompt locally to text messages
    and voice transcripts (e.g. correcting spacing, Farsi nim-fase, and brand spelling).
    """
    replacements = {
        r"\bتیر\s+[آا]هن\b": "تیرآهن",
        r"\bمیل\s*گرد\b": "میلگرد",
        r"\bآهن\s*[آا]لات\b": "آهن‌آلات",
        r"\bریخته\s*گری\b": "ریخته‌گری",
        r"\b[اآ][یي]\s+استیل\b": "AiSteel",
        r"\b[اآ][یي][یي]\s+استیل\b": "AiSteel",
        r"\b[aA][iI]\s*[sS][tT][eE][eE][lL]\b": "AiSteel",
        r"\b[aA][iI][sS][tT][eE][eE][lL]\b": "AiSteel",
    }
    
    corrected = text
    for pattern, replacement in replacements.items():
        corrected = re.sub(pattern, replacement, corrected, flags=re.IGNORECASE)
        
    return corrected

def extract_audio_filename(content: str) -> str:
    """
    Extracts the audio filename if the message represents an attached audio file.
    Returns the filename, or None if it's not an audio attachment.
    """
    content_lower = content.strip().lower()
    audio_extensions = ['.opus', '.wav', '.m4a', '.mp3', '.ogg', '.amr']
    
    # iOS Format: <attached: 00000001.opus> or <attached: voice mail 00000001.opus>
    attached_match = re.search(r"<attached:\s*(?:voice\s+mail\s+)?([^>]+)>", content, re.IGNORECASE)
    if attached_match:
        filename = attached_match.group(1).strip()
        if any(filename.lower().endswith(ext) for ext in audio_extensions):
            return filename
            
    # Android Format: PTT-20260529-WA0001.opus (file attached) or AUD-YYYYMMDD-WAXXXX.opus
    android_match = re.search(r"^([\w-]+\.(?:opus|wav|m4a|mp3|ogg|amr))\s*\(file\s+attached\)$", content.strip(), re.IGNORECASE)
    if android_match:
        return android_match.group(1).strip()
        
    # Fallback if only the filename itself is recorded in the content line
    if any(content_lower.endswith(ext) for ext in audio_extensions):
        if len(content.split()) == 1:
            return content.strip()
            
    return None

def should_skip_message(content: str) -> bool:
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
        
    # Check for non-audio attached files (e.g. PDF, Images) and skip them
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

def extract_audio_from_zip(zip_path: str, filename: str, output_dir: str) -> str:
    """Extracts a specific audio file from the ZIP archive to the output directory."""
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        for f in zip_ref.namelist():
            # Match basename case-insensitively
            if os.path.basename(f).lower() == filename.lower():
                dest_path = os.path.join(output_dir, os.path.basename(f))
                with zip_ref.open(f) as source, open(dest_path, 'wb') as target:
                    shutil.copyfileobj(source, target)
                logger.info(f"Extracted audio file: {os.path.basename(f)} -> {dest_path}")
                return dest_path
    raise FileNotFoundError(f"Audio file '{filename}' not found inside ZIP archive '{zip_path}'.")

def transcribe_audio(audio_path: str) -> dict:
    """
    Transcribes an audio file locally using OpenAI Whisper.
    Uses the highly accurate "small" model, primed for Persian steel trade terms.
    Extracts text transcript, duration, language, and status.
    """
    if whisper is None:
        raise ImportError("OpenAI Whisper library is not installed or failed to import. Run 'python -m pip install -r requirements.txt'")
        
    logger.info(f"Loading Whisper '{WHISPER_MODEL_NAME}' model for transcribing: {os.path.basename(audio_path)}")
    try:
        # Load local PyTorch Whisper model (full 32-bit floating point precision)
        model = whisper.load_model(WHISPER_MODEL_NAME)
        
        # Steel industry terminology prompting in Persian and English
        initial_prompt = "AiSteel, آهن، فولاد، میلگرد، تیرآهن، استارتاپ، بیزینس، متالورژی، ریخته‌گری، نبشی، پروفیل، لوله، خرید فولاد"
        
        logger.info("Running Speech-to-Text transcription...")
        result = model.transcribe(audio_path, language="fa", initial_prompt=initial_prompt)
        
        transcript = result.get("text", "").strip()
        language = result.get("language", "fa")
        
        # Calculate duration based on the end of the final segment
        duration = 0.0
        segments = result.get("segments", [])
        if segments:
            duration = segments[-1].get("end", 0.0)
            
        logger.info(f"Transcription successful! Duration: {duration:.2f}s, Language: {language}")
        return {
            "transcript": transcript,
            "duration": round(duration, 2),
            "language": language,
            "status": "Success"
        }
    except Exception as e:
        logger.error(f"Whisper transcription failed: {e}")
        return {
            "transcript": "",
            "duration": 0.0,
            "language": "fa",
            "status": f"Failed: {str(e)}"
        }

def parse_whatsapp_file(file_path: str):
    """
    Parses WhatsApp chat history export file.
    Supports Android and iOS layouts, handles multi-line messages, and Persian (Farsi) text.
    """
    logger.info(f"Parsing file: {os.path.basename(file_path)}")
    
    # Common WhatsApp export date-time regex patterns (after Farsi digit conversion)
    android_pattern = re.compile(
        r"^(\d{1,4}[/\.-]\d{1,2}[/\.-]\d{1,4}),\s*(\d{1,2}:\d{2}(?::\d{2})?(?:\s?[قوب]\.ظ|\s?[AaPp][Mm])?)\s*-\s*([^:]+):\s*(.*)$"
    )
    ios_pattern = re.compile(
        r"^\[(\d{1,4}[/\.-]\d{1,2}[/\.-]\d{1,4}),\s*(\d{1,2}:\d{2}(?::\d{2})?(?:\s?[قوب]\.ظ|\s?[AaPp][Mm])?)\]\s*([^:]+):\s*(.*)$"
    )
    
    messages = []
    current_msg = None
    
    lines = []
    if file_path.endswith('.zip'):
        with zipfile.ZipFile(file_path, 'r') as zip_ref:
            # Find all .txt files inside the ZIP archive
            zip_txt_files = [f for f in zip_ref.namelist() if f.endswith('.txt')]
            if not zip_txt_files:
                raise ValueError("No .txt file found inside the exported ZIP archive.")
            chat_filename = "_chat.txt" if "_chat.txt" in zip_txt_files else zip_txt_files[0]
            logger.info(f"Extracting and parsing '{chat_filename}' from ZIP archive")
            with zip_ref.open(chat_filename) as chat_file:
                content_bytes = chat_file.read()
                content_str = content_bytes.decode('utf-8-sig', errors='ignore')
                lines = content_str.splitlines()
    else:
        with open(file_path, 'r', encoding='utf-8-sig', errors='ignore') as f:
            lines = f.readlines()
        
    for line_num, line in enumerate(lines, 1):
        # 1. Clean directional markers and standardize narrow non-break spaces
        line_clean = line.replace('\u200e', '').replace('\u200f', '').replace('\u202f', ' ')
        
        # 2. Convert digits ONLY in the date/time prefix of the line to allow regex matching
        if line_clean.startswith('['):
            bracket_idx = line_clean.find(']')
            if bracket_idx != -1:
                prefix = convert_farsi_digits(line_clean[:bracket_idx+1])
                cleaned_line = prefix + line_clean[bracket_idx+1:]
            else:
                cleaned_line = line_clean
        else:
            dash_idx = line_clean.find(' - ')
            if dash_idx != -1:
                prefix = convert_farsi_digits(line_clean[:dash_idx])
                cleaned_line = prefix + line_clean[dash_idx:]
            else:
                cleaned_line = line_clean
        
        match = android_pattern.match(cleaned_line)
        if not match:
            match = ios_pattern.match(cleaned_line)
            
        if match:
            if current_msg:
                messages.append(current_msg)
                
            date_str, time_str, sender, content = match.groups()
            current_msg = {
                "date": date_str.strip(),
                "time": time_str.strip(),
                "sender": sender.strip(),
                "content": content.strip()
            }
        else:
            if current_msg:
                current_msg["content"] += "\n" + line.strip()
                
    if current_msg:
        messages.append(current_msg)
        
    logger.info(f"Successfully parsed {len(messages)} messages from {os.path.basename(file_path)}")
    return messages

def get_column_mapping(sheet):
    """
    Fetches the headers from Google Sheets row 1 and builds an index map (1-based).
    If required columns don't exist, they are dynamically appended to row 1.
    """
    try:
        headers = sheet.row_values(1)
    except Exception:
        headers = []
        
    required_cols = {
        "ID": ["ID", "id", "Id"],
        "Date": ["Date", "date", "تاریخ"],
        "Time": ["Time", "time", "زمان"],
        "Created By": ["Created By", "Sender Name", "CreatedBy", "فرستنده", "created_by"],
        "Raw Content": ["Raw Content", "Message Content", "RawContent", "متن پیام", "raw_content"],
        "Message Hash": ["Message Hash", "MessageHash", "hash", "message_hash"],
        "Import Timestamp": ["Import Timestamp", "ImportTimestamp", "Timestamp", "زمان ورود", "import_timestamp"],
        "Source": ["Source", "source", "منبع"],
        "Audio File": ["Audio File", "AudioFile", "فایل صوتی", "audio_file"],
        "Duration": ["Duration", "duration", "مدت زمان", "ثانیه"],
        "Transcript": ["Transcript", "transcript", "متن صدا", "transcription"],
        "Language": ["Language", "language", "زبان"],
        "Transcription Status": ["Transcription Status", "TranscriptionStatus", "وضعیت متنی‌سازی", "transcription_status"],
        "Normalized Content": ["Normalized Content", "NormalizedContent", "normalized_content", "متن نرمال‌شده", "متن نرمال شده"],
        "Transcription": ["Transcription", "transcription", "بهینه‌سازی شده"],
        "Status": ["Status", "status", "وضعیت"]
    }
    
    # Optional columns from user's template to enrich if present
    optional_cols = {
        "Last Update": ["Last Update", "LastUpdate", "last_update"]
    }
    
    mapping = {}
    updated = False
    
    # If the sheet is empty, initialize with required columns
    if not headers:
        headers = list(required_cols.keys())
        sheet.update('A1:M1', [headers])
        updated = True
        
    # Map required columns
    for field, aliases in required_cols.items():
        found_idx = -1
        for idx, h in enumerate(headers):
            if h.strip().lower() in [a.lower() for a in aliases]:
                found_idx = idx + 1
                break
        if found_idx == -1:
            headers.append(field)
            found_idx = len(headers)
            updated = True
        mapping[field] = found_idx
        
    # Map optional columns if present
    for field, aliases in optional_cols.items():
        found_idx = -1
        for idx, h in enumerate(headers):
            if h.strip().lower() in [a.lower() for a in aliases]:
                found_idx = idx + 1
                break
        if found_idx != -1:
            mapping[field] = found_idx
            
    if updated:
        # Update row 1 with new headers
        col_end = gspread.utils.rowcol_to_a1(1, len(headers))
        sheet.update(f'A1:{col_end}', [headers])
        logger.info(f"Google Sheets headers initialized/updated: {headers}")
        
    return mapping, len(headers)

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
    if not text or len(text.strip()) < 2 or openai_client is None:
        return ""
    
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "user", "content": SYSTEM_PROMPT.format(text=text)},
            ],
            temperature=0.1,
            max_tokens=500,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error(f"  OpenAI API Error in call_ai_editor: {e}")
        return ""

def process_files():
    """Main execution loop to find, parse, and upload WhatsApp chats."""
    print(Fore.CYAN + Style.BRIGHT + "\n==============================================")
    print(Fore.CYAN + Style.BRIGHT + "   WHATSAPP TO GOOGLE SHEETS PIPELINE (Phase 2)   ")
    print(Fore.CYAN + Style.BRIGHT + "==============================================\n")
    
    # 1. Search for files in the input folder (supports both .txt and .zip exports)
    files_to_process = [f for f in os.listdir(INPUT_DIR) if f.endswith('.txt') or f.endswith('.zip')]
    if not files_to_process:
        logger.info(Fore.YELLOW + f"No .txt or .zip chat export files found in the /input directory.")
        print(f"\nPlease place WhatsApp export '.txt' or '.zip' files in: {INPUT_DIR}")
        return
        
    logger.info(Fore.GREEN + f"Found {len(files_to_process)} file(s) to process: {files_to_process}")
    
    # 2. Authenticate and Connect to Google Sheets
    if not os.path.exists(CREDENTIALS_FILE):
        logger.error(Fore.RED + f"Credentials file 'credentials.json' not found at: {CREDENTIALS_FILE}")
        logger.info(Fore.YELLOW + "Please set up your Service Account credential file and save it as credentials.json inside the project root.")
        return
        
    try:
        logger.info("Connecting to Google Sheets...")
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_url(SPREADSHEET_URL)
        sheet = safe_worksheet(spreadsheet, SHEET_NAME)
        logger.info(Fore.GREEN + f"Connected successfully to spreadsheet: '{spreadsheet.title}' -> worksheet: '{sheet.title}' [PROTECTED]")
    except Exception as e:
        logger.error(Fore.RED + f"Failed to connect to Google Sheets: {e}")
        return
        
    # 3. Dynamic Columns and Duplicate Cache Initialization
    try:
        mapping, max_cols = get_column_mapping(sheet)
        logger.info(f"Column Mapping indexes (1-based): {mapping}")
        
        # Load existing Message Hashes to prevent duplicates
        logger.info("Fetching existing records from Google Sheets for duplicate checking...")
        hash_col_idx = mapping["Message Hash"]
        existing_hashes_raw = sheet.col_values(hash_col_idx)
        existing_hashes = set(h.strip() for h in existing_hashes_raw[1:] if h.strip())
        logger.info(Fore.GREEN + f"Loaded {len(existing_hashes)} existing message hashes from sheet.")
    except Exception as e:
        logger.error(Fore.RED + f"Failed to initialize metadata/duplicate cache: {e}")
        return
        
    # 4. Processing Loop
    for file_name in files_to_process:
        file_path = os.path.join(INPUT_DIR, file_name)
        total_msg = 0
        imported_msg = 0
        duplicate_msg = 0
        errors_in_file = 0
        
        try:
            parsed_messages = parse_whatsapp_file(file_path)
            total_msg = len(parsed_messages)
            
            rows_to_insert = []
            import_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            print(Fore.YELLOW + f"\nStarting Import Queue for file: {file_name}")
            print(Fore.WHITE + "--------------------------------------------------")
            
            for idx, msg in enumerate(parsed_messages, 1):
                # Calculate progress percentage
                percent = int((idx / total_msg) * 100)
                
                # Show stable progress bar in terminal
                sys.stdout.write(f"\r{Fore.CYAN}Progress: {percent}% ({idx}/{total_msg}) | Processing sender: {msg['sender'][:12]:<12}")
                sys.stdout.flush()
                
                # Skip non-audio media attachments and uninformative short expressions (بله, چشم, حتما)
                if should_skip_message(msg["content"]):
                    continue
                
                # Check if it is a voice note
                audio_filename = extract_audio_filename(msg["content"])
                is_voice = audio_filename is not None
                
                transcript_text = ""
                duration_sec = 0.0
                lang_code = "fa"
                transcription_status = "N/A"
                
                if is_voice:
                    sys.stdout.write(f"\r{Fore.MAGENTA}[Voice STT] {audio_filename} from {msg['sender'][:12]}...                  \n")
                    sys.stdout.flush()
                    
                    extracted_audio_path = None
                    
                    # Extract file from ZIP if available, otherwise look inside raw folder
                    if file_path.endswith('.zip'):
                        try:
                            extracted_audio_path = extract_audio_from_zip(file_path, audio_filename, TEMP_AUDIO_DIR)
                        except Exception as e:
                            logger.error(f"Could not extract audio '{audio_filename}' from ZIP: {e}")
                    else:
                        local_audio_path = os.path.join(INPUT_DIR, audio_filename)
                        if os.path.exists(local_audio_path):
                            extracted_audio_path = os.path.join(TEMP_AUDIO_DIR, audio_filename)
                            shutil.copy2(local_audio_path, extracted_audio_path)
                            
                    # Perform Local Transcription
                    if extracted_audio_path and os.path.exists(extracted_audio_path):
                        if whisper is None:
                            transcription_status = "Failed: openai-whisper package not installed"
                            sys.stdout.write(f"{Fore.YELLOW}  >> Skipping local transcription: whisper library not installed.\n")
                            sys.stdout.flush()
                        else:
                            try:
                                stt_result = transcribe_audio(extracted_audio_path)
                                transcript_text = stt_result["transcript"]
                                duration_sec = stt_result["duration"]
                                lang_code = stt_result["language"]
                                transcription_status = stt_result["status"]
                                if stt_result["status"] == "Success":
                                    sys.stdout.write(f"{Fore.GREEN}  >> Transcribed: \"{transcript_text[:40]}...\" ({duration_sec}s)\n")
                                else:
                                    sys.stdout.write(f"{Fore.RED}  >> Transcription Failed: {stt_result['status']}\n")
                                sys.stdout.flush()
                            except Exception as e:
                                transcription_status = f"Failed: {str(e)}"
                                sys.stdout.write(f"{Fore.RED}  >> Error: {str(e)}\n")
                                sys.stdout.flush()
                                logger.error(f"Error during audio transcription pipeline: {e}")
                                
                        # Delete temp file
                        try:
                            os.remove(extracted_audio_path)
                        except Exception as e:
                            logger.debug(f"Failed to delete temp file {extracted_audio_path}: {e}")
                    else:
                        transcription_status = "Failed: Audio File Missing"
                        sys.stdout.write(f"{Fore.RED}  >> Failed: Audio file {audio_filename} missing from input source.\n")
                        sys.stdout.flush()
                    
                    # Rules: Transcript becomes Raw Content and apply local terminology auto-corrections
                    corrected_transcript = correct_steel_terminology(transcript_text)
                    
                    # VERY IMPORTANT: If transcription was successful, we write the transcript_text itself.
                    # We ONLY use the fallback label [Voice Message: ...] if the transcription failed or package is not installed.
                    if transcription_status == "Success" and transcript_text:
                        content_for_hash = corrected_transcript
                    else:
                        content_for_hash = f"[Voice Message: {audio_filename}]"
                        
                    source_val = "Voice"
                else:
                    # Regular text message
                    # Apply local terminology auto-corrections to text messages!
                    corrected_text = correct_steel_terminology(msg["content"])
                    content_for_hash = corrected_text
                    source_val = "Text"
                    transcription_status = "N/A"
                
                # SHA-256 Duplicate Check
                msg_hash = generate_message_hash(msg["date"], msg["time"], msg["sender"], content_for_hash)
                if msg_hash in existing_hashes:
                    duplicate_msg += 1
                    continue
                    
                # Generate unique ID
                msg_id = uuid.uuid4().hex
                
                # Perform AI Node1 text optimization on-the-fly
                optimized_text = ""
                if content_for_hash and len(content_for_hash.strip()) >= 2:
                    optimized_text = call_ai_editor(content_for_hash)
                    # Polite rate-limiting between API calls
                    time.sleep(0.5)

                # Build Row according to dynamic column mapping
                row_data = [""] * max_cols
                row_data[mapping["ID"] - 1] = msg_id
                row_data[mapping["Date"] - 1] = msg["date"]
                row_data[mapping["Time"] - 1] = msg["time"]
                row_data[mapping["Created By"] - 1] = msg["sender"]
                row_data[mapping["Raw Content"] - 1] = content_for_hash
                row_data[mapping["Normalized Content"] - 1] = normalize_text(content_for_hash)
                row_data[mapping["Message Hash"] - 1] = msg_hash
                row_data[mapping["Import Timestamp"] - 1] = import_time
                row_data[mapping["Source"] - 1] = source_val
                
                # AI Optimized columns
                row_data[mapping["Transcription"] - 1] = optimized_text
                row_data[mapping["Status"] - 1] = "node1" if optimized_text else ""
                
                # Voice metadata fields
                row_data[mapping["Audio File"] - 1] = audio_filename if audio_filename else ""
                row_data[mapping["Duration"] - 1] = duration_sec if is_voice else ""
                row_data[mapping["Transcript"] - 1] = transcript_text if is_voice else ""
                row_data[mapping["Language"] - 1] = lang_code if is_voice else ""
                row_data[mapping["Transcription Status"] - 1] = transcription_status
                
                # Enrich optional fields
                if "Last Update" in mapping:
                    row_data[mapping["Last Update"] - 1] = import_time
                    
                # Maintain the message queue strictly chronologically
                rows_to_insert.append(row_data)
                existing_hashes.add(msg_hash)
                
            # Finish progress indicator
            sys.stdout.write(f"\r{Fore.GREEN}Progress: 100% ({total_msg}/{total_msg}) | Complete!                      \n")
            sys.stdout.flush()
            print(Fore.WHITE + "--------------------------------------------------")
            
            # Perform Batch Insert if we have new rows
            if rows_to_insert:
                logger.info(f"Inserting {len(rows_to_insert)} new records into '{SHEET_NAME}' worksheet...")
                sheet.append_rows(rows_to_insert, value_input_option='USER_ENTERED')
                imported_msg = len(rows_to_insert)
                logger.info(Fore.GREEN + f"Batch insert completed successfully!")
            else:
                logger.info(Fore.YELLOW + "No new records to import. All items in this file were duplicates/filtered.")
                
            # Move file to processed folder
            shutil.move(file_path, os.path.join(PROCESSED_DIR, file_name))
            logger.info(Fore.GREEN + f"Moved successfully: {file_name} -> /processed")
            
        except Exception as e:
            errors_in_file = 1
            logger.error(Fore.RED + f"Error processing file {file_name}: {e}")
            try:
                shutil.move(file_path, os.path.join(FAILED_DIR, file_name))
                logger.info(Fore.RED + f"Moved file to failed folder: {file_name} -> /failed")
            except Exception as move_err:
                logger.error(Fore.RED + f"Failed to move file to /failed: {move_err}")
                
        # Write Processing Report inside /logs
        report_filename = f"report_{os.path.splitext(file_name)[0]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        report_filepath = os.path.join(LOGS_DIR, report_filename)
        with open(report_filepath, 'w', encoding='utf-8') as report_f:
            report_f.write("=== WHATSAPP IMPORT PROCESS REPORT (Phase 2) ===\n")
            report_f.write(f"File Name: {file_name}\n")
            report_f.write(f"Processed Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            report_f.write(f"Total Messages in File: {total_msg}\n")
            report_f.write(f"Imported Records: {imported_msg}\n")
            report_f.write(f"Duplicate Messages Skipped: {duplicate_msg}\n")
            report_f.write(f"Errors Occurred: {'Yes' if errors_in_file else 'No'}\n")
            
        print(Fore.GREEN + Style.BRIGHT + f"\nSummary for {file_name}:")
        print(f" - Total items: {total_msg}")
        print(f" - Imported: {imported_msg}")
        print(f" - Duplicates skipped: {duplicate_msg}")
        print(f" - Errors: {errors_in_file}")
        print("-" * 46)

if __name__ == "__main__":
    process_files()
