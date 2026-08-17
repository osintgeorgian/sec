import aiosqlite
from pathlib import Path
from typing import Optional, List, Dict, Any
import json
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "data" / "carwatch.db"


async def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                tg_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                lat REAL,
                lng REAL,
                battery INTEGER,
                last_update TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS friends (
                user_id INTEGER,
                friend_id INTEGER,
                PRIMARY KEY (user_id, friend_id),
                FOREIGN KEY (user_id) REFERENCES users(tg_id),
                FOREIGN KEY (friend_id) REFERENCES users(tg_id)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS markers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lat REAL NOT NULL,
                lng REAL NOT NULL,
                note TEXT,
                marker_type TEXT DEFAULT 'custom',
                created_by INTEGER,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (created_by) REFERENCES users(tg_id)
            )
        """)
        await db.commit()


async def upsert_user(tg_id: int, username: str = None, first_name: str = None, last_name: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO users (tg_id, username, first_name, last_name)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(tg_id) DO UPDATE SET
                username = COALESCE(excluded.username, users.username),
                first_name = COALESCE(excluded.first_name, users.first_name),
                last_name = COALESCE(excluded.last_name, users.last_name)
        """, (tg_id, username, first_name, last_name))
        await db.commit()


async def update_location(tg_id: int, lat: float, lng: float, battery: int = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE users SET lat = ?, lng = ?, battery = ?, last_update = ?
            WHERE tg_id = ?
        """, (lat, lng, battery, datetime.utcnow().isoformat(), tg_id))
        await db.commit()


async def add_friend(user_id: int, friend_id: int) -> bool:
    if user_id == friend_id:
        return False
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT OR IGNORE INTO friends (user_id, friend_id) VALUES (?, ?)",
                (user_id, friend_id)
            )
            await db.execute(
                "INSERT OR IGNORE INTO friends (user_id, friend_id) VALUES (?, ?)",
                (friend_id, user_id)
            )
            await db.commit()
            return True
        except Exception:
            return False


async def get_friends(user_id: int) -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT u.tg_id, u.username, u.first_name, u.last_name,
                   u.lat, u.lng, u.battery, u.last_update
            FROM friends f
            JOIN users u ON u.tg_id = f.friend_id
            WHERE f.user_id = ?
        """, (user_id,))
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_friend_ids(user_id: int) -> List[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT friend_id FROM friends WHERE user_id = ?", (user_id,)
        )
        rows = await cursor.fetchall()
        return [r[0] for r in rows]


async def add_marker(lat: float, lng: float, note: str, marker_type: str, created_by: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute("""
            INSERT INTO markers (lat, lng, note, marker_type, created_by)
            VALUES (?, ?, ?, ?, ?)
        """, (lat, lng, note, marker_type, created_by))
        await db.commit()
        return cursor.lastrowid


async def get_all_markers() -> List[Dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT m.*, u.username, u.first_name
            FROM markers m
            LEFT JOIN users u ON u.tg_id = m.created_by
            ORDER BY m.created_at DESC
        """)
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def delete_marker(marker_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM markers WHERE id = ? AND created_by = ?",
            (marker_id, user_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_user(tg_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM users WHERE tg_id = ?", (tg_id,))
        row = await cursor.fetchone()
        return dict(row) if row else None
