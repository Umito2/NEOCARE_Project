"""Shared measurement screening; these existing project limits need clinical review.

This module classifies recorded measurements, never diagnoses their cause.
Timestamp validity is handled by the API before calling this pure evaluator.
"""

import math


DEFAULT_THRESHOLDS = {
    "spo2_min": 92,
    "temperature_warning_c": 38,
    "temperature_critical_c": 39,
    "heart_rate_max_age_0_3": 130,
    "heart_rate_max_age_over_3": 115,
    "respiratory_rate_max_age_0_3": 34,
    "respiratory_rate_max_age_over_3": 26,
}


def analyze_vitals(age, hr, spo2, temp, resp, activity, thresholds=None):
    """Apply the same limits to dashboards, alerts and reports.

    The 25 bpm / 12 breaths per minute activity adjustments were already defined by the project. They now
    participates in the comparison instead of bypassing active measurements.
    Missing context cannot produce Normal, but does not hide an observed alarm.
    """
    limits = {**DEFAULT_THRESHOLDS, **(thresholds or {})}
    recommendations = [
        "Check the wearable fit and repeat the measurement according to the device instructions.",
        "Record the reading, time, and activity to share with the child's clinician.",
        "Contact a pediatric clinician if unusual readings persist or the child seems unwell.",
    ]
    base = {
        "risk_status": "Normal",
        "condition": "No configured alert thresholds exceeded",
        "causes": ["These measurements alone cannot determine the child's health or the cause of symptoms."],
        "recommendations": recommendations,
        "safety_recommendations": [],
    }
    try:
        age, hr, spo2, temp = map(float, (age, hr, spo2, temp))
        resp = float(resp) if resp is not None else None
        if not all(math.isfinite(value) for value in (age, hr, spo2, temp)):
            raise ValueError
        if resp is not None and not math.isfinite(resp):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        return {**base, "risk_status": "Invalid reading", "condition": "Measurements are missing or invalid"}

    young = age <= 3
    hr_limit = limits["heart_rate_max_age_0_3" if young else "heart_rate_max_age_over_3"]
    if activity == "Active":
        hr_limit += 25
        recommendations[0] = "Let the child rest, then repeat the measurement according to the device instructions."
    rr_limit = limits["respiratory_rate_max_age_0_3" if young else "respiratory_rate_max_age_over_3"]
    if activity == "Active":
        rr_limit += 12
    if spo2 < limits["spo2_min"]:
        return {
            **base, "risk_status": "Critical", "condition": "Oxygen below configured alert threshold",
            "causes": ["The recorded oxygen saturation is below the configured threshold; a measurement alone cannot identify its cause."],
            "safety_recommendations": ["The rule-based screen marked this reading Critical because of low oxygen. Seek emergency medical care now; do not wait for AI guidance."],
        }
    if temp >= limits["temperature_critical_c"]:
        return {
            **base, "risk_status": "Critical", "condition": "Temperature at or above configured critical threshold",
            "causes": ["The recorded temperature meets the configured critical threshold; the cause requires clinical assessment."],
            "safety_recommendations": ["The rule-based screen marked this reading Critical because of temperature. Contact a pediatric clinician urgently."],
        }
    exceeded = []
    if temp >= limits["temperature_warning_c"]:
        exceeded.append("Temperature at or above configured warning threshold")
    if activity in ("Sleeping", "Resting", "Active") and hr > hr_limit:
        exceeded.append("Heart rate above the configured activity-adjusted threshold")
    if resp is not None and resp > rr_limit:
        exceeded.append("Respiratory rate above configured threshold")
    if exceeded:
        return {**base, "risk_status": "Warning", "condition": "; ".join(exceeded), "causes": exceeded + base["causes"]}
    if resp is None or activity not in ("Sleeping", "Resting", "Active"):
        return {**base, "risk_status": "Incomplete reading", "condition": "Respiratory rate or valid activity is missing"}
    return base
