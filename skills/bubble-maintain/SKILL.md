---
name: "bubble-maintain"
description: "AI 泡沫監控儀表板（ai-bubble-monitor）的維護入口。當使用者要修改、除錯、擴充或了解這套每交易日自動更新的量化儀表板時使用——包括新增／移除指標、調整層權重或計分錨點、改資料源、動 GitHub Actions、修每週質化覆核排程 prompt、檢查規格與引擎與網站是否同步、排查網站沒更新或圖表卡住不動、確認台股子模型與觸發器。也在使用者輸入 /bubble-maintain 時觸發。"
---

# AI 泡沫監控儀表板 · 維護入口

你要協助使用者修改或除錯「AI 泡沫監控儀表板」這套每交易日自動更新的量化系統。**先把現況叫出來，再談要改什麼。** 不要憑印象回答。

全程使用繁體中文（台灣用語）。

## 這套系統在做什麼（先理解，否則會把它當成又一個新聞儀表板）

一句話：**它不解讀行情，它量測 AI 資本循環的體溫。**

三個知識庫各自獨立運作，這一套是其中唯一的量化庫：

| 庫 | 性質 | 單獨看能回答 |
|---|---|---|
| 投顧知識庫 advisory-knowledge-hub | 敘事．每日．新聞 | 發生了什麼 |
| 節目知識庫 podcast-knowledge-digest | 敘事．每日．專業討論 | 聰明人在想什麼 |
| **AI 泡沫監控 ai-bubble-monitor（本系統）** | **量化．每交易日．自動抓取** | **客觀狀態是什麼** |

**主題匯流訊號報（convergence-weekly）每週會讀本系統的 `data.json`。** 所以 `history` 的連續性與 schema 的穩定性有外部相依，不是只有自己在用——動 schema 前先想一下匯流報的 `renderQuant` 會不會斷。

模型的骨架是**三個頻率層**，不是概念分類：L1 市場與情緒（日頻）、L2 資金與信用（日～週）、L3 基本面兌現（月～季 nowcast）。這是刻意的——概念分類會把季頻的基本面和日頻的市場擠進同一個平均，日頻訊號被稀釋成一條平線。v1 用概念分類，一個月幾乎不動，這就是改版的原因（`MAINTENANCE.md` 第 6.1 節）。

- 網站：<https://gundamnboy.github.io/ai-bubble-monitor/>
- repo：`GunDamnBoy/ai-bubble-monitor`（GitHub Pages 從 `main` 根目錄直出）
- 自動更新：GitHub Actions，cron `30 22 * * 1-5` UTC ＝ 台北週二～週六 06:30
- 每週質化覆核排程：`0 1 * * 1` UTC ＝ 台北週一 09:00

## 文件分工（先理解，否則會把東西寫錯地方）

| 檔案 | 只放什麼 | 誰讀 |
|---|---|---|
| `AGENT_BRIEF.md` | **現在的規格與判斷規則**，含 `data.json` schema | 每週覆核排程每次完整讀一次；維護者 |
| 排程任務的 prompt | **流程骨架**：順序與分支判斷、人機分工。事實細節指向 brief 章節，刻意不重抄 | 排程觸發時執行 |
| `MAINTENANCE.md` | **維護說明＋事故與決策檔案**（第 6 節）：事故經過、被否決的選項 | 維護者 |
| `index.html` 的 `<script id="update-spec">` | **僅指向 brief 的指標**，不放規格 | 讀到這頁 HTML 的工作階段 |

**寫東西前先想清楚放哪一份。** 新的事實細節寫 brief，新的「為什麼」寫 `MAINTENANCE.md` 第 6 節，排程 prompt 只在流程或人機分工改變時才動。

---

## 第 1 步：載入現況（先做完再開口）

1. **先取得工作副本。** 本系統沒有本機掛載，唯一權威是 GitHub。用每週覆核排程裡存放的 fine-grained PAT 淺層 clone 到暫存目錄：

   ```
   git clone --depth 1 https://x-access-token:{TOKEN}@github.com/GunDamnBoy/ai-bubble-monitor.git /tmp/bubble
   ```

   **PAT 只從排程任務的 prompt 取得，絕不寫進任何輸出。** 本工作階段的 GitHub **API 被 proxy 擋，但 HTTPS git 操作正常**——要看 repo 狀態就用 git，不要試 API。
   若上一輪已經 clone 過，改用 `git -C /tmp/bubble pull --ff-only` 確認是最新的，不要在舊副本上作業（曾經在過期 clone 上判斷過現況，結論全錯）。

