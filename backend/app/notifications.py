"""
Mock notification service – Telegram Bot & Email SMTP alert triggers.
In production these would use real API keys; here we log and return success.
"""

import json
from datetime import datetime
from app.database import SessionLocal, AlertLog


async def send_telegram_alert(chat_id: str, message: str) -> dict:
    """Mock Telegram Bot API call."""
    db = SessionLocal()
    log = AlertLog(
        channel="telegram",
        recipient=chat_id,
        message=message,
        sent_at=datetime.utcnow(),
        success=True,
    )
    db.add(log)
    db.commit()
    log_id = log.id
    db.close()

    print(f"[TELEGRAM mock] -> {chat_id}: {message[:80]}...")
    return {
        "ok": True,
        "channel": "telegram",
        "chat_id": chat_id,
        "message_preview": message[:120],
        "log_id": log_id,
    }


async def send_email_alert(to_email: str, subject: str, body: str) -> dict:
    """Mock SMTP email send."""
    db = SessionLocal()
    log = AlertLog(
        channel="email",
        recipient=to_email,
        message=f"Subject: {subject}\n\n{body}",
        sent_at=datetime.utcnow(),
        success=True,
    )
    db.add(log)
    db.commit()
    log_id = log.id
    db.close()

    print(f"[EMAIL mock] -> {to_email}: {subject}")
    return {
        "ok": True,
        "channel": "email",
        "to": to_email,
        "subject": subject,
        "log_id": log_id,
    }


def get_alert_history(limit: int = 50) -> list:
    db = SessionLocal()
    logs = db.query(AlertLog).order_by(AlertLog.sent_at.desc()).limit(limit).all()
    result = [
        {
            "id": l.id,
            "channel": l.channel,
            "recipient": l.recipient,
            "message": l.message[:200],
            "sent_at": l.sent_at.isoformat(),
            "success": l.success,
        }
        for l in logs
    ]
    db.close()
    return result
