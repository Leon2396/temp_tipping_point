"""
SimPy-based Hospital Queue Simulator for What-If analysis.
Simulates patient arrivals, triage, bed assignment, and discharge
with configurable parameters for scenario testing.
"""

import simpy
import random
import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SimConfig:
    """Configuration for a simulation run."""
    duration_hours: int = 24
    num_beds: int = 40
    num_staff: int = 25
    avg_service_minutes: float = 45.0
    base_arrival_rate: float = 8.0  # patients/hour
    dengue_multiplier: float = 1.0
    monsoon_multiplier: float = 1.0
    staff_shortage_pct: float = 0.0  # 0-100
    extra_beds: int = 0
    fast_discharge: bool = False
    seed: int = 42


@dataclass
class SimResults:
    """Results from a simulation run."""
    total_patients: int = 0
    patients_served: int = 0
    patients_turned_away: int = 0
    avg_wait_minutes: float = 0.0
    max_wait_minutes: float = 0.0
    avg_occupancy_pct: float = 0.0
    peak_occupancy_pct: float = 0.0
    peak_queue_length: int = 0
    bottleneck_hours: int = 0  # hours with >85% occupancy
    timeline: list = field(default_factory=list)  # hourly snapshots


def run_simulation(config: SimConfig) -> SimResults:
    """Run a discrete-event hospital simulation."""
    rng = random.Random(config.seed)
    env = simpy.Environment()

    effective_beds = config.num_beds + config.extra_beds
    effective_staff = max(1, int(config.num_staff * (1 - config.staff_shortage_pct / 100)))
    arrival_rate = config.base_arrival_rate * config.dengue_multiplier * config.monsoon_multiplier

    service_time = config.avg_service_minutes
    if config.fast_discharge:
        service_time *= 0.65  # 35% faster

    beds = simpy.Resource(env, capacity=effective_beds)
    staff = simpy.Resource(env, capacity=effective_staff)

    # Metrics collectors
    wait_times = []
    occupancy_samples = []
    queue_samples = []
    turned_away = [0]
    served = [0]
    total = [0]
    timeline = []

    def _diurnal_rate(t):
        hour = (t / 60) % 24
        factor = 0.4 + 0.6 * (math.sin(math.pi * (hour - 5) / 12) ** 2 if 5 <= hour <= 22 else 0.1)
        return arrival_rate * factor

    def patient(env, pid):
        arrival = env.now
        total[0] += 1

        # Check if beds available (turn away if queue > 3× beds)
        if len(beds.queue) > effective_beds * 3:
            turned_away[0] += 1
            return

        with staff.request() as staff_req:
            yield staff_req  # Wait for triage staff
            triage_time = rng.uniform(3, 10)
            yield env.timeout(triage_time)

        with beds.request() as bed_req:
            yield bed_req
            wait = env.now - arrival
            wait_times.append(wait)

            treatment = rng.expovariate(1.0 / service_time)
            yield env.timeout(treatment)
            served[0] += 1

    def patient_generator(env):
        pid = 0
        while True:
            rate = _diurnal_rate(env.now)
            inter_arrival = rng.expovariate(rate / 60)  # convert to minutes
            yield env.timeout(inter_arrival)
            pid += 1
            env.process(patient(env, pid))

    def monitor(env):
        while True:
            occ = beds.count / max(effective_beds, 1) * 100
            occupancy_samples.append(occ)
            queue_samples.append(len(beds.queue))
            if int(env.now) % 60 < 5:  # approx hourly
                timeline.append({
                    "time_minutes": round(env.now, 1),
                    "occupancy_pct": round(occ, 1),
                    "queue_length": len(beds.queue),
                    "staff_busy": staff.count,
                })
            yield env.timeout(5)  # sample every 5 minutes

    env.process(patient_generator(env))
    env.process(monitor(env))
    env.run(until=config.duration_hours * 60)

    # Compile results
    results = SimResults(
        total_patients=total[0],
        patients_served=served[0],
        patients_turned_away=turned_away[0],
        avg_wait_minutes=round(sum(wait_times) / max(len(wait_times), 1), 1),
        max_wait_minutes=round(max(wait_times) if wait_times else 0, 1),
        avg_occupancy_pct=round(sum(occupancy_samples) / max(len(occupancy_samples), 1), 1),
        peak_occupancy_pct=round(max(occupancy_samples) if occupancy_samples else 0, 1),
        peak_queue_length=max(queue_samples) if queue_samples else 0,
        bottleneck_hours=sum(1 for o in occupancy_samples if o > 85) * 5 // 60,
        timeline=timeline,
    )
    return results
