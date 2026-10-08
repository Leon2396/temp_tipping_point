# 🏥 TippingPoint — Predictive Hospital Bottleneck Intelligence

> **Team:** NULL & VOID  
> **Domain:** Sustainability (SDG 3, SDG 9, SDG 13)

TippingPoint is an AI-assisted decision-support platform that predicts hospital bottlenecks before they occur. It combines real-time operational metrics with seasonal patterns (monsoon illness, flu surges) to forecast congestion, discover recoverable hidden capacity, simulate intervention scenarios, and recommend high-impact operational actions.

---

## 🚀 Key Features

* **Predictive Risk Timeline & Tipping-Point Meter:** Live department risk scoring and estimated time-to-critical-capacity.
* **Explainable Ripple & Hidden-Capacity Map:** Pinpoints root causes (e.g., pending discharge/cleaning) and departmental spillover effects.
* **What-If Intervention Simulator:** Test patient surges and staff shortages before applying real-world changes.
* **Best-Fix Recommendation Engine:** Ranks actionable interventions while maintaining human control.
* **Alert System:** Integrated Telegram Bot and Email notifications when thresholds are breached.
* **Historical Replay:** Validate prediction accuracy using past surge scenarios.

---

## 🛠️ Tech Stack

* **Backend:** Python (FastAPI, SimPy, scikit-learn, Pandas, SQLite)
* **Frontend:** React with Tailwind CSS & Lucide Icons
* **Notifications:** Telegram Bot API / SMTP

---

## 🏃 Running Locally

```bash
# 1. Clone the repository
git clone [https://github.com/Leon2396/temp_tipping_point.git](https://github.com/Leon2396/temp_tipping_point.git)
cd temp_tipping_point

# 2. Install dependencies
pip install -r backend/requirements.txt

# 3. Start the server
python -m uvicorn backend.app.main:app --reload
