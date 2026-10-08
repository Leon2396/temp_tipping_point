"""
Synthetic data generator – populates SQLite with realistic hospital data.
Generates 7 departments × 30 days of hourly snapshots with seasonal patterns,
dengue/monsoon surges, and realistic occupancy curves.
"""

import random
import math
import json
from datetime import datetime, timedelta
from app.database import (
    init_db, SessionLocal, DB_PATH,
    Department, DepartmentSnapshot, BottleneckPrediction,
    Intervention, ReplayScenario
)

DEPARTMENTS = [
    {"name": "Emergency",          "total_beds": 40,  "total_staff": 25, "avg_service_minutes": 45},
    {"name": "ICU",                "total_beds": 20,  "total_staff": 18, "avg_service_minutes": 120},
    {"name": "General Ward",       "total_beds": 100, "total_staff": 30, "avg_service_minutes": 60},
    {"name": "Pediatrics",         "total_beds": 30,  "total_staff": 15, "avg_service_minutes": 50},
    {"name": "Maternity",          "total_beds": 25,  "total_staff": 12, "avg_service_minutes": 90},
    {"name": "Orthopedics",        "total_beds": 20,  "total_staff": 10, "avg_service_minutes": 75},
    {"name": "Outpatient (OPD)",   "total_beds": 0,   "total_staff": 20, "avg_service_minutes": 20},
]

INTERVENTIONS = [
    {"name": "Fast-Track Discharge Protocol",   "description": "Expedite discharge paperwork to free beds within 1 hour",    "impact_score": 85, "effort_level": "low"},
    {"name": "Deploy Surge Nursing Team",       "description": "Activate on-call nurses for 6-hour emergency shift",         "impact_score": 78, "effort_level": "medium"},
    {"name": "Divert to Partner Hospital",      "description": "Re-route ambulances to nearby facility for 4 hours",         "impact_score": 72, "effort_level": "high"},
    {"name": "Open Overflow Ward B3",           "description": "Activate reserve ward with 15 beds and minimal staff",       "impact_score": 68, "effort_level": "medium"},
    {"name": "Accelerate Bed Cleaning Cycle",   "description": "Switch to rapid turnover cleaning protocol (15 min target)", "impact_score": 60, "effort_level": "low"},
    {"name": "Postpone Elective Admissions",    "description": "Delay non-urgent admissions for 24 hours",                   "impact_score": 55, "effort_level": "low"},
    {"name": "Telemedicine OPD Overflow",       "description": "Route stable OPD patients to virtual consultations",         "impact_score": 50, "effort_level": "low"},
]

REPLAY_SCENARIOS = [
    {
        "name": "Monsoon Surge – Aug 2025",
        "description": "Heavy monsoon rains caused waterlogging; 3× ER influx over 72 hours with dengue co-morbidities.",
        "start_time": datetime(2025, 8, 12, 6, 0),
        "end_time": datetime(2025, 8, 15, 6, 0),
        "peak_occupancy_pct": 97.3,
        "prediction_accuracy": 88.5,
        "mae": 4.2,
    },
    {
        "name": "Dengue Outbreak – Oct 2025",
        "description": "Severe dengue wave; Pediatrics and General Ward at >95% for 5 days.",
        "start_time": datetime(2025, 10, 1, 0, 0),
        "end_time": datetime(2025, 10, 6, 0, 0),
        "peak_occupancy_pct": 99.1,
        "prediction_accuracy": 91.2,
        "mae": 3.1,
    },
    {
        "name": "Multi-Vehicle Accident – Jan 2026",
        "description": "Highway pile-up sent 45 trauma patients in 2 hours; ICU and Emergency maxed.",
        "start_time": datetime(2026, 1, 18, 14, 0),
        "end_time": datetime(2026, 1, 19, 14, 0),
        "peak_occupancy_pct": 100.0,
        "prediction_accuracy": 76.8,
        "mae": 7.5,
    },
    {
        "name": "Festival Long Weekend – Mar 2026",
        "description": "Holi weekend with spike in burns, dehydration, and food poisoning cases.",
        "start_time": datetime(2026, 3, 13, 0, 0),
        "end_time": datetime(2026, 3, 16, 0, 0),
        "peak_occupancy_pct": 89.4,
        "prediction_accuracy": 93.1,
        "mae": 2.8,
    },
]


def _hour_factor(hour: int) -> float:
    """Simulates diurnal admission pattern – peak around 10-11 AM and 6-8 PM."""
    return 0.4 + 0.6 * (math.sin(math.pi * (hour - 5) / 12) ** 2 if 5 <= hour <= 22 else 0.1)


def _day_of_week_factor(dow: int) -> float:
    """Monday=0. Weekdays busier, slight dip on weekends."""
    return 1.0 if dow < 5 else 0.75


