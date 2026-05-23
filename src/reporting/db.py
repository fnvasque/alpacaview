from contextlib import contextmanager
from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session


def get_reporting_engine(db_url: str):
    connect_args = {"check_same_thread": False} if "sqlite" in db_url else {}
    return create_engine(db_url, connect_args=connect_args)


@contextmanager
def get_reporting_session(engine) -> Generator[Session, None, None]:
    _Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = _Session()
    try:
        yield session
    finally:
        session.close()
