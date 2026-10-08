"""Rule-based waterlogging / flood risk scoring from forecast data."""
from datetime import datetime, timedelta, timezone

HEAVY_HOURLY, HEAVY_3H = 15.0, 30.0   # mm: triggers a WARNING
WATCH_HOURLY, WATCH_3H = 7.5, 15.0    # mm: triggers a WATCH

ADVICE = {
    "Low": [
        "No action needed. Check again if the weather changes.",
    ],
    "Moderate": [
        "Avoid parking in low-lying spots and underpasses.",
        "Clear drains and gutters near your home if it is safe to do so.",
        "Keep your phone charged.",
    ],
    "High": [
        "Move vehicles and valuables to higher ground or upper floors.",
        "Avoid underpasses, low roads and riverbanks.",
        "Keep a torch, power bank, drinking water and medicines ready.",
        "Plan an alternate route before you travel.",
    ],
    "Severe": [
        "Do not drive or walk through flooded roads.",
        "Move to higher ground if water is entering your area.",
        "Switch off electricity at the mains if water may enter the house.",
        "Follow instructions from your local disaster management authority.",
    ],
}


def _clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def _num(v):
    return float(v) if isinstance(v, (int, float)) else 0.0


def _now_index(times, utc_offset_seconds):
    local = datetime.now(timezone.utc) + timedelta(seconds=utc_offset_seconds)
    key = local.strftime("%Y-%m-%dT%H:00")
    return times.index(key) if key in times else None


def _first_trigger(series, hourly_thr, window_thr):
    for k in range(len(series)):
        if series[k] >= hourly_thr or sum(series[k:k + 3]) >= window_thr:
            return k
    return None


def _river_ratio(flood):
    try:
        d = flood["daily"]
        peak = max(_num(x) for x in d["river_discharge"][:3])
        means = [_num(x) for x in d["river_discharge_mean"][:3]]
        mean = sum(means) / len(means)
        return peak / mean if mean > 0 else None
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def _elev_points(elev):
    if elev is None:
        return 0.0
    if elev <= 10:
        return 10.0
    if elev <= 50:
        return 6.0
    if elev <= 150:
        return 3.0
    return 0.0


def _river_points(ratio):
    if ratio is None:
        return 0.0
    if ratio >= 3:
        return 10.0
    if ratio >= 2:
        return 6.0
    if ratio >= 1.3:
        return 3.0
    return 0.0


def _level(score):
    if score < 25:
        return "Low"
    if score < 50:
        return "Moderate"
    if score < 75:
        return "High"
    return "Severe"


def compute_risk(weather, flood=None):
    h = weather["hourly"]
    times = h["time"]
    i = _now_index(times, weather.get("utc_offset_seconds", 0))
    if i is None:
        raise ValueError("Forecast data does not cover the current hour")

    precip = [_num(x) for x in h["precipitation"]]
    nxt = precip[i:i + 24]
    if not nxt:
        raise ValueError("No forecast hours available")

    next6 = sum(nxt[:6])
    next24 = sum(nxt)
    peak = max(nxt)
    peak_in = nxt.index(peak)
    past48 = sum(precip[max(0, i - 48):i])

    soil_list = h.get("soil_moisture_0_to_1cm") or []
    soil = _num(soil_list[i]) if i < len(soil_list) else 0.0
    probs = h.get("precipitation_probability") or []
    prob = max((_num(x) for x in probs[i:i + 24]), default=0.0)

    elev = weather.get("elevation")
    ratio = _river_ratio(flood) if flood else None

    factors = [
        ("Rain intensity (peak hour)", 30 * _clamp(peak / 30), 30),
        ("Rain in next 24 h", 25 * _clamp(next24 / 100), 25),
        ("Rain in last 48 h", 15 * _clamp(past48 / 60), 15),
        ("Soil saturation", 10 * _clamp((soil - 0.25) / 0.15), 10),
        ("Low-lying terrain", _elev_points(elev), 10),
        ("River discharge", _river_points(ratio), 10),
    ]
    score = round(sum(f[1] for f in factors))
    level = _level(score)

    heavy = _first_trigger(nxt, HEAVY_HOURLY, HEAVY_3H)
    watch = _first_trigger(nxt, WATCH_HOURLY, WATCH_3H)

    if heavy is not None or score >= 75:
        lead = heavy if heavy is not None else 0
        if heavy is None:
            msg = "Ground, terrain or river conditions make flooding very likely."
        elif lead == 0:
            msg = "Heavy rain is expected right now. Waterlogging is likely."
        else:
            msg = f"Heavy rain expected in about {lead} h. Prepare now."
        alert = {"level": "warning", "lead_hours": lead, "message": msg}
    elif watch is not None or score >= 50:
        lead = watch if watch is not None else 0
        msg = (
            "Moderate to heavy rain is possible soon. Stay alert."
            if lead == 0
            else f"Moderate to heavy rain possible in about {lead} h. Stay alert."
        )
        alert = {"level": "watch", "lead_hours": lead, "message": msg}
    else:
        alert = {"level": "none", "lead_hours": None,
                 "message": "No significant rain expected in the next 24 hours."}

    return {
        "score": score,
        "level": level,
        "alert": alert,
        "elevation_m": elev,
        "stats": {
            "next6_mm": round(next6, 1),
            "next24_mm": round(next24, 1),
            "peak_mm_h": round(peak, 1),
            "peak_in_hours": peak_in,
            "past48_mm": round(past48, 1),
            "soil_moisture": round(soil, 3),
            "rain_probability": round(prob),
            "river_ratio": round(ratio, 2) if ratio is not None else None,
        },
        "factors": [
            {"name": n, "points": round(p, 1), "max": m} for n, p, m in factors
        ],
        "hourly": [
            {"time": times[i + k], "mm": round(v, 1)} for k, v in enumerate(nxt)
        ],
        "advice": ADVICE[level],
        "updated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }