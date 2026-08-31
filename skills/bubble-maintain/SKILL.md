---
name: "bubble-maintain"
description: "AI 泡沫監控儀表板（ai-bubble-monitor）的維護入口指標。維護、除錯、擴充這套每交易日自動更新的量化儀表板時，走 Cowork 的 /maintain（bubble）；規格看 repo 內的 AGENT_BRIEF.md，維護與事故檔案看 MAINTENANCE.md。也在使用者輸入 /bubble-maintain 時觸發。"
---

# AI 泡沫監控儀表板 · 維護入口（指標）

**維護流程已併入 Cowork 的 `/maintain` skill（`bubble/` 資料夾）。** 走那裡：載入現況 → 子代理獨立比對漂移 → 報告 → 拿到確認才動手 → 交付。

**這份檔案刻意只留指標，不留規格。** 它沒有任何機器在跟 `AGENT_BRIEF.md` 對帳，所以只要抄一份規格進來，它就會安靜地變成第二個真相來源然後過期——2026-08-17 的稽核在這份檔案抓到 7 處落後現況的抄本（其中「換路徑可以繞開快取」那條是 `MAINTENANCE.md` §6.10 明文判定為事後歸因並已刪除的做法）。**新的事實細節寫 `AGENT_BRIEF.md`，新的「為什麼」寫 `MAINTENANCE.md` 第 6 節。**

| 我想… | 去哪 |
|---|---|
| 看系統現在健不健康 | `python3 healthcheck.py`（唯讀，不碰 git、不連網） |
| 知道規格：模型、指標、錨點、schema、人機分工 | `AGENT_BRIEF.md` |
| 知道怎麼改、踩過什麼坑、為什麼是現在這樣 | `MAINTENANCE.md` |
| 實際動手維護 | Cowork 的 `/maintain`，選 AI 泡沫監控 |

三件在動手前就該知道的事：

- **發布走發布器，不要自己 push。** 只改 `data.json` 就寫進 `~/outbox/bubble/`（60 秒內由 launchd 自動發布）；動到程式或文件交 `.patch` 由使用者 `git am`。兩道閘門（`gate.py`、`healthcheck.py`）在 `auto_publish.py` 裡，繞過它就是繞過閘門。細節見 `MAINTENANCE.md` §3。**不索取、不使用任何 token。**
- **數字一律有來源，抓不到就空著**（`INTERNALS.md` §5.1）。這是整套系統的根本契約。
- **`history` 只附加、同日去重、永不改寫既有日期**——象限軌跡與主題匯流訊號報的跨期比較都靠它。
