# 內部實作參考（INTERNALS）

> **只有在你要動程式、改 schema、或追查某個舊行為時才需要打開。**
> 每週質化覆核**不需要**讀它——覆核要用的東西全部留在 `AGENT_BRIEF.md`。
>
> **章節編號沿用原本的 §5／§6／§10。** 全站既有的交叉引用（`§5.1`、
> 「§6 末的『幾處一組』」、`§5.2`…）因此一個都不用改，只是換了個檔案。
> 拆出來的理由與代價見 `MAINTENANCE.md` §6.19。

## 什麼時候該來這裡

| 你要做的事 | 去哪一節 |
|---|---|
| 改抓取邏輯、加新來源、調重試或節流 | §5 資料管線 |
| 查某一項抓取失敗時實際填什麼 | §5 的降級表 |
| 加減 `data.json` 欄位、改前端讀的鍵 | §6 schema ＋ 末尾的「幾處一組」 |
| 追查某個舊行為是哪一版改出來的 | §10 變更紀錄 |
| **改指標定義、錨點、權重、觸發器門檻** | **回 `AGENT_BRIEF.md` §3／§4** |
| **每週覆核怎麼做、能動哪些欄位、怎麼發布** | **回 `AGENT_BRIEF.md` §8** |

**錨點與指標定義刻意留在 `AGENT_BRIEF.md`。** `healthcheck.py` 對它們做機械對帳
（brief ↔ `data.json` ↔ 引擎），搬過來就要同時改 parse 路徑，而
**一個改錯的 parse 路徑會安靜地變成沒有對帳**——那比不拆更糟。

---

## 5. 資料管線 `scripts/update_data.py`

### 5.1 核心契約：**絕不編造數字**

```python
def attempt(name, fn):
    try: fn(); ok.append(name)
    except Exception as ex: fail.append(name); log(f"[FAIL] {name}: {ex}")
```

每一個抓取動作都包在 `attempt()` 裡。**任何單一來源失敗只會被記進 `meta.lastAutoRun.fail`，該指標沿用上一次的值與 `asof`，其餘照常更新。** 這條規則凌駕一切：寧可讓一個指標停在上週，也不要讓它出現一個猜出來的數字。

抓不到又沒有舊值時，`score` 設 `null`，前端顯示「待數據」灰燈，該指標退出當層平均。

**這條契約過去有兩個實作上的漏洞，v2.1.8 已補**：整層指標全部無效時 `dims` 曾經填 `50.0`（一個編出來的中性分），現在填 `null`，`composite` 改以剩餘層重新歸一（比照 `tw.heat`）；`debt` 找不到 ≥330 天前的基期時曾經拿最新值當基期（等於替那家公司編一個 0% 年增再算進合計），現在整家剔除、分子分母一起不算。**兩個漏洞的共同型態是「編一個看起來合理的值讓計算不中斷」**——而 `healthcheck.py` 過去用同一條規則重算，所以兩邊會一起說謊，機器抓不到。

### 5.2 函式地圖

