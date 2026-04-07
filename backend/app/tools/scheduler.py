"""
Reminder Scheduler — fires saved reminders at the right time.

Uses APScheduler (lightweight, no Redis needed).
Reminders are stored in SQLite by the tools/manager.py `reminder` tool.
This module polls the DB every 30 seconds and fires any due reminders
by pushing them to all active WebSocket connections.
"""
import asyncio
import logging
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("jarvis.scheduler")


class ReminderScheduler:
    """Polls SQLite for due reminders and fires a callback."""

    def __init__(self, db_path: Path, on_reminder: Callable[[str], None]):
        self.db_path = db_path
        self.on_reminder = on_reminder
        self._task: Optional[asyncio.Task] = None
        self._init_db()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id         INTEGER PRIMARY KEY,
                text       TEXT    NOT NULL,
                due_at     TEXT,
                created_at TEXT    NOT NULL,
                triggered  INTEGER DEFAULT 0
            )
        """)
        conn.commit()
        conn.close()

    async def start(self):
        """Start background polling loop."""
        self._task = asyncio.create_task(self._poll_loop())
        logger.info("Reminder scheduler started")

    def stop(self):
        if self._task:
            self._task.cancel()

    async def _poll_loop(self):
        while True:
            try:
                await asyncio.sleep(30)  # check every 30 seconds
                self._check_and_fire()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler poll error: {e}")

    def _check_and_fire(self):
        conn = sqlite3.connect(self.db_path)
        now = datetime.now()

        rows = conn.execute(
            "SELECT id, text, due_at FROM reminders WHERE triggered=0"
        ).fetchall()

        for row_id, text, due_at in rows:
            should_fire = False

            if due_at:
                try:
                    due = datetime.fromisoformat(due_at)
                    should_fire = now >= due
                except ValueError:
                    pass
            else:
                # Try to parse time hints from the reminder text
                due = self._parse_time_from_text(text, now)
                if due and now >= due:
                    should_fire = True
                    # Save parsed due_at for future reference
                    conn.execute(
                        "UPDATE reminders SET due_at=? WHERE id=?",
                        (due.isoformat(), row_id)
                    )

            if should_fire:
                logger.info(f"Firing reminder: {text}")
                conn.execute(
                    "UPDATE reminders SET triggered=1 WHERE id=?", (row_id,)
                )
                self.on_reminder(f"Reminder: {text}")

        conn.commit()
        conn.close()

    def _parse_time_from_text(
        self, text: str, now: datetime
    ) -> Optional[datetime]:
        """
        Very simple NLP for time hints embedded in reminder text.
        Examples:
          "remind me in 10 minutes to call John"
          "remind me at 3pm to take medicine"
          "remind me tomorrow at 9am for standup"
        """
        text_l = text.lower()

        # "in X minutes/hours"
        m = re.search(r"in\s+(\d+)\s+(minute|min|hour|hr)", text_l)
        if m:
            amount = int(m.group(1))
            unit = m.group(2)
            if "hour" in unit or "hr" in unit:
                return now + timedelta(hours=amount)
            return now + timedelta(minutes=amount)

        # "at HH:MM" or "at 3pm"
        m = re.search(r"at\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", text_l)
        if m:
            hour = int(m.group(1))
            minute = int(m.group(2) or 0)
            ampm = m.group(3)
            if ampm == "pm" and hour != 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if target < now:
                target += timedelta(days=1)  # next occurrence
            return target

        # "tomorrow"
        if "tomorrow" in text_l:
            return now.replace(hour=9, minute=0, second=0) + timedelta(days=1)

        return None

    def add_reminder(self, text: str, due_at: Optional[datetime] = None):
        """Programmatically add a reminder (used by tools/manager.py)."""
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "INSERT INTO reminders (text, due_at, created_at) VALUES (?,?,?)",
            (text, due_at.isoformat() if due_at else None, datetime.now().isoformat())
        )
        conn.commit()
        conn.close()
