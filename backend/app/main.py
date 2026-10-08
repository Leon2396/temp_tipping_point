"""
TippingPoint – FastAPI Application (main entry point).
Provides REST endpoints for dashboard, predictions, simulation, alerts, and replay.
"""

import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import (
    get_db, init_db,
    Department, DepartmentSnapshot, BottleneckPrediction,
    Intervention, AlertLog, ReplayScenario,
)
from app.predictor import predict_risk, predict_all, train_model
from app.simulator import run_simulation, SimConfig, SimResults
from app.notifications import send_telegram_alert, send_email_alert, get_alert_history
from app.seed import seed_data

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "frontend")


# ── Lifespan ────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_data()
    train_model()
    yield


# ── App Setup ───────────────────────────────────────────────────────────
app = FastAPI(
    title="TippingPoint API",
    description="Predictive Hospital Bottleneck Intelligence",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic Schemas ───────────────────────────────────────────────────
class SimRequest(BaseModel):
    department_id: int = 1
    duration_hours: int = 24
    dengue_multiplier: float = 1.0
    monsoon_multiplier: float = 1.0
    staff_shortage_pct: float = 0.0
    extra_beds: int = 0
    fast_discharge: bool = False


class AlertRequest(BaseModel):
    channel: str = "telegram"  # telegram | email
    recipient: str = "ops-team"
    message: str = ""
    subject: str = "TippingPoint Alert"


class ApproveRequest(BaseModel):
    approved_by: str = "Dr. Admin"


# ═══════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════

# ── Dashboard Overview ──────────────────────────────────────────────────
@app.get("/api/dashboard")
def dashboard_overview(db: Session = Depends(get_db)):
    """Returns department summaries with latest snapshot + risk."""
    departments = db.query(Department).all()
    result = []
    for dept in departments:
        snap = (
            db.query(DepartmentSnapshot)
            .filter_by(department_id=dept.id)
            .order_by(DepartmentSnapshot.timestamp.desc())
            .first()
        )
        pred = (
            db.query(BottleneckPrediction)
            .filter_by(department_id=dept.id)
            .order_by(BottleneckPrediction.predicted_at.desc())
            .first()
        )
        result.append({
            "id": dept.id,
            "name": dept.name,
            "total_beds": dept.total_beds,
            "total_staff": dept.total_staff,
            "snapshot": {
                "occupied_beds": snap.occupied_beds if snap else 0,
                "queue_length": snap.queue_length if snap else 0,
                "avg_wait_minutes": snap.avg_wait_minutes if snap else 0,
                "staff_on_duty": snap.staff_on_duty if snap else 0,
                "pending_discharges": snap.pending_discharges if snap else 0,
                "pending_cleaning": snap.pending_cleaning if snap else 0,
                "inflow_rate": snap.inflow_rate if snap else 0,
                "outflow_rate": snap.outflow_rate if snap else 0,
                "timestamp": snap.timestamp.isoformat() if snap else None,
            } if snap else None,
            "prediction": {
                "risk_score": pred.risk_score if pred else 0,
                "tipping_window": {
                    "start": pred.tipping_window_start.isoformat() if pred and pred.tipping_window_start else None,
                    "end": pred.tipping_window_end.isoformat() if pred and pred.tipping_window_end else None,
                },
                "factors": json.loads(pred.top_factors) if pred else [],
                "spillover": json.loads(pred.spillover_targets) if pred else [],
            } if pred else None,
        })
    return {"departments": result, "timestamp": datetime.utcnow().isoformat()}


# ── Department Detail & Time-Series ────────────────────────────────────
@app.get("/api/departments/{dept_id}/timeseries")
def department_timeseries(
    dept_id: int,
    hours: int = Query(default=72, ge=1, le=720),
    db: Session = Depends(get_db),
):
    """Returns hourly snapshots for a department."""
    dept = db.query(Department).filter_by(id=dept_id).first()
    if not dept:
        raise HTTPException(404, "Department not found")

    latest = (
        db.query(func.max(DepartmentSnapshot.timestamp))
        .filter_by(department_id=dept_id)
        .scalar()
    )
    if not latest:
        return {"department": dept.name, "data": []}

    cutoff = latest - timedelta(hours=hours)
    snaps = (
        db.query(DepartmentSnapshot)
        .filter(DepartmentSnapshot.department_id == dept_id, DepartmentSnapshot.timestamp >= cutoff)
        .order_by(DepartmentSnapshot.timestamp)
        .all()
    )

    data = [
        {
            "timestamp": s.timestamp.isoformat(),
            "occupied_beds": s.occupied_beds,
            "queue_length": s.queue_length,
            "avg_wait_minutes": s.avg_wait_minutes,
            "staff_on_duty": s.staff_on_duty,
            "pending_discharges": s.pending_discharges,
            "pending_cleaning": s.pending_cleaning,
            "inflow_rate": s.inflow_rate,
            "outflow_rate": s.outflow_rate,
            "dengue_factor": s.dengue_factor,
            "monsoon_factor": s.monsoon_factor,
            "occupancy_pct": round(s.occupied_beds / dept.total_beds * 100, 1) if dept.total_beds > 0 else 0,
        }
        for s in snaps
    ]
    return {"department": dept.name, "total_beds": dept.total_beds, "data": data}


# ── ML Predictions ──────────────────────────────────────────────────────
@app.get("/api/predictions")
def get_all_predictions():
    """Re-run ML predictions for all departments."""
    return {"predictions": predict_all()}


@app.get("/api/predictions/{dept_id}")
def get_department_prediction(dept_id: int):
    return predict_risk(dept_id)


# ── What-If Simulator ──────────────────────────────────────────────────
@app.post("/api/simulate")
def simulate_scenario(req: SimRequest, db: Session = Depends(get_db)):
    dept = db.query(Department).filter_by(id=req.department_id).first()
    if not dept:
        raise HTTPException(404, "Department not found")

    config = SimConfig(
        duration_hours=req.duration_hours,
        num_beds=dept.total_beds,
        num_staff=dept.total_staff,
        avg_service_minutes=dept.avg_service_minutes,
        base_arrival_rate=8.0,
        dengue_multiplier=req.dengue_multiplier,
        monsoon_multiplier=req.monsoon_multiplier,
        staff_shortage_pct=req.staff_shortage_pct,
        extra_beds=req.extra_beds,
        fast_discharge=req.fast_discharge,
    )
    results = run_simulation(config)
    return {
        "department": dept.name,
        "config": {
            "duration_hours": config.duration_hours,
            "effective_beds": dept.total_beds + req.extra_beds,
            "dengue_multiplier": req.dengue_multiplier,
            "monsoon_multiplier": req.monsoon_multiplier,
            "staff_shortage_pct": req.staff_shortage_pct,
            "fast_discharge": req.fast_discharge,
        },
        "results": {
            "total_patients": results.total_patients,
            "patients_served": results.patients_served,
            "patients_turned_away": results.patients_turned_away,
            "avg_wait_minutes": results.avg_wait_minutes,
            "max_wait_minutes": results.max_wait_minutes,
            "avg_occupancy_pct": results.avg_occupancy_pct,
            "peak_occupancy_pct": results.peak_occupancy_pct,
            "peak_queue_length": results.peak_queue_length,
            "bottleneck_hours": results.bottleneck_hours,
        },
        "timeline": results.timeline,
    }


# ── Interventions / Best-Fix ───────────────────────────────────────────
@app.get("/api/interventions")
def list_interventions(db: Session = Depends(get_db)):
    items = db.query(Intervention).order_by(Intervention.impact_score.desc()).all()
    return {
        "interventions": [
            {
                "id": i.id,
                "name": i.name,
                "description": i.description,
                "impact_score": i.impact_score,
                "effort_level": i.effort_level,
                "approved": i.approved,
                "approved_by": i.approved_by,
            }
            for i in items
        ]
    }


@app.post("/api/interventions/{intervention_id}/approve")
def approve_intervention(intervention_id: int, req: ApproveRequest, db: Session = Depends(get_db)):
    item = db.query(Intervention).filter_by(id=intervention_id).first()
    if not item:
        raise HTTPException(404, "Intervention not found")
    item.approved = True
    item.approved_by = req.approved_by
    db.commit()
    return {"ok": True, "intervention_id": intervention_id, "approved_by": req.approved_by}


# ── Alerts ──────────────────────────────────────────────────────────────
@app.post("/api/alerts/send")
async def send_alert(req: AlertRequest):
    if req.channel == "telegram":
        result = await send_telegram_alert(req.recipient, req.message)
    elif req.channel == "email":
        result = await send_email_alert(req.recipient, req.subject, req.message)
    else:
        raise HTTPException(400, "Channel must be 'telegram' or 'email'")
    return result


@app.get("/api/alerts/history")
def alert_history():
    return {"alerts": get_alert_history()}


# ── Historical Replay ──────────────────────────────────────────────────
@app.get("/api/replay/scenarios")
def list_replay_scenarios(db: Session = Depends(get_db)):
    scenarios = db.query(ReplayScenario).order_by(ReplayScenario.start_time.desc()).all()
    return {
        "scenarios": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "start_time": s.start_time.isoformat(),
                "end_time": s.end_time.isoformat(),
                "peak_occupancy_pct": s.peak_occupancy_pct,
                "prediction_accuracy": s.prediction_accuracy,
                "mae": s.mae,
            }
            for s in scenarios
        ]
    }