| 區塊 | 函式 | 備註 |
|---|---|---|
| 基礎 | `http_get` `pw` `vix_score` `zone` `asof_date` `set_fresh` | `zone(None)` 回 `"pending"`；`http_get` 對 timeout／連線失敗／5xx 重試 2 次（間隔 2 秒），4xx 不重試；`asof_date` 吃 `YYYY-MM-DD`／`YYYY-MM`／`YYYYQn` 三種格式，**看不懂或日期不合法（`2026-13`）一律回 `None`、不拋例外**；`set_fresh` 在寫檔前依 `IND_MAXAGE` 重標全部 `fresh`，解析再包一層 `try`——**它在原子寫檔的前一行，拋例外等於當天整份資料寫不進去，而壞掉的 `asof` 還留在檔案裡讓之後每次執行都死在同一行** |
| 總經 | `fred(series, days=620)` `fred_back(obs, back_days)` `fred_latest_and_back(series, back_days, days=620)` | `fredgraph.csv`；要同時取多個回看期時用 `fred()` 抓一次再 `fred_back()` 取值，不要重複抓（`fred_latest_and_back` 現在也只是這兩者的組合）。**`BAMLH0A0HYM2` 與 `BAMLH0A3HYC` 自 2026-04 起在 FRED 只保留 3 年觀測值**（2026-08-17 實測 metadata：`2023-08-15` 起）——620 天的預設回看期還在範圍內，但**任何想拉長回看期或做歷史校準的念頭都會在這裡撞牆**，要更長的歷史得回 ICE 原始來源（付費） |
| 價格 | `px_rows(ysym, ssym=None, rng="4y")` → **三層備援** `yf_chart`(yfinance) → `yahoo_chart`(raw API) → `stooq` | Stooq 在 Actions runner 被擋，只當最後備援。命中哪一層記進模組層的 `PX_HIT`，供台股卡片的 `sub` 顯示當次來源 |
| 統計 | `series_stats` `gsy_stats` | `gsy_stats` 需 ≥505 筆算 `ret24`、≥758 筆算 `accel`、≥505 筆算 `vol1y`（`volchg` 用） |
| 估值/情緒 | `multpl_cape` `slickcharts_mag7` `aaii_sentiment` `cboe_putcall` `cnn_fear_greed` | `aaii_sentiment` 持續在 Actions 端被擋；`cboe_putcall` 時好時壞；`cnn_fear_greed` 2026-08-10 新接入、Actions 端成敗未實測（皆見 §9）|
| 信用 | `orcl_bond_yield` | Public.com 報價頁。`hyoas`／`ccc` 取不到 91 天基期時**直接 fail 沿用舊值**，不用 0bp 的假變化計分 |
| 季報 | `edgar_rows` `to_quarters` `bucket` `refresh_edgar` `rpo_backlog` | 見 5.3。另有幾個藏在實作裡的門檻：`rpo_backlog` 若前期端點與目標日相差 >75 天就跳過該公司；`debt` 年增要求回看 ≥330 天；**`fcf` 的 YoY 在基期 TTM FCF ≤0 時沿用舊值**（負基期會把 −10B→+5B 這種改善算成 −150% 的滿熱分） |
| 台灣 | `tw_monthly_rev` `tw_bwibbu` `_margin_on` `tw_margin_balance` `backfill_margin_hist` `tw_day_trade_ratio` `tw_index_today` `taifex_tsmc_weight` `tw_customs_export_yoy` | 見 5.4 |
| 新聞 | `_parse_news_items` `fetch_news` | 見 5.5 |
| 主流程 | `main()` `selftest()` | `python3 scripts/update_data.py --selftest`。`data.json` 走**原子寫檔**（`.tmp` → rename），半寫檔會讓之後每次執行在 `json.loads` 就死 |

### 5.3 SEC EDGAR 引擎

- API：`https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/us-gaap/{tag}.json`，**必須帶符合 SEC 規範的 User-Agent**（含聯絡 email），否則 403。
- CIK：`MSFT 0000789019`、`AMZN 0001018724`、`GOOGL 0001652044`、`META 0001326801`、`ORCL 0001341439`
- 財年起點：`MSFT 7/1`、`ORCL 6/1`、其餘 `1/1`
- **標籤有公司差異**：`capex` 一般用 `PaymentsToAcquirePropertyPlantAndEquipment`，**AMZN 用 `PaymentsToAcquireProductiveAssets`**；`debt` 一般用 `LongTermDebtNoncurrent`，**ORCL 用 `LongTermNotesPayable`**；`rev` 一般用 `RevenueFromContractWithCustomerExcludingAssessedTax`，**GOOGL 新期間改用 `Revenues`**。新增公司或發現斷檔時先查標籤。
- **10-Q 的現金流量表是 YTD 累計，必須差分**。`to_quarters()` 同時吃「直接 3 個月列」與「同財年起點的 YTD 鏈相減」，並用 `80 ≤ 天數 ≤ 100` 判定是否為單季。這段有 `selftest()` 覆蓋，改動後務必跑。
- **初步季度 nowcast（v2 解決季頻落後的主解）**：若下一季已有 **≥3/5 家**申報，就計算初步合計，缺的公司沿用上一季，產出 `{prov: True, have: n, missing: [...]}`。前端畫成**空心點／45% 透明長條／※ 標記**。五家到齊後自動轉為正式值。
  - **新聞稿 ≠ SEC 申報**。公司開完財報會到 10-Q 進 EDGAR 之間有數天到數週落差，圖表沒動通常是這個原因，不是壞掉。

### 5.4 台灣資料源（全部公開、免金鑰）