2. **跑健康檢查**，機械式檢查一次做完：

   ```
   python3 /tmp/bubble/healthcheck.py
   ```

   它不改 repo、不連網、不碰 git（只在系統暫存目錄寫一個唯一檔名的 `.js` 給 `node --check`，跑完刪掉），會自動偵測 repo 位置，也可以用 `--repo <路徑>` 指定。輸出每行是 PASS／WARN／FAIL，**把 FAIL 與 WARN 全部帶進第 3 步的報告**。

3. 讀 `MAINTENANCE.md`（全部，含第 5 節待辦與第 6 節事故檔案）。
4. 讀 `AGENT_BRIEF.md`（**全部**，含第 10 節變更紀錄）。
5. 用 `mcp__claude-code-remote__list_triggers` 找到「AI 泡沫監控：每週質化覆核與發布（v2）」，記下 `cron_expression`、`enabled`、`next_run_at`、通知設定，並讀它的 prompt 全文。
   **這個工具的輸出很大，可能超過 token 上限而被存成檔案**；真的存成檔案就用 Python 解析，回傳結構是 `{"data": [ ... ]}`，prompt 在 `job_config` 底下。
   **那份 prompt 裡有 PAT 明文——解析時只取需要的欄位，絕不整段回貼到對話或摘要裡。**
6. 讀 `data.json` 的 `stage`（四階段檢查清單本週的證據）與 `events` 前幾條——**這兩塊是你這次要下判斷的材料**，不是驗算。`meta.lastAutoRun` 與 `history` 不用自己翻，健康檢查已經印出來了。

健康檢查已涵蓋的項目**不要再手動重跑一遍**：層分數與 composite 重算、象限、台股子群、錨點單調性、燈號一致性、指標項數 vs `LAYER_N`、觸發器齊全、`history` 排序與末筆對齊 `meta.built`、`meta.lastAutoRun` 的成功／失敗項與「有沒有已知清單以外的新失敗來源」、brief §9 已知失效來源 vs `KNOWN_FAIL` 白名單對帳、`asof` 未來日期偵測、**質化指標的 `note` 軌跡終點 vs 現在的 `score`、`note` 有沒有日期、`asof` 依各項頻率分開設的過期門檻**、`stage` 的內部一致性（清單狀態、`current`、以及「點亮 X／6」這句**存在與否**及數字是否符合清單實算）、brief 錨點與權重比對、brief 第 4.6 節台灣錨點 vs 引擎 AST、workflow cron 與 Pages 步驟、`--selftest`、`node --check`、`index.html` 那句「N 項指標依三層頻率分組」vs 實際項數、內嵌退路快照（`meta.version`、v2 區塊齊全、`history` 筆數、以及**與現行 `data.json` 的 `built`／`composite`／`regime` 有沒有脫節到會誤導**）、`charts.spreads` 的前端讀取鍵與欄位 vs 引擎實際寫入對帳。你的注意力應該放在腳本抓不到的東西上——也就是下一步。

---

## 第 2 步：比對同步狀態（這是本 skill 最重要的價值）

`healthcheck.py` 只能抓機械式與數值型的不一致。**敘述性的矛盾只能靠讀。**

**用 Agent 子代理做獨立比對，不要自己讀完就下結論。** 這是既有三套系統反覆驗證過的做法：主線自己比對後常判定「大體同步」，子代理獨立比對卻能抓出實質矛盾與遺漏規則。**這是固定步驟，不是可選項。**

給子代理的指示要包含這些面向，並要求指出行號與原文、只回報不一致處、不要提改進建議、**不要複製貼上任何看起來像 token 的字串**：

**`AGENT_BRIEF.md` ↔ 排程 prompt**

