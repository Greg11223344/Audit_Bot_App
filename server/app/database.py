from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import DATABASE_URL

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}

# pool_pre_ping: managed Postgres on most PaaS platforms will silently drop idle connections;
# without this, the first query after a quiet period fails with a stale-connection error.
engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
