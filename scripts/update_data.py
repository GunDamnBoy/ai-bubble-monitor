#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 泡沫監控儀表板 v2：每日自動更新 data.json（GitHub Actions）。
v2 架構：三層頻率（L1 市場與情緒 35% / L2 資金與信用 35% / L3 基本面兌現 30%）
＋引爆觸發器面板＋象限定位＋台灣供應鏈 v2（月營收/官方PE/融資/集中度/出口）。
原則：任一來源失敗只記錄並沿用舊值，絕不編造、絕不讓整次更新失敗。"""
import json, re, sys, math, datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data.json"
OFFLINE = "--offline" in sys.argv
TODAY = (dt.datetime.utcnow() + dt.timedelta(hours=8)).date()   # 台北日期
UA_DEFAULT = "ai-bubble-monitor/2.0 (github actions; haonung.chiang@gmail.com)"
UA_BROWSER = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
UA_SEC = "Kenny Chiang haonung.chiang@gmail.com"
LOG = []

def log(m):
    LOG.append(str(m)); print(str(m), flush=True)

def http_get(url, ua=None, referer=None):
    if OFFLINE:
        raise RuntimeError("offline mode")
    import requests
    h = {"User-Agent": ua or UA_DEFAULT}
    if referer: h["Referer"] = referer
    r = requests.get(url, headers=h, timeout=45)
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
    if s is None: return "pending"
    return "green" if s < 33 else ("yellow" if s < 67 else ("orange" if s < 84 else "red"))

# ---------------- generic fetchers（v1 驗證過） ----------------
def fred(series, days=620):
    start = (TODAY - dt.timedelta(days=days)).isoformat()
    txt = http_get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}&cosd={start}").text
    out = []
    for line in txt.strip().splitlines()[1:]:
        p = line.split(",")
        if len(p) >= 2 and re.match(r"\d{4}-\d{2}-\d{2}", p[0]):
            try: out.append((dt.date.fromisoformat(p[0]), float(p[1])))
            except ValueError: pass
    if not out: raise RuntimeError(f"FRED {series}: empty")
    return out

def fred_back(obs, back_days):
    """從已取得的 FRED 觀測序列取 back_days 天前的值；序列不夠長回 None。"""
    d_last = obs[-1][0]
    for d, v in reversed(obs):
        if d <= d_last - dt.timedelta(days=back_days):
            return v
    return None

def fred_latest_and_back(series, back_days, days=620):
    obs = fred(series, days)
    d_last, v_last = obs[-1]
    return d_last, v_last, fred_back(obs, back_days)

def stooq(sym, days=1500):
    d1 = (TODAY - dt.timedelta(days=days)).strftime("%Y%m%d")
    txt = http_get(f"https://stooq.com/q/d/l/?s={sym}&i=d&d1={d1}&d2={TODAY.strftime('%Y%m%d')}").text
    out = []
    for line in txt.strip().splitlines()[1:]:
        p = line.split(",")
        if len(p) >= 5 and re.match(r"\d{4}-\d{2}-\d{2}", p[0]):
            try:
                c = float(p[4])
                if c > 0: out.append((dt.date.fromisoformat(p[0]), c))
            except ValueError: pass
    if len(out) < 30: raise RuntimeError(f"stooq {sym}: {len(out)} rows")
    return out

def yahoo_chart(sym, rng="4y"):
    from urllib.parse import quote
    j = http_get(f"https://query1.finance.yahoo.com/v8/finance/chart/{quote(sym)}?range={rng}&interval=1d",
                 ua=UA_BROWSER).json()
    res = j["chart"]["result"][0]
    out = [(dt.datetime.utcfromtimestamp(t).date(), float(c))
           for t, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]) if c]
    if len(out) < 30: raise RuntimeError(f"yahoo {sym}: {len(out)} rows")
    return out

def yf_chart(sym, rng="4y"):
    if OFFLINE: raise RuntimeError("offline mode")
    import yfinance as yf
    df = yf.Ticker(sym).history(period=rng, interval="1d", auto_adjust=False)
    rows = [(idx.date(), float(c)) for idx, c in df["Close"].items() if c and c > 0]
    if len(rows) < 30: raise RuntimeError(f"yfinance {sym}: {len(rows)} rows")
    return rows

def px_rows(ysym, ssym=None, rng="4y"):
    errs = []
    for fn in (lambda: yf_chart(ysym, rng), lambda: yahoo_chart(ysym, rng)):
        try: return fn()
        except Exception as e: errs.append(str(e)[:70])
    if ssym:
        try: return stooq(ssym)
        except Exception as e: errs.append(str(e)[:70])
    raise RuntimeError(" / ".join(errs))

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

def gsy_stats(rows):
    """Greenwood-Shleifer 統計：24個月漲幅、加速度、波動率一年變化（需約3年資料）。"""
    closes = [c for _, c in rows]
    n = len(closes)
    st = {}
    if n >= 505:
        st["ret24"] = (closes[-1] / closes[-505] - 1) * 100
    if n >= 758:
        prior24 = (closes[-253] / closes[-758] - 1) * 100
        st["accel"] = st["ret24"] - prior24
    if n >= 505:
        def vol(seg):
            rets = [math.log(seg[i] / seg[i - 1]) for i in range(1, len(seg)) if seg[i - 1] > 0]
            m = sum(rets) / len(rets)
            return math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1)) * math.sqrt(252) * 100
        st["vol1y"] = vol(closes[-253:])
        st["volchg"] = st["vol1y"] - vol(closes[-505:-252])
    return st

def multpl_cape():
    html = http_get("https://www.multpl.com/shiller-pe").text
    m = re.search(r'id="current"[^>]*>.*?([0-9]{1,3}\.[0-9]{1,2})', html, re.S) or \
        re.search(r"Shiller PE Ratio[^0-9]{0,60}([0-9]{1,3}\.[0-9]{1,2})", html, re.S)
    if not m: raise RuntimeError("multpl: pattern not found")
    v = float(m.group(1))
    if not (5 < v < 80): raise RuntimeError(f"multpl: implausible {v}")
    return v

def slickcharts_mag7():
    html = http_get("https://www.slickcharts.com/sp500").text
    w = {}
    for t in ["NVDA", "AAPL", "MSFT", "AMZN", "GOOGL", "GOOG", "META", "TSLA"]:
        m = re.search(r">" + t + r"</a></td>\s*<td[^>]*>([0-9.]+)%?</td>", html) or \
            re.search(r"/symbol/" + t + r'"[^>]*>[^<]*</a>.*?([0-9]{1,2}\.[0-9]{2})%', html, re.S)
        if m: w[t] = float(m.group(1))
    if len(w) < 8: raise RuntimeError(f"slickcharts: {len(w)}/8")
    return sum(w.values())

# ---------------- v2 新增：情緒與信用 ----------------
def aaii_sentiment():
    html = http_get("https://www.aaii.com/sentimentsurvey/sent_results", ua=UA_BROWSER).text
    rows = re.findall(
        r"(\d{1,2}/\d{1,2}/\d{4})[^%]{0,400}?([0-9]{1,2}\.[0-9])%[^%]{0,200}?([0-9]{1,2}\.[0-9])%[^%]{0,200}?([0-9]{1,2}\.[0-9])%",
        html, re.S)
    if not rows: raise RuntimeError("aaii: no rows parsed")
    d, bull, neu, bear = rows[0]
    m, dd, y = d.split("/")
    return dt.date(int(y), int(m), int(dd)), float(bull), float(neu), float(bear)

def cboe_putcall():
    html = http_get("https://www.cboe.com/us/options/market_statistics/daily/", ua=UA_BROWSER,
                    referer="https://www.cboe.com/").text
    def grab(label):
        m = re.search(label + r"[^0-9]{0,120}?([0-9]\.[0-9]{1,3})", html, re.S | re.I)
        return float(m.group(1)) if m else None
    eq = grab(r"EQUITY PUT/CALL RATIO")
    if eq is None: raise RuntimeError("cboe: equity ratio not found")
    return {"equity": eq, "total": grab(r"TOTAL PUT/CALL RATIO"), "index": grab(r"INDEX PUT/CALL RATIO")}

def orcl_bond_yield():
    html = http_get("https://public.com/bonds/corporate/oracle-corp/orcl-4.375-05-15-2055-68389xbg9",
                    ua=UA_BROWSER).text
    m = re.search(r"([0-9]{1,2}\.[0-9]{1,2})%\s*(?:YTM|[Yy]ield)", html) or \
        re.search(r"[Yy]ield[^0-9]{0,30}([0-9]{1,2}\.[0-9]{1,2})", html)
    if not m: raise RuntimeError("public.com: yield not found")
    v = float(m.group(1))
    if not (2 < v < 20): raise RuntimeError(f"orcl bond implausible {v}")
    return v

# ---------------- v2 新增：RPO 合約儲備 ----------------
RPO_CIKS = {"MSFT": "0000789019", "GOOGL": "0001652044", "ORCL": "0001341439"}

def rpo_backlog():
    tot_now = tot_prior = 0.0
    det = []
    for co, cik in RPO_CIKS.items():
        j = http_get(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/RevenueRemainingPerformanceObligation.json",
                     ua=UA_SEC).json()
        pts = {}
        for u in j.get("units", {}).get("USD", []):
            if u.get("end") and u.get("val") is not None:
                pts[u["end"]] = max(pts.get(u["end"], 0), float(u["val"]))
        if not pts: continue
        ends = sorted(pts)
        latest = ends[-1]
        target = dt.date.fromisoformat(latest) - dt.timedelta(days=365)
        prior = min(ends, key=lambda e: abs((dt.date.fromisoformat(e) - target).days))
        if abs((dt.date.fromisoformat(prior) - target).days) > 75: continue
        tot_now += pts[latest]; tot_prior += pts[prior]
        det.append(f"{co} ${pts[latest] / 1e9:.0f}B({latest[:7]})")
    if tot_prior <= 0: raise RuntimeError("rpo: insufficient history")
    return (tot_now / tot_prior - 1) * 100, tot_now / 1e9, "＋".join(det)

# ---------------- v2 新增：台灣公開數據 ----------------
TW_BASKET = [("2330", "台積電", "晶圓代工"), ("2317", "鴻海", "AI伺服器組裝"), ("2382", "廣達", "AI伺服器ODM"),
             ("3231", "緯創", "ODM/GPU板"), ("6669", "緯穎", "CSP直供伺服器"), ("3017", "奇鋐", "散熱"),
             ("2308", "台達電", "電源/液冷"), ("3661", "世芯-KY", "ASIC"), ("3443", "創意", "ASIC"),
             ("2345", "智邦", "交換器")]

def tw_monthly_rev():
    arr = http_get("https://openapi.twse.com.tw/v1/opendata/t187ap05_L", ua=UA_BROWSER).json()
    idx = {r.get("公司代號"): r for r in arr}
    table, wsum, wtot = [], 0.0, 0.0
    month = None
    for code, name, role in TW_BASKET:
        r = idx.get(code)
        if not r: continue
        try:
            yoy = float(r["營業收入-去年同月增減(%)"])
            mom = float(r["營業收入-上月比較增減(%)"])
            rev = float(r["營業收入-當月營收"])
        except (KeyError, ValueError, TypeError):
            continue
        month = r.get("資料年月", month)
        table.append({"code": code, "name": name, "role": role,
                      "yoy": round(yoy, 1), "mom": round(mom, 1), "rev": round(rev / 1e6, 1)})
        wsum += yoy * rev; wtot += rev
    if not table or wtot <= 0: raise RuntimeError("tw rev: no basket rows")
    comp = wsum / wtot
    if month and len(month) == 5:
        month = f"{int(month[:3]) + 1911}-{month[3:]}"
    return round(comp, 1), table, month

def tw_bwibbu():
    arr = http_get("https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL", ua=UA_BROWSER).json()
    idx = {r.get("Code"): r for r in arr}
    out = {}
    for code, name, _ in TW_BASKET:
        r = idx.get(code)
        if r:
            try:
                out[code] = {"pe": float(r["PEratio"]) if r["PEratio"] else None,
                             "pb": float(r["PBratio"]) if r["PBratio"] else None}
            except (ValueError, TypeError):
                pass
    if "2330" not in out or not out["2330"]["pe"]: raise RuntimeError("bwibbu: no 2330")
    d = arr[0].get("Date", "")
    if len(d) == 7: d = f"{int(d[:3]) + 1911}-{d[3:5]}-{d[5:]}"
    return out, d

def tw_margin_balance():
    for back in range(0, 10):
        d = (TODAY - dt.timedelta(days=back)).strftime("%Y%m%d")
        try:
            j = http_get(f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json&date={d}&selectType=MS",
                         ua=UA_BROWSER).json()
        except Exception:
            continue
        if j.get("stat") == "OK":
            tables = j.get("tables") or [j]
            for t in tables:
                for row in t.get("data", []):
                    if row and "融資金額" in str(row[0]):
                        bal = float(str(row[-1]).replace(",", "")) / 1e6   # 仟元→十億元
                        return d, round(bal, 1)
    raise RuntimeError("margin: no trading day found in 10 days")

def tw_index_today():
    arr = http_get("https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX", ua=UA_BROWSER).json()
    taiex = elec = None
    d = None
    for r in arr:
        nm = r.get("指數", "")
        try:
            if nm == "發行量加權股價指數":
                taiex = float(str(r["收盤指數"]).replace(",", "")); d = r.get("日期")
            elif "電子" in nm and elec is None and "報酬" not in nm:
                elec = float(str(r["收盤指數"]).replace(",", ""))
        except (ValueError, TypeError, KeyError):
            continue
    if not taiex or not elec: raise RuntimeError("mi_index: missing taiex/elec")
    if d and len(d) == 7: d = f"{int(d[:3]) + 1911}-{d[3:5]}-{d[5:]}"
    return d or str(TODAY), taiex, elec

def taifex_tsmc_weight():
    html = http_get("https://www.taifex.com.tw/cht/9/futuresQADetail", ua=UA_BROWSER).text
    m = re.search(r"2330[^0-9%]{0,120}?([0-9]{1,2}\.[0-9]{1,4})\s*%", html, re.S)
    if not m: raise RuntimeError("taifex: 2330 weight not found")
    v = float(m.group(1))
    if not (15 < v < 70): raise RuntimeError(f"taifex implausible {v}")
    return v

def tw_customs_export_yoy():
    txt = http_get("https://opendata.customs.gov.tw/data/6053/csv.csv", ua=UA_BROWSER).text
    rows = []
    for line in txt.splitlines()[1:]:
        p = [x.strip().strip('"') for x in line.split(",")]
        if len(p) >= 3 and p[0].isdigit() and p[1].isdigit():
            try: rows.append((int(p[0]), int(p[1]), float(p[2])))
            except ValueError: pass
    if len(rows) < 14: raise RuntimeError("customs: too few rows")
    y, mth, v = rows[0]
    prior = [r for r in rows if r[0] == y - 1 and r[1] == mth]
    if not prior or prior[0][2] <= 0: raise RuntimeError("customs: no prior year row")
    return f"{y + 1911}-{mth:02d}", (v / prior[0][2] - 1) * 100

# ---------------- 新聞（v1 驗證過） ----------------
NEWS_QUERIES = [
    '"AI bubble" when:4d',
    '(hyperscaler OR "data center") (capex OR debt OR financing OR bonds) when:4d',
    '(Nvidia OR OpenAI OR Anthropic) (deal OR funding OR investment OR IPO) when:4d',
    '(TSMC OR Samsung OR semiconductor) (stocks OR earnings OR selloff OR rally) when:4d',
    '("AI trade" OR "AI stocks") (Wall Street OR market OR investors) when:3d',
]
NEWS_W = {"bloomberg": 5, "reuters": 5, "financial times": 5, "the wall street journal": 5, "wsj": 5,
          "cnbc": 4, "barron's": 4, "the information": 4, "the economist": 4, "axios": 3,
          "fortune": 3, "marketwatch": 3, "nikkei asia": 3, "semafor": 3, "techcrunch": 2,
          "business insider": 2, "yahoo finance": 2, "investor's business daily": 2}
NEWS_BAN = {"globenewswire", "pr newswire", "business wire", "the motley fool", "simply wall st",
            "zacks investment research", "benzinga", "stocktwits", "openpr", "seeking alpha"}

def _parse_news_items(xmltxt):
    import xml.etree.ElementTree as ET
    from email.utils import parsedate_to_datetime
    out = []
    for it in ET.fromstring(xmltxt).iter("item"):
        try:
            title = (it.findtext("title") or "").strip()
            link = (it.findtext("link") or "").strip()
            pd = parsedate_to_datetime(it.findtext("pubDate"))
            s = it.find("source")
            src = (s.text or "").strip() if s is not None else ""
            if not title or not link or pd is None: continue
            if title.endswith(" - " + src): title = title[: -(len(src) + 3)].strip()
            out.append({"title": title, "url": link, "src": src, "pd": pd})
        except Exception:
            continue
    return out

def fetch_news(max_items=12):
    from urllib.parse import quote
    items, seen = [], set()
    now = dt.datetime.now(dt.timezone.utc)
    for q in NEWS_QUERIES:
        try:
            raw = _parse_news_items(http_get("https://news.google.com/rss/search?q=" + quote(q) +
                                             "&hl=en-US&gl=US&ceid=US:en", ua=UA_BROWSER).text)
        except Exception as ex:
            log(f"  news query fail: {ex}"); continue
        for x in raw:
            if x["src"].lower() in NEWS_BAN: continue
            key = re.sub(r"\W+", "", x["title"].lower())[:70]
            if key in seen: continue
            age = max(0.0, (now - x["pd"]).total_seconds() / 86400)
            if age > 5: continue
            seen.add(key)
            x["score"] = NEWS_W.get(x["src"].lower(), 1) * 2 + max(0.0, 4 - age * 1.5)
            items.append(x)
    if len(items) < 5: raise RuntimeError(f"news: {len(items)} items")
    items.sort(key=lambda x: x["score"], reverse=True)
    per, picked = {}, []
    for x in items:
        if per.get(x["src"], 0) >= 3: continue
        per[x["src"]] = per.get(x["src"], 0) + 1
        picked.append(x)
        if len(picked) >= max_items: break
    picked.sort(key=lambda x: x["pd"], reverse=True)
    tz8 = dt.timezone(dt.timedelta(hours=8))
    return [{"d": x["pd"].astimezone(tz8).strftime("%m-%d"),
             "t": x["title"] + ("｜" + x["src"] if x["src"] else ""), "url": x["url"]} for x in picked]

# ---------------- EDGAR 季度引擎（v1）＋初步季度 nowcast（v2） ----------------
CIK = {"MSFT": "0000789019", "AMZN": "0001018724", "GOOGL": "0001652044",
       "META": "0001326801", "ORCL": "0001341439"}
FY_START = {"MSFT": (7, 1), "AMZN": (1, 1), "GOOGL": (1, 1), "META": (1, 1), "ORCL": (6, 1)}
CONCEPTS = {
    "capex": {"*": ["PaymentsToAcquirePropertyPlantAndEquipment"],
              "AMZN": ["PaymentsToAcquireProductiveAssets", "PaymentsToAcquirePropertyPlantAndEquipment"]},
    "ocf":   {"*": ["NetCashProvidedByUsedInOperatingActivities",
                    "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]},
    "dep":   {"*": ["Depreciation", "DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet"],
              "AMZN": ["DepreciationDepletionAndAmortization", "Depreciation"]},
    "rev":   {"*": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues"]},
    "debt":  {"*": ["LongTermDebtNoncurrent", "LongTermDebt"],
              "ORCL": ["LongTermNotesPayable", "LongTermDebtNoncurrent"]},
}

def edgar_rows(co, names, min_end="2023-06-01"):
    import time
    for name in names:
        try:
            time.sleep(0.2)
            j = http_get(f"https://data.sec.gov/api/xbrl/companyconcept/CIK{CIK[co]}/us-gaap/{name}.json",
                         ua=UA_SEC).json()
        except Exception as ex:
            log(f"    edgar {co}/{name}: {ex}"); continue
        rows, seen = [], set()
        for u in j.get("units", {}).get("USD", []):
            end = u.get("end")
            if not end or end < min_end or u.get("val") is None: continue
            k = (u.get("start"), end)
            if k in seen: continue
            seen.add(k)
            rows.append((u.get("start"), end, float(u["val"])))
        if rows: return name, rows
    return None, []

def to_quarters(rows, fy_start):
    D = dt.date.fromisoformat
    out = {}
    parsed = [(D(s) if s else None, D(e), v) for s, e, v in rows]
    for s, e, v in parsed:
        if s and 80 <= (e - s).days <= 100: out[e] = v
    chains = {}
    for s, e, v in parsed:
        if s and (s.month, s.day) == fy_start: chains.setdefault(s, []).append((e, v))
    for s, ch in chains.items():
        ch = sorted(set(ch))
        fe, fv = ch[0]
        if 80 <= (fe - s).days <= 100 and fe not in out: out[fe] = fv
        prev = None
        for e, v in ch:
            if prev and 80 <= (e - prev[0]).days <= 100 and e not in out: out[e] = v - prev[1]
            prev = (e, v)
    return dict(sorted(out.items()))

def bucket(d):
    q = {1: 1, 2: 1, 3: 1, 4: 2, 5: 2, 6: 2, 7: 3, 8: 3, 9: 3, 10: 4, 11: 4, 12: 4}[d.month]
    return f"{d.year}Q{q}"

def refresh_edgar(data):
    cos = list(CIK)
    Q = {}
    for co in cos:
        for m in ("capex", "ocf"):
            tag, rows = edgar_rows(co, CONCEPTS[m].get(co, CONCEPTS[m]["*"]))
            if not rows: raise RuntimeError(f"EDGAR {co} {m}: no data")
            Q.setdefault(co, {})[m] = to_quarters(rows, FY_START[co])
    BQ = {}
    for co in cos:
        for m in ("capex", "ocf"):
            for e, v in Q[co][m].items():
                BQ.setdefault(bucket(e), {}).setdefault(m, {})[co] = v
    labels = sorted(BQ)
    agg = []
    for lb in labels:
        row = BQ[lb]
        have = [c for c in cos if c in row.get("capex", {}) and c in row.get("ocf", {})]
        if len(have) == 5:
            cx = sum(row["capex"][c] for c in cos) / 1e9
            oc = sum(row["ocf"][c] for c in cos) / 1e9
            agg.append({"q": lb, "capex": round(cx, 1), "ocf": round(oc, 1),
                        "fcf": round(oc - cx, 1), "ratio": round(100 * cx / oc, 1)})
    agg = [a for a in agg if a["q"] >= "2023Q3"]
    if len(agg) < 8: raise RuntimeError(f"EDGAR agg: {len(agg)} quarters")
    # ---- 初步季度（≥3/5 到齊，缺者沿用其最近一季值）----
    prov = None
    nxt = [lb for lb in labels if lb > agg[-1]["q"]]
    if nxt:
        lb = nxt[0]; row = BQ[lb]
        have = [c for c in cos if c in row.get("capex", {}) and c in row.get("ocf", {})]
        if len(have) >= 3:
            cx = oc = 0.0
            missing = [c for c in cos if c not in have]
            for c in cos:
                if c in have:
                    cx += row["capex"][c]; oc += row["ocf"][c]
                else:
                    cx += Q[c]["capex"][sorted(Q[c]["capex"])[-1]]
                    oc += Q[c]["ocf"][sorted(Q[c]["ocf"])[-1]]
            prov = {"q": lb, "capex": round(cx / 1e9, 1), "ocf": round(oc / 1e9, 1),
                    "fcf": round((oc - cx) / 1e9, 1), "ratio": round(100 * cx / oc, 1),
                    "prov": True, "have": len(have), "missing": missing}
    ttm = []
    for i in range(3, len(agg)):
        w = agg[i - 3:i + 1]
        cx = sum(x["capex"] for x in w); oc = sum(x["ocf"] for x in w)
        ttm.append({"q": w[-1]["q"], "capex": round(cx, 1), "ocf": round(oc, 1),
                    "fcf": round(oc - cx, 1), "ratio": round(100 * cx / oc, 1)})
    ttm_prov = None
    if prov:
        w = agg[-3:] + [prov]
        cx = sum(x["capex"] for x in w); oc = sum(x["ocf"] for x in w)
        ttm_prov = {"q": prov["q"], "capex": round(cx, 1), "ocf": round(oc, 1),
                    "fcf": round(oc - cx, 1), "ratio": round(100 * cx / oc, 1), "prov": True}
    dna_g, rev_g = [], []
    for co in cos:
        try:
            _, dro = edgar_rows(co, CONCEPTS["dep"].get(co, CONCEPTS["dep"]["*"]))
            _, rro = edgar_rows(co, CONCEPTS["rev"].get(co, CONCEPTS["rev"]["*"]))
            if co == "GOOGL":
                _, extra = edgar_rows(co, ["Revenues"])
                seen = {(s, e) for s, e, _ in rro}
                rro += [r for r in extra if (r[0], r[1]) not in seen]
            dq, rq = to_quarters(dro, FY_START[co]), to_quarters(rro, FY_START[co])
            def yoy(qd):
                ends = sorted(qd); le = ends[-1]
                pri = [e for e in ends if abs((le - dt.timedelta(days=365) - e).days) <= 20]
                return (qd[le] / qd[pri[-1]] - 1) * 100 if pri and qd[pri[-1]] else None
            g1, g2 = yoy(dq), yoy(rq)
            if g1 is not None and g2 is not None:
                dna_g.append(g1); rev_g.append(g2)
        except Exception as ex:
            log(f"  dnagap {co}: skip ({ex})")
    debt_now = debt_prior = 0.0
    debt_series = {}
    for co in cos:
        _, dr = edgar_rows(co, CONCEPTS["debt"].get(co, CONCEPTS["debt"]["*"]), min_end="2023-09-01")
        pts = sorted({(dt.date.fromisoformat(e), v) for _, e, v in dr})
        if not pts: raise RuntimeError(f"EDGAR {co} debt: no data")
        le, lv = pts[-1]
        debt_now += lv
        pri = [v for e, v in pts if (le - e).days >= 330]
        debt_prior += pri[-1] if pri else lv
        debt_series[co] = pts
    grid = sorted({q["q"] for q in agg if q["q"] >= "2023Q4"} | ({prov["q"]} if prov else set()))
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
        if full: debt_chart.append((lb, round(tot / 1e9, 1)))
    return {"agg": agg, "prov": prov, "ttm": ttm, "ttm_prov": ttm_prov,
            "dna_gap": (sum(dna_g) / len(dna_g) - sum(rev_g) / len(rev_g)) if len(dna_g) >= 4 else None,
            "debt_now": debt_now / 1e9, "debt_prior": debt_prior / 1e9, "debt_chart": debt_chart}

# ---------------- main ----------------
def main():
    data = json.loads(DATA.read_text())
    IND = {i["id"]: i for i in data["indicators"]}
    params = data.setdefault("params", {})
    params.setdefault("nvda_eps", 6.31); params.setdefault("tsmc_eps", 86.27)
    params.setdefault("ngdp_nominal", 4.9); params.setdefault("megaipo_done", False)
    sp = data["charts"].setdefault("spreads", {})
    tw = data["tw"]
    ok, fail = [], []

    def upd(iid, value, disp, score, asof=None, sub=None):
        i = IND[iid]
        i["value"], i["disp"] = value, disp
        i["score"] = round(score, 1) if score is not None else None
        i["zone"] = zone(i["score"])
        i["asof"] = asof or str(TODAY)
        i["fresh"] = "ok"
        if sub is not None: i["sub"] = sub

    def attempt(name, fn):
        try:
            fn(); ok.append(name)
        except Exception as ex:
            fail.append(name); log(f"[FAIL] {name}: {ex}")

    # ============ L1 市場與情緒 ============
    S = {}
    def f_px(key, y, s, rng):
        def go(): S[key] = px_rows(y, s, rng)
        return go
    attempt("px SOXX", f_px("soxx", "SOXX", "soxx.us", "4y"))
    attempt("px SPY", f_px("spy", "SPY", "spy.us", "2y"))
    attempt("px NVDA", f_px("nvda", "NVDA", "nvda.us", "2y"))
    attempt("px 2330", f_px("2330", "2330.TW", "2330.tw", "2y"))

    def f_gsy():
        g = gsy_stats(S["soxx"])
        if "ret24" not in g: raise RuntimeError("insufficient history")
        st = series_stats(S["soxx"])
        upd("gsy_runup", round(g["ret24"], 1), f"{g['ret24']:+.0f}%（24個月）",
            pw(g["ret24"], IND["gsy_runup"]["anchors"]), str(st["date"]),
            sub="文獻校準：≥100%→其後24個月崩盤率53%、≥150%→80%（Greenwood-Shleifer）")
        if "accel" in g:
            upd("gsy_accel", round(g["accel"], 1), f"{g['accel']:+.0f}pp",
                pw(g["accel"], IND["gsy_accel"]["anchors"]), str(st["date"]))
        if "volchg" in g:
            upd("volchg", round(g["volchg"], 1), f"{g['volchg']:+.1f}pp（年化 {g['vol1y']:.0f}%）",
                pw(g["volchg"], IND["volchg"]["anchors"]), str(st["date"]))
    if "soxx" in S: attempt("calc GSY", f_gsy)

    def f_mom():
        a, b = series_stats(S["soxx"]), series_stats(S["spy"])
        mom = a["chg3m"] - b["chg3m"]
        upd("soxmom", round(mom, 1), f"{mom:+.0f}pp", pw(mom, IND["soxmom"]["anchors"]), str(a["date"]))
    if "soxx" in S and "spy" in S: attempt("calc soxmom", f_mom)

    def f_nvda():
        st = series_stats(S["nvda"])
        pe = st["close"] / params["nvda_eps"]
        upd("nvdape", round(pe, 2), f"{pe:.1f}×", pw(pe, IND["nvdape"]["anchors"]), str(st["date"]),
            sub=f"距200日線 {((st['close'] / st['dma200']) - 1) * 100:+.1f}%")
    if "nvda" in S: attempt("calc nvdape", f_nvda)

    def f_cape():
        v = multpl_cape(); upd("cape", v, f"{v:.1f}×", pw(v, IND["cape"]["anchors"]))
    def f_mag7():
        v = slickcharts_mag7(); upd("mag7", round(v, 2), f"{v:.1f}%", pw(v, IND["mag7"]["anchors"]))
    attempt("multpl CAPE", f_cape); attempt("slickcharts Mag7", f_mag7)

    senti = {}
    def f_aaii():
        d, bull, neu, bear = aaii_sentiment()
        senti["aaii"] = {"spread": bull - bear, "date": str(d)}
    def f_pc():
        senti["pc"] = cboe_putcall()
    def f_vixv():
        d, v, _ = fred_latest_and_back("VIXCLS", 0)
        senti["vix"] = {"v": v, "date": str(d)}
        sp["vix"] = {"now": v, "asof": str(d)}
    attempt("AAII", f_aaii); attempt("CBOE putcall", f_pc); attempt("FRED VIX", f_vixv)
    def f_senti():
        parts, notes = [], []
        if "aaii" in senti:
            parts.append(pw(senti["aaii"]["spread"], [[-25, 5], [0, 40], [20, 75], [35, 100]]))
            notes.append(f"AAII多空差 {senti['aaii']['spread']:+.1f}pp")
        if "pc" in senti and senti["pc"].get("equity"):
            parts.append(pw(-senti["pc"]["equity"], [[-1.0, 10], [-0.8, 33], [-0.62, 67], [-0.45, 100]]))
            notes.append(f"個股P/C {senti['pc']['equity']:.2f}")
        if "vix" in senti:
            parts.append(vix_score(senti["vix"]["v"]))
            notes.append(f"VIX {senti['vix']['v']:.1f}")
        if not parts: raise RuntimeError("no sentiment inputs")
        upd("senti", round(sum(parts) / len(parts), 1), "｜".join(notes), sum(parts) / len(parts),
            sub="AAII（週）＋CBOE 個股 Put/Call（日）＋VIX（日）等權合成")
    attempt("calc senti", f_senti)

    # ============ L2 資金與信用 ============
    def f_hy():
        obs = fred("BAMLH0A0HYM2")
        d, v = obs[-1]; b = fred_back(obs, 91)
        d3 = (v - b) * 100 if b is not None else 0.0
        upd("hyoas", v, f"{v:.2f}%（3個月 {d3:+.0f}bp）", pw(d3, IND["hyoas"]["anchors"]), str(d))
        sp["hy"] = {"now": v, "m3": b, "y1": fred_back(obs, 365), "asof": str(d)}
    def f_ccc():
        d, v, b = fred_latest_and_back("BAMLH0A3HYC", 91)
        d3 = (v - b) * 100 if b is not None else 0.0
        s = (pw(v, IND["ccc"]["anchors"]) + pw(d3, [[-50, 0], [0, 33], [100, 67], [250, 100]])) / 2
        upd("ccc", v, f"{v:.2f}%（3個月 {d3:+.0f}bp）", s, str(d),
            sub="最弱信用層日頻壓力計；2022 熊市高點約 12%")
        sp["ccc"] = {"now": v, "m3": b, "asof": str(d)}
    def f_orclbond():
        v = orcl_bond_yield()
        upd("orclbond", v, f"{v:.2f}%", pw(v, IND["orclbond"]["anchors"]))
        sp["orclbond"] = {"now": v, "asof": str(TODAY)}
    def f_ig():
        obs = fred("BAMLC0A0CM")
        d, v = obs[-1]
        sp["ig"] = {"now": v, "m3": fred_back(obs, 91), "asof": str(d)}
    def f_fedfunds():
        obs = fred("FEDFUNDS")
        d, v = obs[-1]
        sp["fedfunds"] = {"now": v, "y1": fred_back(obs, 365), "asof": str(d)}
    def f_usinfo():
        obs = fred("USINFO")
        d, v = obs[-1]
        sp["usinfo"] = {"now": v, "y1": fred_back(obs, 365), "asof": str(d)}
    attempt("FRED HY", f_hy); attempt("FRED CCC", f_ccc)
    attempt("ORCL bond", f_orclbond); attempt("FRED IG", f_ig)
    attempt("FRED FEDFUNDS 磚塊", f_fedfunds); attempt("FRED USINFO 磚塊", f_usinfo)

    # ============ L3 基本面兌現 ============
    def f_rpo():
        yoy, tot, det = rpo_backlog()
        upd("rpo", round(yoy, 1), f"+{yoy:.0f}%（合計 ${tot:.0f}B）",
            pw(-yoy, [[-60, 0], [-35, 25], [-15, 55], [0, 80], [15, 100]]), sub=det)
    attempt("EDGAR RPO", f_rpo)

    def f_edgar():
        E = refresh_edgar(data)
        data["charts"]["aggQ"] = E["agg"] + ([E["prov"]] if E["prov"] else [])
        data["charts"]["ttm"] = E["ttm"] + ([E["ttm_prov"]] if E["ttm_prov"] else [])
        if E["debt_chart"]:
            data["charts"]["debt"]["labels"] = [x[0] for x in E["debt_chart"]]
            data["charts"]["debt"]["values"] = [x[1] for x in E["debt_chart"]]
        t = E["ttm"][-1]
        sub = f"官方最新單季 {E['agg'][-1]['ratio']:.1f}%"
        if E["prov"]:
            sub = (f"{E['prov']['q']} 初步：單季 {E['prov']['ratio']:.1f}%、TTM {E['ttm_prov']['ratio']:.1f}%"
                   f"（{E['prov']['have']}/5 家已申報，缺 {'/'.join(E['prov']['missing'])} 沿用上季）")
        upd("capexocf", t["ratio"], f"{t['ratio']:.1f}%", pw(t["ratio"], IND["capexocf"]["anchors"]), t["q"], sub=sub)
        if len(E["ttm"]) >= 5 and E["ttm"][-5]["fcf"]:
            g = (t["fcf"] / E["ttm"][-5]["fcf"] - 1) * 100
            upd("fcf", round(g, 1), f"{g:+.1f}%", pw(g, IND["fcf"]["anchors"]), t["q"],
                sub=f"TTM FCF ${t['fcf']}B" + (f"｜初步 ${E['ttm_prov']['fcf']}B" if E["ttm_prov"] else ""))
        if E["dna_gap"] is not None:
            upd("dnagap", round(E["dna_gap"], 1), f"{E['dna_gap']:+.1f}pp",
                pw(E["dna_gap"], IND["dnagap"]["anchors"]), t["q"])
        if E["debt_prior"]:
            g = (E["debt_now"] / E["debt_prior"] - 1) * 100
            upd("debt", round(g, 1), f"{g:+.1f}%", pw(g, IND["debt"]["anchors"]), t["q"],
                sub=f"合計 ${E['debt_now']:.0f}B")
    attempt("EDGAR quarterly", f_edgar)

    # ============ 台灣供應鏈 v2 ============
    TWI = {i["id"]: i for i in tw["items"]}
    def tupd(iid, value, disp, score, asof=None):
        t = TWI[iid]
        t["value"], t["disp"] = value, disp
        t["score"] = round(score, 1) if score is not None else None
        t["asof"] = asof or str(TODAY)

    def f_twrev():
        comp, table, month = tw_monthly_rev()
        tw["revTable"] = table; tw["revMonth"] = month
        tupd("tw_rev", comp, f"加權年增 {comp:+.1f}%",
             pw(-comp, [[-90, 5], [-45, 20], [-12, 45], [0, 65], [15, 90]]), month or str(TODAY))
    attempt("TW 月營收", f_twrev)

    def f_twpe():
        pes, d = tw_bwibbu()
        tw["officialPE"] = pes
        pe = pes["2330"]["pe"]
        tupd("tsmc_pe", pe, f"{pe:.1f}×（官方）", pw(pe, [[15, 0], [22, 33], [28, 67], [35, 100]]), d)
        odm = [pes[c]["pe"] for c in ["2317", "2382", "3231", "6669"] if c in pes and pes[c]["pe"]]
        if odm:
            avg = sum(odm) / len(odm)
            tupd("odm_pe", round(avg, 1), f"平均 {avg:.1f}×（官方）",
                 pw(avg, [[10, 0], [15, 33], [20, 67], [28, 100]]), d)
    attempt("TW 官方PE", f_twpe)

    def f_tw2330():
        st = series_stats(S["2330"])
        dev = (st["close"] / st["dma200"] - 1) * 100
        tupd("tsmc_200dma", round(dev, 1), f"{dev:+.1f}%",
             pw(dev, [[0, 0], [15, 33], [30, 67], [50, 100]]), str(st["date"]))
        if "chg52w" in st:
            tupd("tsmc_52w", round(st["chg52w"], 1), f"{st['chg52w']:+.1f}%",
                 pw(st["chg52w"], [[20, 0], [50, 33], [90, 67], [150, 100]]), str(st["date"]))
        if "pos52w" in st:
            tupd("twii_pos", round(st["pos52w"], 1), f"{st['pos52w']:.1f}%",
                 pw(st["pos52w"], [[50, 0], [75, 33], [90, 67], [100, 100]]), str(st["date"]))
    if "2330" in S: attempt("calc TW 2330", f_tw2330)

    def f_twidx():
        d, taiex, elec = tw_index_today()
        hist = tw.setdefault("idx_hist", [])
        if not hist or hist[-1]["d"] != d:
            hist.append({"d": d, "taiex": taiex, "elec": elec})
        tw["idx_hist"] = hist[-90:]
        if len(hist) >= 21:
            rel = (hist[-1]["elec"] / hist[-21]["elec"] - 1) * 100 - (hist[-1]["taiex"] / hist[-21]["taiex"] - 1) * 100
            tupd("elec_rel", round(rel, 1), f"{rel:+.1f}pp（20日）",
                 pw(rel, [[-3, 15], [0, 35], [4, 67], [10, 100]]), d)
        else:
            tupd("elec_rel", None, f"序列累積中（{len(hist)}/21 交易日）", None, d)
    attempt("TW 電子指數", f_twidx)

    def f_twmargin():
        d, bal = tw_margin_balance()
        dd = f"{d[:4]}-{d[4:6]}-{d[6:]}"
        hist = tw.setdefault("margin_hist", [])
        if not hist or hist[-1]["d"] != dd:
            hist.append({"d": dd, "bal": bal})
        tw["margin_hist"] = hist[-90:]
        if len(hist) >= 21:
            g = (hist[-1]["bal"] / hist[-21]["bal"] - 1) * 100
            tupd("tw_margin", bal, f"{bal:.0f} 十億元（20日 {g:+.1f}%）",
                 pw(g, [[-4, 10], [0, 35], [5, 67], [12, 100]]), dd)
        else:
            tupd("tw_margin", bal, f"{bal:.0f} 十億元（序列累積中 {len(hist)}/21）", None, dd)
    attempt("TW 融資餘額", f_twmargin)

    def f_twweight():
        v = taifex_tsmc_weight()
        tupd("tsmc_weight", v, f"{v:.2f}%", pw(v, [[30, 20], [38, 50], [45, 80], [52, 100]]))
    attempt("TW 台積電權重", f_twweight)

    def f_twexport():
        month, yoy = tw_customs_export_yoy()
        tupd("tw_export", round(yoy, 1), f"{yoy:+.1f}%（{month}）",
             pw(-yoy, [[-50, 10], [-20, 30], [0, 60], [10, 85]]), month)
    attempt("TW 海關出口", f_twexport)

    subs_def = {"動能": ["tsmc_200dma", "tsmc_52w", "elec_rel", "twii_pos"],
                "估值": ["tsmc_pe", "odm_pe"],
                "籌碼": ["tw_margin"],
                "基本面": ["tw_rev", "tw_export"]}
    subs = {}
    for k, ids in subs_def.items():
        ss = [TWI[i]["score"] for i in ids if i in TWI and TWI[i].get("score") is not None]
        subs[k] = round(sum(ss) / len(ss), 1) if ss else None
    tw["subs"] = subs
    wmap = {"動能": 0.3, "估值": 0.3, "籌碼": 0.2, "基本面": 0.2}
    valid = {k: v for k, v in subs.items() if v is not None}
    wsum = sum(wmap[k] for k in valid)
    if wsum: tw["heat"] = round(sum(v * wmap[k] for k, v in valid.items()) / wsum, 1)

    # ============ 引爆觸發器 ============
    trig_vals = {}
    def f_cpi():
        obs = fred("CPIAUCSL", days=800)
        base = [v for d, v in obs if d <= obs[-1][0] - dt.timedelta(days=360)]
        trig_vals["cpi"] = ((obs[-1][1] / base[-1] - 1) * 100, obs[-1][0])
    def f_ff():
        d, v, _ = fred_latest_and_back("FEDFUNDS", 0)
        trig_vals["ff"] = (v, d)
    def f_y10():
        trig_vals["y10"] = fred_latest_and_back("DGS10", 91)
    attempt("FRED CPI", f_cpi); attempt("FRED FEDFUNDS", f_ff); attempt("FRED DGS10", f_y10)

    def set_trig(tid, state, val, asof=None):
        """asof 要填「這個判斷所依據的資料」的日期，不是今天。

        來源抓失敗時 sp／IND 裡留的是上一輪的舊值，判斷照樣算得出來；這時若把
        asof 蓋成今天，前端就會顯示成今天剛驗證過——對使用者謊報新鮮度，正是
        §5.1「絕不編造數字」要擋的事。只有真的沒有來源日期可用（megaipo 這種
        人工旗標）才退回 TODAY。
        """
        for t in data["triggers"]:
            if t["id"] == tid:
                t["state"] = 1 if state else 0
                t["value"] = val
                t["asof"] = str(asof or TODAY)
    hy = sp.get("hy", {})
    if hy.get("now") is not None and hy.get("m3") is not None:
        d3 = (hy["now"] - hy["m3"]) * 100
        set_trig("hy80", d3 >= 80, f"{d3:+.0f}bp/3M", hy.get("asof"))
    if sp.get("ccc", {}).get("now") is not None:
        set_trig("ccc12", sp["ccc"]["now"] >= 12, f"{sp['ccc']['now']:.2f}%",
                 sp["ccc"].get("asof"))
    if "cpi" in trig_vals:
        v, d = trig_vals["cpi"]
        set_trig("cpi4", v >= 4, f"{v:.1f}%", d)
    if "ff" in trig_vals:
        v, d = trig_vals["ff"]
        set_trig("policy_gap", v >= params["ngdp_nominal"],
                 f"FF {v:.2f}% vs 名目GDP≈{params['ngdp_nominal']}%", d)
    if "y10" in trig_vals:
        d, v, b = trig_vals["y10"]
        set_trig("y10_5", v >= 5.0, f"{v:.2f}%", d)
        sp["us10y"] = {"now": v, "m3": b, "asof": str(d)}
    if IND.get("gsy_runup", {}).get("value") is not None:
        set_trig("gsy150", IND["gsy_runup"]["value"] >= 150,
                 f"{IND['gsy_runup']['value']:+.0f}%", IND["gsy_runup"].get("asof"))
    # megaipo 是人工旗標，沒有外部資料來源，用 TODAY 是對的
    set_trig("megaipo", bool(params.get("megaipo_done")), "已完成" if params.get("megaipo_done") else "未發生")

    # ============ 新聞 ============
    def f_news():
        data["events"] = fetch_news()
    attempt("Google News", f_news)

    # ============ 層分數、綜合、象限、歷史 ============
    dims = {}
    for dk in data["dimMeta"]:
        ss = [i["score"] for i in data["indicators"] if i["dim"] == dk and i.get("score") is not None]
        dims[dk] = round(sum(ss) / len(ss), 1) if ss else 50.0
    data["dims"] = dims
    data["composite"] = round(sum(data["dimMeta"][dk]["w"] * dims[dk] for dk in dims), 1)
    heat = round((dims["L1"] + dims["L2"]) / 2, 1)
    support = round(100 - dims["L3"], 1)
    if heat >= 55 and support < 45: regime = "泡沫危險區"
    elif heat >= 55: regime = "過熱但有撐（melt-up 風險）"
    elif support >= 45: regime = "健康擴張"
    else: regime = "失速風險"
    data["quadrant"] = {"heat": heat, "support": support, "regime": regime}

    snap = {"date": str(TODAY), "composite": data["composite"], "dims": dims,
            "tw": tw.get("heat"), "quad": [support, heat]}
    hist = [h for h in data["history"] if h["date"] != str(TODAY)]
    hist.append(snap)
    data["history"] = hist[-400:]
    data["meta"]["built"] = str(TODAY)
    data["meta"]["builtTime"] = f"{TODAY}（GitHub Actions 自動更新）"
    data["meta"]["lastAutoRun"] = {"date": str(TODAY), "ok": ok, "fail": fail}

    DATA.write_text(json.dumps(data, ensure_ascii=False, indent=1))
    log(f"done. composite={data['composite']} dims={dims} tw={tw.get('heat')} regime={regime} ok={len(ok)} fail={len(fail)}")
    if fail: log("failed (old values kept): " + ", ".join(fail))

def selftest():
    assert abs(pw(42.18, [[25, 0], [32, 33], [40, 67], [44.19, 100]]) - 84.2) < 0.1
    assert vix_score(16.73) == 50.0
    assert zone(None) == "pending"
    rows = [("2023-07-01", "2023-09-30", 9917), ("2023-10-01", "2023-12-31", 9735),
            ("2024-01-01", "2024-03-31", 10952), ("2023-07-01", "2024-03-31", 30604),
            ("2023-07-01", "2024-06-30", 44477)]
    q = to_quarters(rows, (7, 1))
    assert q[dt.date(2024, 6, 30)] == 13873
    closes = [(dt.date(2020, 1, 1) + dt.timedelta(days=i), 100 * (1.001 ** i)) for i in range(800)]
    g = gsy_stats(closes)
    assert "ret24" in g and "accel" in g and "volchg" in g
    fx = '<rss><channel><item><title>T - Bloomberg</title><link>https://x/a</link><pubDate>Mon, 20 Jul 2026 08:00:00 GMT</pubDate><source url="https://b.com">Bloomberg</source></item></channel></rss>'
    assert _parse_news_items(fx)[0]["title"] == "T"
    assert bucket(dt.date(2026, 2, 28)) == "2026Q1" and bucket(dt.date(2026, 5, 31)) == "2026Q2"
    print("selftest OK")

if __name__ == "__main__":
    if "--selftest" in sys.argv: selftest()
    else: main()
