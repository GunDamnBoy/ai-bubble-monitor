#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 泡沫監控儀表板：每日自動更新 data.json（GitHub Actions）。
原則：任一來源失敗只記錄並沿用舊值，絕不編造、絕不讓整次更新失敗。
量化指標自動更新；質化指標（qual=True 且無 anchors 者）由每週人工覆核。"""
import json, re, sys, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data.json"
OFFLINE = "--offline" in sys.argv
TODAY = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()   # 台北日期
UA_DEFAULT = "ai-bubble-monitor/1.0 (github actions; haonung.chiang@gmail.com)"
UA_BROWSER = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
UA_SEC = "Kenny Chiang haonung.chiang@gmail.com"   # SEC 規範：姓名＋聯絡信箱
LOG = []

def log(m):
    LOG.append(str(m)); print(str(m), flush=True)

def http_get(url, ua=None):
    if OFFLINE:
        raise RuntimeError("offline mode")
    import requests
    r = requests.get(url, headers={"User-Agent": ua or UA_DEFAULT}, timeout=45)
    r.raise_for_status()
    return r

# ---------------- scoring ----------------
def pw(v, anchors):
    pts = sorted([tuple(a) for a in anchors])
    if v <= pts[0][0]: return float(pts[0][1])
    if v >= pts[-1][0]: return float(pts[-1][1])
    for (v0, s0), (v1, s1) in zip(pts, pts[1:]):
        if v0 <= v <= v1:
            return s0 + (s1 - s0) * (v - v0) / (v1 - v0)

def vix_score(v):
    if v >= 35: return 95.0
    if v >= 28: return 67 + (v - 28) / 7 * 28
    if v >= 18: return 33.0
    if v >= 13: return 50.0
    return 70.0

def zone(s):
    return "green" if s < 33 else ("yellow" if s < 67 else ("orange" if s < 84 else "red"))

# ---------------- fetchers ----------------
def fred(series, days=620):
    start = (TODAY - dt.timedelta(days=days)).isoformat()
    txt = http_get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}").text
    out = []
    for line in txt.strip().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) >= 2 and re.match(r"\d{4}-\d{2}-\d{2}", parts[0]):
            try:
                out.append((dt.date.fromisoformat(parts[0]), float(parts[1])))
            except ValueError:
                pass
    if not out:
        raise RuntimeError(f"FRED {series}: empty")
    return out

def fred_latest_and_back(series, back_days):
    obs = fred(series)
    d_last, v_last = obs[-1]
    v_back = None
    for d, v in reversed(obs):
        if d <= d_last - dt.timedelta(days=back_days):
            v_back = v
            break
    return d_last, v_last, v_back

def stooq(sym, days=620):
    d1 = (TODAY - dt.timedelta(days=days)).strftime("%Y%m%d")
    txt = http_get(f"https://stooq.com/q/d/l/?s={sym}&i=d&d1={d1}&d2={TODAY.strftime('%Y%m%d')}").text
    out = []
    for line in txt.strip().splitlines()[1:]:
        p = line.split(",")
        if len(p) >= 5 and re.match(r"\d{4}-\d{2}-\d{2}", p[0]):
            try:
                c = float(p[4])
                if c > 0:
                    out.append((dt.date.fromisoformat(p[0]), c))
            except ValueError:
                pass
    if len(out) < 30:
        raise RuntimeError(f"stooq {sym}: {len(out)} rows")
    return out

def yahoo_chart(sym, rng="2y"):
    from urllib.parse import quote
    j = http_get(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(sym)}?range={rng}&interval=1d",
                 ua=UA_BROWSER).json()
    res = j["chart"]["result"][0]
    ts = res["timestamp"]
    closes = res["indicators"]["quote"][0]["close"]
    out = [(dt.datetime.utcfromtimestamp(t).date(), float(c))
           for t, c in zip(ts, closes) if c]
    if len(out) < 30:
        raise RuntimeError(f"yahoo {sym}: {len(out)} rows")
    return out

def px_stats(ysym, ssym=None):
    """Yahoo Chart API 為主，Stooq 備援。"""
    try:
        return series_stats(yahoo_chart(ysym))
    except Exception as e1:
        if ssym:
            try:
                return series_stats(stooq(ssym))
            except Exception as e2:
                raise RuntimeError(f"yahoo({e1}) & stooq({e2})")
        raise

def series_stats(rows):
    closes = [c for _, c in rows]
    last_d, last_c = rows[-1]
    st = {"date": last_d, "close": last_c}
    if len(closes) >= 200: st["dma200"] = sum(closes[-200:]) / 200
    if len(closes) >= 253: st["chg52w"] = (last_c / closes[-253] - 1) * 100
    if len(closes) >= 64:  st["chg3m"] = (last_c / closes[-64] - 1) * 100
    if len(closes) >= 253:
        w = closes[-253:]
        st["pos52w"] = (last_c - min(w)) / (max(w) - min(w)) * 100 if max(w) > min(w) else 50.0
    return st

def multpl_cape():
    html = http_get("https://www.multpl.com/shiller-pe").text
    m = re.search(r'id="current"[^>]*>.*?([0-9]{1,3}\.[0-9]{1,2})', html, re.S) or \
        re.search(r"Shiller PE Ratio[^0-9]{0,60}([0-9]{1,3}\.[0-9]{1,2})", html, re.S)
    if not m:
        raise RuntimeError("multpl: pattern not found")
    v = float(m.group(1))
    if not (5 < v < 80):
        raise RuntimeError(f"multpl: implausible {v}")
    return v

def slickcharts_mag7():
    html = http_get("https://www.slickcharts.com/sp500").text
    weights = {}
    for tick in ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "GOOG", "META", "TSLA"]:
        m = re.search(r">" + tick + r"</a></td>\s*<td[^>]*>([0-9.]+)%?</td>", html) or \
            re.search(r"/symbol/" + tick + r'"[^>]*>[^<]*</a>.*?([0-9]{1,2}\.[0-9]{2})%', html, re.S)
        if m:
            weights[tick] = float(m.group(1))
    if len(weights) < 8:
        raise RuntimeError(f"slickcharts: only {len(weights)} of 8 tickers parsed")
    return sum(weights.values())

# ---------------- EDGAR quarterly engine ----------------
CIK = {"MSFT": "0000789019", "AMZN": "0001018724", "GOOGL": "0001652044",
       "META": "0001326801", "ORCL": "0001341439"}
FY_START = {"MSFT": (7, 1), "AMZN": (1, 1), "GOOGL": (1, 1), "META": (1, 1), "ORCL": (6, 1)}
CONCEPTS = {
    "capex": {"*": ["PaymentsToAcquirePropertyPlantAndEquipment"],
              "AMZN": ["PaymentsToAcquireProductiveAssets", "PaymentsToAcquirePropertyPlantAndEquipment"]},
    "ocf":   {"*": ["NetCashProvidedByUsedInOperatingActivities",
                    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]},
    "dep":   {"*": ["Depreciation", "DepreciationDepletionAndAmortization",
                    "DepreciationAmortizationAndAccretionNet"],
              "AMZN": ["DepreciationDepletionAndAmortization", "Depreciation"]},
    "rev":   {"*": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"]},
    "debt":  {"*": ["LongTermDebtNoncurrent", "LongTermDebt"],
              "ORCL": ["LongTermNotesPayable", "LongTermDebtNoncurrent"]},
}

def edgar_rows(co, concept_names, min_end="2023-06-01"):
    """回傳 [(start|None, end, val)]，同 (start,end) 去重。"""
    import time
    for name in concept_names:
        try:
            time.sleep(0.2)   # SEC 流量禮儀
            j = http_get(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{CIK[co]}/us-gaap/{name}.json",
                         ua=UA_SEC).json()
        except Exception as ex:
            log(f"    edgar {co}/{name}: {ex}")
            continue
        rows, seen = [], set()
        for unit in j.get("units", {}).get("USD", []):
            end = unit.get("end")
            if not end or end < min_end or unit.get("val") is None:
                continue
            key = (unit.get("start"), end)
            if key in seen:
                continue
            seen.add(key)
            rows.append((unit.get("start"), end, float(unit["val"])))
        if rows:
            return name, rows
    return None, []

def to_quarters(rows, fy_start):
    """3個月直接列＋YTD 差分 → {end_date: 單季值}（與初版 compute.py 相同邏輯）"""
    D = dt.date.fromisoformat
    out = {}
    parsed = [(D(s) if s else None, D(e), v) for s, e, v in rows]
    for s, e, v in parsed:
        if s and 80 <= (e - s).days <= 100:
            out[e] = v
    chains = {}
    for s, e, v in parsed:
        if s and (s.month, s.day) == fy_start:
            chains.setdefault(s, []).append((e, v))
    for s, ch in chains.items():
        ch = sorted(set(ch))
        fe, fv = ch[0]
        if 80 <= (fe - s).days <= 100 and fe not in out:
            out[fe] = fv
        prev = None
        for e, v in ch:
            if prev and 80 <= (e - prev[0]).days <= 100 and e not in out:
                out[e] = v - prev[1]
            prev = (e, v)
    return dict(sorted(out.items()))

def bucket(d):
    q = {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 2, 7: 3, 8: 3, 9: 3, 10: 4, 11: 4, 12: 4}[d.month]
    return f"{d.year}Q{q}"

def refresh_edgar(data):
    """全量重建 aggQ/ttm/debt 序列與 D3/D4 財報指標。任何公司缺料→整塊沿用舊值。"""
    cos = list(CIK)
    Q = {}
    for co in cos:
        for metric in ("capex", "ocf"):
            names = CONCEPTS[metric].get(co, CONCEPTS[metric]["*"])
            tag, rows = edgar_rows(co, names)
            if not rows:
                raise RuntimeError(f"EDGAR {co} {metric}: no data")
            Q.setdefault(co, {})[metric] = to_quarters(rows, FY_START[co])
    BQ = {}
    for co in cos:
        for metric in ("capex", "ocf"):
            for e, v in Q[co][metric].items():
                BQ.setdefault(bucket(e), {}).setdefault(metric, {})[co] = v
    agg = []
    for lb in sorted(BQ):
        row = BQ[lb]
        if all(co in row.get("capex", {}) for co in cos) and all(co in row.get("ocf", {}) for co in cos):
            cx = sum(row["capex"][c] for c in cos) / 1e3 / 1e6
            oc = sum(row["ocf"][c] for c in cos) / 1e3 / 1e6
            agg.append({"q": lb, "capex": round(cx, 1), "ocf": round(oc, 1),
                        "fcf": round(oc - cx, 1), "ratio": round(100 * cx / oc, 1)})
    agg = [a for a in agg if a["q"] >= "2023Q3"]
    if len(agg) < 8:
        raise RuntimeError(f"EDGAR agg: only {len(agg)} quarters")
    ttm = []
    for i in range(3, len(agg)):
        w = agg[i - 3:i + 1]
        cx = sum(x["capex"] for x in w); oc = sum(x["ocf"] for x in w)
        ttm.append({"q": w[-1]["q"], "capex": round(cx, 1), "ocf": round(oc, 1),
                    "fcf": round(oc - cx, 1), "ratio": round(100 * cx / oc, 1)})
    # dep/rev 最新同季 YoY（缺者跳過該公司）
    dna_g, rev_g = [], []
    for co in cos:
        try:
            _, dro = edgar_rows(co, CONCEPTS["dep"].get(co, CONCEPTS["dep"]["*"]))
            _, rro = edgar_rows(co, CONCEPTS["rev"].get(co, CONCEPTS["rev"]["*"]))
            if co == "GOOGL":  # 新期間改用 Revenues，合併兩標籤
                _, extra = edgar_rows(co, ["Revenues"])
                seen = {(s, e) for s, e, _ in rro}
                rro += [r for r in extra if (r[0], r[1]) not in seen]
            dq = to_quarters(dro, FY_START[co]); rq = to_quarters(rro, FY_START[co])
            def yoy(qd):
                ends = sorted(qd)
                le = ends[-1]
                prior = [e for e in ends if abs((le - dt.timedelta(days=365) - e).days) <= 20]
                return (qd[le] / qd[prior[-1]] - 1) * 100 if prior and qd[prior[-1]] else None
            g1, g2 = yoy(dq), yoy(rq)
            if g1 is not None and g2 is not None:
                dna_g.append(g1); rev_g.append(g2)
        except Exception as ex:
            log(f"  dnagap {co}: skip ({ex})")
    # debt
    debt_now = debt_prior = 0.0
    debt_series = {}
    for co in cos:
        _, dr = edgar_rows(co, CONCEPTS["debt"].get(co, CONCEPTS["debt"]["*"]), min_end="2023-09-01")
        pts = sorted({(dt.date.fromisoformat(e), v) for _, e, v in dr})
        if not pts:
            raise RuntimeError(f"EDGAR {co} debt: no data")
        le, lv = pts[-1]
        debt_now += lv
        pri = [v for e, v in pts if (le - e).days >= 330]
        debt_prior += pri[-1] if pri else lv
        debt_series[co] = pts
    # 債務圖表序列（季末網格，前向填補）
    grid = sorted({q["q"] for q in agg if q["q"] >= "2023Q4"})
    qend = {}
    for lb in grid:
        y, qn = int(lb[:4]), int(lb[-1])
        qend[lb] = dt.date(y, [3, 6, 9, 12][qn - 1], [31, 30, 30, 31][qn - 1])
    debt_chart = []
    for lb in grid:
        tot, full = 0.0, True
        for co in cos:
            vals = [v for e, v in debt_series[co] if e <= qend[lb] + dt.timedelta(days=15)]
            if vals: tot += vals[-1]
            else: full = False
        if full:
            debt_chart.append((lb, round(tot / 1e9, 1)))
    return {"agg": agg, "ttm": ttm,
            "dna_gap": (sum(dna_g) / len(dna_g) - sum(rev_g) / len(rev_g)) if len(dna_g) >= 4 else None,
            "dna_avg": sum(dna_g) / len(dna_g) if dna_g else None,
            "rev_avg": sum(rev_g) / len(rev_g) if rev_g else None,
            "debt_now": debt_now / 1e9, "debt_prior": debt_prior / 1e9,
            "debt_chart": debt_chart}

# ---------------- main ----------------
def main():
    data = json.loads(DATA.read_text())
    IND = {i["id"]: i for i in data["indicators"]}
    TWI = {i["id"]: i for i in data["tw"]["items"]}
    params = data.setdefault("params", {"nvda_eps": 6.31, "tsmc_eps": 75.49})
    sp = data["charts"]["spreads"]
    ok, fail = [], []

    def upd(iid, value, disp, score, asof=None, sub=None):
        i = IND[iid]
        i["value"], i["disp"], i["score"], i["zone"] = value, disp, round(score, 1), zone(score)
        i["asof"] = asof or str(TODAY)
        i["fresh"] = "ok"
        if sub is not None: i["sub"] = sub

    def attempt(name, fn):
        try:
            fn(); ok.append(name)
        except Exception as ex:
            fail.append(name); log(f"[FAIL] {name}: {ex}")

    # ---- FRED ----
    def f_hy():
        d, v, b = fred_latest_and_back("BAMLH0A0HYM2", 91)
        d3 = (v - b) * 100 if b is not None else 0.0
        upd("hyoas", v, f"{v:.2f}%", pw(d3, IND["hyoas"]["anchors"]), str(d))
        sp["hy"] = {"now": v, "m3": b if b is not None else sp["hy"].get("m3"),
                    "y1": sp["hy"].get("y1"), "asof": str(d)}
        obs = fred("BAMLH0A0HYM2")
        y1 = [x for t, x in obs if t <= d - dt.timedelta(days=360)]
        if y1: sp["hy"]["y1"] = y1[-1]
    def f_ig():
        d, v, b = fred_latest_and_back("BAMLC0A0CM", 91)
        sp["ig"] = {"now": v, "m3": b, "y1": sp["ig"].get("y1"), "asof": str(d)}
        IND["hyoas"]["sub"] = f"IG OAS {v:.2f}%"
    def f_vix():
        d, v, _ = fred_latest_and_back("VIXCLS", 0)
        upd("vix", v, f"{v:.1f}", vix_score(v), str(d))
        sp["vix"] = {"now": v, "asof": str(d)}
    def f_10y():
        d, v, b = fred_latest_and_back("DGS10", 91)
        chg = f"（3個月 {(v-b)*100:+.0f}bp）" if b is not None else ""
        upd("us10y", v, f"{v:.2f}%{chg}", pw(v, IND["us10y"]["anchors"]), str(d))
        sp["us10y"] = {"now": v, "m3": b, "asof": str(d)}
    def f_fed():
        d, v, y1 = fred_latest_and_back("FEDFUNDS", 360)
        i = IND["fed"]
        i["value"], i["asof"] = v, str(d)
        i["disp"] = f"{v:.2f}%" + (f"（年變動 {(v-y1)*100:+.0f}bp）" if y1 is not None else "")
        sp["fedfunds"] = {"now": v, "y1": y1, "asof": str(d)}
    def f_jobs():
        d, v, y1 = fred_latest_and_back("USINFO", 360)
        if y1:
            g = (v / y1 - 1) * 100
            upd("itjobs", round(g, 1), f"{g:+.1f}%", pw(g, IND["itjobs"]["anchors"]), str(d))
        sp["usinfo"] = {"now": v, "y1": y1, "asof": str(d)}
    attempt("FRED HY", f_hy); attempt("FRED IG", f_ig); attempt("FRED VIX", f_vix)
    attempt("FRED 10Y", f_10y); attempt("FRED FED", f_fed); attempt("FRED JOBS", f_jobs)

    # ---- 價格（Yahoo 為主、Stooq 備援）----
    S = {}
    PX = {"nvda": ("NVDA", "nvda.us"), "soxx": ("SOXX", "soxx.us"),
          "spy": ("SPY", "spy.us"), "2330": ("2330.TW", "2330.tw")}
    def f_px(key, ysym, ssym):
        def go(): S[key] = px_stats(ysym, ssym)
        return go
    for key, (ysym, ssym) in PX.items():
        attempt(f"px {ysym}", f_px(key, ysym, ssym))
    def f_nvda():
        st = S["nvda"]
        pe = st["close"] / params["nvda_eps"]
        upd("nvdape", round(pe, 2), f"{pe:.1f}×", pw(pe, IND["nvdape"]["anchors"]), str(st["date"]))
        dev = (st["close"] / st["dma200"] - 1) * 100
        upd("nvda200", round(dev, 1), f"{dev:+.1f}%", pw(dev, IND["nvda200"]["anchors"]), str(st["date"]))
    def f_sox():
        mom = S["soxx"]["chg3m"] - S["spy"]["chg3m"]
        upd("soxmom", round(mom, 1), f"{mom:+.0f}pp",
            pw(mom, IND["soxmom"]["anchors"]), str(S["soxx"]["date"]))
    def f_tsmc():
        st = S["2330"]
        pe = st["close"] / params["tsmc_eps"]
        for iid, val, disp, anch in [
            ("tsmc_pe", pe, f"{pe:.1f}×", [[15, 0], [22, 33], [28, 67], [35, 100]]),
            ("tsmc_200dma", (st["close"] / st["dma200"] - 1) * 100, None, [[0, 0], [15, 33], [30, 67], [50, 100]]),
            ("tsmc_52w", st.get("chg52w"), None, [[20, 0], [50, 33], [90, 67], [150, 100]])]:
            if val is None: continue
            t = TWI[iid]
            t["value"] = round(val, 2)
            t["disp"] = disp or f"{val:+.1f}%"
            t["score"] = round(pw(val, anch), 1)
            t["asof"] = str(st["date"])
    if "nvda" in S: attempt("calc nvda", f_nvda)
    if "soxx" in S and "spy" in S: attempt("calc soxmom", f_sox)
    if "2330" in S: attempt("calc tsmc", f_tsmc)
    def f_twii():
        st = px_stats("^TWII", "^twii")
        if st and "pos52w" in st:
            t = TWI["twii_pos"]
            t["value"] = round(st["pos52w"], 1); t["disp"] = f"{st['pos52w']:.1f}%"
            t["score"] = round(pw(st["pos52w"], [[50, 0], [75, 33], [90, 67], [100, 100]]), 1)
            t["asof"] = str(st["date"])
        else:
            raise RuntimeError("TWII: no 52w stats")
    attempt("px ^TWII", f_twii)

    # ---- scrapes ----
    def f_cape():
        v = multpl_cape()
        upd("cape", v, f"{v:.1f}×", pw(v, IND["cape"]["anchors"]))
    def f_mag7():
        v = slickcharts_mag7()
        upd("mag7", round(v, 2), f"{v:.1f}%", pw(v, IND["mag7"]["anchors"]))
    attempt("multpl CAPE", f_cape); attempt("slickcharts Mag7", f_mag7)

    # ---- EDGAR（僅在能完整重建時才覆蓋）----
    def f_edgar():
        E = refresh_edgar(data)
        agg, ttm = E["agg"], E["ttm"]
        data["charts"]["aggQ"], data["charts"]["ttm"] = agg, ttm
        if E["debt_chart"]:
            data["charts"]["debt"]["labels"] = [x[0] for x in E["debt_chart"]]
            data["charts"]["debt"]["values"] = [x[1] for x in E["debt_chart"]]
        t = ttm[-1]
        upd("capexocf", t["ratio"], f"{t['ratio']:.1f}%",
            pw(t["ratio"], IND["capexocf"]["anchors"]), t["q"],
            sub=f"最新單季 {agg[-1]['ratio']:.1f}%")
        if len(ttm) >= 5 and ttm[-5]["fcf"]:
            g = (t["fcf"] / ttm[-5]["fcf"] - 1) * 100
            qg = (agg[-1]["fcf"] / agg[-5]["fcf"] - 1) * 100 if len(agg) >= 5 and agg[-5]["fcf"] else None
            upd("fcf", round(g, 1), f"{g:+.1f}%", pw(g, IND["fcf"]["anchors"]), t["q"],
                sub=f"單季 FCF ${agg[-1]['fcf']}B" + (f"（年增 {qg:+.1f}%）" if qg is not None else ""))
        if E["dna_gap"] is not None:
            upd("dnagap", round(E["dna_gap"], 1), f"{E['dna_gap']:+.1f}pp",
                pw(E["dna_gap"], IND["dnagap"]["anchors"]), t["q"])
        if E["debt_prior"]:
            g = (E["debt_now"] / E["debt_prior"] - 1) * 100
            upd("debt", round(g, 1), f"{g:+.1f}%", pw(g, IND["debt"]["anchors"]), t["q"])
    attempt("EDGAR quarterly", f_edgar)

    # ---- 重算維度與綜合 ----
    dims = {}
    for dk in data["dimMeta"]:
        ss = [i["score"] for i in data["indicators"] if i["dim"] == dk]
        dims[dk] = round(sum(ss) / len(ss), 1)
    data["dims"] = dims
    data["composite"] = round(sum(data["dimMeta"][dk]["w"] * dims[dk] for dk in dims), 1)
    tw_scores = [i["score"] for i in data["tw"]["items"]]
    data["tw"]["heat"] = round(sum(tw_scores) / len(tw_scores), 1)

    # ---- history / meta ----
    snap = {"date": str(TODAY), "composite": data["composite"], "dims": dims, "tw": data["tw"]["heat"]}
    hist = [h for h in data["history"] if h["date"] != str(TODAY)]
    hist.append(snap)
    data["history"] = hist[-400:]
    data["meta"]["built"] = str(TODAY)
    data["meta"]["builtTime"] = f"{TODAY}（GitHub Actions 自動更新）"
    data["meta"]["lastAutoRun"] = {"date": str(TODAY), "ok": ok, "fail": fail}

    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    log(f"done. composite={data['composite']} tw={data['tw']['heat']} ok={len(ok)} fail={len(fail)}")
    if fail:
        log("failed sources (old values kept): " + ", ".join(fail))

def selftest():
    assert abs(pw(42.18, [[25, 0], [32, 33], [40, 67], [44.19, 100]]) - 84.2) < 0.1
    assert abs(pw(33.89, [[20, 0], [25, 33], [32, 67], [38, 100]]) - 77.4) < 0.1
    assert abs(pw(75.3, [[40, 0], [60, 33], [80, 67], [110, 100]]) - 59.0) < 0.1
    assert abs(pw(-14, [[-30, 0], [0, 25], [30, 50], [80, 75], [150, 100]]) - 13.3) < 0.1
    assert vix_score(16.73) == 50.0
    # EDGAR 差分 fixture（MSFT FY24：FY 44477 − 9M 30604 = Q4 13873）
    rows = [("2023-07-01", "2023-09-30", 9917), ("2023-10-01", "2023-12-31", 9735),
            ("2024-01-01", "2024-03-31", 10952), ("2023-07-01", "2024-03-31", 30604),
            ("2023-07-01", "2024-06-30", 44477)]
    q = to_quarters(rows, (7, 1))
    assert q[dt.date(2024, 6, 30)] == 13873, q
    print("selftest OK")

if __name__ == "__main__":
    if "--selftest" in sys.argv:
        selftest()
    else:
        main()
