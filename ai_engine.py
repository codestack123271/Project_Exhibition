"""AI/ML engine - the four modules from the review PPT (slides 10-13):
 1. waitlist confirmation prediction   2. connecting-train safety score
 3. book-or-wait advisor               4. personalised recommendations
Models train at start-up on *synthetic* history. Replace the generators with real PNR / delay logs
(same feature columns) to move from demo to production."""
import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
CI = {"SL": 0, "3A": 1, "2A": 2, "1A": 3}
MIN_TRANSFER = 15  # minutes needed to change trains
_sig = lambda x: 1 / (1 + np.exp(-x))

class AIEngine:
    def __init__(self, seed=42):
        self.r = np.random.default_rng(seed); self.seed = seed
        self._fit_waitlist(); self._fit_fill(); self._fit_connection()

    # 1 -- waitlist confirmation probability (classification)
    def _fit_waitlist(self):
        r, n = self.r, 6000
        wl, days, c, pop, peak = r.integers(1, 150, n), r.integers(0, 120, n), r.integers(0, 4, n), r.random(n), r.integers(0, 2, n)
        z = 1.4 + 0.025 * days + 0.15 * c - 0.06 * wl * (1 + 0.7 * pop + 0.5 * peak)
        self.wl_model = GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=self.seed).fit(
            np.c_[wl, days, c, pop, peak], r.random(n) < _sig(z))
    def waitlist_prob(self, wl, days, cls, pop, peak):
        return float(self.wl_model.predict_proba([[wl, days, CI[cls], pop, peak]])[0][1])

    # 3 -- occupancy forecast (regression) used by the book-or-wait advisor
    def _fit_fill(self):
        r, n = self.r, 5000
        o, days, pop, peak = r.random(n), r.integers(0, 120, n), r.random(n), r.integers(0, 2, n)
        o3 = np.minimum(1, o + (0.02 + 0.12 * pop + 0.08 * peak) * (o + 0.2) * np.where(days < 10, 1.6, 1) + r.normal(0, .02, n))
        self.fill_model = GradientBoostingRegressor(n_estimators=80, max_depth=3, random_state=self.seed).fit(np.c_[o, days, pop, peak], o3)

    def advise(self, days, occ, cls, pop, peak, wl=None):
        """Plain-language Book Now / Wait recommendation (not a raw chart)."""
        if wl:
            p0 = self.waitlist_prob(wl, days, cls, pop, peak)
            p3 = self.waitlist_prob(max(1, int(wl * .88)), max(days - 3, 0), cls, pop, peak)
            if days > 3 and p3 - p0 > .05:
                return dict(advice="WAIT", reason=f"Confirmation odds forecast to improve from {p0:.0%} to {p3:.0%} within 3 days.", wl_prob=round(p0, 2))
            return dict(advice="BOOK_NOW", reason=f"Odds are not forecast to improve ({p0:.0%} now); book early to hold a better waitlist position.", wl_prob=round(p0, 2))
        o3 = float(self.fill_model.predict([[occ, days, pop, peak]])[0])
        if o3 >= .95 or occ >= .8 or days <= 5:
            return dict(advice="BOOK_NOW", reason=f"Seats forecast to be ~{o3:.0%} full in 3 days; fares may rise.", wl_prob=None)
        if days >= 15 and o3 < .7:
            return dict(advice="WAIT", reason=f"Demand is low (~{o3:.0%} full in 3 days); no rush.", wl_prob=None)
        return dict(advice="BOOK_NOW", reason="Waiting offers no clear benefit.", wl_prob=None)
    @staticmethod
    def fare_multiplier(days, occ): return 1 + (0.10 if days <= 3 else 0) + (0.15 if occ >= .9 else 0)

    # 2 -- connecting-train safety (classification on delay history)
    def _fit_connection(self):
        r, n = self.r, 6000
        mu, sd, buf, fog, hr = r.uniform(0, 45, n), r.uniform(3, 30, n), r.integers(5, 241, n), r.integers(0, 2, n), r.integers(0, 24, n)
        delay = np.maximum(0, r.normal(mu * (1 + .5 * fog), sd * (1 + .3 * fog)))
        self.conn_model = GradientBoostingClassifier(n_estimators=100, max_depth=3, random_state=self.seed).fit(
            np.c_[buf, mu, sd, fog, hr], delay <= buf - MIN_TRANSFER)
    def connection_safety(self, buffer_min, avg_delay, delay_sd, month, hour):
        fog = int(month in (12, 1, 2))
        p = lambda b: float(self.conn_model.predict_proba([[b, avg_delay, delay_sd, fog, hour]])[0][1])
        safe = p(buffer_min)
        rec = next((b for b in range(MIN_TRANSFER, 301, 5) if p(b) >= .9), 300)
        return dict(safe_pct=round(safe * 100), recommended_buffer=rec, risky=safe < .8)

    # 4 -- personalised recommendation (content-based scoring)
    @staticmethod
    def recommend(profile, cands):
        """profile: {'cls':[..], 'hours':[..]} from booking history. cands: dicts with train_no, dep_hour, avg_delay, classes, min_fare."""
        fares = [c["min_fare"] for c in cands]; lo, hi = min(fares), max(fares) or 1
        out = {}
        for c in cands:
            punct = 1 - min(c["avg_delay"], 60) / 60
            cheap = 1 - (c["min_fare"] - lo) / (hi - lo + 1e-9)
            if profile["cls"]:
                cm = sum(k in c["classes"] for k in set(profile["cls"])) / len(set(profile["cls"]))
                tm = 1 - min(abs(c["dep_hour"] - h) for h in profile["hours"]) / 12
                score, why = .35 * cm + .30 * tm + .20 * punct + .15 * cheap, "matches your usual class and departure time"
            else:
                score, why = .6 * punct + .4 * cheap, "punctual and good value"
            out[c["train_no"]] = (round(score, 3), why)
        return out
