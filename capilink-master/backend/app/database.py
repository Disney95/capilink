"""
CapiLink — Backend
Conexión a Postgres vía SQLAlchemy. El DDL real vive en schema_postgres.sql
(este archivo asume que ese script ya se corrió contra la base de datos;
no se usa Base.metadata.create_all porque las vistas y triggers del
ledger no se pueden expresar con el ORM).
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql+psycopg2://capilink:capilink@localhost:5432/capilink",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
