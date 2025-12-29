# # hard safety logic
# # No LLM can override this.

# from datetime import time


# PEAK_HOURS = (time(9, 0), time(21, 0))


# def is_peak_hour(current_time):
#     return PEAK_HOURS[0] <= current_time <= PEAK_HOURS[1]


# def can_self_heal(
#     state: str,
#     confidence: float,
#     has_vip_users: bool,
#     blast_radius: str,
#     current_time,
# ):
#     """
#     Telecom-safe self healing gate.
#     """

#     if state not in ["Unstable", "Degrading"]:
#         return False

#     if confidence < 0.7:
#         return False

#     if blast_radius != "LOW":
#         return False

#     if has_vip_users:
#         return False

#     if is_peak_hour(current_time):
#         return False

#     return True
from datetime import time, datetime

PEAK_HOURS = (time(9, 0), time(21, 0))


def is_peak_hour():
    now = datetime.utcnow().time()
    return PEAK_HOURS[0] <= now <= PEAK_HOURS[1]


def can_execute_sop(
    state: str,
    confidence: float,
    blast_radius: str,
    has_vip_users: bool,
):
    if state not in ["Unstable", "Degrading"]:
        return False, "State not eligible"

    if confidence < 0.7:
        return False, "Low confidence"

    if blast_radius != "LOW":
        return False, "High blast radius"

    if has_vip_users:
        return False, "VIP users impacted"

    if is_peak_hour():
        return False, "Peak hours restriction"

    return True, "Eligible for self-healing"
