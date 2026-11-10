from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from app.config import settings

# If using SQLite, ensure the target directory exists and configure threading
connect_args = {}
db_url = settings.database_url
if db_url.startswith("sqlite:///"):
    sqlite_path = db_url.replace("sqlite:///", "")
    db_file = Path(sqlite_path)
    if not db_file.is_absolute():
        # resolve relative to backend / project root
        db_file = Path(__file__).resolve().parents[2] / sqlite_path
        db_url = f"sqlite:///{db_file}"
    db_file.parent.mkdir(parents=True, exist_ok=True)
    connect_args["check_same_thread"] = False

engine = create_engine(
    db_url,
    pool_pre_ping=True,
    connect_args=connect_args,
)

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


from contextlib import contextmanager


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
