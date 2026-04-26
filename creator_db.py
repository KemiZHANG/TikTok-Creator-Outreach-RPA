import sqlite3
from pathlib import Path

from utils import BASE_DIR, log


DB_PATH = BASE_DIR / "processed_creators.db"


def init_processed_creators_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_creators (
                creator_name TEXT PRIMARY KEY,
                processed_time TEXT DEFAULT (datetime('now', 'localtime'))
            )
            """
        )
        conn.commit()
    log(f"达人去重数据库已就绪: {DB_PATH}")


def clear_processed_creators() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("DELETE FROM processed_creators")
        conn.commit()
    log("已按本次启动选择清空达人去重数据库")


def normalize_creator_name(creator_name: str) -> str:
    return " ".join((creator_name or "").strip().split())


def is_creator_processed(creator_name: str) -> bool:
    normalized_name = normalize_creator_name(creator_name)
    if not normalized_name:
        return False

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "SELECT 1 FROM processed_creators WHERE creator_name = ? LIMIT 1",
            (normalized_name,),
        )
        return cursor.fetchone() is not None


def add_processed_creator(creator_name: str) -> None:
    normalized_name = normalize_creator_name(creator_name)
    if not normalized_name:
        log("达人名称为空，未写入数据库", level="WARNING")
        return

    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO processed_creators (creator_name, processed_time)
            VALUES (?, datetime('now', 'localtime'))
            """,
            (normalized_name,),
        )
        conn.commit()
    log(f"已写入达人去重数据库: {normalized_name}")