| 資料 | 端點 |
|---|---|
| 月營收 | `https://openapi.twse.com.tw/v1/opendata/t187ap05_L` |
| 官方本益比／殖利率 | `https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL` |
| 融資餘額 | `https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN` |
| 當沖交易統計 | `https://www.twse.com.tw/rwd/zh/dayTrading/TWTB4U` ← 回應第一張表是市場統計，第二張是逐檔明細；**欄位位置不寫死**，照 `fields` 找「買進成交金額占市場比重」的索引 |
| 大盤／電子指數 | `https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX` |
| 台積電指數權重 | `https://www.taifex.com.tw/cht/9/futuresQADetail` ← **擋機器人，只能人工每月更新** |
| 海關出口 | `https://opendata.customs.gov.tw/data/6053/csv.csv` |

兩條**來源格式防呆**：海關 CSV **自行排序、不信任列序**；TWSE 電子指數用**精確名匹配**（保留子字串備援）。兩者都是來源改版時會靜默給錯值的地方。

`elec_rel` 與 `tw_margin` 需要 `idx_hist`／`margin_hist` 累積滿 **21 個交易日**才算得出來；未滿時 `score` 為 `null`、`disp` 顯示「序列累積中 n/21」。兩份歷史各保留最近 90 筆。

**`margin_hist` 不必等**（v2.1.6 起）：`MI_MARGN` 吃 `date=` 參數，`backfill_margin_hist()` 會在筆數不足 21 時往回抓（最多回看 45 個日曆日、跳過週末、每次請求間隔 0.3 秒），補滿之後每次執行直接跳過。**它只補、不覆蓋既有筆**。**`idx_hist` 自 v2.2.7 起也能回補**：改走 `www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=&type=IND`（23KB；`type=ALL` 回 4.1MB、含 32,000 列個股行情，不要用），`backfill_idx_hist()` 作法照抄 `backfill_margin_hist()`。**指數一律用精確名 `發行量加權股價指數`／`電子工業類指數`，沒有子字串退路**——舊版的退路 `"電子" in nm and "報酬" not in nm` 取第一個命中，實測抓到的是第三條序列（見 `MAINTENANCE.md` §6.20）。**寬鬆的退路在這裡不是保險，是安靜換掉量測對象的機制**；TWSE 改名的正確處理是報錯。回補時會先丟掉不在電子工業類指數量級（500–12000）的舊筆——**混尺度算出來的 20 期變化不是訊號是垃圾，而它會長得像一個正常的數字**。`scripts/tw_idx_probe.py` 是當初探路的工具，`--which` 可以重現舊版退路咬到哪一列。

### 5.5 新聞流 `events`

- Google News RSS，5 組查詢（`"AI bubble"`／hyperscaler capex-debt-financing／Nvidia-OpenAI-Anthropic deal-funding-IPO／TSMC-Samsung-semiconductor／"AI trade"），皆帶 `when:3d`~`when:4d`。
- 來源權威加權 `NEWS_W`（Bloomberg/Reuters/FT/WSJ = 5，CNBC/Barron's/The Information/The Economist = 4…），垃圾來源 `NEWS_BAN` 直接剔除（GlobeNewswire、PR Newswire、Motley Fool、Benzinga、Seeking Alpha 等）。
- 排序分數 `= 來源權重×2 + max(0, 4 − 天數×1.5)`；同來源上限 3 條；**超過 5 天丟棄**；標題正規化去重；最終取 12 條**由新到舊**排列。
- 連結**只收 http／https scheme**，其餘丟棄。
- 少於 5 條就整批失敗（沿用舊 `events`），不半吊子發布。

---

## 6. `data.json` schema

