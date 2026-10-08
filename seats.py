"""Coach / seat / berth logic, derived from the berth tables in rail.py."""
CLASSES = {  # cls: (coach prefix, seats per coach, fare Rs/km, reservation fee)
    "SL": ("S", 72, 0.55, 20), "3A": ("B", 72, 1.45, 40), "2A": ("A", 54, 2.10, 50), "1A": ("H", 24, 3.60, 60)}
def berth_type(cls, n):
    if cls in ("SL", "3A"): return ["Side Upper", "Lower", "Middle", "Upper", "Lower", "Middle", "Upper", "Side Lower"][n % 8]
    if cls == "2A": return ["Side Upper", "Lower", "Upper", "Lower", "Upper", "Side Lower"][n % 6]
    return "Lower" if n % 2 else "Upper"
def locate(cls, idx, per_coach):
    """Global seat index (1-based) -> (coach label, seat number in coach, berth)."""
    coach_no, seat = (idx - 1) // per_coach + 1, (idx - 1) % per_coach + 1
    return f"{CLASSES[cls][0]}{coach_no}", seat, berth_type(cls, seat)
