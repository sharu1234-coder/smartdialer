from __future__ import annotations
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from app.config import get_settings

settings = get_settings()

engine = create_engine(
    settings.database_url,
    pool_pre_ping=True,
    pool_size=5,        # 5 persistent connections per API process
    max_overflow=5,     # 5 overflow connections — 10 max per process
    pool_timeout=30,    # raise after 30s waiting for a connection
    pool_recycle=1800,  # recycle connections older than 30 min
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_all_tables():
    Base.metadata.create_all(bind=engine)


def drop_all_tables():
    Base.metadata.drop_all(bind=engine)
