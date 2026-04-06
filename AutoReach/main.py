#!/usr/bin/env python3
"""
Bulk internship/job outreach sender.

Reads recipients from a CSV file and sends one email per row with:
- Per-row fallback logic for subject/company/name
- Intro text loaded from a template file
- Resume attachment
- Dry-run support
- CSV logging for sent/skipped/failed rows
"""

from __future__ import annotations

import argparse
import csv
import mimetypes
import os
import re
import socket
import smtplib
import ssl
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import certifi
from dotenv import load_dotenv


EMAIL_REGEX = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
HARD_DEFAULT_SUBJECT = "Internship Application - Mohamed Bougaydane"
HARD_DEFAULT_COMPANY = "your company"
HARD_DEFAULT_NAME = "Hiring Team"


@dataclass
class AppConfig:
    smtp_host: str
    smtp_port: int
    smtp_username: str
    smtp_password: str
    sender_email: str
    use_tls: bool
    ssl_ca_bundle: Optional[Path]
    default_subject: str
    default_company: str
    default_name: str
    delay_seconds: float
    max_emails_per_run: Optional[int]
    log_file: Path


class SafeDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send internship/job application emails from a CSV file."
    )
    parser.add_argument(
        "--csv",
        dest="csv_path",
        default="emails.csv",
        help="Path to recipients CSV file (default: emails.csv)",
    )
    parser.add_argument(
        "--intro",
        dest="intro_path",
        default="intro.txt",
        help="Path to intro template text file (default: intro.txt)",
    )
    parser.add_argument(
        "--resume",
        dest="resume_path",
        default="resume.pdf",
        help="Path to resume attachment (default: resume.pdf)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview actions without sending emails",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum emails to attempt in this run",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=None,
        help="Delay in seconds between sends",
    )
    parser.add_argument(
        "--log",
        dest="log_path",
        default=None,
        help="Path to CSV log file (default from .env or sent_log.csv)",
    )
    return parser.parse_args()


def is_valid_email(value: str) -> bool:
    return bool(EMAIL_REGEX.match(value.strip()))


