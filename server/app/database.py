from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import DATABASE_URL

# pool_pre_ping: managed Postgres on most PaaS platforms (and Supabase) will silently drop idle
# connections; without this, the first query after a quiet period fails with a stale-connection
# error instead of transparently reconnecting.
engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