- **排程 prompt 的第一步有沒有「完整讀一次 `AGENT_BRIEF.md`」。** 整個文件分工建立在這條指向鏈上——brief 承擔事實細節、prompt 只留流程骨架。鏈一斷，rubric、燈號界、覆寫禁令的例外全部拿不到，而且從 prompt 本身看不出缺了什麼。**先查這一條。**
- 執行時刻與 cron（brief 第 8 節 vs 排程設定 vs workflow 檔）
- 人機分工：brief 第 8.1／8.2 節的清單與 prompt 裡的清單是否**逐項**相符（列出只出現在其中一邊的 id；`stage.current`／`tsmc_52w`／`twii_pos` 這類單項最容易被漏掉）
- **「絕對不要重抓 `events`／`triggers` 與所有自動指標」**這條禁令有沒有同時出現在兩份（漏掉會讓覆核用殘值蓋掉好資料，這是最容易漂移也最傷的一條），以及 `events` 可補 1–2 條的例外
- **收尾重算的順序**：指標 `zone` → 層分數 → `composite` → `quadrant` → `tw.subs`／`tw.heat` → `history` 附加 → `meta.built`／`meta.builtTime`（**但 `meta.lastAutoRun` 不動**），共**七步**，兩份是否一致。第七步最容易被當成不重要而漏掉，但 healthcheck 硬性要求 `history` 最後一筆的日期等於 `meta.built`，漏掉會直接 FAIL 擋住推送
- 質化指標的 rubric（brief 第 4.5 節）與 prompt 裡的評分指示
- `note` 必須記錄上週分數與變動理由這條規則
- 推送方式、commit 訊息格式、token 只用於 git 且不得顯示明文
- **線上驗證打的是網站還是 repo，以及用的是哪個工具**。抓 `raw.githubusercontent.com` 只證明 commit 進了 repo，正是 6.2 事故分不出來的那種情況——要抓 `gundamnboy.github.io`。但**這一步不能用 `curl`**：本容器的 Bash 連不到 `github.io`（回 http=000），排程 prompt 舊版寫的那行 curl 從來沒有真的成功過，只會拿到空字串然後往下走得像沒事一樣。要確認 prompt 裡用的是 `WebFetch`，而且重抓的繞快取方式是**換路徑**（多打斜線）而不是加 `?t=`——後者實測無效，快取鍵忽略 query string
- 推播摘要的格式與「⚠ 警示」的觸發條件
- **排程 prompt 遺漏了 brief 的哪些關鍵規則**

**`AGENT_BRIEF.md` ↔ `scripts/update_data.py` ↔ `index.html`**（本系統獨有、也最容易漂移的一面）

- 指標數量、`id`、所屬層，三處是否一致
- 特殊計分規則（VIX 非單調、Greenwood-Shleifer 校準）在 brief 與 `vix_score`／`gsy_stats` 是否相符
- 台股子群定義與權重（brief 第 4.6 節 vs `subs_def`／`wmap`）、`TW_BASKET` 的 10 檔
- 觸發器 7 項的 `id`、門檻、`note`
- brief 第 6 節的 schema vs 實際 `data.json` 的鍵 vs `index.html` 的 render 函式
- **`index.html` 讀了引擎沒寫的鍵**（`charts.spreads` 的子鍵最容易出這種事，缺鍵或缺欄位會畫出 `NaN`；改法是「缺值就不畫」，不是補假值）。`charts.spreads` 這一塊 `healthcheck.py` 已做機械對帳，子代理要看的是**其他還沒被涵蓋的 `DATA.*` 讀取**（`charts` 其餘子物件、`params`、`stage`、`tw.*`）
- **render 函式裡寫死的敘述文字**。這些不在 `data.json` 裡，healthcheck 抓不到，只能靠讀——問「這句話明年還會是對的嗎」
- brief 第 9 節的已知失效來源 vs `meta.lastAutoRun.fail` 的實際內容。**「新的失敗來源」healthcheck 已會報**，子代理要看的是反向：§9 裡列著、但已經好幾週沒再失敗的來源（代表那一列該更新了），以及 §9 寫的「目前處置」是否還符合引擎現在真正的降級行為

**`AGENT_BRIEF.md` 內部自我一致性**

- 同一個數值在不同段落是否打架（權重、錨點、天數、筆數上限、**各層的指標項數**）
- **「質化指標佔總權重 X%」是否還算得出來**：依等權規則實算 Σ（層權重 × 該層質化項數 ÷ 該層總項數）。加減任何一個指標都會動到它，而且沒有人會記得回來改
- 上文的流程敘述是否已被下文的修正取代卻沒改
- 第 5 節的函式地圖是否還反映 `update_data.py` 的實作（含簽章）
- 交叉引用是否有效——寫「rubric 見 4.5」時，第 4.5 節真的有那一列嗎
- `MAINTENANCE.md` 第 5 節的待辦是否已經解決卻沒刪

**三處一組的實作**（改 schema 時最容易漏）

`AGENT_BRIEF.md` 第 6 節的 schema、`scripts/update_data.py`、`index.html` 的 `renderQuad`／`renderTriggers`／`renderTwV2` 與圖表區——**這三處是一組**，任一處改了另外兩處都要跟上。**漏掉第三處時頁面不會報錯，只會靜靜地少畫一塊。**