```
meta      { version:2, built, builtTime, nextUpdate, artifactId,
            lastAutoRun:{date, ok:[...], fail:[...], streak:{來源:連續成功次數}} }
             streak 由引擎累計：成功 +1、失敗歸零、**本次沒跑到的來源整個消失**
             （鍵集合永遠等於 ok ∪ fail）。單位是「引擎執行次數」不是天數——
             workflow_dispatch 與推程式碼觸發的那幾次也會 +1，所以它是下限而非日曆週。
             用途只有一個：讓 §9 那條「連續數週成功就該退場」的維護規則變成
             healthcheck 抓得到的東西。§9 表上「追蹤＝無」的那兩列不會有 streak
composite  number                       綜合溫度 0–100
dims       { L1, L2, L3 }               層分數；整層指標全部無效時該層為 null，
                                       composite 以剩餘層的權重重新歸一（v2.1.8）
dimMeta    { L1:{name,w,note}, L2:{...}, L3:{...} }   w 加總必須 = 1.0
zones      [ {max,label,color} × 5 ]
indicators [ 22 × {id, dim, name, value, disp, score, zone, anchors, dir,
                   asof, fresh, src, url, note, qual, sub?} ]
             fresh 由引擎依 asof 與 IND_MAXAGE 逐日重標（v2.1.4 起）：超過門檻
             寫 "stale"，前端據此畫「⚠ 資料延遲」。門檻依自然更新頻率分組——
             日頻自動 10 天（連假加上來源當天沒更新，5-6 天是常態，10 天才算卡住）、
             季頻 EDGAR 130 天、質化沿用 §4.5 的 21／75／130；未列的一律 45 天預設。
             **asof 解不出日期就維持 "ok"**（標錯比不標更糟）。healthcheck 會用引擎
             自己那份門檻與 asof_date 重算一次跟存檔比對，不一致是 FAIL
             dir 是**給人看的方向說明字串**（"越高越熱"、"越負越熱"、
             "質化評分（0-100）"…），純展示、不參與計分。方向相反的指標走
             **§3.2 的兩套慣例之一**（取負號／遞減錨點），不要照 dir 另寫邏輯
triggers   [ 8 × {id, name, state(0/1), value, note, asof, prog} ]
             prog＝距門檻進度 0–100%（現值÷門檻，夾在 0–100），由引擎逐日重算；
             megaipo 是人工旗標無連續量，prog 恆為 null。它是展示欄位，
             不參與任何計分（觸發器本來就不進綜合溫度，§3.5）。
             2026-08-10 新增——引擎第一次跑新版之前，舊 data.json 沒有這個鍵，
             前端遇缺就不畫進度條
quadrant   { heat, support, regime }    對應層為 null 時 heat／support 也是 null、
                                       regime 寫「待數據」；前端 renderQuad 遇 heat==null 不畫
tw         { heat, subs:{動能,估值,籌碼,基本面}, subWeights:{同上四鍵:權重},
             items[11], revTable[10],
             revMonth, officialPE{代號:{pe,pb}}, idx_hist[≤90], margin_hist[≤90] }
             items 每筆 {id,name,value,disp,score,note,src,url,asof,sub?}——**沒有 zone**，
             燈號由前端 zoneOf(score) 現算（讀 i.zone 會拿到 undefined）。
             sub 由引擎依當次實際情形生成、沒東西可寫就不寫這個鍵（v2.1.4 起，
             目前只有走三層備援的三個價格項用得到）；前端缺鍵就不畫
charts     { aggQ[], ttm[], debt{labels,values,note}, spreads{hy,ig,us10y,vix,
             fedfunds,usinfo,ccc,orclbond} }
             aggQ/ttm 每筆 {q,capex,ocf,fcf,ratio}，初步季另有 {prov,have,missing}
             （ttm 的 prov 沿用 aggQ，不重複記 have/missing）
             spreads 各鍵 {now, asof}，另視情況有 m3（3個月前）／y1（1年前）；
             **前端只畫存在的鍵**，缺 m3/y1 就不畫那一段（不要畫 NaN）
stage      { current, label, stages[4], checklist[6]{item,state,evi}, note }
events     [ ≤12 × {d:"MM-DD", t:"標題｜來源", url} ]
history    [ ≤400 × {date, composite, dims, tw, quad:[support,heat], trig} ]
             trig＝當日觸發器點亮數（2026-08-10 新增；舊筆沒有，屬正常，
             不要回頭補寫——覆核比較「上週點亮數」時，2026-08-10 之後的筆
             直接讀 trig，更早的仍要在動手前記當下基準）
params     { nvda_eps, ngdp_nominal, megaipo_done }
```

**`history` 只附加、同日去重、永不改寫既有日期。** 象限軌跡與匯流報的跨期比較都靠它。
**`history` 內舊筆的 `dims` 可能還是 v1 的 `D1–D6` 鍵**，這是正常的——改版當日之前的資料就是那個架構，不要回頭改寫成 L1/L2/L3。

### schema 改動的「幾處一組」

**這組連動叫「幾處一組」，刻意不帶數字**——目前是五處，而它每次都在長（原本三處，後來補了第四、第五處），把數字寫進名字只會讓四份文件各記一個版本。清單以本節為準。

改 `data.json` 結構時，**下面這幾處必須一起改**，前三處是核心：本檔第 6 節、`scripts/update_data.py`、`index.html` 的對應 render 函式（`renderQuad` / `renderTriggers` / `renderTwV2` / **`renderTwProse`** / 圖表區）。漏掉第三處時頁面不會報錯，只會靜靜地少畫一塊。`renderTwProse` 最容易被忘記——它讀 `tw.items`、`tw.heat`、`composite` 生成台股解讀文字，`healthcheck.py` 已把它列為必檢的四個 v2 render 函式之一。

