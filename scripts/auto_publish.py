#!/usr/bin/env python3
"""每週質化覆核的自動發布。由 launchd 每 60 秒觸發，跑在 Mac 上。

用法：auto_publish.py [outbox] [repo]
預設：~/outbox/bubble  →  ~/Projects/ai-bubble-monitor

## 為什麼不共用 kb-core 的 `tools/publish.py`

那支的第 2 條設計是**不可改寫守衛**：`data/<date>.json` 已存在且內容不同就
exit 11 拒絕覆寫——「已發布的一期就是已發布的樣子」。

泡沫監控的 `data.json` **每個交易日都被 Actions 覆寫**，語意正好相反。
硬塞進去會破壞那支程式存在的理由。所以照同一個**模式**另寫一支：
每 60 秒、自己的 outbox 子目錄、閘門在寫入之前、每次發布都寫回執、
永不 force push。**共用的是紀律，不是程式碼。**

## 空輪次

週頻系統的絕大多數輪次都是空的。**空輪次完全不印東西**——
一週會有一萬次，印了就把真正的訊息淹掉。有草稿才開始寫 log。

## 失敗的兩種，處理方式不同

- **內容問題**（gate.py 或 healthcheck.py 不過）：草稿改名成 `.parked`，
  不再重試。它不會自己好，每 60 秒重試一次只會洗版。
- **推送問題**（pull／push 失敗、遠端不通）：留著草稿，下一輪再試，
  但累計次數；超過上限也 park。**網路會自己好，設定錯誤不會。**

兩種都寫回執。**沒有回執代表這支根本沒跑**，那跟「回執說失敗」是兩件事。
"""
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

MAX_PUSH_RETRY = 30          # 每 60 秒一次 → 半小時
STAMP = re.compile(r"^data-(\d{4}-\d{2}-\d{2})\.json$")


def sh(args, cwd, timeout=180):
    p = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def log(m):
    print(f"[{dt.datetime.now():%Y-%m-%d %H:%M:%S}] {m}", flush=True)


def receipt(outbox, stamp, code, phase, detail, extra=None):
    r = {"system": "ai-bubble-monitor", "stamp": stamp, "exit": code,
         "phase": phase, "detail": detail[-2000:],
         "at": dt.datetime.now().astimezone().isoformat()}
    if extra: r.update(extra)
    (outbox / f"{stamp}.receipt.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return r


def park(draft, why):
    """內容問題：改名不再重試。它不會自己好。"""
    dest = draft.with_suffix(draft.suffix + ".parked")
    draft.rename(dest)
    log(f"**已 park**：{dest.name}（{why}）。修好之後把 .parked 拿掉就會重試。")


def main():
    outbox = Path(sys.argv[1] if len(sys.argv) > 1
                  else os.path.expanduser("~/outbox/bubble"))
    repo = Path(sys.argv[2] if len(sys.argv) > 2
                else os.path.expanduser("~/Projects/ai-bubble-monitor"))
    outbox.mkdir(parents=True, exist_ok=True)
    (outbox / "_done").mkdir(exist_ok=True)

    drafts = sorted((p for p in outbox.glob("data-*.json") if STAMP.match(p.name)),
                    key=lambda p: p.stat().st_mtime)
    if not drafts:
        return 0                      # 空輪次：安靜。一週一萬次。
    draft = drafts[-1]
    stamp = STAMP.match(draft.name).group(1)
    log(f"=== 發現草稿 {draft.name} ===")

    if not (repo / ".git").is_dir():
        log(f"**找不到 clone：{repo}**")
        receipt(outbox, stamp, 2, "repo", f"missing {repo}")
        return 2

    try:
        payload = json.loads(draft.read_text(encoding="utf-8"))
    except Exception as e:
        receipt(outbox, stamp, 3, "parse", f"{e.__class__.__name__}: {e}")
        park(draft, "不是合法 JSON"); return 3

    code, out = sh(["git", "status", "--porcelain"], repo)
    if code or out.strip():
        log(f"**工作區不乾淨，不動它**：\n{out.strip()[:600]}")
        receipt(outbox, stamp, 4, "dirty", out)
        return 4                      # 留著草稿：人清乾淨之後下一輪就會發。

    code, out = sh(["git", "pull", "--rebase"], repo)
    if code:
        return retry_or_park(outbox, draft, stamp, "pull", out)
    log("pull --rebase 完成")

    before = None
    dj = repo / "data.json"
    try: before = json.loads(dj.read_text(encoding="utf-8")).get("composite")
    except Exception: pass

    shutil.copy2(draft, dj)
    staged = ["data.json"]
    html = outbox / f"index-{stamp}.html"
    if html.is_file():
        shutil.copy2(html, repo / "index.html"); staged.append("index.html")
        log(f"同時套用 {html.name}")

    for name, args in (("gate", [sys.executable, "scripts/gate.py"]),
                       ("healthcheck", [sys.executable, "healthcheck.py", "--repo", "."])):
        code, out = sh(args, repo)
        log(f"--- {name} ---\n{out.strip()[-3000:]}")
        if code:
            sh(["git", "checkout", "--"] + staged, repo)
            receipt(outbox, stamp, 5, name, out,
                    {"composite_before": before,
                     "composite_draft": payload.get("composite")})
            park(draft, f"{name} 沒過")
            return 5

    sh(["git", "add"] + staged, repo)
    code, _ = sh(["git", "diff", "--cached", "--quiet"], repo)
    if code == 0:
        log("內容與 repo 相同，不做空提交")
        shutil.move(str(draft), outbox / "_done" / draft.name)
        receipt(outbox, stamp, 0, "nochange", "draft identical to repo")
        return 0

    sh(["git", "-c", "user.name=GunDamnBoy",
        "-c", "user.email=haonung.chiang@gmail.com",
        "commit", "-m", f"data: weekly qualitative review {stamp}"], repo)
    code, out = sh(["git", "push"], repo)
    if code:
        sh(["git", "reset", "--soft", "HEAD~1"], repo)
        sh(["git", "restore", "--staged"] + staged, repo)
        sh(["git", "checkout", "--"] + staged, repo)
        return retry_or_park(outbox, draft, stamp, "push", out)

    shutil.move(str(draft), outbox / "_done" / draft.name)
    if html.is_file(): shutil.move(str(html), outbox / "_done" / html.name)
    log(f"**已發布 {stamp}**　composite {before} → {payload.get('composite')}")
    receipt(outbox, stamp, 0, "pushed", out,
            {"composite_before": before, "composite_after": payload.get("composite"),
             "staged": staged})
    return 0


def retry_or_park(outbox, draft, stamp, phase, out):
    """推送類的失敗留著重試——網路會自己好。但不要無限重試。"""
    n = outbox / f".{stamp}.attempts"
    k = int(n.read_text()) + 1 if n.is_file() else 1
    n.write_text(str(k))
    log(f"**{phase} 失敗（第 {k} 次）**：\n{out.strip()[-800:]}")
    receipt(outbox, stamp, 6, phase, out, {"attempts": k})
    if k >= MAX_PUSH_RETRY:
        park(draft, f"{phase} 連續失敗 {k} 次")
        n.unlink(missing_ok=True)
    return 6


if __name__ == "__main__":
    sys.exit(main())