@app.get("/api/replay/{scenario_id}/simulate")
def replay_simulate(scenario_id: int, db: Session = Depends(get_db)):
    """Simulate a historical scenario with default vs optimized parameters."""
    scenario = db.query(ReplayScenario).filter_by(id=scenario_id).first()
    if not scenario:
        raise HTTPException(404, "Scenario not found")

    # Map scenario type to sim params
    is_dengue = "dengue" in scenario.name.lower()
    is_monsoon = "monsoon" in scenario.name.lower()
    is_accident = "accident" in scenario.name.lower()

    base_config = SimConfig(
        duration_hours=max(24, int((scenario.end_time - scenario.start_time).total_seconds() / 3600)),
        num_beds=40,
        num_staff=25,
        dengue_multiplier=2.5 if is_dengue else 1.0,
        monsoon_multiplier=2.0 if is_monsoon else 1.0,
        staff_shortage_pct=10 if is_accident else 0,
    )
    base_results = run_simulation(base_config)

    # Optimized scenario (applied interventions)
    opt_config = SimConfig(
        duration_hours=base_config.duration_hours,
        num_beds=40,
        num_staff=25,
        dengue_multiplier=base_config.dengue_multiplier,
        monsoon_multiplier=base_config.monsoon_multiplier,
        staff_shortage_pct=0,
        extra_beds=10,
        fast_discharge=True,
        seed=43,
    )
    opt_results = run_simulation(opt_config)

    return {
        "scenario": {
            "id": scenario.id,
            "name": scenario.name,
            "description": scenario.description,
            "prediction_accuracy": scenario.prediction_accuracy,
            "mae": scenario.mae,
        },
        "baseline": {
            "avg_wait": base_results.avg_wait_minutes,
            "peak_occupancy": base_results.peak_occupancy_pct,
            "turned_away": base_results.patients_turned_away,
            "bottleneck_hours": base_results.bottleneck_hours,
            "timeline": base_results.timeline,
        },
        "optimized": {
            "avg_wait": opt_results.avg_wait_minutes,
            "peak_occupancy": opt_results.peak_occupancy_pct,
            "turned_away": opt_results.patients_turned_away,
            "bottleneck_hours": opt_results.bottleneck_hours,
            "timeline": opt_results.timeline,
        },
        "report_card": {
            "wait_reduction_pct": round((1 - opt_results.avg_wait_minutes / max(base_results.avg_wait_minutes, 0.1)) * 100, 1),
            "occupancy_reduction_pct": round((1 - opt_results.peak_occupancy_pct / max(base_results.peak_occupancy_pct, 0.1)) * 100, 1),
            "extra_patients_served": opt_results.patients_served - base_results.patients_served,
            "bottleneck_hours_saved": base_results.bottleneck_hours - opt_results.bottleneck_hours,
        },
    }


# ── Health Check ────────────────────────────────────────────────────────
@app.get("/api/health")
def health():
    return {"status": "ok", "service": "TippingPoint", "version": "1.0.0"}


# ── Frontend Serving ────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
def serve_frontend():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>Frontend not found</h1>", status_code=404)