**還有第四處**：`index.html` 內嵌的 `<script id="dashboard-data">` 是 fetch 失敗時的離線退路快照。它不必每天更新，但**改 schema 或改版時要重灌**，否則離線開啟會退回舊架構的頁面。`healthcheck.py` 會比對它的 `meta.version`、v2 必要區塊是否齊全、`history` 筆數，並偵測它是否**舊到會講出另一個故事**（`meta.built` 落後現行 `data.json` 逾 45 天、`composite` 差逾 5、或象限 `regime` 不同就 WARN）。門檻刻意鬆——快照本來就是舊的拷貝，只有舊到「fetch 失敗那天使用者看到另一套數字」才算問題。但小幅漂移機器仍然抓不到，改版時還是要靠人記得重灌。

---

## 第 3 步：向使用者報告現況

用簡短的表格或條列講清楚：

- **健康檢查結果**：FAIL 與 WARN 逐條列出，PASS 用一行帶過
- **目前讀數**：`composite`、L1／L2／L3、`heat`／`support`／`regime`、觸發器點亮數、台股 `tw.heat` 與四個子群
- 最近一次自動更新的日期、成功與失敗項數，**失敗項裡有沒有 AAII／CBOE／TAIFEX 以外的新面孔**
- 季度圖表停在哪一季、是不是初步季（幾家已申報、缺誰）
- 排程狀態：下次執行、是否啟用、有沒有開推播；Cowork 桌面 artifact 的快照停在哪一天
- **brief 與排程 prompt 有沒有不同步**，有的話具體指出哪幾處、哪一邊是對的
- **brief 與引擎／網站有沒有不同步**
- **brief 內部有沒有自打架**
- `MAINTENANCE.md` 第 5 節列出的待辦與觀察中事項

然後問使用者這次想改什麼。**不要在還沒問之前就開始改。**

---

## 第 4 步：執行修改

依 `MAINTENANCE.md` 第 2 節的標準流程：

1. 先跑一次 `healthcheck.py` 記下現況（改壞了才知道是不是自己弄的）
2. 改 `AGENT_BRIEF.md`（規格）
3. 改 `scripts/update_data.py`（引擎）。動到 `to_quarters`／`pw`／`vix_score`／`bucket`／`gsy_stats`／新聞解析時，**一定要跑 `python3 scripts/update_data.py --selftest`**
4. 動到 `data.json` 結構時，**三處一起改**：brief 第 6 節、`update_data.py`、`index.html` 的對應 render
5. 只在**流程或人機分工改變**時才動排程 prompt，用 `mcp__claude-code-remote__update_trigger` 同步。
   **`prompt` 是整份取代，不是局部編輯**——送出前確認所有段落都帶上了，漏掉的段落等於刪除。**含 token 的那段也要原樣帶回去，但不要顯示在對話裡。**
6. 在 brief 第 10 節加變更紀錄，**寫清楚為什麼改**，不只是改了什麼；
   事故經過與被否決的選項寫進 `MAINTENANCE.md` 第 6 節
7. 若已知的坑或待辦有變化，同步更新 `MAINTENANCE.md` 第 4、5 節

**改完當下就再比對一次第 2 步的清單。** 大改動最容易在自己身上留下新的不同步。

### 「網站沒更新」的排查順序（不要直接改程式）

1. `data.json` 在 repo 裡也是舊的 → Actions 沒跑或整批失敗，去看 Actions log
2. repo 裡是新的、網站是舊的 → **Pages 沒重建**，先確認 workflow 最後的 `POST /pages/builds` 步驟還在且沒失敗
3. 兩邊都新、只有瀏覽器是舊的 → 快取，網址加 `?v=時間戳` 再看（這是**瀏覽器**快取，query string 對它有效；但對 WebFetch／Pages 邊緣那層快取無效，那層要換路徑，見「驗證」一節）

---

## 絕對不要做的事