**第四處**：`index.html` 內嵌的 `<script id="dashboard-data">` 是 fetch 失敗時的離線退路快照。**v2.2.6 起由引擎自己重灌**（`refresh_fallback_snapshot()`，在寫完 `data.json` 之後）——但**不是每天**：只在落後 >14 天、`composite` 差 >3 分、`meta.version` 不同、`regime` 不同、或舊快照解不出來時才動，門檻刻意比 `healthcheck.py` 的 WARN（45 天／5 分）更緊，所以那個 WARN 不該再有機會亮。重灌與不重灌都會 log，靜默跳過的守衛比沒有守衛更糟。寫回前會把自己產出的 JSON 再解析一次才落地——regex 換字串出錯時頁面仍是合法 HTML、只有那塊 JSON 壞掉，而**平常沒有人看得到它**。`scripts/gate.py` 因此也驗這一塊，發布路徑上多一道。它仍然**不需要每天更新**，但**改 schema 或改版時必須重新灌一次**，否則離線開啟會退回舊架構的頁面（v1→v2 期間就發生過，退路快照停在六維 54.1）。**重灌時把內嵌那份的 `history` 裁到最後 60 筆**（頁面體積考量；`healthcheck.py` 超過 60 筆會 WARN，**0 筆也會 WARN**——那代表重灌時把陣列灌空了）。`healthcheck.py` 另比對它的 `meta.version`、v2 必要區塊、`history` 筆數，以及 `composite`／`meta.built` 是否與 `data.json` 明顯脫節。

**快照有一個結構性例外：它的 `fresh` 是凍住的。** `fresh` 自 v2.1.4 起是活徽章，但快照裡那份永遠停在重灌當天的值——所以 fetch 失敗、頁面退到離線快照的那一天，不管快照多舊都不會出現「⚠ 資料延遲」。這是接受的取捨（快照本來就是應急拷貝，`meta.built` 會誠實顯示它有多舊），機器不驗這一項。

**第五處，而且最常被漏掉：`healthcheck.py` 自己。** 它為了能獨立驗算，硬寫了幾組常數——`LAYER_N`（各層指標項數）、`QUAL`（質化指標集合）、`TRIG`（觸發器 id）、`KNOWN_FAIL`（已知失效來源白名單）、`QUAL_MAXAGE`（質化 `asof` 的過期門檻，見 §4.5）。**引擎那邊還有兩張表**：`IND_MAXAGE`（全部 22 個指標的 `fresh` 門檻）與 **`TRIG_NOTE`**（全部 8 個觸發器的卡片說明，v2.2.10 起由引擎無條件覆寫）——兩張都不在 `healthcheck.py` 裡，但加減指標或觸發器時一樣要跟著改：`IND_MAXAGE` 漏了會靜默套 45 天預設，`TRIG_NOTE` 漏了會靜默沿用種子值（那正是 `gsy150` 那顆的成因）。`healthcheck.py` 兩張都會比對 key 集合，不符即 FAIL。**加減指標、改層歸屬、換觸發器、或某個來源恢復／新壞掉時，這個檔案也要改。** 它是把關每週交付的工具（FAIL 必須是 0），所以漏改它的下場不是靜靜少畫一塊，而是整條每週流程被自己的檢查擋住。

不過**這幾組常數的嚴厲程度不一樣**，別記成一律 FAIL：`QUAL`、`TRIG`、`KNOWN_FAIL` 對不上是 **FAIL**（擋住交付），`QUAL_MAXAGE` 與 `index.html` 的 `QUALF` 分級對不上也是 **FAIL**（`asof` 單純超過門檻則是 WARN），`LAYER_N` 與 `data.json` 對不上只是 **WARN**。這個差別是刻意的——FAIL 那幾組不一致必然代表有人漏改，而層人數本來就會因為「刻意增減指標」而變動，那時該提醒的是「記得回頭改 §4 各層表與 §4.5 的 28.9%」，不是把人擋在門外。

**但 `LAYER_N` 有第二個用途，那個是 FAIL**：`index.html` 那句「N 項指標依三層頻率分組」也拿它對帳，數字對不上直接擋住交付。理由是那句話是**寫給使用者看的**，錯了就是在頁面上說謊，跟「內部常數暫時落後」不是同一件事。所以增減指標時，`index.html` 那個數字是**必改**的，不是提醒。