def seed_data():
    init_db()
    db = SessionLocal()

    # Check if data already seeded
    if db.query(Department).count() > 0:
        print("Database already seeded – skipping.")
        db.close()
        return

    # ── 1. Departments ──────────────────────────────────────────────────
    dept_objs = []
    for d in DEPARTMENTS:
        dept = Department(**d)
        db.add(dept)
        dept_objs.append(dept)
    db.commit()
    for d in dept_objs:
        db.refresh(d)

    # ── 2. Snapshots (30 days × 24 hours × 7 departments) ──────────────
    start = datetime(2026, 9, 8, 0, 0)
    total_hours = 30 * 24
    random.seed(42)

    for dept in dept_objs:
        base_occ = 0.55 if dept.name != "Outpatient (OPD)" else 0.0
        for h in range(total_hours):
            ts = start + timedelta(hours=h)
            hour = ts.hour
            dow = ts.weekday()
            day_idx = h // 24

            hf = _hour_factor(hour)
            df = _day_of_week_factor(dow)

            # Dengue surge days 10-18
            dengue = min(1.0, max(0.0, 0.7 * math.exp(-0.3 * abs(day_idx - 14)))) if 8 <= day_idx <= 20 else 0.0
            # Monsoon surge days 18-25
            monsoon = min(1.0, max(0.0, 0.6 * math.exp(-0.4 * abs(day_idx - 22)))) if 16 <= day_idx <= 28 else 0.0
            accident = random.random() < 0.02  # 2% chance per hour

            noise = random.gauss(0, 0.05)
            occ_ratio = min(1.0, max(0.1, base_occ * hf * df + 0.15 * dengue + 0.12 * monsoon + (0.3 if accident else 0) + noise))

            if dept.name == "Outpatient (OPD)":
                occupied = 0
                queue = max(0, int(20 * hf * df + 8 * dengue + random.randint(-3, 5)))
            else:
                occupied = int(dept.total_beds * occ_ratio)
                queue = max(0, int((occupied / max(dept.total_beds, 1) - 0.7) * 15 + random.randint(-2, 4)))

            staff_ratio = max(0.4, min(1.0, 0.7 + 0.3 * hf + random.gauss(0, 0.05)))
            staff = max(1, int(dept.total_staff * staff_ratio))

            pending_d = max(0, int(occupied * random.uniform(0.02, 0.12))) if dept.total_beds > 0 else 0
            pending_c = max(0, int(pending_d * random.uniform(0.3, 0.8)))

            inflow = max(0.0, round(queue * 0.3 + random.uniform(0.5, 3.0), 1))
            outflow = max(0.0, round(inflow * random.uniform(0.6, 1.1), 1))

            snap = DepartmentSnapshot(
                department_id=dept.id,
                timestamp=ts,
                occupied_beds=occupied,
                queue_length=queue,
                avg_wait_minutes=round(max(0, queue * dept.avg_service_minutes / max(staff, 1) + random.gauss(0, 5)), 1),
                staff_on_duty=staff,
                pending_discharges=pending_d,
                pending_cleaning=pending_c,
                inflow_rate=inflow,
                outflow_rate=outflow,
                dengue_factor=round(dengue, 3),
                monsoon_factor=round(monsoon, 3),
                accident_spike=accident,
            )
            db.add(snap)

        # Flush per department to avoid huge memory
        db.commit()

    # ── 3. Seed some predictions for latest timestamp ───────────────────
    latest_ts = start + timedelta(hours=total_hours - 1)
    for dept in dept_objs:
        snap = db.query(DepartmentSnapshot).filter_by(
            department_id=dept.id, timestamp=latest_ts
        ).first()
        if not snap:
            continue

        occ_pct = (snap.occupied_beds / dept.total_beds * 100) if dept.total_beds > 0 else (snap.queue_length / 20 * 100)
        risk = min(100, max(0, occ_pct * 0.6 + snap.queue_length * 2 + snap.pending_discharges * 3 + snap.dengue_factor * 15 + snap.monsoon_factor * 12 + random.uniform(-5, 5)))

        factors = []
        if snap.pending_discharges > 2:
            factors.append({"factor": "Pending Discharges", "weight": round(snap.pending_discharges * 3, 1)})
        if snap.pending_cleaning > 1:
            factors.append({"factor": "Pending Bed Cleaning", "weight": round(snap.pending_cleaning * 2.5, 1)})
        if snap.dengue_factor > 0.3:
            factors.append({"factor": "Dengue Surge", "weight": round(snap.dengue_factor * 15, 1)})
        if snap.monsoon_factor > 0.2:
            factors.append({"factor": "Monsoon Influx", "weight": round(snap.monsoon_factor * 12, 1)})
        if snap.queue_length > 5:
            factors.append({"factor": "High Queue Length", "weight": round(snap.queue_length * 1.5, 1)})
        if snap.staff_on_duty < dept.total_staff * 0.6:
            factors.append({"factor": "Staff Shortage", "weight": 10.0})

        spillover = []
        if risk > 70 and dept.name == "Emergency":
            spillover = ["ICU", "General Ward"]
        elif risk > 70 and dept.name == "ICU":
            spillover = ["General Ward"]
        elif risk > 75:
            spillover = ["Emergency"]

        pred = BottleneckPrediction(
            department_id=dept.id,
            predicted_at=latest_ts,
            risk_score=round(risk, 1),
            tipping_window_start=latest_ts + timedelta(hours=1) if risk > 60 else None,
            tipping_window_end=latest_ts + timedelta(hours=4) if risk > 60 else None,
            top_factors=json.dumps(factors),
            spillover_targets=json.dumps(spillover),
        )
        db.add(pred)

    # ── 4. Interventions ────────────────────────────────────────────────
    for idx, iv in enumerate(INTERVENTIONS):
        db.add(Intervention(**iv, department_id=dept_objs[idx % len(dept_objs)].id))

    # ── 5. Replay Scenarios ─────────────────────────────────────────────
    for rs in REPLAY_SCENARIOS:
        db.add(ReplayScenario(**rs))

    db.commit()
    db.close()
    print(f"[OK] Seeded database at {DB_PATH}")


if __name__ == "__main__":
    seed_data()