def to_bool(value: str, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def load_config(args: argparse.Namespace) -> AppConfig:
    load_dotenv()

    smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587").strip())
    smtp_username = os.getenv("SMTP_USERNAME", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()
    sender_email = os.getenv("SENDER_EMAIL", smtp_username).strip()

    if not smtp_username or not smtp_password or not sender_email:
        raise ValueError(
            "Missing SMTP credentials. Set SMTP_USERNAME, SMTP_PASSWORD, and SENDER_EMAIL in .env"
        )

    default_subject = os.getenv("DEFAULT_SUBJECT", HARD_DEFAULT_SUBJECT).strip() or HARD_DEFAULT_SUBJECT
    default_company = os.getenv("DEFAULT_COMPANY", HARD_DEFAULT_COMPANY).strip() or HARD_DEFAULT_COMPANY
    default_name = os.getenv("DEFAULT_NAME", HARD_DEFAULT_NAME).strip() or HARD_DEFAULT_NAME

    use_tls = to_bool(os.getenv("USE_TLS", "true"), default=True)
    ssl_ca_bundle_value = os.getenv("SSL_CA_BUNDLE", "").strip()
    ssl_ca_bundle = Path(ssl_ca_bundle_value) if ssl_ca_bundle_value else None

    env_delay = os.getenv("SEND_DELAY_SECONDS", "3")
    delay_seconds = args.delay if args.delay is not None else float(env_delay)

    env_max = os.getenv("MAX_EMAILS_PER_RUN", "").strip()
    max_emails_per_run = args.limit if args.limit is not None else (int(env_max) if env_max else None)

    log_file_value = args.log_path or os.getenv("LOG_FILE", "sent_log.csv")
    log_file = Path(log_file_value)

    return AppConfig(
        smtp_host=smtp_host,
        smtp_port=smtp_port,
        smtp_username=smtp_username,
        smtp_password=smtp_password,
        sender_email=sender_email,
        use_tls=use_tls,
        ssl_ca_bundle=ssl_ca_bundle,
        default_subject=default_subject,
        default_company=default_company,
        default_name=default_name,
        delay_seconds=delay_seconds,
        max_emails_per_run=max_emails_per_run,
        log_file=log_file,
    )


def read_intro_template(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Intro template not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def read_recipients(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Recipients CSV not found: {path}")

    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError("CSV appears empty or missing header row.")

        lower_fields = {name.lower() for name in reader.fieldnames}
        if "email" not in lower_fields:
            raise ValueError("CSV must contain at least an 'email' column.")

        rows: List[Dict[str, str]] = []
        for row in reader:
            normalized = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k is not None}
            rows.append(normalized)

    return rows


def dedupe_by_email(rows: Iterable[Dict[str, str]]) -> List[Dict[str, str]]:
    deduped: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        email = row.get("email", "").strip().lower()
        if not email:
            # Keep empty-email rows so they can be logged as SKIPPED later.
            deduped.append(row)
            continue

        if email in seen:
            continue

        seen.add(email)
        deduped.append(row)
    return deduped


def render_body(intro_template: str, name: str, company: str, email: str) -> str:
    placeholders = SafeDict(name=name, company=company, email=email)
    rendered_intro = intro_template.format_map(placeholders)
    return rendered_intro


def choose_subject(row: Dict[str, str], cfg: AppConfig) -> str:
    return row.get("subject", "").strip() or cfg.default_subject or HARD_DEFAULT_SUBJECT


def choose_company(row: Dict[str, str], cfg: AppConfig) -> str:
    return row.get("company", "").strip() or cfg.default_company or HARD_DEFAULT_COMPANY


def choose_name(row: Dict[str, str], cfg: AppConfig) -> str:
    return row.get("name", "").strip() or cfg.default_name or HARD_DEFAULT_NAME


def attach_file(message: EmailMessage, file_path: Path) -> None:
    if not file_path.exists():
        raise FileNotFoundError(f"Resume file not found: {file_path}")

    mime_type, _ = mimetypes.guess_type(str(file_path))
    if mime_type:
        maintype, subtype = mime_type.split("/", 1)
    else:
        maintype, subtype = "application", "octet-stream"

    with file_path.open("rb") as f:
        message.add_attachment(
            f.read(),
            maintype=maintype,
            subtype=subtype,
            filename=file_path.name,
        )


def build_message(
    *,
    sender_email: str,
    recipient_email: str,
    subject: str,
    body: str,
    resume_path: Path,
) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = sender_email
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.set_content(body)
    attach_file(msg, resume_path)
    return msg


def ensure_log_header(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)

    if log_file.exists() and log_file.stat().st_size > 0:
        return

    with log_file.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "timestamp",
            "email",
            "company",
            "subject",
            "status",
            "reason",
            "dry_run",
        ])


def write_log(
    log_file: Path,
    *,
    email: str,
    company: str,
    subject: str,
    status: str,
    reason: str,
    dry_run: bool,
) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)

    with log_file.open("a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                datetime.now().isoformat(timespec="seconds"),
                email,
                company,
                subject,
                status,
                reason,
                str(dry_run),
            ]
        )


def create_tls_context(cfg: AppConfig) -> ssl.SSLContext:
    cafile = str(cfg.ssl_ca_bundle) if cfg.ssl_ca_bundle else certifi.where()
    if cfg.ssl_ca_bundle and not cfg.ssl_ca_bundle.exists():
        raise FileNotFoundError(f"SSL_CA_BUNDLE file not found: {cfg.ssl_ca_bundle}")
    return ssl.create_default_context(cafile=cafile)


