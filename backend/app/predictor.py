"""
ML Predictor – scikit-learn based bottleneck risk scoring.
Trains a GradientBoosting model on historical snapshot features and outputs
risk scores (0-100) with SHAP-style feature importance.
"""

import json
import numpy as np
from datetime import datetime, timedelta
from sklearn.ensemble import GradientBoostingRegressor
from sklearn.preprocessing import StandardScaler
from app.database import SessionLocal, Department, DepartmentSnapshot, BottleneckPrediction

# Feature columns extracted from snapshots
FEATURE_NAMES = [
    "occupancy_pct", "queue_length", "avg_wait_minutes",
    "staff_ratio", "pending_discharges", "pending_cleaning",
    "inflow_rate", "outflow_rate", "dengue_factor",
    "monsoon_factor", "accident_spike", "hour_sin", "hour_cos",
]

_model = None
_scaler = None


def _extract_features(snap, dept):
    occ_pct = (snap.occupied_beds / dept.total_beds * 100) if dept.total_beds > 0 else (snap.queue_length / 20 * 100)
    hour = snap.timestamp.hour
    return [
        occ_pct,
        snap.queue_length,
        snap.avg_wait_minutes,
        snap.staff_on_duty / max(dept.total_staff, 1),
        snap.pending_discharges,
        snap.pending_cleaning,
        snap.inflow_rate,
        snap.outflow_rate,
        snap.dengue_factor,
        snap.monsoon_factor,
        float(snap.accident_spike),
        np.sin(2 * np.pi * hour / 24),
        np.cos(2 * np.pi * hour / 24),
    ]


def _compute_label(snap, dept):
    """Heuristic risk label for training (0-100)."""
    occ_pct = (snap.occupied_beds / dept.total_beds * 100) if dept.total_beds > 0 else (snap.queue_length / 20 * 100)
    risk = (
        occ_pct * 0.45
        + snap.queue_length * 1.8
        + snap.pending_discharges * 2.5
        + snap.pending_cleaning * 2.0
        + snap.dengue_factor * 14
        + snap.monsoon_factor * 11
        + (20 if snap.accident_spike else 0)
        - snap.staff_on_duty / max(dept.total_staff, 1) * 10
    )
    return max(0, min(100, risk))


def train_model():
    global _model, _scaler
    db = SessionLocal()
    departments = db.query(Department).all()

    X, y = [], []
    for dept in departments:
        snaps = db.query(DepartmentSnapshot).filter_by(department_id=dept.id).all()
        for snap in snaps:
            X.append(_extract_features(snap, dept))
            y.append(_compute_label(snap, dept))
    db.close()

    X = np.array(X)
    y = np.array(y)

    _scaler = StandardScaler()
    X_scaled = _scaler.fit_transform(X)

    _model = GradientBoostingRegressor(
        n_estimators=120, max_depth=5, learning_rate=0.1, random_state=42
    )
    _model.fit(X_scaled, y)
    print(f"[OK] Trained bottleneck model on {len(y)} samples (R2={_model.score(X_scaled, y):.3f})")


def predict_risk(department_id: int) -> dict:
    """Return current risk prediction for a department."""
    if _model is None:
        train_model()

    db = SessionLocal()
    dept = db.query(Department).filter_by(id=department_id).first()
    snap = (
        db.query(DepartmentSnapshot)
        .filter_by(department_id=department_id)
        .order_by(DepartmentSnapshot.timestamp.desc())
        .first()
    )

    if not dept or not snap:
        db.close()
        return {"risk_score": 0, "factors": [], "spillover": []}

    dept_name = str(dept.name)
    features = _extract_features(snap, dept)
    X = np.array([features])
    X_scaled = _scaler.transform(X)

    risk_score = float(np.clip(_model.predict(X_scaled)[0], 0, 100))

    # Feature importance as explainability proxy
    importances = _model.feature_importances_
    factor_list = []
    for i, (fname, imp) in enumerate(zip(FEATURE_NAMES, importances)):
        if imp > 0.03:
            factor_list.append({
                "factor": fname.replace("_", " ").title(),
                "weight": round(imp * 100, 1),
                "value": round(features[i], 2),
            })
    factor_list.sort(key=lambda f: f["weight"], reverse=True)

    # Spillover estimation
    spillover = []
    if risk_score > 70:
        if dept_name == "Emergency":
            spillover = ["ICU", "General Ward"]
        elif dept_name == "ICU":
            spillover = ["General Ward", "Emergency"]
        elif dept_name == "Pediatrics":
            spillover = ["General Ward"]
        else:
            spillover = ["Emergency"]

    # Tipping window
    tw_start = None
    tw_end = None
    if risk_score > 60:
        now = snap.timestamp
        tw_start = (now + timedelta(minutes=30)).isoformat()
        tw_end = (now + timedelta(hours=3)).isoformat()

    # Store prediction
    pred = BottleneckPrediction(
        department_id=department_id,
        predicted_at=datetime.utcnow(),
        risk_score=round(risk_score, 1),
        tipping_window_start=datetime.fromisoformat(tw_start) if tw_start else None,
        tipping_window_end=datetime.fromisoformat(tw_end) if tw_end else None,
        top_factors=json.dumps(factor_list),
        spillover_targets=json.dumps(spillover),
    )
    db.add(pred)
    db.commit()
    db.close()

    return {
        "department_id": department_id,
        "department_name": dept_name,
        "risk_score": round(risk_score, 1),
        "tipping_window": {"start": tw_start, "end": tw_end} if tw_start else None,
        "factors": factor_list[:6],
        "spillover": spillover,
    }


def predict_all() -> list:
    db = SessionLocal()
    dept_ids = [d.id for d in db.query(Department).all()]
    db.close()
    return [predict_risk(did) for did in dept_ids]