---

## 10. 變更紀錄

**本節只留索引。** 一句話寫改了什麼，「為什麼改」與事故經過在 `MAINTENANCE.md` 第 6 節，逐行差異看 `git log`。**規則本身一律寫在上面的章節——來這裡找規則就是找錯地方。**

| 版本 | 日期 | 改了什麼 | 為什麼／事故經過 |
|---|---|---|---|
| **v2.2.10** | 2026-08-31 | **把三類「沒有守衛的敘述」收回引擎，並讓規格追上本機發布制**：① `triggers[].note` 改由引擎的 `TRIG_NOTE` 無條件覆寫——它過去是種子值，v2.2.1 把 `indicators[].note` 交給引擎時漏了這一份，`gsy150` 因此繼續對使用者宣稱「歷史崩盤機率 80% 區」，而 §4.1 早已禁止這句話——同時在 `healthcheck.py` 補上`TRIG_NOTE` ⊇ `TRIG` 的 FAIL 級守衛，比照 `IND_MAXAGE` 的做法，免得同型漏洞原地重生；② `rpo` 的 `asof` 改填申報期別（取三家最舊），`IND_MAXAGE` 由 10 天改回 130 天——先前不帶 `asof` 落成執行日，既謊報新鮮度也讓過期門檻永遠不觸發；③ `AGENT_BRIEF` §8.3／§8.4、`MAINTENANCE` §2／§3 由雲端交付制改寫為 outbox＋launchd，補進 `.heartbeat` 與 exit 13、把「沒有回執」由常態改判為異常；④ 頁面兩句寫死敘述（觸發器出處、申報時滯）與 §5 四條已完成的待辦一併更正 | `MAINTENANCE.md` §6.24 |
| **v2.2.9** | 2026-08-23 | 每週覆核改為**自動發布**：覆核把 `data-YYYY-MM-DD.json` 寫進 `~/outbox/bubble/`，`com.kenny.kbpublish.bubble` 每 60 秒跑 `scripts/auto_publish.py`（pull --rebase → gate → healthcheck → commit → push → 回執）。形狀比照另外四套 kbpublish，但不共用 `tools/publish.py`——那支的不可改寫守衛與本專案「每日覆寫同一個 data.json」的語意相反。內容失敗 park、推送失敗重試 | `MAINTENANCE.md` §6.23 |
| **v2.2.8** | 2026-08-22 | 新增觸發器 `sahm05`（Sahm Rule ≥0.50pp，FRED `SAHMREALTIME`）——七項觸發器過去全是市場與信用，這是唯一量實體經濟的一項。曲線斜率刻意不加：BMRI 用連續百分位、沒有公開門檻，自己選一個數字然後掛 GS 的名字就是 §6.15 換件衣服。觸發器 7 → 8，不動權重、不斷歷史 | `MAINTENANCE.md` §6.21 |
| **v2.2.7** | 2026-08-22 | `idx_hist` 可回補（RWD `MI_INDEX?date=&type=IND`）＋**修掉一個安靜的量測錯誤**：`tw_index_today()` 的精確名 `電子類指數` 在 openapi 裡不存在，每次都落到子字串退路並咬到第三條序列（存的是 24,519，正解是電子工業類指數 2,872）。改用精確名、移除退路、回補時丟掉舊尺度的筆；healthcheck 新增 elec 尺度一致性檢查 | `MAINTENANCE.md` §6.20 |
| **v2.2.6** | 2026-08-22 | 離線退路快照改由引擎自動重灌（`refresh_fallback_snapshot()`）——只在落後 >14 天／`composite` 差 >3／版本或 regime 不同時才動，寫回前先驗 JSON，`gate.py` 與 workflow 同步納入 `index.html`。新增 `scripts/tw_idx_probe.py`（`idx_hist` 回補的前置探針，不寫任何檔案） | 見 §5 與本節 |
| **v2.2.5** | 2026-08-22 | 規格書拆成兩檔：§5 資料管線／§6 schema／§10 變更紀錄搬到 `INTERNALS.md`（**編號沿用**，既有交叉引用零改動），`AGENT_BRIEF.md` −36%（39,024 → 24,956 字元）。§4 錨點表刻意不搬——healthcheck 對它做機械對帳，搬了就要改 parse 路徑。新增三道守衛檢查指向鏈與防回填 | `MAINTENANCE.md` §6.19 |
| **v2.2.4** | 2026-08-22 | `senti` 的 VIX 補第二層來源（FRED `VIXCLS` → yfinance `^VIX`），命中層記在 `senti.vix.src`、`asof` 跟著實際來源走。**沒有新增任何輸入**——期限結構（來源停更 35 天）、`^VVIX`（與 VIX 的 20 日變化相關 0.79，是同一件事量兩次）、`^SKEW`（與 VIX 幾乎正交，但中位數 36 年上移 21%，固定錨點站不住）三個候選各死在一條事前判準上 | `MAINTENANCE.md` §6.18 |
| **v2.2.3** | 2026-08-22 | 發布路徑修復：`bubble-publish` 與本機 clone 在這台機器上**根本不存在**，8/17 那次每週覆核因此沒有發布出去；§8.3 改寫成現行流程（clone 在 iCloud 之外、先 `git pull --ff-only`、`gate.py`＋`healthcheck.py` 兩道關卡、不過就還原）。Excel 版正式退場（不再維護，相關敘述全部移除） | `MAINTENANCE.md` §6.17 |
| **v2.2.2** | 2026-08-22 | `gsy_runup` 的標的本身換過兩次定義（SOXX 於 2021-06-21 換標的指數、`^SOX` 於 2024-04-22 改權重上限），§4.1 與卡片 `note` 加註「跨 2021／2024 不是同一籃股票」；**指標不改**。CNN Fear & Greed 退出 §9 與 `KNOWN_FAIL`（streak 17 ≥ 15）。新增 `scripts/gate.py` 發布閘門與 `scripts/sox_compare.py` | `MAINTENANCE.md` §6.16 |
| **v2.2.1** | 2026-08-17 | 回測第一輪的結論：`gsy_runup` 的文獻機率是**引用**、不是本標的的校準（論文的 run-up 三條件我們只實作了一個、崩盤是窗內最大回撤、單位是 ≥10 家公司的產業組合）。§4.1 改寫、`gsy150` 出處加限定、卡片 `note` 改由引擎寫 | `MAINTENANCE.md` §6.15 |
| **v2.2.0** | 2026-08-17 | 回測第一階段的工具：`scripts/backtest.py` ＋ 只手動觸發的 `backtest.yml`，驗 `gsy_runup` 那組唯一有文獻校準的錨點；產出進 `backtest/`，不碰 `data.json`、已排除在每日 workflow 的 push 觸發之外 | `MAINTENANCE.md` §5 |
| **v2.1.10** | 2026-08-17 | 複驗第二輪：前端補齊 `null` 防禦（`support` 為 null 時不畫象限點、`[null,null]` 不進軌跡、六處會印出 `null` 的地方）；§3.2／§3.3／§8.4 的公式與 §4.6／§6 的項數跟上 v2.1.7–8 | `MAINTENANCE.md` §6.14 |
| **v2.1.8** | 2026-08-17 | 補掉 §5.1「絕不編造數字」的兩個實作漏洞：`dims` 整層無效不再填 50.0（改 null＋composite 重新歸一）、`debt` 缺 330 天基期不再拿最新值假裝零成長（改整家剔除）。healthcheck 同步改，否則兩邊會一起說謊 | `MAINTENANCE.md` §6.14 |
| **v2.1.7** | 2026-08-17 | 籌碼子群補第二項 `tw_daytrade`（TWSE 當沖占市場比重 TWTB4U，即期比率、不需序列）——四組子群自此都不是單點，籌碼不會再整組消失 | `MAINTENANCE.md` §4 |
| **v2.1.6** | 2026-08-17 | `margin_hist` 改為回補（`MI_MARGN` 吃 `date=`，不足 21 筆時往回抓 45 個日曆日）——籌碼子群不必再等 21 個交易日，補齊當天 `tw.heat` 會跳一次且那一跳是人為的 | `MAINTENANCE.md` §4 |
| **v2.1.5** | 2026-08-17 | CBOE Put/Call 退場（streak 16 ≥ 門檻 15，從 §9 與 `KNOWN_FAIL` 移除，之後再壞掉會是 FAIL）；§8.3 的 WebFetch 能力改成分來源講（SEC／CNN 的 JSON 讀得到、FRED 的 CSV 是 binary、Yahoo／Stooq 回空，皆實測）；§5.2 補記 FRED 的 HY／CCC 只留 3 年觀測 | `MAINTENANCE.md` §2 |
| **v2.1.4** | 2026-08-17 | `fresh` 修活：引擎依 `IND_MAXAGE` 逐日重標，healthcheck 用引擎自己的門檻與 `asof_date` 重算對帳（FAIL 級）；台股三個價格項的 `sub` 顯示當次真正命中的備援層 | `MAINTENANCE.md` §6.13 |
| **v2.1.3** | 2026-08-17 | `healthcheck.py` 新增燈號界三處對帳（引擎 `zone()`／前端 `zoneOf()`／`stripHTML()` 色帶）——§4.4 原本寫著「沒有機器在比對」，補上了 | `MAINTENANCE.md` §6.7 的標準 |
| **v2.1.2** | 2026-08-17 | 前端補上四個缺欄位防禦（`charts.debt.note`、指標卡與總表的 `zone`、`tw.heat` 的「null／100」），並拆掉五處寫死判語（`vc` 誤標 L3、「不同調」與 `evalNvdaCmp` 打架、無條件宣稱與論文結論一致、`evalStagePhase` 撐不到第三／四階段、2026Q1 驗算數字改為現算）；§3.4 兩組界改為正面表述；`healthcheck.py` 的 `find_repo` 不再無條件掃家目錄（在使用者 Mac 上會掛死、`--repo` 形同虛設）；§8.3 由禁令改為白名單、§6 的「幾處一組」去掉數字、§8.2 補 `stage` 的完成條件；`fresh` 死欄位與兩個既有回退寫進規格 | `MAINTENANCE.md` §6.13 |
| **v2.1.1** | 2026-08-17 | 文件瘦身：本節由敘事改為索引；只寫在本節裡的三個實作門檻搬進 §5.2；`skills/bubble-maintain/` 縮成指標；修掉六處已被自己推翻的抄本與兩個指錯的交叉引用 | `MAINTENANCE.md` §6.12 |
| **v2.1.0** | 2026-08-10 | 發布改人機協作（雲端交付 patch／`data-YYYY-MM-DD.json`／離線 HTML，使用者本機推送）；PAT 移出排程 prompt；`asof` 統一填資料本身的日期；引擎健壯化（重試、原子寫檔、負基期防呆、缺 91 天基期即 fail）；healthcheck 的「今天」改用台北日並補掉三個「抓不到就靜默跳過」的洞；前端補畫 CCC／Oracle 磚塊、hero 變化徽章、觸發器距門檻進度條；新增 `senti` 的 CNN F&G 第四輸入、`triggers[].prog`、`history[].trig` | `MAINTENANCE.md` §6.11 |
| **v2.0.4** | 2026-08-06 | 把「子群從 `null` 補齊那天 `tw.heat` 會不連續跳、方向可上可下」寫成通則交給 `healthcheck.py` 算（§4.6），不在文件裡寫死當下的模擬值 | `MAINTENANCE.md` §4、§6.10 |
| **v2.0.3** | 2026-08-04 | 刪掉「多打斜線」這個 cache-buster——它是事後歸因；改為明說目前只有「換檔名」可靠 | `MAINTENANCE.md` §6.10 |
| **v2.0.2** | 2026-08-04 | 第二輪子代理比對：頁面上寫死的敘述與數字（分區界線 5 份、觸發器項數 3 份、台股子群權重 2 份…）全部改為從 `data.json` 現算；`senti`／`tw.items` 的 `src`／`url` 改由引擎依當次成功的來源生成；新增 `meta.lastAutoRun.streak`，讓 §9 的退場規則第一次變成可執行 | `MAINTENANCE.md` §6.8、§6.9 |
| **v2.0.1** | 2026-08-04 | 第一輪比對：補掉 `NaN`／缺鍵／v1 殘值；排程 prompt 由「整份複製規格」改為流程骨架＋指向本檔；新增 `healthcheck.py` 與 `MAINTENANCE.md` | `MAINTENANCE.md` §6.7 |
| **v2** | 2026-08-04 | 三層頻率架構取代 v1 六維：L1／L2／L3 = 35／35／30、象限（heat × support）與軌跡、7 項引爆觸發器、季頻落後三解（初步季 nowcast／RPO／台灣月營收）、台灣供應鏈擴為 10 項 | `MAINTENANCE.md` §6.1 |
| **v1** | 2026-07-17 | 以中金〈如何監測 AI 泡沫?〉四維為起點的六維 21 指標；核心數字經 SEC EDGAR 原始 XBRL 獨立驗證（2026Q1 五大雲廠 Capex/OCF = 94.0%，與原文吻合） | `MAINTENANCE.md` §6.1 |
