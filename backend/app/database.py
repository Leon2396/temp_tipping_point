"""
TippingPoint – Database models & connection setup (SQLite via SQLAlchemy).
"""

from sqlalchemy import (
    create_engine, Column, Integer, Float, String, DateTime, Boolean, Text, ForeignKey
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
from datetime import datetime
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "tippingpoint.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ── Department ──────────────────────────────────────────────────────────
class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False)
    total_beds = Column(Integer, nullable=False)
    total_staff = Column(Integer, nullable=False)
    avg_service_minutes = Column(Float, default=30.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    snapshots = relationship("DepartmentSnapshot", back_populates="department")
    predictions = relationship("BottleneckPrediction", back_populates="department")


# ── DepartmentSnapshot (time-series operational state) ──────────────────
class DepartmentSnapshot(Base):
    __tablename__ = "department_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    timestamp = Column(DateTime, nullable=False, index=True)

    occupied_beds = Column(Integer, default=0)
    queue_length = Column(Integer, default=0)
    avg_wait_minutes = Column(Float, default=0.0)
    staff_on_duty = Column(Integer, default=0)
    pending_discharges = Column(Integer, default=0)
    pending_cleaning = Column(Integer, default=0)
    inflow_rate = Column(Float, default=0.0)  # patients/hour
    outflow_rate = Column(Float, default=0.0)

    # External factors
    dengue_factor = Column(Float, default=0.0)  # 0-1 severity
    monsoon_factor = Column(Float, default=0.0)
    accident_spike = Column(Boolean, default=False)

    department = relationship("Department", back_populates="snapshots")


# ── BottleneckPrediction ────────────────────────────────────────────────
class BottleneckPrediction(Base):
    __tablename__ = "bottleneck_predictions"

    id = Column(Integer, primary_key=True, index=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=False)
    predicted_at = Column(DateTime, default=datetime.utcnow)
    risk_score = Column(Float, nullable=False)   # 0-100
    tipping_window_start = Column(DateTime, nullable=True)
    tipping_window_end = Column(DateTime, nullable=True)
    top_factors = Column(Text, default="[]")      # JSON list
    spillover_targets = Column(Text, default="[]")  # JSON list of dept names

    department = relationship("Department", back_populates="predictions")


# ── Intervention ────────────────────────────────────────────────────────
class Intervention(Base):
    __tablename__ = "interventions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    impact_score = Column(Float, default=0.0)
    effort_level = Column(String(20), default="medium")  # low/medium/high
    approved = Column(Boolean, default=False)
    approved_by = Column(String(100), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)


# ── Alert Log ───────────────────────────────────────────────────────────
class AlertLog(Base):
    __tablename__ = "alert_logs"

    id = Column(Integer, primary_key=True, index=True)
    channel = Column(String(50), nullable=False)  # telegram / email
    recipient = Column(String(200), nullable=False)
    message = Column(Text, nullable=False)
    sent_at = Column(DateTime, default=datetime.utcnow)
    success = Column(Boolean, default=True)


# ── Historical Replay ──────────────────────────────────────────────────
class ReplayScenario(Base):
    __tablename__ = "replay_scenarios"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, default="")
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    peak_occupancy_pct = Column(Float, default=0.0)
    prediction_accuracy = Column(Float, default=0.0)
    mae = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
