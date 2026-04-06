# Job/Internship Bulk Email Sender

Automate internship/job outreach in a simple and controlled way.

Instead of manually sending emails one by one, this project reads recipients from `emails.csv`, builds an email for each row, attaches your resume, and sends it with safe fallbacks and logging.

---

## Project Idea

### Problem
A student wants to apply to many companies. Sending the same email manually to every HR address is repetitive, slow, and error-prone.

### Solution
This script automates the process:
1. Read emails from a CSV file
2. Read your introduction text from a template file
3. Use row-specific company/subject/name when provided
4. Handle missing values with defaults
5. Send one email at a time with your resume attached
6. Track everything in a log file

---

## Features

- ✅ Read recipients from `emails.csv`
- ✅ Supports columns: `email`, `name`, `company`, `subject`
- ✅ Handles empty `name/company/subject` with fallback values
- ✅ Validates email format
- ✅ Deduplicates duplicate emails
- ✅ Attaches resume file (`resume.pdf` by default)
- ✅ `--dry-run` mode to preview without sending
- ✅ Delay between emails to reduce spam risk
- ✅ CSV log output (`sent_log.csv`)

---

## File Structure

```bash
.
├── main.py
├── .env.example
├── emails.csv
├── intro.txt
├── requirements.txt
└── README.md
```

> You should add your own `resume.pdf` file in the same folder (or pass a custom path with `--resume`).

---

## Setup Instructions

## 1) Install dependencies

```bash
pip3 install -r requirements.txt
```

## 2) Create your environment file

Copy `.env.example` to `.env` and fill in your real SMTP credentials.

```bash
cp .env.example .env
```

Edit `.env` values:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=your_email@gmail.com
SMTP_PASSWORD=your_app_password
SENDER_EMAIL=your_email@gmail.com
USE_TLS=true

DEFAULT_SUBJECT=Internship Application - your name 
DEFAULT_COMPANY=your company
DEFAULT_NAME=Hiring Team

SEND_DELAY_SECONDS=3
MAX_EMAILS_PER_RUN=
LOG_FILE=sent_log.csv
```

### Gmail note
Use an **App Password** (not your normal password) if your provider requires it.

---

## 3) Prepare input files

### `emails.csv`

Use this header:

```csv
email,name,company,subject
hr@company1.com,Recruitment Team,Company 1,Application for Internship - Mohamed Bougaydane
jobs@company2.com,,Company 2,
talent@company3.com,HR Team,,
```

### `intro.txt`

Template with optional placeholders:
- `{name}`
- `{company}`
- `{email}`

Example:

```txt
Hello {name},

My name is Mohamed Bougaydane, and I am a software engineering student currently looking for an internship opportunity.
I am very interested in {company} and would be glad to contribute.

Please find my resume attached.
```

### `resume.pdf`

Place your real resume file in the project root.

---

## How It Works (Logic)

For each row in `emails.csv`:

1. Validate `email`
   - If empty/invalid → skip and log.
2. Resolve fallback values:
   - `subject`: row subject → `DEFAULT_SUBJECT` → hardcoded fallback
   - `company`: row company → `DEFAULT_COMPANY` → `"your company"`
   - `name`: row name → `DEFAULT_NAME` → `"Hiring Team"`
3. Build email body from `intro.txt`
4. Attach `resume.pdf`
5. Send via SMTP (or preview in dry-run)
6. Write status into `sent_log.csv`

---

## Usage

## Send emails to all recipients (easy mode)

```bash
python3 main.py
```

This sends to all valid emails found in `emails.csv`.

## Optional preview mode

```bash
python3 main.py --dry-run
```

## Useful flags

```bash
python3 main.py --dry-run --limit 5 --delay 2
python3 main.py --csv contacts.csv --intro message.txt --resume my_cv.pdf
python3 main.py --log outreach_log.csv
```

---

## Output Log

The script creates/updates a CSV log (default `sent_log.csv`) with:

- timestamp
- email
- company
- subject
- status (`SENT`, `DRY_RUN`, `SKIPPED`, `FAILED`)
- reason
- dry_run

---

## Safety & Best Practices

- Use `--dry-run` before real sends
- Start with a small `--limit` (e.g., 3)
- Keep delay between emails (2–5 seconds)
- Send only to relevant professional contacts
- Respect provider anti-spam limits and local regulations

---

## Quick Start Checklist

1. `pip3 install -r requirements.txt`
2. `cp .env.example .env` and fill credentials
3. Add your `resume.pdf`
4. Update `emails.csv`
5. Update `intro.txt`
6. Run `python3 main.py`