- **絕不編造數字。** 抓不到的來源沿用上一次的值與 `asof`，失敗記進 `meta.lastAutoRun.fail`；連舊值都沒有就把 `score` 設 `null`，讓它顯示灰燈並退出當層平均。這是整套系統的根本契約，寧可空著也不要猜。
- **不要在每週覆核的工作階段重抓自動指標。** 覆核容器的網路有兩條路、能力不同：Bash 的 `curl`／`requests` **只通得到 `github.com` 與 `raw.githubusercontent.com`**（FRED、Stooq、SEC、TAIFEX 一律連不上，**連 `gundamnboy.github.io` 都連不上**），而通得到外網的 `WebSearch`／`WebFetch` 讀 CSV／JSON 端點只會拿到亂碼。所以禁令的真正理由不是「連不到網路」，是**能連到網路的那條路拿不到引擎要的東西**。硬要重抓的下場是抓到空值或殘值，然後把好的舊值蓋掉。對照表見 `AGENT_BRIEF.md` 第 8.3 節。
- **不要重抓 `events`、`triggers`。** `events` 是每日 Google News 管線的產出，覆核時重寫等於把新的換成更舊的（`MAINTENANCE.md` 第 6.3 節）。真的漏了重大事件最多補 1–2 條並附 url。
- **但要分清楚「重抓」和「重算」。** `quadrant`、`dims`、`composite`、`tw.subs`／`tw.heat` 是從指標分數導出的，質化分數一改就**必須**重算（brief 第 8.4 節）。把它們當成不可動的欄位，反而會讓頁面自相矛盾。
- **不要改寫既有的 `history` 筆數。** 只附加、同日去重。舊筆帶 v1 的 `D1–D6` 鍵是正常的，不要回頭改成 L1/L2/L3。象限軌跡與匯流報的跨期比較都靠它。
- **不要刪 workflow 最後那個 `POST /pages/builds` 步驟。** 用 `GITHUB_TOKEN` 推的 commit 不會觸發 Pages 佈建，這是 GitHub 的防迴圈設計不是 bug（第 6.2 節事故）。
- **不要在任何摘要、artifact、log 或對話中顯示 PAT 明文。** 它只用於本 repo 的 git 操作。
- **不要給 22 個指標各自的權重欄位。** 權重只放在層級，理由見第 6.6 節——22 個可調參數等於 22 個漂移面。加減指標本身就是在調權重。
- **不要把觸發器折成分數併進綜合溫度。** 離散門檻混進連續量會讓溫度在門檻附近來回跳（第 6.5 節）。
- **不要在指標卡或 render 函式裡寫死會過期的敘述。** 自動指標會隨數值變的話寫進 `sub` 由引擎生成，`note` 只留結構性說明（第 6.4 節）。**質化指標相反**——它們沒有引擎可生成 `sub`，`note` 必須留「上週分數 → 本週分數 ＋ 理由」的軌跡。
- **不要把 `senti` 拿掉來解決 AAII／CBOE 被擋。** 拿掉等於改了 L1 的權重結構，正解是換一個不擋機器人的情緒源。
- 不要只改 brief 或只改排程 prompt 其中一邊。
- 不要在過期的本機 clone 上作業。判斷現況前先確認工作副本與 `origin/main` 同步。

---

## 驗證

改完後：

1. 重跑 `python3 healthcheck.py`，確認沒有新的 FAIL，WARN 只剩已知的那幾項
2. 動到引擎就跑 `python3 scripts/update_data.py --selftest`
3. **再叫一次子代理**做 brief ↔ 排程 prompt ↔ 引擎的獨立比對，確認這次改動沒有製造新的不同步、也沒有在瘦身時弄丟關鍵規則
4. 推送後**一定要驗證線上**。**不要用 `curl`**——本容器的 Bash 連不到 `gundamnboy.github.io`（回 http=000，不是逾時也不是 404，是連線直接被擋），curl 會拿到空字串，接在後面的 `python3 -c` 則丟 JSONDecodeError，而流程往下走看起來像沒事。用 `WebFetch`（同一個 URL 有 15 分鐘快取，**繞法見下方，不要用 query string**）：

   ```
   WebFetch url: https://gundamnboy.github.io/ai-bubble-monitor/data.json
   prompt: Report verbatim the value of meta.built, the top-level composite number, and quadrant.regime. Output only those three values.
   ```

   比對 `meta.built` 與 `composite` 是不是你剛推的那一版。**只看網頁上的日期不夠**——Pages 沒重建時日期也會是舊的，而那正是最需要抓到的情況。

   **重抓時要換路徑，不要加 `?t=`。** 這個 URL 有 15 分鐘快取，而快取鍵**忽略 query string**——`?t=<時間戳>` 是無效的 cache-buster（2026-08-04 實測，連五次換時間戳橫跨 26 分鐘全拿回舊版，一路誤判成 Pages 沒重建）。有效的是讓路徑不同，多打斜線即可，Pages 照樣服務：`…/ai-bubble-monitor//data.json`、`///data.json`，一次加一個。
   分不出「站台是舊的」還是「你看到的是舊的」時，**去抓一個不可能有快取的 URL**——例如這次推送新改的 `README.md`。它若是新版，站台就已經好了。
   （這兩條合起來是「文件寫了一個沒人驗證過的指令」的典型案例，見 `MAINTENANCE.md` 第 6 節：**寫進流程的每一行指令，都要在寫的當下實際跑過一次**——包括那行指令裡的每一個「繞過某某」的小技巧。）
5. 若動到 `index.html`，抽出 `<script>` 區塊後 `node --check`（healthcheck 已含此項），並實際開一次頁面確認象限圖、觸發器列、台股區都有畫出來
