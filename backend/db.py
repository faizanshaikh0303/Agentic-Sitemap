from sqlalchemy import create_engine, Column, Integer, String, Text, JSON, DateTime, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:password@localhost:5432/agentic_sitemap"
)

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Product(Base):
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, unique=True, index=True)
    title = Column(String)
    price = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    raw_text = Column(Text, nullable=True)
    cta_buttons = Column(JSON, default=list)
    review_snippets = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)

    summary = relationship("Summary", back_populates="product", uselist=False, cascade="all, delete-orphan")


class Summary(Base):
    __tablename__ = "summaries"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, ForeignKey("products.id"))
    summary_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

    product = relationship("Product", back_populates="summary")


class Comparison(Base):
    __tablename__ = "comparisons"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text)
    without_context = Column(Text)
    with_context = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
