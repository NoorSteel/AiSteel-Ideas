# AiSteel WhatsApp to Google Sheets Importer (Phase 2 - Voice Messages)

A local Python application designed to import exported WhatsApp group chat text logs and **voice messages (on-the-fly local transcription using Whisper)** into Google Sheets. It automatically handles Farsi (Persian) text, preserves message order, prevents duplicate insertions, maps columns dynamically, and moves files gracefully through a pipeline.

---

## Folder Structure

```text
AiSteel-bot/
├── input/                 # PLACE YOUR EXPORTED WHATSAPP .txt OR .zip FILES HERE
├── processed/             # Files successfully imported are automatically moved here
├── failed/                # Files that encountered parsing or API errors are moved here
├── logs/                  # Standard logs (.log) and process reports (.txt) are saved here
├── temp_audio/            # Created dynamically during audio extraction and cleaned up after
├── credentials.json       # Service Account credentials file (Download from Google Cloud)
├── main.py                # Main executable python script
├── requirements.txt       # Project python dependencies
└── README.md              # Documentation and instructions
```

---

## Requirements & Local Whisper Setup

To run local speech-to-text transcription, you must have Python 3.8+ and **`ffmpeg`** installed on your system.

### 1. Install System ffmpeg (Required by Whisper)
Whisper relies on `ffmpeg` to process audio files.
* **Option A (Highly Recommended - via Chocolatey)**:
  Open PowerShell as Administrator and run:
  ```powershell
  choco install ffmpeg
  ```
* **Option B (Manual)**:
  1. Download the `ffmpeg` Windows build from [Gyan.dev](https://www.gyan.dev/ffmpeg/builds/).
  2. Extract the folder to a permanent location (e.g., `C:\ffmpeg`).
  3. Add the `C:\ffmpeg\bin` directory to your Windows System environment variable **`PATH`**.
  4. Restart your terminal and verify by running:
     ```powershell
     ffmpeg -version
     ```

### 2. Install Python Dependencies
Install the required libraries (including `openai-whisper` and PyTorch dependencies):
```powershell
python -m pip install -r requirements.txt
```
> **Note**: The first time you run a voice note transcription, Whisper will automatically download the `"medium"` language model (~1.5GB) to your local cache folder for superior Farsi accuracy. If you configure it to `"large"` in `main.py`, it will download a ~3.0GB model.

---

## Google Sheets & Service Account Setup

To allow the script to write message data to your Google Sheet, you must set up a Google Cloud Service Account and download its credential key.

### 1. Create a Service Account on Google Cloud Console
1. Open the [Google Cloud Console](https://console.cloud.google.com/).
2. Select your project (ensure you select **`No Organization`** when creating a project to avoid policy restrictions, or disable the `iam.disableServiceAccountKeyCreation` policy).
3. Enable the **Google Sheets API** and **Google Drive API** in the API Library.
4. Go to **IAM & Admin** > **Service Accounts** and click **Create Service Account**.
5. Give it a name and click **Done**.

### 2. Download Key (credentials.json)
1. On the **Service Accounts** page, click your newly created account.
2. Navigate to the **Keys** tab at the top.
3. Click **Add Key** > **Create New Key**.
4. Select **JSON** format and click **Create**.
5. Save the downloaded JSON file into the **`AiSteel-bot`** project folder and rename it exactly to **`credentials.json`**.

### 3. Share the Google Sheet
1. Open your target Google Sheet: [AiSteel Spreadsheet](https://docs.google.com/spreadsheets/d/19C4vdoFIlMQGhAyUmYjaoSatU-jQPy4BJIpoXbMZkEM/edit)
2. Copy the **Service Account Email** address (from your `credentials.json` file under `client_email`, e.g., `aisteel@aisteel-497807.iam.gserviceaccount.com`).
3. Click the **Share** button in the top-right corner of the Google Sheet page.
4. Paste the Service Account Email address, grant it the **Editor** permission, and click **Share**.

---

## How to Run the Script

1. **Export Chat**: Export your WhatsApp group chat as a `.zip` file (which includes media).
2. **Input File**: Copy the exported `.zip` file directly into the `/input` folder of the project.
3. **Execute Pipeline**: Run the script:
   ```powershell
   python main.py
   ```

### What Happens Behind the Scenes?
* **File Processing**: The script dynamically scans `/input` for `.txt` or `.zip` files.
* **ZIP Auto-extraction**: It extracts the chat log (`_chat.txt`) and locates the specific voice files (e.g. `.opus` or `.wav`) on-the-fly into a `temp_audio/` folder, cleaning them up after transcription.
* **Steel-primed Local STT**: It loads the OpenAI Whisper model locally and uses a customized prompt to transcribe Persian & English mixed steel industry terms (e.g. *میلگرد، تیرآهن، متالورژی، ریخته‌گری، استارتاپ*).
* **Metadata Extraction**: Calculates the duration based on segment timestamps and auto-detects the spoken language.
* **Sheets Update**:
  - The script maps columns dynamically and appends the new fields to your headers:
    - **`Source`**: `"Voice"` (for voice messages) or `"Text"` (for text).
    - **`Audio File`**: Filename of the audio file.
    - **`Duration`**: Length of the audio in seconds.
    - **`Transcript`**: Local transcribed text.
    - **`Language`**: Language code (`fa`).
    - **`Transcription Status`**: `"Success"` or `"Failed"`.
  - The voice transcript automatically populates the **`Raw Content`** column, and the message duplicate check works seamlessly!
