from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from app.config.settings import settings

DATABASE_URL = getattr(
    settings,
    "DATABASE_URL",
    "sqlite:///./agentos.db"  # fallback for dev
)

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite")
    else {}
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()
def init_db():
    from app.persistence import models
    Base.metadata.create_all(bind=engine)
