from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


# =========================================================
# 数据库目录
# =========================================================

BASE_DIR = Path(__file__).resolve().parent

DATA_DIR = BASE_DIR / "data"

DATA_DIR.mkdir(
    exist_ok=True
)

DB_PATH = (
    DATA_DIR
    / "market_radar.db"
)

DATABASE_URL = (
    f"sqlite:///{DB_PATH.as_posix()}"
)


# =========================================================
# SQLAlchemy Base
# =========================================================

class Base(DeclarativeBase):
    pass


# =========================================================
# Database Engine
# =========================================================

engine = create_engine(
    DATABASE_URL,
    echo=False,
)


# =========================================================
# SQLite 外键支持
# =========================================================

@event.listens_for(
    engine,
    "connect",
)
def enable_foreign_keys(
    dbapi_connection,
    connection_record,
):

    cursor = (
        dbapi_connection.cursor()
    )

    cursor.execute(
        "PRAGMA foreign_keys=ON"
    )

    cursor.close()


# =========================================================
# Session
# =========================================================

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)