def maybe_connect_smtp(cfg: AppConfig, dry_run: bool):
    if dry_run:
        return None

    try:
        server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30)
        server.ehlo()
        if cfg.use_tls:
            context = create_tls_context(cfg)
            server.starttls(context=context)
            server.ehlo()
        server.login(cfg.smtp_username, cfg.smtp_password)
        return server
    except smtplib.SMTPAuthenticationError as exc:
        raise RuntimeError(
            "SMTP authentication failed. Check SMTP_USERNAME and SMTP_PASSWORD (for Gmail, use an App Password)."
        ) from exc
    except (ssl.SSLCertVerificationError, ssl.SSLError) as exc:
        raise RuntimeError(
            "SSL/TLS certificate verification failed while connecting to SMTP. "
            "If you are behind a corporate/school proxy, export its root certificate and set SSL_CA_BUNDLE in .env. "
            "Otherwise, verify your local certificate store and Python installation."
        ) from exc
    except (socket.timeout, TimeoutError) as exc:
        raise RuntimeError(
            f"SMTP connection timed out to {cfg.smtp_host}:{cfg.smtp_port}. "
            "Check your internet connection, firewall, VPN/proxy, or try another network."
        ) from exc
    except smtplib.SMTPException as exc:
        raise RuntimeError(f"SMTP error while connecting/sending: {exc}") from exc


def process_recipients(
    rows: List[Dict[str, str]],
    *,
    cfg: AppConfig,
    intro_template: str,
    resume_path: Path,
    dry_run: bool,
) -> Tuple[int, int, int]:
    sent = 0
    skipped = 0
    failed = 0

    attempted = 0
    limit = cfg.max_emails_per_run

    smtp_server = None
    try:
        smtp_server = maybe_connect_smtp(cfg, dry_run)

        for row in rows:
            email = row.get("email", "").strip()

            if limit is not None and attempted >= limit:
                break

            if not email:
                skipped += 1
                write_log(
                    cfg.log_file,
                    email="",
                    company="",
                    subject="",
                    status="SKIPPED",
                    reason="Missing email",
                    dry_run=dry_run,
                )
                continue

            if not is_valid_email(email):
                skipped += 1
                write_log(
                    cfg.log_file,
                    email=email,
                    company=row.get("company", ""),
                    subject=row.get("subject", ""),
                    status="SKIPPED",
                    reason="Invalid email format",
                    dry_run=dry_run,
                )
                continue

            company = choose_company(row, cfg)
            subject = choose_subject(row, cfg)
            name = choose_name(row, cfg)
            body = render_body(intro_template, name=name, company=company, email=email)

            attempted += 1

            try:
                message = build_message(
                    sender_email=cfg.sender_email,
                    recipient_email=email,
                    subject=subject,
                    body=body,
                    resume_path=resume_path,
                )

                if dry_run:
                    print(f"[DRY RUN] Would send to {email} | subject='{subject}' | company='{company}'")
                else:
                    assert smtp_server is not None
                    smtp_server.send_message(message)
                    print(f"[SENT] {email}")

                sent += 1
                write_log(
                    cfg.log_file,
                    email=email,
                    company=company,
                    subject=subject,
                    status="SENT" if not dry_run else "DRY_RUN",
                    reason="",
                    dry_run=dry_run,
                )
            except Exception as exc:
                failed += 1
                write_log(
                    cfg.log_file,
                    email=email,
                    company=company,
                    subject=subject,
                    status="FAILED",
                    reason=str(exc),
                    dry_run=dry_run,
                )
                print(f"[FAILED] {email} -> {exc}")

            if cfg.delay_seconds > 0 and (limit is None or attempted < limit):
                time.sleep(cfg.delay_seconds)
    finally:
        if smtp_server is not None:
            smtp_server.quit()

    return sent, skipped, failed


def main() -> int:
    args = parse_args()

    try:
        cfg = load_config(args)
        recipients = read_recipients(Path(args.csv_path))
        recipients = dedupe_by_email(recipients)

        intro_template = read_intro_template(Path(args.intro_path))
        resume_path = Path(args.resume_path)

        ensure_log_header(cfg.log_file)

        print(f"Loaded {len(recipients)} unique recipient(s).")
        if cfg.max_emails_per_run is not None:
            print(f"Run limit: {cfg.max_emails_per_run} email(s)")
        print(f"Dry run: {args.dry_run}")

        sent, skipped, failed = process_recipients(
            recipients,
            cfg=cfg,
            intro_template=intro_template,
            resume_path=resume_path,
            dry_run=args.dry_run,
        )

        print("\n=== Summary ===")
        print(f"Sent/previewed: {sent}")
        print(f"Skipped: {skipped}")
        print(f"Failed: {failed}")
        print(f"Log file: {cfg.log_file}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
