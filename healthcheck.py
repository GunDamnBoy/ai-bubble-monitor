#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI 泡沫監控儀表板 · 健康檢查（不改 repo、不碰 git、不連網）

「不改 repo」是精確的說法：本檔不會動 repo 內的任何檔案，但為了用 `node --check`
驗 index.html 的 JS 語法，會在系統暫存目錄寫一個唯一檔名的 .js 並在結束時刪掉。

用法：
    python3 healthcheck.py              # 自動偵測 repo 位置
    python3 healthcheck.py --repo PATH  # 指定 repo

輸出每行為 PASS／WARN／FAIL。維護時把 FAIL 與 WARN 全部帶進報告。
"""
import argparse
import ast
import datetime as dt
import json
import os
import re
import subprocess
import sys

R = {"pass": 0, "warn": 0, "fail": 0}
_LINES = []


def _p(kind, msg):
    R[kind] += 1
    _LINES.append((kind, msg))
    print(f"{kind.upper():4} {msg}")


def days_ago(s):
    """把 YYYY-MM-DD 轉成距今天數；格式不對回 None（不擋流程）。"""
    try:
        return (TODAY_TPE - dt.date.fromisoformat(str(s)[:10])).days
    except Exception:
        return None


def num(x):
    """只有真的是數字才回傳 float；None／字串／布林一律回 None。"""
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def near(a, b, tol=0.15):
    """兩者都是數字、且差距在容忍值內才算相符。

    不要退回舊的 `(a or -999)` 寫法：存檔值合法地等於 0（例如某層全部指標
    都是 0 分、或 tw 子群算出 0.0）時，`0 or -999` 會變成 -999 而誤報不一致。
    """
    fa, fb = num(a), num(b)
    return fa is not None and fb is not None and abs(fa - fb) <= tol


def ok(m): _p("pass", m)
def warn(m): _p("warn", m)
def bad(m): _p("fail", m)


# 各層指標項數。層人數直接決定質化佔比（等權平均），加減指標必須回頭改
# AGENT_BRIEF §4 各層表與 §4.5 的 28.9%。放在模組層是因為 index.html 那句
# 「N 項指標依三層頻率分組」也要拿它對帳。
LAYER_N = {"L1": 9, "L2": 7, "L3": 6}

# 已知會失敗、設計上可降級的來源。
# 鍵＝`meta.lastAutoRun.fail` 裡出現的字串（由 update_data.py 的 attempt() 標籤決定）；
# 值＝AGENT_BRIEF.md 第 9 節那一列的辨識關鍵字。
# 兩者要對得起來：只加進這裡而沒寫進 §9，等於偷偷把一個失敗來源正常化。
KNOWN_FAIL = {
    "AAII": "AAII",
    "CBOE putcall": "CBOE",
    "TW 台積電權重": "台積電權重",
    # 2026-08-10 新接入 senti 的第四輸入。端點以 WebFetch 驗證過活著，但 Actions runner
    # 通不通未實測（CNN 對機器人的態度不明）——先進白名單讓失敗只 WARN 不 FAIL，
    # 由 streak 見真章：連續成功 ≥15 次就會 WARN 提醒把它從這裡與 §9 一起移除。
    "CNN FearGreed": "CNN",
}
# CBOE 是「時好時壞」不是「已修好」（2026-08-04 成功，之前多次失敗），所以留在名單裡。
# 把它拿掉的話，下一個抓失敗的日子會變成 FAIL 而擋住每週推送——而那正是這個系統
# 設計上允許降級的情況。真正修好、連續數週都成功之後才移除，並同步刪掉 brief §9 那一列。
#
# 「連續數週都成功」以前沒有依據可查（data.json 只留最後一次自動更新），所以那條維護
# 規則寫了也執行不了。現在引擎會累計 meta.lastAutoRun.streak，超過這個門檻就 WARN，
# 提醒把該來源從 §9 與本名單一起移除。15 次自動更新 ≈ 三週（每週五個交易日）。
OK_STREAK_RETIRE = 15

# 「今天」一律用台北日——引擎的 TODAY 是 UTC+8（update_data.py:13），asof 蓋的是台北日期。
# 本檔若用容器本地的 date.today()（Actions／覆核容器都是 UTC），在 UTC 16:00–24:00 的
# 窗口（台北隔日 00:00–08:00）會把引擎當天的戳記全判成「未來日期」而 FAIL 擋住流程。
TODAY_TPE = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=8)).date()

# 質化指標的 asof 過期門檻（天），依各項的自然更新頻率分開設，見 AGENT_BRIEF §4.5。
# 未列在這裡的質化 id 一律套 45 天預設——新增第七個質化指標時記得補一列。
# 放在模組層是因為 index.html 來源表的 QUALF 分級也要拿它對帳。
QUAL_MAXAGE = {"narrative": 21, "circular": 21, "weakcredit": 21,  # 每週覆核
               "tokens": 75,                                       # 月度第三方彙整
               "vc": 130, "cloudrev": 130}                         # 季度


def find_repo(explicit=None):
    cands = []
    if explicit:
        cands.append(explicit)
    cands.append(os.path.dirname(os.path.abspath(__file__)))
    cands += [os.path.expanduser("~/ai-bubble-monitor"), "/tmp/v2"]
    for base in ("/sessions", os.path.expanduser("~")):
        if os.path.isdir(base):
            for root, dirs, _ in os.walk(base):
                if root.count(os.sep) - base.count(os.sep) > 4:
                    dirs[:] = []
                    continue
                if "ai-bubble-monitor" in dirs:
                    cands.append(os.path.join(root, "ai-bubble-monitor"))
                    dirs[:] = [d for d in dirs if d != "ai-bubble-monitor"]
    for c in cands:
        if c and os.path.isfile(os.path.join(c, "data.json")) and os.path.isfile(os.path.join(c, "index.html")):
            return c
    return None


# ---------------------------------------------------------------- 1. data.json
def check_data(repo):
    path = os.path.join(repo, "data.json")
    try:
        d = json.load(open(path, encoding="utf-8"))
    except Exception as ex:
        bad(f"data.json 無法解析：{ex}")
        return None
    ok("data.json 可解析")

    meta = d.get("meta", {})
    if meta.get("version") != 2:
        warn(f"meta.version = {meta.get('version')}（本檢查針對 v2 撰寫）")

    # 新鮮度
    built = meta.get("built")
    try:
        age = (TODAY_TPE - dt.date.fromisoformat(built)).days
        if age <= 1:
            ok(f"資料新鮮度：built={built}（{age} 天前）")
        elif age <= 4:
            warn(f"資料新鮮度：built={built}（{age} 天前；遇連假可能正常）")
        else:
            bad(f"資料新鮮度：built={built}（{age} 天前，Actions 可能已停擺）")
    except Exception:
        bad(f"meta.built 格式異常：{built!r}")

    # 層權重
    dm = d.get("dimMeta", {})
    wsum = sum(v.get("w", 0) for v in dm.values())
    if abs(wsum - 1.0) < 1e-9:
        ok("dimMeta 權重加總 = 1.0（" + "／".join(f"{k} {v['w']}" for k, v in dm.items()) + "）")
    else:
        bad(f"dimMeta 權重加總 = {wsum}，應為 1.0")

    # 指標 → 層分數 → 綜合溫度 → 象限：全部重算比對
    inds = d.get("indicators", [])
    got_n = {k: sum(1 for i in inds if i.get("dim") == k) for k in dm}
    if len(inds) == sum(LAYER_N.values()) and got_n == LAYER_N:
        ok(f"indicators 共 {len(inds)} 項，層人數符合規格 {LAYER_N}")
    else:
        warn(f"指標數 {len(inds)} 項、層人數 {got_n}，規格是 {sum(LAYER_N.values())} 項 {LAYER_N}"
             "（若是刻意增減，要同步更新 AGENT_BRIEF §4 各層表與 §4.5 的質化佔比 28.9%）")

    recomputed = {}
    for dk in dm:
        ss = [i["score"] for i in inds if i.get("dim") == dk and i.get("score") is not None]
        recomputed[dk] = round(sum(ss) / len(ss), 1) if ss else 50.0
    stored = d.get("dims", {})
    diffs = [f"{k}: 存 {stored.get(k)} vs 算 {recomputed[k]}" for k in recomputed
             if not near(stored.get(k), recomputed[k])]
    if diffs:
        bad("層分數與指標不一致（有人改了分數沒重算）：" + "；".join(diffs))
    else:
        ok(f"層分數與指標一致：{recomputed}")

    comp = round(sum(dm[k]["w"] * recomputed[k] for k in recomputed), 1)
    if not near(d.get("composite"), comp):
        bad(f"composite 不一致：存 {d.get('composite')} vs 算 {comp}")
    else:
        ok(f"composite 一致：{comp}")

    heat = round((recomputed["L1"] + recomputed["L2"]) / 2, 1)
    support = round(100 - recomputed["L3"], 1)
    regime = ("泡沫危險區" if heat >= 55 and support < 45 else
              "過熱但有撐（melt-up 風險）" if heat >= 55 else
              "健康擴張" if support >= 45 else "失速風險")
    q = d.get("quadrant", {})
    if not (near(q.get("heat"), heat) and near(q.get("support"), support)):
        bad(f"quadrant 不一致：存 {q} vs 算 heat={heat} support={support}")
    elif q.get("regime") != regime:
        bad(f"regime 不一致：存「{q.get('regime')}」vs 算「{regime}」")
    else:
        ok(f"象限一致：heat={heat} support={support}｜{regime}")

    # 指標欄位完整性
    need = {"id", "dim", "name", "score", "zone", "asof", "fresh"}
    prob = []
    for i in inds:
        miss = need - set(i)
        if miss:
            prob.append(f"{i.get('id')} 缺 {sorted(miss)}")
            continue
        s = i["score"]
        if s is not None and not (0 <= s <= 100):
            prob.append(f"{i['id']} score={s} 超出 0-100")
        z = "pending" if s is None else ("green" if s < 33 else "yellow" if s < 67 else "orange" if s < 84 else "red")
        if i["zone"] != z:
            prob.append(f"{i['id']} zone={i['zone']} 應為 {z}")
        a = i.get("anchors")
        if a and any(a[k][0] >= a[k + 1][0] for k in range(len(a) - 1)):
            prob.append(f"{i['id']} anchors 的 x 未遞增")
        if i.get("dim") not in dm:
            prob.append(f"{i['id']} dim={i.get('dim')} 不在 dimMeta")
    if prob:
        bad("指標欄位問題：" + "；".join(prob))
    else:
        ok("指標欄位、燈號、錨點單調性皆正常")

    # null 分數（退出平均）
    nulls = [i["id"] for i in inds if i.get("score") is None]
    if nulls:
        warn(f"score 為 null（已退出當層平均）：{', '.join(nulls)}")
    else:
        ok("無 null 分數指標")

    # 質化指標集合
    QUAL = {"narrative", "circular", "weakcredit", "vc", "cloudrev", "tokens"}
    actual = {i["id"] for i in inds if i.get("qual")}
    if actual == QUAL:
        ok(f"質化指標集合符合規格（{len(QUAL)} 項）")
    else:
        bad(f"質化指標集合漂移：多 {sorted(actual - QUAL)}、少 {sorted(QUAL - actual)}")

    # 質化指標的 note／asof 稽核。
    #
    # 質化分數沒有引擎可以重算，唯一的查核機制是人寫的 note（AGENT_BRIEF §4.5）。
    # 但「note 一定要有分數軌跡」這條沒辦法無差別套用：vc／cloudrev 是季度指標，
    # 分數整季不動時 note 本來就不該重寫，硬要求會製造永遠修不掉的 WARN——
    # 而永遠修不掉的 WARN 等於沒有 WARN。所以這裡只查三件做得到的事：
    #   (1) note 裡若寫了「… → Y」的軌跡，Y 必須等於現在的 score
    #       （這才是真正的失效模式：分數改了、note 忘了改，或改錯邊）
    #   (2) note 裡要有一個看得出來的日期／月份，否則理由無從判斷是否過期
    #   (3) asof 停太久 → 這一項已經連續好幾次覆核沒被真正看過
    #       門檻依各指標的自然更新頻率分開設，不用同一個數字。
    # （QUAL_MAXAGE 已移到模組層，因為 check_brief 也要拿它跟 index.html 的 QUALF 對帳）
    # 「本週由 4.5 下修至 4.0（score 80→70）」「本週由橙(82)轉紅(85)」都要抓得到
    TRAIL = [re.compile(r"(\d+(?:\.\d+)?)\s*(?:→|->)\s*(\d+(?:\.\d+)?)"),
             re.compile(r"本週由\D{0,4}(\d+(?:\.\d+)?)\D{0,6}?"
                        r"(?:轉|升至|降至|上修至|下修至|改為)\D{0,4}(\d+(?:\.\d+)?)")]
    DATEISH = re.compile(r"\d{4}-\d{1,2}(?:-\d{1,2})?|\d{1,2}\s*[/月]\s*\d{0,2}")
    qprob, qwarn = [], []
    for i in inds:
        if not i.get("qual"):
            continue
        qid, note, sc = i["id"], str(i.get("note") or ""), num(i.get("score"))
        # (1) 軌跡終點對不對得上現在的分數
        ends = [m for rx in TRAIL for m in rx.finditer(note)]
        if ends and sc is not None:
            tail = float(ends[-1].group(2))
            # 級距分數（0–100）才比對；narrative 那種「4.5 下修至 4.0」是原始級數，跳過
            if tail > 5 and abs(tail - sc) > 1e-9:
                qprob.append(f"{qid}：note 軌跡終點 {tail:g} ≠ 現在的 score {sc:g}")
        # (2) 日期
        if not DATEISH.search(note):
            qwarn.append(f"{qid} 的 note 沒有任何可辨識的日期")
        # (3) asof 停太久
        a = days_ago(str(i.get("asof"))[:7] + "-01"
                     if re.fullmatch(r"\d{4}-\d{2}\D*", str(i.get("asof")) or "")
                     else i.get("asof"))
        lim = QUAL_MAXAGE.get(qid, 45)
        if a is None:
            qwarn.append(f"{qid} 的 asof={i.get('asof')!r} 解不出日期")
        elif a > lim:
            qwarn.append(f"{qid} 的 asof 已 {a} 天沒動（該項門檻 {lim} 天）")
    if qprob:
        bad("質化 note 與 score 不符：" + "；".join(qprob))
    for w in qwarn:
        warn("質化：" + w)
    if not qprob and not qwarn:
        ok(f"質化 {len(QUAL)} 項的 note 軌跡、日期與 asof 新鮮度皆正常")

    # 觸發器
    TRIG = {"hy80", "ccc12", "gsy150", "cpi4", "policy_gap", "y10_5", "megaipo"}
    tr = d.get("triggers", [])
    tids = {t.get("id") for t in tr}
    if tids == TRIG:
        lit = [t["id"] for t in tr if t.get("state")]
        ok(f"觸發器 7 項齊全，點亮 {len(lit)}/7" + ("：" + ", ".join(lit) if lit else ""))
    else:
        bad(f"觸發器集合漂移：多 {sorted(tids - TRIG)}、少 {sorted(TRIG - tids)}")
    if any(t.get("state") not in (0, 1, True, False) for t in tr):
        bad("觸發器 state 必須是 0/1")

    # asof 不可以是未來：那只可能來自「拿今天當來源日期」這類編造
    future = []
    for label, rows in (("指標", inds), ("觸發器", tr),
                        ("tw.items", (d.get("tw") or {}).get("items") or [])):
        for r in rows:
            a = days_ago(r.get("asof"))
            if a is not None and a < 0:
                future.append(f"{label} {r.get('id')}（{r.get('asof')}）")
    if future:
        bad("asof 是未來日期：" + "／".join(future))

    # 台灣
    tw = d.get("tw", {})
    TWI = {t["id"]: t for t in tw.get("items", [])}
    subs_def = {"動能": ["tsmc_200dma", "tsmc_52w", "elec_rel", "twii_pos"],
                "估值": ["tsmc_pe", "odm_pe"], "籌碼": ["tw_margin"],
                "基本面": ["tw_rev", "tw_export"]}
    missing = [i for ids in subs_def.values() for i in ids if i not in TWI]
    if missing:
        bad(f"tw.items 缺少子群成員：{missing}")
    subs = {}
    for k, ids in subs_def.items():
        ss = [TWI[i]["score"] for i in ids if i in TWI and TWI[i].get("score") is not None]
        subs[k] = round(sum(ss) / len(ss), 1) if ss else None
    sd = [f"{k}: 存 {tw.get('subs', {}).get(k)} vs 算 {v}" for k, v in subs.items()
          if (tw.get("subs", {}).get(k) is None) != (v is None)
          or (v is not None and not near(tw.get("subs", {}).get(k), v))]
    if sd:
        bad("tw.subs 不一致：" + "；".join(sd))
    else:
        ok(f"tw.subs 一致：{subs}")
    wmap = {"動能": .3, "估值": .3, "籌碼": .2, "基本面": .2}
    valid = {k: v for k, v in subs.items() if v is not None}
    ws = sum(wmap[k] for k in valid)
    if not ws:
        # 四組全 null：分母為 0，heat 算不出來。以前這裡直接跳過，連 heat 一致性
        # 都不檢查，等於整塊靜默——正是 §4.5 批判過的「抓不到就跳過」。
        bad("tw.subs 四組全為 null，tw.heat 無法計算（台股資料整批失效？）")
    if ws:
        h = round(sum(v * wmap[k] for k, v in valid.items()) / ws, 1)
        if not near(tw.get("heat"), h):
            bad(f"tw.heat 不一致：存 {tw.get('heat')} vs 算 {h}")
        else:
            ok(f"tw.heat 一致：{h}")
        # 分母不是 1.0 時要講出來。null 子群被剔除後重新歸一是設計，但它意味著
        # **那個子群補回來的那一天，tw.heat 會不連續地跳一下**——看起來會像資料出錯。
        # 沉默地 PASS 等於把一個未來一定會發生的誤判留給下一個人。
        if ws < 0.999:
            gone = [k for k in subs if subs[k] is None]
            base = sum(v * wmap[kk] for kk, v in valid.items())   # 分子（尚未歸一）
            sim = ""
            if len(gone) == 1:
                g = gone[0]
                sim = "，屆時約為 " + "／".join(
                    f"{g} {x} 分→heat {round(base + wmap[g] * x, 1)}" for x in (35, 50, 67))
            warn(f"tw.heat 目前以 {len(valid)}/4 組歸一（分母 {ws:.1f}，缺：{'、'.join(gone)}）"
                 f"——補齊那天 heat 會不連續跳動（現值 {tw.get('heat')}）{sim}")
    if "tsmc_weight" in TWI:
        aw = TWI["tsmc_weight"].get("asof")
        try:
            age = (TODAY_TPE - dt.date.fromisoformat(str(aw))).days
            (warn if age > 45 else ok)(f"tsmc_weight（人工月更）asof={aw}（{age} 天前）")
        except Exception:
            warn(f"tsmc_weight asof 格式異常：{aw!r}")

    # history
    h = d.get("history", [])
    dates = [x.get("date") for x in h]
    if len(dates) != len(set(dates)):
        dup = sorted({x for x in dates if dates.count(x) > 1})
        bad(f"history 有重複日期：{dup}")
    elif dates != sorted(dates):
        bad("history 未依日期遞增排序")
    elif len(h) > 400:
        bad(f"history 共 {len(h)} 筆，超過 400 上限")
    else:
        ok(f"history {len(h)} 筆，日期唯一且遞增（{dates[0]} → {dates[-1]}）")
    if dates and dates[-1] != built:
        bad(f"history 最後一筆 {dates[-1]} ≠ meta.built {built}")
    noquad = [x["date"] for x in h if "quad" not in x]
    if noquad:
        warn(f"history 有 {len(noquad)} 筆缺 quad（改版前的舊筆屬正常）：{noquad[0]} … {noquad[-1]}")
    trail = [x for x in h if "quad" in x]
    ok(f"象限軌跡目前 {len(trail)} 個點") if trail else bad("象限軌跡沒有任何點")

    # events：逐項獨立判斷，不要用 elif 串（第一個問題會蓋掉後面的）
    ev = d.get("events", [])
    if not ev:
        bad("events 空白")
    else:
        probs = []
        if len(ev) > 12:
            probs.append(f"共 {len(ev)} 條，超過 12 上限")
        nourl = [str(x.get("t", "?"))[:16] for x in ev if not x.get("url")]
        if nourl:
            probs.append(f"{len(nourl)} 條缺 url（{nourl[0]}…）")
        nod = [str(x.get("t", "?"))[:16] for x in ev if not x.get("d")]
        if nod:
            probs.append(f"{len(nod)} 條缺日期 d（{nod[0]}…）")
        if probs:
            bad("events：" + "；".join(probs))
        else:
            ok(f"events {len(ev)} 條、皆有 url（最新 {ev[0].get('d')}）")

    # stage：純人工維護，最常見的漏更新是「勾選數改了，current 與 note 沒跟著改」
    st = d.get("stage", {})
    sprob = []
    cl = st.get("checklist", [])
    if len(cl) != 6:
        sprob.append(f"checklist 應為 6 項，實際 {len(cl)}")
    badst = [c.get("item", "?")[:12] for c in cl if num(c.get("state")) not in (0.0, 0.5, 1.0)]
    if badst:
        sprob.append(f"checklist state 只能是 0／0.5／1，異常：{badst}")
    cur = num(st.get("current"))
    if cur is None or not (1 <= cur <= 4):
        sprob.append(f"stage.current={st.get('current')!r} 應是 1–4 的數")
    sts = st.get("stages", [])
    act = [s for s in sts if s.get("active")]
    if len(sts) != 4:
        sprob.append(f"stages 應為 4 階，實際 {len(sts)}")
    if len(act) != 1:
        sprob.append(f"stages 必須剛好一階 active，實際 {len(act)} 階")
    elif cur is not None and int(cur) != act[0].get("n"):
        sprob.append(f"stage.current={cur} 的整數位與 active 階段 n={act[0].get('n')} 不符")
    if len(act) == 1:
        an = act[0].get("n") or 0
        wrong = [s.get("n") for s in sts
                 if bool(s.get("done")) != ((s.get("n") or 0) < an)]
        if wrong:
            sprob.append(f"stages 的 done 應為「n < active 才 True」，不符：{wrong}")
    # note 開頭的「點亮 X／6」必須等於 checklist 實際加總
    # note 開頭的「點亮 X／6」必須存在，且等於 checklist 實際加總。
    # 這裡刻意「抓不到就報錯」而不是「抓不到就跳過」：舊版寫成 `if m and …`，
    # 於是把全形／改成半形、或改寫句型，就會靜靜地關掉比對，而且照樣印一行 PASS
    # 說 stage 一致——比沒有檢查更糟。斜線兩種都收，句型不對則明講。
    lit = sum(num(c.get("state")) or 0 for c in cl)
    m = re.search(r"點亮\s*([0-9.]+)\s*[／/]\s*(\d+)", str(st.get("note", "")))
    if not m:
        sprob.append("stage.note 找不到「點亮 X／6」這一句（格式要照抄，"
                     f"目前 checklist 實算是 {lit:g}／{len(cl)}）")
    elif abs(float(m.group(1)) - lit) > 1e-9 or int(m.group(2)) != len(cl):
        sprob.append(f"stage.note 寫「點亮 {m.group(1)}／{m.group(2)}」，"
                     f"但 checklist 實際是 {lit:g}／{len(cl)}")
    if sprob:
        bad("stage：" + "；".join(sprob))
    else:
        ok(f"stage 一致：{st.get('label')} current={st.get('current')}，checklist 點亮 {lit:g}／{len(cl)}")

    # charts
    ch = d.get("charts", {})
    for k in ("aggQ", "ttm"):
        rows = ch.get(k, [])
        qs = [r.get("q") for r in rows]
        if qs != sorted(qs):
            bad(f"charts.{k} 季別未遞增")
        prov = [r for r in rows if r.get("prov")]
        if prov:
            p = prov[-1]
            if p.get("have") is None:
                # ttm 的初步旗標由 aggQ 帶入，本身不重複記 have／missing
                ok(f"charts.{k} 末筆為初步季 {p['q']}（初步旗標沿用 aggQ）")
            else:
                miss = "／".join(p.get("missing", [])) or "無"
                ok(f"charts.{k} 末筆為初步季 {p['q']}（{p['have']}/5 家，缺 {miss}）")
        else:
            ok(f"charts.{k} 末筆 {qs[-1] if qs else '無'}（無初步季）")

    # lastAutoRun
    lar = meta.get("lastAutoRun", {})
    if not lar:
        # 整塊缺失代表引擎從未成功跑完過——這不該只是末行一句「成功 0 項」的誤導 PASS
        bad("meta.lastAutoRun 不存在或為空：引擎從未寫過執行紀錄，自動更新可能從沒跑成功過")
    KNOWN = set(KNOWN_FAIL)
    fails = set(lar.get("fail", []))
    newf = fails - KNOWN
    if newf:
        bad(f"出現新的失敗來源（非已知清單）：{sorted(newf)}")
    if fails & KNOWN:
        warn(f"已知失敗來源（設計上可降級）：{sorted(fails & KNOWN)}")
    # §9 的反向規則：白名單裡的來源若已連續成功夠久，就該退場，否則它會安靜地留著，
    # 下次真的壞掉只會是 WARN 而不是 FAIL。沒有 streak 欄位代表引擎還沒跑過新版，不報錯。
    # 抓不到就 WARN，不是靜默跳過照印 PASS——後者可以無聲關掉整個比對，
    # 這正是 §4.5 那條「舊版寫成『抓不到就跳過』比沒有檢查更糟」的教訓。
    stk = lar.get("streak")
    if not isinstance(stk, dict) or not stk:
        warn("meta.lastAutoRun.streak 不存在或為空，白名單退場檢查跳過"
             "（引擎跑過一次新版就會有；若已跑過還是空的，就是引擎那段沒生效）")
    else:
        retire = {k: stk[k] for k in KNOWN if stk.get(k, 0) >= OK_STREAK_RETIRE}
        if retire:
            warn("已連續成功 ≥%d 次、可考慮從 brief §9 與 KNOWN_FAIL 移除：%s"
                 % (OK_STREAK_RETIRE, ", ".join(f"{k}({v})" for k, v in sorted(retire.items()))))
        else:
            # 沒出現在 streak 裡的白名單來源標成「—」：它代表該來源這次既沒成功也沒失敗，
            # 通常表示 attempt() 標籤被改了而 §9／KNOWN_FAIL 沒跟上。
            ok("白名單來源的連續成功次數都還沒到退場門檻（%d 次執行）：%s" % (
                OK_STREAK_RETIRE,
                ", ".join(f"{k}={stk[k]}" if k in stk else f"{k}=—（本次未執行）"
                          for k in sorted(KNOWN))))
        absent = [k for k in KNOWN if k not in stk]
        if absent:
            warn("白名單來源本次既不在 ok 也不在 fail（attempt 標籤可能已改名）：%s"
                 % ", ".join(sorted(absent)))
    ok(f"最近一次自動更新 {lar.get('date')}：成功 {len(lar.get('ok', []))} 項、失敗 {len(fails)} 項")
    return d


# ------------------------------------------------------------ 2. brief 一致性
def check_brief(repo, d):
    path = os.path.join(repo, "AGENT_BRIEF.md")
    if not os.path.isfile(path):
        bad("找不到 AGENT_BRIEF.md")
        return
    txt = open(path, encoding="utf-8").read()
    ok("AGENT_BRIEF.md 存在")
    if not d:
        return

    # 層權重
    dm = d["dimMeta"]
    for dk, label in (("L1", "L1"), ("L2", "L2"), ("L3", "L3")):
        m = re.search(r"\*\*" + dk + r"\*\*\s*\|[^|]*\|\s*\*\*([0-9.]+)\*\*", txt)
        if not m:
            warn(f"brief 中找不到 {label} 的權重列")
        elif abs(float(m.group(1)) - dm[dk]["w"]) > 1e-9:
            bad(f"brief 的 {label} 權重 {m.group(1)} ≠ data.json 的 {dm[dk]['w']}")
    ok("brief 層權重與 data.json 比對完成")

    # 錨點
    IND = {i["id"]: i for i in d["indicators"]}
    mism, checked = [], 0
    for line in txt.splitlines():
        m = re.match(r"\|\s*`(\w+)`\s*\|", line)
        if not m or m.group(1) not in IND:
            continue
        a = re.findall(r"`(\[\[[^`]*\]\])`", line)
        if not a:
            continue
        try:
            want = ast.literal_eval(a[0])
        except Exception:
            continue
        checked += 1
        got = IND[m.group(1)].get("anchors")
        if got and [[float(x) for x in p] for p in want] != [[float(x) for x in p] for p in got]:
            mism.append(f"{m.group(1)}: brief {want} vs data {got}")
    if mism:
        bad("brief 錨點與 data.json 不符：" + "；".join(mism))
    else:
        ok(f"brief 錨點與 data.json 相符（比對 {checked} 項）")

    # 台灣指標錨點：tw.items 沒有 anchors 欄位，錨點只寫在引擎的 tupd(...) 裡，
    # brief §4.6 的表是人手改分數時唯一的規格來源 → 必須機械比對，否則一定漂
    up = os.path.join(repo, "scripts", "update_data.py")
    if os.path.isfile(up):
        eng = engine_tw_anchors(up)
        if not eng:
            # 引擎重構（tupd 改名、分數先存變數再傳）會讓這裡回空 dict，之後
            # mism2／undoc／bt 全空、三個分支都不走——「抓不到就靜默跳過照印 PASS」
            # 的變體，只是藏在 else-chain 的縫裡。抓不到就要說。
            warn("引擎的台灣錨點解析不到（tupd 呼叫型態可能已改），§4.6 對帳整段跳過")
        bt = {}
        for line in txt.splitlines():
            m = re.match(r"\|\s*`(\w+)`\s*\|", line)
            if not m or m.group(1) not in eng:
                continue
            a = re.findall(r"`(\[\[[^`]*\]\])`", line)
            if a:
                try:
                    bt[m.group(1)] = ast.literal_eval(a[0])
                except Exception:
                    pass
        undoc = sorted(set(eng) - set(bt))
        mism2 = [f"{k}: brief {bt[k]} vs 引擎 {eng[k]}" for k in sorted(bt)
                 if [[float(x) for x in p] for p in bt[k]]
                 != [[float(x) for x in p] for p in eng[k]]]
        if mism2:
            bad("brief §4.6 的台灣錨點與 update_data.py 不符：" + "；".join(mism2))
        elif undoc:
            warn(f"引擎有錨點但 brief §4.6 沒記的台灣指標：{undoc}（手改分數時會沒有依據）")
        elif bt:
            ok(f"brief §4.6 台灣錨點與引擎一致（比對 {len(bt)} 項）")

    # 台股子群權重：brief §4.6 的表 ↔ 引擎的 wmap ↔ data.json 的 tw.subWeights。
    # 三處一致的規則本來只寫在文件裡，依 MAINTENANCE §6.7／§6.8 的結論改成機器把關。
    up_ = os.path.join(repo, "scripts", "update_data.py")
    if os.path.isfile(up_):
        msrc = re.search(r"wmap\s*=\s*(\{[^}]*\})", open(up_, encoding="utf-8").read())
        if not msrc:
            warn("update_data.py 找不到 wmap，台股子群權重無法對帳（是不是改名了？）")
        else:
            eng_w = {k: float(v) for k, v in ast.literal_eval(msrc.group(1)).items()}
            bw = {}
            for line in txt.split("\n"):
                m = re.match(r"\|\s*(動能|估值|籌碼|基本面)\s*\|\s*([\d.]+)\s*\|", line)
                if m:
                    bw[m.group(1)] = float(m.group(2))
            dw = {k: float(v) for k, v in (d.get("tw", {}).get("subWeights") or {}).items()}
            if bw != eng_w:
                bad(f"brief §4.6 子群權重 {bw} 與引擎 wmap {eng_w} 不符")
            elif not dw:
                warn("data.json 缺 tw.subWeights（前端會少印子群權重；引擎跑過一次就會有）")
            elif dw != eng_w:
                bad(f"data.json 的 tw.subWeights {dw} 與引擎 wmap {eng_w} 不符")
            elif abs(sum(eng_w.values()) - 1.0) > 1e-9:
                bad(f"台股子群權重加總 {sum(eng_w.values())} ≠ 1.0")
            else:
                ok(f"台股子群權重三處一致且加總 = 1.0：{eng_w}")

        # 子群的**成員組成**（不只權重）：brief §4.6 的表 ↔ 引擎的 subs_def。
        # 「籌碼是唯一的單點子群」這句話在 brief 與 MAINTENANCE 各有一份拷貝，
        # 改了成員而沒同步就會無聲變成假的——依 §6.8 的教訓，交給機器守。
        esrc = re.search(r"subs_def\s*=\s*(\{.*?\})\s*\n", open(up_, encoding="utf-8").read(), re.S)
        if not esrc:
            warn("update_data.py 找不到 subs_def，台股子群成員無法對帳")
        else:
            try:
                eng_m = {k: sorted(v) for k, v in ast.literal_eval(esrc.group(1)).items()}
            except Exception:
                eng_m = None
                warn("update_data.py 的 subs_def 解析失敗，台股子群成員無法對帳")
            if eng_m:
                bm = {}
                for line in txt.split("\n"):
                    m = re.match(r"\|\s*(動能|估值|籌碼|基本面)\s*\|\s*[\d.]+\s*\|(.+?)\|", line)
                    if m:
                        bm[m.group(1)] = sorted(re.findall(r"`(\w+)`", m.group(2)))
                if bm != eng_m:
                    diff = [f"{k}: brief {bm.get(k)} vs 引擎 {eng_m.get(k)}"
                            for k in set(bm) | set(eng_m) if bm.get(k) != eng_m.get(k)]
                    bad("brief §4.6 子群成員與引擎 subs_def 不符：" + "；".join(diff))
                else:
                    singles = [k for k, v in eng_m.items() if len(v) == 1]
                    ok(f"台股子群成員 brief↔引擎一致（單點子群：{singles or '無'}）")

    # index.html 來源表的質化頻率分級（QUALF）↔ 本檔的 QUAL_MAXAGE。
    # 兩份分級各自寫死，改一邊不會有人記得改另一邊——正是要靠機器盯的那種。
    ih = os.path.join(repo, "index.html")
    if os.path.isfile(ih):
        mq = re.search(r"const QUALF = (\{.*?\});", open(ih, encoding="utf-8").read(), re.S)
        if not mq:
            warn("index.html 找不到 QUALF，質化頻率分級無法對帳")
        else:
            fe = dict(re.findall(r"(\w+)\s*:\s*\"([^\"]+)\"", mq.group(1)))
            # 天數門檻 → 該落在哪個頻率字眼
            def band(days):
                return "週" if days <= 30 else ("月" if days <= 90 else "季")
            mism = [f"{k}: 來源表寫「{fe[k]}」但 QUAL_MAXAGE={QUAL_MAXAGE[k]} 天（應為{band(QUAL_MAXAGE[k])}頻）"
                    for k in QUAL_MAXAGE if k in fe and not fe[k].startswith(band(QUAL_MAXAGE[k]))]
            missq = sorted(set(QUAL_MAXAGE) - set(fe))
            if mism:
                bad("index.html 來源表的質化頻率與 QUAL_MAXAGE 不符：" + "；".join(mism))
            elif missq:
                warn(f"QUAL_MAXAGE 有、index.html 的 QUALF 沒列的質化指標：{missq}（會落到預設值）")
            else:
                ok(f"index.html 來源表質化頻率與 QUAL_MAXAGE 一致（{len(fe)} 項）")

    # §9 已知失效來源 vs healthcheck 的 KNOWN_FAIL 白名單
    s9 = txt.split("## 9.", 1)[-1].split("\n## 10.", 1)[0]
    undoc9 = [k for k, kw in KNOWN_FAIL.items() if kw not in s9]
    if undoc9:
        bad("healthcheck 把 " + "／".join(undoc9) +
            " 當成已知可降級的失敗來源，但 brief 第 9 節沒有這一列"
            "（等於偷偷把失敗正常化）")
    else:
        ok(f"brief §9 已知失效來源與 healthcheck 白名單一致（{len(KNOWN_FAIL)} 項）")

    # 觸發器門檻文字
    for tid in ("hy80", "ccc12", "gsy150", "cpi4", "policy_gap", "y10_5", "megaipo"):
        if f"`{tid}`" not in txt:
            bad(f"brief 第 3.5 節缺觸發器 {tid}")

    # 台灣籃
    up = os.path.join(repo, "scripts", "update_data.py")
    if os.path.isfile(up):
        src = open(up, encoding="utf-8").read()
        codes = set(re.findall(r'\("(\d{4})", "', src.split("TW_BASKET", 1)[-1][:600]))
        bcodes = set(re.findall(r"`(\d{4}) ", txt)) | set(re.findall(r"`(\d{4})\s", txt))
        miss = codes - bcodes
        if miss:
            bad(f"brief 的台灣籃缺少 update_data.py 有的代號：{sorted(miss)}")
        elif codes:
            ok(f"台灣月營收籃 {len(codes)} 檔，brief 與引擎一致")

    # cron
    wf = os.path.join(repo, ".github", "workflows", "update.yml")
    if os.path.isfile(wf):
        y = open(wf, encoding="utf-8").read()
        # 單引號、雙引號、裸值三種 YAML 寫法都要認得（含行尾註解）；認不得就 WARN，不能無聲消失。
        # 行首只允許空白與 "-"，免得先匹配到被註解掉的 cron 行而誤判 FAIL。
        m = re.search(r"^[ \t-]*cron:\s*['\"]?([^'\"\n#]+?)['\"]?\s*(?:#.*)?$", y, re.M)
        if m:
            if m.group(1).strip() in txt:
                ok(f"workflow cron `{m.group(1).strip()}` 與 brief 一致")
            else:
                bad(f"workflow cron `{m.group(1).strip()}` 未出現在 brief 第 7 節")
        else:
            warn("update.yml 裡解析不到 cron 表達式，cron↔brief 對帳跳過")
        if "pages/builds" in y:
            ok("workflow 保有 Pages 明確重建步驟（GITHUB_TOKEN 推送不會自動重建）")
        else:
            bad("workflow 缺少 POST /pages/builds 步驟 → 網站會停在舊值")
        if re.search(r"pages:\s*write", y):
            ok("workflow 具備 pages: write 權限")
        else:
            bad("workflow 缺少 pages: write 權限")
    else:
        bad("找不到 .github/workflows/update.yml")


# -------------------------------------------------------- 3-a. 內嵌退路快照
def check_fallback(html, d):
    """index.html 內嵌的 #dashboard-data 是 fetch data.json 失敗時的離線退路。
    它不會自動更新，v1→v2 改版時最容易被遺忘（曾發生整頁退回 v1 舊模型）。"""
    m = re.search(r'<script[^>]*id="dashboard-data"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        bad("index.html 找不到 #dashboard-data 內嵌退路快照")
        return
    try:
        fb = json.loads(m.group(1))
    except Exception as ex:
        bad(f"#dashboard-data 內嵌快照不是合法 JSON：{ex}")
        return

    fv = (fb.get("meta") or {}).get("version")
    dv = (d.get("meta") or {}).get("version") if d else None
    if dv is None:
        warn("data.json 沒有 meta.version，無法比對內嵌快照版本")
    elif fv == dv:
        ok(f"#dashboard-data 內嵌快照版本與 data.json 相同（v{fv}）")
    else:
        bad(f"#dashboard-data 內嵌快照是 v{fv}，data.json 是 v{dv}"
            "（fetch 失敗時整頁會退回舊模型，須以現行 data.json 重新產生）")

    for k in ("triggers", "quadrant", "dims"):
        if k not in fb:
            bad(f"#dashboard-data 內嵌快照缺 v2 區塊 {k}")

    fh, dh = len(fb.get("history") or []), len((d or {}).get("history") or [])
    if fh > 60:
        warn(f"#dashboard-data 內嵌快照 history {fh} 筆，超過 60 筆就該裁到最後 60 筆以免頁面過大")
    elif fh:
        ok(f"#dashboard-data 內嵌快照 history {fh} 筆（data.json {dh} 筆）")
    else:
        warn("#dashboard-data 內嵌快照 history 是空的（離線開啟時象限軌跡與歷史表會整塊消失）")

    # 快照本來就是「某個時點的拷貝」，跟 data.json 不同是正常的；危險的是它舊到
    # 講出另一個故事——fetch 失敗那天，使用者看到的會是這份快照而不是最新數字。
    # 所以不比對「有沒有差」，只比對「差到會誤導沒有」。
    if d:
        fb_built, d_built = (fb.get("meta") or {}).get("built"), (d.get("meta") or {}).get("built")
        lag = None
        try:
            lag = (dt.date.fromisoformat(str(d_built)[:10])
                   - dt.date.fromisoformat(str(fb_built)[:10])).days
        except Exception:
            warn(f"內嵌快照 meta.built={fb_built!r} 解不出日期，無法判斷落後多久")
        div = []
        if lag is not None and lag > 45:
            div.append(f"built 落後 data.json {lag} 天（{fb_built} vs {d_built}）")
        fc, dc = num(fb.get("composite")), num(d.get("composite"))
        if fc is not None and dc is not None and abs(fc - dc) > 5:
            div.append(f"composite 差 {abs(fc - dc):.1f}（快照 {fc} vs 現行 {dc}）")
        fr = (fb.get("quadrant") or {}).get("regime")
        dr = (d.get("quadrant") or {}).get("regime")
        if fr and dr and fr != dr:
            div.append(f"象限 regime 不同（快照「{fr}」vs 現行「{dr}」）")
        if div:
            warn("內嵌快照已舊到會誤導，請以現行 data.json 重灌："
                 + "；".join(div))
        elif lag is not None:
            ok(f"內嵌快照與現行 data.json 差距在容忍範圍內（落後 {lag} 天）")


def engine_tw_anchors(path):
    """用 AST 抓出 tupd("id", ..., pw(值, [[錨點]]), ...) 裡的錨點字面值。

    台灣指標的錨點沒有進 data.json（tw.items 沒有 anchors 欄位），只以字面量
    寫在引擎裡，所以這是唯一能跟 brief §4.6 對帳的來源。抓不到（例如分數不是
    直接由 pw 算出來）就不列入，寧可少報也不要誤報。
    """
    out = {}
    if not os.path.isfile(path):
        return out
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except SyntaxError:
        return out
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "tupd" and n.args):
            continue
        iid = n.args[0]
        if not (isinstance(iid, ast.Constant) and isinstance(iid.value, str)):
            continue
        for sub in ast.walk(n):
            if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                    and sub.func.id == "pw" and len(sub.args) >= 2):
                try:
                    out[iid.value] = ast.literal_eval(sub.args[1])
                except Exception:
                    pass
                break
    return out


def engine_spreads(path):
    """用 AST 找出 update_data.py 寫進 sp[...] 的鍵與欄位。
    回傳 {鍵: {欄位, ...}}；只認得字面量寫法（sp["hy"] = {...}、sp["hy"]["y1"] = ...），
    動態組出來的鍵抓不到，所以這裡的結果是「保證有寫」而不是「全部」。"""
    out = {}
    if not os.path.isfile(path):
        return out
    try:
        tree = ast.parse(open(path, encoding="utf-8").read())
    except SyntaxError:
        return out

    def const(node):
        return node.value if isinstance(node, ast.Constant) else None

    for n in ast.walk(tree):
        if not isinstance(n, ast.Assign):
            continue
        for t in n.targets:
            if not isinstance(t, ast.Subscript):
                continue
            base, key = t.value, const(t.slice)
            if isinstance(base, ast.Name) and base.id == "sp" and isinstance(key, str):
                flds = out.setdefault(key, set())
                if isinstance(n.value, ast.Dict):
                    flds.update(k for k in map(const, n.value.keys) if isinstance(k, str))
            elif (isinstance(base, ast.Subscript) and isinstance(base.value, ast.Name)
                  and base.value.id == "sp" and isinstance(const(base.slice), str)
                  and isinstance(key, str)):
                out.setdefault(const(base.slice), set()).add(key)
    return out


# -------------------------------------------------------- 3-b. spreads 欄位對帳
def check_spreads_keys(repo, html, d):
    """前端信用磚塊直接讀 charts.spreads.<鍵>.<欄位>；引擎沒寫的欄位會算成 NaN
    並顯示成「−NaNbp」。曾經真的上線過，所以做成機械檢查。"""
    if "const sp = DATA.charts.spreads" not in html:
        warn("index.html 找不到 const sp = DATA.charts.spreads，略過 spreads 對帳")
        return
    js = "\n".join(re.findall(
        r"<script(?![^>]*application/json)[^>]*>(.*?)</script>", html, re.S))
    # 點記法 sp.hy.m3 與括號記法 sp["hy"]["m3"] 都要認得，否則改個寫法就漏檢
    read_keys = set(re.findall(r"\bsp\.([A-Za-z_]\w*)", js))
    read_keys |= set(re.findall(r"""\bsp\[\s*["'](\w+)["']\s*\]""", js))
    # 鍵與欄位各自可能是 .name 或 ["name"]，四種組合都要抓
    KEY = r"""(?:\.([A-Za-z_]\w*)|\[\s*["'](\w+)["']\s*\])"""
    read_fields = set()
    for k1, k2, f1, f2 in re.findall(r"\bsp" + KEY + r"\s*" + KEY, js):
        read_fields.add(((k1 or k2), (f1 or f2)))
    if not read_keys:
        warn("index.html 沒有讀取任何 charts.spreads 鍵，略過對帳")
        return

    up = os.path.join(repo, "scripts", "update_data.py")
    written = engine_spreads(up)
    live = d.get("charts", {}).get("spreads") or {} if d else {}

    miss = sorted(read_keys - set(written) - set(live))
    if miss:
        bad("index.html 讀 charts.spreads 的 " + "／".join(miss) +
            "，但 update_data.py 沒有寫入（該磚塊會空白或顯示 NaN）")
    else:
        ok(f"charts.spreads 前端讀取的 {len(read_keys)} 個鍵，引擎都有寫入")

    # data.json 還有、但引擎已經不再寫的鍵：現在看起來正常，值卻永遠凍在今天
    # （不能只用 read_keys - written - live，那會被 live 裡的殘值蓋掉這類退化）
    regress = sorted((read_keys & set(live)) - set(written))
    if regress:
        bad("charts.spreads 的 " + "／".join(regress) +
            " 仍在 data.json 裡，但 update_data.py 已經不寫了"
            "（前端照畫，值會停在最後一次寫入的日期，看起來卻很正常）")

    unused = sorted(set(written) - read_keys)
    if unused:
        warn("引擎寫了 charts.spreads 的 " + "／".join(unused) +
             "，但前端沒有畫（無害，確認是不是忘了做磚塊）")

    holes, pending = [], []
    for k, f in sorted(read_fields):
        if k not in live or not isinstance(live[k], dict):
            continue          # 鍵本身的問題已在上面報過
        if f in live[k]:
            continue
        (pending if f in written.get(k, set()) else holes).append(f"{k}.{f}")
    if holes:
        bad("前端讀得到鍵但引擎沒寫欄位：" + "／".join(holes) +
            "（相減會變成 NaN，引擎要補寫或前端要略過）")
    if pending:
        warn("引擎已寫但現行 data.json 還沒有的欄位：" + "／".join(pending) +
             "（下次自動更新後生效；在那之前線上仍是舊值）")
    if not holes and not pending:
        ok(f"charts.spreads 前端讀取的 {len(read_fields)} 個欄位在 data.json 中都存在")

    # 月頻序列（FEDFUNDS、USINFO）本來就落後 30–60 天，只抓真的凍住的殘留
    stale = [f"{k}（{v['asof']}）" for k, v in live.items()
             if isinstance(v, dict) and v.get("asof")
             and (days_ago(v["asof"]) or 0) > 120]
    if stale:
        warn("charts.spreads 這些鍵的 asof 超過 120 天，確認引擎是否真的有在抓："
             + "／".join(sorted(stale)))


# -------------------------------------------------------- 3. 引擎與前端
def check_code(repo, d):
    up = os.path.join(repo, "scripts", "update_data.py")
    if not os.path.isfile(up):
        bad("找不到 scripts/update_data.py")
    else:
        try:
            r = subprocess.run([sys.executable, up, "--selftest"], capture_output=True,
                               text=True, timeout=90, cwd=repo)
            if r.returncode == 0 and "selftest OK" in r.stdout:
                ok("update_data.py --selftest 通過")
            else:
                bad(f"update_data.py --selftest 失敗：{(r.stderr or r.stdout).strip()[-300:]}")
        except Exception as ex:
            warn(f"無法執行 selftest：{ex}")

    idx = os.path.join(repo, "index.html")
    if not os.path.isfile(idx):
        bad("找不到 index.html")
        return
    html = open(idx, encoding="utf-8").read()
    if 'fetch("data.json"' in html or "fetch('data.json'" in html:
        ok("index.html 採 fetch-first 讀取 data.json")
    else:
        bad("index.html 沒有 fetch data.json 的邏輯（會永遠顯示內嵌快照）")
    for fn in ("renderQuad", "renderTriggers", "renderTwV2", "renderTwProse"):
        if fn not in html:
            bad(f"index.html 缺 v2 render 函式 {fn}")

    # index.html 有一句寫死的「N 項指標依三層頻率分組」。它是結構性敘述、不必由引擎生成，
    # 但加減指標時最容易漏改（MAINTENANCE §6.4 的老毛病）——所以把它交給機器對帳。
    mN = re.search(r"(\d+)\s*項指標依三層頻率分組", html)
    real = sum(LAYER_N.values())
    if not mN:
        warn("index.html 找不到「N 項指標依三層頻率分組」這句，無法核對指標項數")
    elif int(mN.group(1)) != real:
        bad(f"index.html 寫「{mN.group(1)} 項指標」，但三層實際共 {real} 項"
            f"（{'＋'.join(f'{k} {v}' for k, v in LAYER_N.items())}）")
    else:
        ok(f"index.html 的「{real} 項指標」與三層項數一致")

    # 象限分界 45／55 在四個地方各有一份：引擎（update_data.py 的 regime 判斷）、
    # 本檔（下方 quadrant 重算）、brief §3.3、前端 renderQuad 的底圖與分隔線。
    # 前三份互相對帳，唯獨前端那份沒人看——改門檻時象限背景不會跟著動，
    # 頁面會把點畫在錯的色塊上（對使用者說謊 → FAIL，比照「N 項指標」那句的定級）。
    if "X(45)" in html and "Y(55)" in html and "45,55,100" in html:
        ok("index.html renderQuad 的 45/55 象限分界與引擎一致（第四份拷貝有對帳）")
    else:
        bad("index.html renderQuad 找不到 45/55 象限分界（X(45)/Y(55)）——"
            "門檻可能已改而前端底圖沒跟上，或 renderQuad 被重構（重構後請同步更新本檢查）")

    check_fallback(html, d)
    check_spreads_keys(repo, html, d)

    # JS 語法
    blocks = re.findall(r"<script(?![^>]*application/json)[^>]*>(.*?)</script>", html, re.S)
    js = "\n".join(blocks)
    if not js.strip():
        warn("index.html 找不到可檢查的 <script> 區塊")
        return
    # 用固定檔名（舊版是 /tmp/_bubble_check.js）會在兩個 healthcheck 同時跑時互相蓋掉，
    # 而且寫檔動作若放在 try 外面，磁碟滿或 /tmp 唯讀時會直接把整個健康檢查炸掉。
    # 改用 tempfile 產生唯一檔名，並把寫檔一起包進 try。
    import tempfile
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix="bubble_check_", suffix=".js")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(js)
        r = subprocess.run(["node", "--check", tmp], capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            ok("index.html 的 JS 語法正常（node --check）")
        else:
            bad(f"index.html JS 語法錯誤：{r.stderr.strip()[:300]}")
    except FileNotFoundError:
        warn("環境無 node，略過 JS 語法檢查")
    except Exception as ex:
        warn(f"JS 語法檢查未完成：{ex}")
    finally:
        try:
            if tmp:
                os.remove(tmp)
        except OSError:
            pass

    mt = os.path.join(repo, "MAINTENANCE.md")
    ok("MAINTENANCE.md 存在") if os.path.isfile(mt) else bad("找不到 MAINTENANCE.md")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo")
    a = ap.parse_args()
    repo = find_repo(a.repo)
    if not repo:
        print("FAIL 找不到 ai-bubble-monitor（用 --repo 指定路徑）")
        sys.exit(2)
    print(f"repo: {repo}\n" + "-" * 60)
    d = check_data(repo)
    print("-" * 60)
    check_brief(repo, d)
    print("-" * 60)
    check_code(repo, d)
    print("-" * 60)
    print(f"總計  PASS {R['pass']}　WARN {R['warn']}　FAIL {R['fail']}")
    sys.exit(1 if R["fail"] else 0)


if __name__ == "__main__":
    main()
