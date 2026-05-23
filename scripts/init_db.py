import os
import sys

# Ensure project root is on path when run as a script
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.models  # noqa: F401 — registers all ORM models with Base.metadata
from app.database import Base
from sqlalchemy import create_engine, text

DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///./alpacaview.db")
connect_args = {"check_same_thread": False} if "sqlite" in DATABASE_URL else {}

try:
    engine = create_engine(DATABASE_URL, connect_args=connect_args)
    Base.metadata.create_all(bind=engine)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    print(f"Database initialized. Tables: {list(Base.metadata.tables.keys())}")
    sys.exit(0)
except Exception as exc:
    print(f"Database initialization failed: {exc}")
    sys.exit(1)
