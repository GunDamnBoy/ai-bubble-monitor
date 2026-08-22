#!/bin/bash
# 安裝每週覆核的自動發布。可重複執行。
#
# 生效的是 ~/Library/LaunchAgents/ 裡的副本，版控的那一份在本 repo 的 launchd/。
# 兩邊會漂移而 launchd 不會告訴你——所以這支每次都從版控那份重新複製。
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.kenny.kbpublish.bubble"
SRC="$REPO/launchd/$LABEL.plist"
DST="$HOME/Library/LaunchAgents/$LABEL.plist"
OUTBOX="$HOME/outbox/bubble"

[ -f "$SRC" ] || { echo "找不到 ${SRC}" >&2; exit 1; }

echo "== 1. outbox 子目錄 =="
mkdir -p "$OUTBOX/_done"
echo "$OUTBOX"

echo
echo "== 2. 複製 plist（版控 → 生效） =="
mkdir -p "$HOME/Library/LaunchAgents"
cp "$SRC" "$DST"
plutil -lint "$DST"

echo
echo "== 3. 載入 =="
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$DST"
launchctl print "gui/$(id -u)/$LABEL" | grep -E "state|program|last exit" | head -5 || true

echo
echo "== 4. 確認 =="
PY=$(/usr/bin/plutil -extract ProgramArguments.0 raw "$DST")
echo "直譯器  : ${PY}"
[ -x "$PY" ] || echo "  **這個直譯器不存在或不可執行——改 plist 的第一個參數**"
"$PY" "$REPO/scripts/auto_publish.py" "$OUTBOX" "$REPO" && \
  echo "空輪次跑得起來（沒有輸出是對的）"
echo
# **變數一律加大括號。** 後面緊接全形標點時，bash 會把那幾個位元組當成變數名的
# 一部分，於是 `$OUTBOX，` 變成 `$OUTBOX，`（找不到）而 set -u 讓整支腳本
# 在最後一行掛掉——**前面每一步都成功了，結束碼卻是非零**。
echo "完成。把 data-YYYY-MM-DD.json 放進 ${OUTBOX}，60 秒內會自動發布。"
echo "回執在 ${OUTBOX}/<日期>.receipt.json；log 在 ${OUTBOX}/publish.log。"
