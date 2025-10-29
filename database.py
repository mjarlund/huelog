"""Database management for Hue Event Logger."""
import sqlite3
import json
import structlog
from typing import List, Dict, Any, Optional
from contextlib import contextmanager
from config import config

logger = structlog.get_logger(__name__)


class HueDatabase:
    """Manages SQLite database operations for Hue events and diagnostics."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.db_path
        self.init_db()

    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def init_db(self):
        """Initialize database tables."""
        with self.get_connection() as conn:
            cur = conn.cursor()

            # Events table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts TEXT NOT NULL,
                    rid TEXT,
                    rtype TEXT,
                    raw TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")

            # Devices catalog
            cur.execute("""
                CREATE TABLE IF NOT EXISTS devices(
                    rid TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    type TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )""")

            # Diagnostics table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS diag(
                    rid TEXT NOT NULL,
                    day TEXT NOT NULL,
                    disconnects INTEGER NOT NULL DEFAULT 0,
                    minutes_unreachable INTEGER NOT NULL DEFAULT 0,
                    last_seen_ts TEXT,
                    battery_low INTEGER NOT NULL DEFAULT 0,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (rid, day)
                )""")

            # Add indexes for better performance
            cur.execute("CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_events_rid ON events(rid)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_events_rtype ON events(rtype)")
            cur.execute("CREATE INDEX IF NOT EXISTS idx_diag_day ON diag(day)")

            conn.commit()
            logger.info("Database initialized successfully")

    def insert_event(self, ts: str, rid: str, rtype: str, raw_obj: Dict[str, Any]):
        """Insert a new event into the database."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO events(ts, rid, rtype, raw) VALUES(?,?,?,?)",
                (ts, rid, rtype, json.dumps(raw_obj))
            )
            conn.commit()

    def get_events(self, query: str = None, limit: int = 200) -> List[sqlite3.Row]:
        """Retrieve events with optional filtering."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            if query:
                cur.execute("""
                    SELECT ts, rid, rtype, raw FROM events
                    WHERE raw LIKE ? OR rid LIKE ? OR rtype LIKE ?
                    ORDER BY id DESC LIMIT ?
                """, (f"%{query}%", f"%{query}%", f"%{query}%", limit))
            else:
                cur.execute("""
                    SELECT ts, rid, rtype, raw FROM events
                    ORDER BY id DESC LIMIT ?
                """, (limit,))
            return cur.fetchall()

    def get_events_since_id(self, last_id: int) -> List[sqlite3.Row]:
        """Get events since a specific ID for live-streaming."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT id, ts, rid, rtype, raw FROM events
                WHERE id > ? ORDER BY id
            """, (last_id,))
            return cur.fetchall()

    def get_max_event_id(self) -> int:
        """Get the maximum event ID."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COALESCE(MAX(id), 0) FROM events")
            return cur.fetchone()[0]

    def upsert_device(self, rid: str, name: str, device_type: str):
        """Insert or update device information."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO devices(rid, name, type, updated_at)
                VALUES(?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(rid) DO UPDATE SET 
                    name=excluded.name, 
                    type=excluded.type,
                    updated_at=CURRENT_TIMESTAMP
            """, (rid, name, device_type))
            conn.commit()

    def get_device_info(self, rid: str) -> Optional[Dict[str, Any]]:
        """Get device information by resource ID."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT rid, name, type, updated_at 
                FROM devices 
                WHERE rid = ?
            """, (rid,))
            row = cur.fetchone()

            if row:
                return {
                    "rid": row["rid"],
                    "name": row["name"],
                    "type": row["type"],
                    "updated_at": row["updated_at"]
                }
            return None

    def update_device_last_seen(self, rid: str, ts: str, day: str):
        """Update the last seen timestamp for a device."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO diag(rid, day, last_seen_ts, updated_at)
                VALUES(?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(rid, day) DO UPDATE SET 
                    last_seen_ts=excluded.last_seen_ts,
                    updated_at=CURRENT_TIMESTAMP
            """, (rid, day, ts))
            conn.commit()

    def increment_disconnects(self, rid: str, day: str):
        """Increment disconnect count for a device."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO diag(rid, day, disconnects, updated_at)
                VALUES(?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(rid, day) DO UPDATE SET 
                    disconnects = disconnects + 1,
                    updated_at = CURRENT_TIMESTAMP
            """, (rid, day))
            conn.commit()

    def add_unreachable_minutes(self, rid: str, day: str, minutes: int):
        """Add unreachable minutes for a device."""
        if minutes <= 0:
            return

        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO diag(rid, day, minutes_unreachable, updated_at)
                VALUES(?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(rid, day) DO UPDATE SET 
                    minutes_unreachable = minutes_unreachable + ?,
                    updated_at = CURRENT_TIMESTAMP
            """, (rid, day, int(minutes), int(minutes)))
            conn.commit()

    def set_battery_low(self, rid: str, day: str, is_low: bool):
        """Set battery low flag for a device."""
        if not is_low:
            return

        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO diag(rid, day, battery_low, updated_at)
                VALUES(?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(rid, day) DO UPDATE SET 
                    battery_low = MAX(battery_low, 1),
                    updated_at = CURRENT_TIMESTAMP
            """, (rid, day))
            conn.commit()

    def get_device_health(self, since: str) -> List[sqlite3.Row]:
        """Get device health statistics since a given date."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                SELECT d.rid,
                       COALESCE(dev.name, d.rid) AS name,
                       COALESCE(dev.type, 'device') AS type,
                       SUM(d.disconnects) AS disconnects,
                       SUM(d.minutes_unreachable) AS minutes_unreachable,
                       MAX(d.last_seen_ts) AS last_seen_ts,
                       MAX(d.battery_low) AS battery_low
                FROM diag d
                LEFT JOIN devices dev ON dev.rid = d.rid
                WHERE d.day >= ?
                GROUP BY d.rid
            """, (since,))
            return cur.fetchall()

    def cleanup_old_events(self, days_to_keep: int = 30):
        """Clean up old events to prevent database bloat."""
        with self.get_connection() as conn:
            cur = conn.cursor()
            cur.execute("""
                DELETE FROM events 
                WHERE created_at < datetime('now', '-{} days')
            """.format(days_to_keep))
            deleted = cur.rowcount
            conn.commit()
            logger.info("Cleaned up old events", deleted_count=deleted)
            return deleted
