# AI 泡沫監控儀表板 · 規格書（AGENT_BRIEF）

> 這份是**現在的規格與判斷規則**，是本系統的唯一真相來源。
> 每週質化覆核排程每次執行前完整讀一次。事故經過與被否決的選項寫在 `MAINTENANCE.md` 第 6 節，不要寫進這裡。
> 版本：**v2.1.2（三層頻率架構）**｜最後修訂 2026-08-17

---

## 0. 這套系統在做什麼

一句話：**它不預測崩盤，它把「泡沫」拆成可被公開資料每日測量的溫度計，並在幾個歷史上真正致命的門檻被踩到時點亮警示燈。**

它是三個知識庫之中唯一的**量化庫**（另兩個是敘事庫）：

| 庫 | 性質 | 單獨看能回答 |
|---|---|---|
| 投顧知識庫 advisory-knowledge-hub | 敘事．每日．新聞 | 發生了什麼 |
| 節目知識庫 podcast-knowledge-digest | 敘事．每日．專業討論 | 聰明人在想什麼 |
| **AI 泡沫監控 ai-bubble-monitor（本系統）** | **量化．每交易日．自動抓取** | **客觀狀態是什麼** |

主題匯流訊號報（convergence-weekly）會來讀本系統的 `data.json`，用它跟兩個敘事庫做「背離」判定。因此 **`history` 的連續性與 `data.json` 的 schema 穩定性有外部相依**——改 schema 前先想到匯流報。

**判斷本系統做得好不好的唯一標準：分數的變動是否來自世界真的變了，而不是來自我們改了公式。** 每一次動權重、動錨點、動指標集合，歷史序列的可比性就斷一次。

---

## 1. 部署拓撲

| 位置 | 內容 | 更新者 |
|---|---|---|
| GitHub repo `GunDamnBoy/ai-bubble-monitor` | `index.html`、`data.json`、`scripts/update_data.py`、`.github/workflows/update.yml`、本檔、`MAINTENANCE.md`、`healthcheck.py` | GitHub Actions（自動）＋維護者 |
| 網站 <https://gundamnboy.github.io/ai-bubble-monitor/> | GitHub Pages，從 `main` 分支根目錄直出 | Actions 推送後由 API 明確要求重建 |
| Cowork 桌面 artifact `ai-bubble-monitor` | 內嵌 `data.json` 的單檔 HTML 快照 | 維護工作階段（桌面連線時）；排程執行連不到桌面，只交付 HTML 檔 |
| Excel `AI泡沫監控儀表板.xlsm` | v1 版、含 `UpdateAll()` 巨集按鈕 | 使用者手動按按鈕；**尚未升到 v2**，見 `MAINTENANCE.md` 第 5 節 |

**唯讀分工**：`index.html`（外殼與繪圖）極少需要動；`data.json` 是每日被機器改寫的資料層；`scripts/update_data.py` 是引擎。

---

## 2. 檔案分工（先理解，否則會把東西寫錯地方）

| 檔案 | 只放什麼 | 誰讀 |
|---|---|---|
| `AGENT_BRIEF.md`（本檔） | **現在的規格與判斷規則**，含 `data.json` schema | 每週質化覆核排程每次完整讀一次；維護者 |
| 每週排程任務的 prompt | **流程骨架**：順序、分支、人機分工。事實細節指向本檔章節，刻意不重抄 | 排程觸發時執行 |
| `MAINTENANCE.md` | **維護說明＋事故與決策檔案**（第 6 節）：事故經過、誤判過程、被否決的選項 | 維護者 |
| `healthcheck.py` | **機械式檢查**（唯讀、不改任何檔案）：重算層分數／`composite`／象限／`tw` 並與存檔比對、錨點與權重的 brief↔資料比對、workflow 關鍵步驟、`--selftest`、JS 語法，以及內嵌退路快照的 `meta.version` 比對、`charts.spreads` 前端讀取鍵與欄位 vs 引擎 AST 實際寫入的對帳、來源過期偵測 | 維護者每次動手前後各跑一次；每週覆核交付前 **FAIL 必須是 0** |
| `index.html` 內的 `<script id="update-spec">` | **僅指向本檔的指標**，不再重複規格（v2 起） | 未來讀到這頁 HTML 的工作階段 |
| Cowork skill `/maintain`（`bubble/`） | **維護入口**：載入現況 → 子代理比對 → 報告 → 才動手。repo 內 `skills/bubble-maintain/` 只留指標，**不放規格**（沒有機器跟本檔對帳，抄進去就會過期） | 維護者 |

**新的事實細節寫本檔，新的「為什麼」寫 `MAINTENANCE.md` 第 6 節，排程 prompt 只在流程或分支改變時才動。**

**排程 prompt 的第一步永遠是「完整讀一次本檔」。** 本檔刻意承擔所有事實細節、prompt 只留流程骨架，這個分工只有在指向鏈沒斷的前提下成立——prompt 若沒有讀本檔，rubric、燈號界、覆寫禁令的例外條款在執行端一條都拿不到。

---

## 3. 模型架構（v2）

### 3.1 三個頻率層

不用中金的四維（需求／現金流／融資來源／外部約束）當骨架，理由見 `MAINTENANCE.md` 第 6.1 節。v2 依**資料更新頻率**分層，讓日頻的東西每天動、季頻的東西不要拖累日頻訊號：

| 層 | 名稱 | 權重 | 頻率 | 內容 |
|---|---|---|---|---|
| **L1** | 市場與情緒 | **0.35** | 日頻 | 價格統計（GSY）＋估值＋集中度＋情緒 |
| **L2** | 資金與信用 | **0.35** | 日／週頻 | 2026 共識斷層線：債務、利差、循環融資 |
| **L3** | 基本面兌現 | **0.30** | 月／季 nowcast | capex 消化度、RPO、變現 |

權重存在 `data.json` 的 `dimMeta.{L1,L2,L3}.w`，**三者必須加總為 1.0**。

### 3.2 分數合成

```
層分數  = 該層所有 score 非 null 的指標「等權平均」   ← 指標層是等權，沒有個別權重欄位
綜合溫度 = Σ dimMeta[層].w × 層分數
```

**指標之間刻意不設個別權重。** 加減指標就等於改權重，這是有意的設計：權重集中在層級（3 個數字），比 22 個數字容易審查也不容易漂移。要調某個主題的份量，正確做法是在那一層增減指標，不是加權重欄位。

分數一律 0–100，**越高越熱**。方向相反的原始值有**兩套慣例並存**，`dir` 欄位一律不參與計分：

| 慣例 | 適用指標 | 做法 |
|---|---|---|
| **取負號** | `rpo`、`tw_rev`、`tw_export`、`senti` 的個股 P/C 子輸入 | 錨點的 x 遞增、y 遞增，餵進去的值先加負號（`pw(-yoy, ...)`） |
| **遞減錨點** | `fcf`、`cloudrev` | 值照原樣餵，錨點自己的 y 由高到低（`[[-80,100],…,[10,0]]`），第 4 節標「（反向）」的就是這種 |

**手改分數前先看該指標屬於哪一套**，弄錯會得到完全相反的分數。判斷方法：`anchors` 的 y 是遞減的就是第二套，遞增的就是第一套。新增反向指標時**優先用取負號**——遞減錨點會讓 §3.4 的燈號界不直觀，這兩個是歷史遺留。

### 3.3 象限定位（v2 新增，比單一溫度更有訊息量）

```
heat    = (L1 + L2) / 2        ← 市場與資金有多熱
support = 100 − L3             ← 基本面還有多少支撐（L3 越高＝兌現越差＝支撐越少）
```

| 條件 | regime |
|---|---|
| `heat ≥ 55` 且 `support < 45` | 泡沫危險區 |
| `heat ≥ 55` | 過熱但有撐（melt-up 風險） |
| `support ≥ 45` | 健康擴張 |
| 其他 | 失速風險 |

`history` 每筆記 `quad: [support, heat]`，前端畫成象限軌跡。**這條軌跡是本系統最有價值的產出**，比當日的絕對分數重要。

**45／55 這組分界在 `index.html` 的 `renderQuad` 有第二份寫死拷貝**，改分界要兩邊一起改——`healthcheck.py` 對帳這一組，不一致是 **FAIL**（比照「N 項指標」，理由是它決定使用者看到哪一個 `regime`）。

### 3.4 溫度分區

`zones`（`data.json` 內）：`0–25 冷靜期／25–45 健康擴張／45–65 過熱警戒／65–84 泡沫化進行／84–100 極端狂熱`。
單一指標的燈號 `zone` 用另一組界：`<33 綠／33–67 黃／67–84 橘／≥84 紅／null 待數據`。
**兩組界各自獨立、界線不要互相換算**：`zones` 負責分區「標籤」（冷靜期／過熱警戒…），`zone` 負責燈號「顏色」。頁面上同一顆 chip 常常兩者並用——hero 與台股 chip 都是拿 `zoneOf()` 上色、再拿 `zones` 取標籤，那是刻意的；不可以的是拿其中一組的界線去推另一組。

### 3.5 引爆觸發器（7 項，布林、不進分數）

取 GS／BofA／UBS 三家門檻的聯集。**它們刻意不進綜合溫度**——溫度是連續的體溫，觸發器是離散的跳電。混在一起會讓溫度在門檻附近亂跳。

| id | 條件 | 出處 |
|---|---|---|
| `hy80` | HY 利差 3 個月走闊 ≥ 80bp | GS／歷史典型 |
| `ccc12` | CCC 利差 ≥ 12%（2022 熊市水位） | 最弱信用層 |
| `gsy150` | SOXX 24 個月漲幅 ≥ 150% | Greenwood-Shleifer：其後 24 月崩盤率 80% |
| `cpi4` | CPI 年增 ≥ 4% | BofA Hartnett |
| `policy_gap` | 政策利率 ≥ 名目 GDP 成長 | UBS 前提條件 |
| `y10_5` | 美債 10 年 ≥ 5% | 估值折現的斷點 |
| `megaipo` | OpenAI／SpaceX 巨型 IPO 完成 | BofA：週期見頂訊號（**人工旗標** `params.megaipo_done`） |

### 3.6 階段判定

`stage.current`（1–4 的小數）＋ `stage.checklist` 六項（`state` 為 0／0.5／1，每項要有 `evi` 證據字串）。這是質化的，由每週覆核維護。

---

## 4. 指標總表

### 4.1 L1 市場與情緒（9 項，權重 0.35）

| id | 名稱 | 型態 | 來源 | 錨點 |
|---|---|---|---|---|
| `cape` | Shiller CAPE（標普500） | 自動 | multpl.com | `[[25,0],[32,33],[40,67],[44.19,100]]` |
| `mag7` | Mag7 佔標普500市值比重 | 自動 | SlickCharts | `[[20,0],[25,33],[32,67],[38,100]]` |
| `nvdape` | NVIDIA 本益比 | 自動 | Yahoo/Stooq ÷ `params.nvda_eps` | `[[20,0],[35,33],[55,67],[90,100]]` |
| `gsy_runup` | **GSY 24 個月漲幅（SOXX）** | 自動 | 價格序列 | `[[25,0],[50,25],[100,60],[150,85],[250,100]]` |
| `gsy_accel` | GSY 加速度（**當下 24 月漲幅 − 一年前 24 月漲幅**） | 自動 | 價格序列 | `[[-30,5],[0,30],[30,60],[80,90],[150,100]]` |
| `volchg` | 已實現波動率一年變化 | 自動 | 價格序列 | `[[-6,10],[0,33],[5,67],[15,100]]` |
| `soxmom` | 半導體相對動能（SOXX−SPY，3個月） | 自動 | 價格序列 | `[[0,0],[10,33],[25,67],[60,100]]` |
| `senti` | 情緒與投機溫度（合成） | 自動 | AAII＋CBOE P/C＋VIX＋CNN F&G **等權平均（可得幾項平均幾項）** | 見 4.4 |
| `narrative` | 泡沫敘事熱度 | **質化** | 媒體監測 | 1–5 級 →10/30/50/70/90 |

**`gsy_runup` 是全表唯一有歷史校準的指標**（Greenwood-Shleifer, JFE 2019）：產業 24 個月漲幅 ≥100% → 其後 24 個月崩盤機率 53%；≥150% → 80%。錨點就是照這個機率曲線設的，**不要因為「看起來太高」而調鬆它**。

### 4.2 L2 資金與信用（7 項，權重 0.35）

| id | 名稱 | 型態 | 來源 | 錨點 |
|---|---|---|---|---|
| `debt` | 五大雲廠長期債務年增率 | 自動 | SEC EDGAR | `[[0,0],[10,33],[30,67],[80,100]]` |
| `hyoas` | 高收益債利差（3個月變化 bp） | 自動 | FRED `BAMLH0A0HYM2` | `[[-30,0],[0,25],[30,50],[80,75],[150,100]]` |
| `ccc` | CCC 級利差 | 自動 | FRED `BAMLH0A3HYC` | 水位錨 `[[5,0],[7,33],[10,60],[13,85],[16,100]]` 與 3 月變化錨 `[[-50,0],[0,33],[100,67],[250,100]]` **各半** |
| `orclbond` | Oracle 2055 長債殖利率 | 自動 | Public.com 債券報價 | `[[5,10],[6,35],[7,60],[8,80],[10,100]]` |
| `circular` | 循環融資強度（供應商融資） | **質化** | CNBC/Bloomberg | rubric 見 4.5 |
| `weakcredit` | 弱資質信用單點（金絲雀） | **質化** | 市場報導 | rubric 見 4.5 |
| `vc` | VC／IPO 熱度與集中度 | **質化** | Crunchbase News | rubric 見 4.5 |

### 4.3 L3 基本面兌現（6 項，權重 0.30）

| id | 名稱 | 型態 | 來源 | 錨點 |
|---|---|---|---|---|
| `capexocf` | 五大雲廠 Capex／OCF（TTM） | 自動 | SEC EDGAR | `[[40,0],[60,33],[80,67],[110,100]]` |
| `fcf` | 五大雲廠自由現金流（TTM 年增） | 自動 | SEC EDGAR | `[[-80,100],[-40,67],[0,33],[10,0]]`（反向） |
| `dnagap` | 折舊成長 − 營收成長（pp） | 自動 | SEC EDGAR | `[[0,0],[5,33],[15,67],[35,100]]` |
| `rpo` | 合約儲備 RPO 年增（MSFT＋GOOGL＋ORCL） | 自動 | SEC EDGAR | 取負後 `[[-60,0],[-35,25],[-15,55],[0,80],[15,100]]` |
| `cloudrev` | 三大雲業務營收年增率 | **質化** | 各公司財報（季） | `[[5,100],[15,67],[25,33],[40,0]]`（反向） |
| `tokens` | Token 經濟（用量×單價） | **質化** | OpenRouter／第三方 | rubric 見 4.5 |

`dnagap` 取代了 v1 的「ROIC > WACC」——理由見 `MAINTENANCE.md` 第 6.1 節。

### 4.4 特殊計分規則

- **分段線性 `pw(v, anchors)`**：錨點須依 x 遞增；區間內線性內插，兩端夾住。**分數只在 Python 端計算**，前端不重算、只渲染 `data.json` 裡的 `score`（v1 曾在前端另算一份，兩邊會漂）。
  **燈號 `zone` 是例外**：`indicators[]` 有存 `zone`、前端直接渲染，但 `tw.items[]` 沒有（`tupd()` 不寫），所以台股卡片與 TAB4 引用台股指標時是由前端的 `zoneOf(score)` 現算。也就是說 §3.4 的 `<33/33–67/67–84/≥84` 這組界**在引擎的 `zone()` 與前端的 `zoneOf()`／`stripHTML()` 各有一份實作，沒有機器在比對**。改這組界要三個地方一起改。
- **VIX 非單調特例**（`vix_score`）：`≥35→95`／`28–35→67~95 線性`／`18–28→33`／`13–18→50`／`<13→70`。低 VIX 是自滿、高 VIX 是恐慌，兩端都不是「健康」。
- **`senti` 是合成指標**：AAII 多空差、CBOE 個股 Put/Call（取負）、VIX 特例分數、CNN Fear & Greed（2026-08-10 接入，見 §9），**可得幾項就平均幾項**。哪幾項真的參與了合成，看卡片的 `sub`——`sub`／`dir`／`src`／`url` 這四欄都由引擎依當次成功的來源生成，不是寫死的（v2.0.2 前 `dir`／`src`／`url`／`note` 寫死三來源，只有 `sub` 誠實）。`note` 已改寫成不提「這次合成了哪幾個」的結構性說明（原本還寫著「散戶淨空」，那是 AAII 導出的判斷，AAII 被擋的日子就是憑空的）。目前穩定被擋的只有 AAII，CBOE 時好時壞，見第 9 節。
  兩個子輸入的錨點：AAII 多空差 `[[-25,5],[0,40],[20,75],[35,100]]`、**取負後**的個股 P/C `[[-1.0,10],[-0.8,33],[-0.62,67],[-0.45,100]]`；CNN F&G 本身就是 0–100 貪婪度，**直讀不經錨點**。**注意它與 `vix_score` 在恐慌端方向相反**：F&G 極恐慌→趨近 0（降溫），`vix_score` VIX≥35→95（恐慌也是風險）——這是接受的取捨，senti 量的是投機熱度，恐慌日「不熱」是事實，VIX 特例才是刻意的例外；另 F&G 的七個成分本身含 VIX，有部分重複計入，接受。

#### 錨點不在 `data.json` 裡的三個指標

`healthcheck.py` 的 brief↔資料錨點對帳只比得到 `indicators[].anchors` 有值的項目，下面三個一律跳過，所以**本文件是它們唯一的規格來源**（跟 §4.6 的台灣指標同一種情況）：

| id | 狀況 |
|---|---|
| `senti` | `anchors: null`（合成指標），兩個子輸入的錨點見上一行，寫死在 `f_senti()` |
| `rpo` | `anchors: null`，取負後的錨點只寫在 `main()` 內 `f_rpo()` 的 `pw(-yoy, ...)` 呼叫裡（**不在 `refresh_edgar()`**，RPO 走 `rpo_backlog()`） |
| `ccc` | `anchors` 只存水位錨；**3 個月變化錨不在 `data.json`**，寫死在引擎，且 healthcheck 的比對只取第一組 |

改這三項的錨點時，記得**兩邊都要改**，而且沒有機器會提醒你。

### 4.5 質化指標評分 rubric

| id | rubric |
|---|---|
| `vc` | `0–33`：AI 佔 VC <40% 且無巨型輪／`33–67`：佔比 40–65% 或單輪 >$20B／`67–84`：佔比 >65% ＋$50B 級輪次／`84+`：擴散至無收入初創普遍高估值 |
| `circular` | `0–33`：零星小額／`33–67`：龍頭對客戶投資年化 <$20B／`67–84`：>$40B/年或綁定合約常態化／`84+`：供應商融資成為需求主要來源 |
| `weakcredit` | `0–33`：無異常／`33–67`：個別 CDS 走闊／`67–84`：指標性公司 CDS 創高或 FCF 大幅轉負／`84+`：再融資失敗／違約事件 |
| `narrative` | 1 級=10（無人談論）／2=30／3=50（廣泛討論分歧）／4=70／5=90（恐慌共識） |
| `cloudrev` | 走錨點不走文字級距：三大雲業務營收年增率代入 `[[5,100],[15,67],[25,33],[40,0]]`（反向）。財報季更新，非財報季沿用 |
| `tokens` | `0–33`：用量增速 > 單價跌幅，單位經濟改善／`33–67`：兩者相抵，營收靠增量堆／`67–84`：單價跌幅吃掉用量成長，推理毛利轉負的報導出現／`84+`：主要供應商公開承認推理虧損或大幅漲價 |

質化指標依等權規則實際佔總權重 **28.9%**（L1 `0.35×1/9` ＋ L2 `0.35×3/7` ＋ L3 `0.30×2/6`），是本系統最大的主觀性來源。**加減指標會改變這個數字，改完要回來更正。**

**每次調整質化分數，`note` 必須寫上「上週分數 → 本週分數 ＋ 變動理由與日期來源」**，這是唯一能事後查核漂移的機制。這條是質化指標的**例外**——`MAINTENANCE.md` 第 6.4 節「`note` 只留不隨時間變的結構性說明」是針對自動指標講的，自動指標的時效性敘述一律走 `sub`（由引擎生成），質化指標沒有引擎可生成，所以改用 `note` 留軌跡。

`healthcheck.py` 對質化指標做三件機械檢查：

1. `note` 裡若寫了「… → Y」或「本週由 X 轉 Y」這種軌跡，**Y 必須等於該指標現在的 `score`**，不符就 FAIL。這抓的是最實際的失效模式：分數改了而 `note` 忘了改，或改錯邊。（`narrative` 那種「4.5 下修至 4.0」是 1–5 級的原始級數不是分數，檢查會自動略過 5 以下的數字。）
2. `note` 裡要有一個看得出來的日期或月份，沒有就 WARN——沒有日期的理由，下一次覆核無從判斷它是不是已經過期。
3. `asof` 停太久就 WARN，門檻**依各指標的自然更新頻率分開設**：`narrative`／`circular`／`weakcredit` 每週覆核，21 天；`tokens` 是月度第三方彙整，75 天；`vc`／`cloudrev` 是季度指標，130 天。門檻寫在 `healthcheck.py` 的 `QUAL_MAXAGE`，改頻率要一起改。**未列在該表裡的質化 id 一律套 45 天預設**，所以新增第七個質化指標時要記得進去補一列，否則它會靜靜地被當成月頻。另外 `asof` 若**解不出日期**也會 WARN；`YYYY-MM` 形式可以過關（會補成當月 1 日再算），後面接括號說明（例如「2026-05（第三方彙整）」）也解得出來。

刻意**沒有**要求「每一項每次都要有軌跡」：`vc`／`cloudrev` 整季不動時 `note` 本來就不該重寫，硬要求只會製造永遠修不掉的 WARN，而永遠修不掉的 WARN 等於沒有 WARN。**分數沒動的那幾週不必重寫 `note`**。`asof` 一律填**資料本身的日期**（§8.4 的通則；覆核日不是資料日期），連續多週沒有新資料時上面第 3 條的 WARN 會自然出現——那不是要你把 `asof` 改成覆核日消音，而是要你在推播摘要註明「本週已查核、無新資料」。

**兩條 `note` 的書寫慣例（機器抓不到，但每週都要照做）**：

- 指標跨區時（燈號換色），`note` 開頭標「本週由X轉Y」，讓事後翻閱時一眼看到轉折點。
- `stage.note` 裡必須有「點亮 X／6」這一句，且 X 要等於 `checklist` 實算的點亮數（半格算 0.5）。全形半形斜線都收，但**句子整個不見就是 FAIL**——舊版寫成「抓不到就跳過」，於是改寫句型可以無聲關掉比對還照樣印 PASS，比沒有檢查更糟，現在改成抓不到就報錯。

### 4.6 台灣供應鏈（10 項，獨立計分，不進綜合溫度）

`tw.items` 共十項，其中**九項**經 `tw.subs` 四個子群再加權成 `tw.heat`（第十項 `tsmc_weight` 不入子群，見下）：

| 子群 | 權重 | 成員 |
|---|---|---|
| 動能 | 0.30 | `tsmc_200dma`、`tsmc_52w`、`elec_rel`、`twii_pos` |
| 估值 | 0.30 | `tsmc_pe`、`odm_pe` |
| 籌碼 | 0.20 | `tw_margin` |
| 基本面 | 0.20 | `tw_rev`、`tw_export` |

子群內等權平均、忽略 null；`tw.heat` 依上表加權，**null 的子群剔除後重新歸一**。

**歸一的代價：某組子群從 null 變成有值的那一天，`tw.heat` 會不連續地跳一次。** 分母從「剩餘權重和」變回 1.0，新進來的那組整份權重一次生效。**方向可上可下**——取決於新進來的分數比現有加權平均高還是低，不要預設是往上跳。

**籌碼是四組裡唯一的單點子群**（只有 `tw_margin`），所以最常遇到這件事的就是它：`tw_margin` 需要 21 個交易日的序列才算得出 20 日變化，序列未滿期間整個 20% 權重都不在分母裡。這不是 bug，但它會讓人以為資料出錯。

**當下缺哪幾組、補齊後 heat 會落在哪，一律看 `healthcheck.py` 的 WARN**，它在分母 ≠ 1.0 時會印出缺項與三個情境的模擬值。**這裡刻意不寫具體數字與日期**——那種東西寫進文件就會過期，而 heat 每天都在動，今天算的模擬值到補齊那天早就不是這個數了（WARN 訊息也因此寫「屆時**約**為」）。

要消除這個跳動只有兩條路：給籌碼補第二項指標，或接受它。目前選後者，因為融資餘額是台股籌碼面唯一日頻、官方、免金鑰的序列。**若哪天真的補了第二項，記得回來改這一段與 `MAINTENANCE.md` 第 4 節那條坑**——「唯一的單點子群」這句話屆時就不成立了。**`healthcheck.py` 會把上表的成員組成跟引擎的 `subs_def` 對帳，改了成員而沒同步就 FAIL。**

這組權重由引擎寫進 `data.json` 的 `tw.subWeights`，前端讀它、不再自己抄一份（v2.0.2 前 `index.html` 有第二份寫死拷貝，改 `wmap` 不會動到頁面）。改權重要同時改上表與引擎的 `wmap`——**`healthcheck.py` 會比對上表 ↔ `wmap` ↔ `tw.subWeights` 三處並檢查加總 = 1.0，不一致直接 FAIL。**

`tsmc_weight`（台積電佔加權指數權重）**刻意不屬於任何子群**，只作為集中度的展示項。

#### 台灣指標的錨點

**`tw.items` 的物件裡沒有 `anchors` 欄位**（跟 `indicators` 不一樣），錨點只以字面值寫在引擎的 `tupd(...)` 呼叫裡。所以要手改台灣指標的分數時，唯一的規格來源是下表：

| id | 餵進 `pw()` 的值 | 錨點 |
|---|---|---|
| `tsmc_weight` | 權重 %（正向） | `[[30,20],[38,50],[45,80],[52,100]]` |
| `tsmc_pe` | P/E（正向） | `[[15,0],[22,33],[28,67],[35,100]]` |
| `odm_pe` | 平均 P/E（正向） | `[[10,0],[15,33],[20,67],[28,100]]` |
| `tsmc_200dma` | 偏離 %（正向） | `[[0,0],[15,33],[30,67],[50,100]]` |
| `tsmc_52w` | 52 週漲幅 %（正向） | `[[20,0],[50,33],[90,67],[150,100]]` |
| `twii_pos` | 52 週位階 %（正向） | `[[50,0],[75,33],[90,67],[100,100]]` |
| `elec_rel` | 電子相對大盤 pp（正向） | `[[-3,15],[0,35],[4,67],[10,100]]` |
| `tw_margin` | 融資餘額 20 日變動 %（正向） | `[[-4,10],[0,35],[5,67],[12,100]]` |
| `tw_rev` | **月營收年增取負** `-comp` | `[[-90,5],[-45,20],[-12,45],[0,65],[15,90]]` |
| `tw_export` | **海關出口年增取負** `-yoy` | `[[-50,10],[-20,30],[0,60],[10,85]]` |

`tw_rev`／`tw_export` 是反證指標（成長越快越不像泡沫破裂），依 §3.2 的通則**取負號後**再餵錨點——手算時最容易在這裡把符號弄反。

**每月只有 `tsmc_weight` 需要人更新**（TAIFEX 擋機器人，Actions 端固定失敗），其餘九項由引擎每交易日自動更新，屬於 §8.3 覆核不動的欄位。

**`tw.items` 的 `src`／`url` 由引擎的 `TW_SRC` 表無條件寫入**，不再是 `data.json` 的種子值（v2.0.2 前 `tupd()` 只寫數值，於是 `tsmc_pe` 早就改抓 TWSE 官方了、卡片卻還掛著 Google Finance，同一張卡的 `note` 自己在打臉）。換資料源時改 `TW_SRC`，不要改 `data.json`。

但 `TW_SRC` 是**靜態表，不是當次真正走的路徑**：`tsmc_200dma`／`tsmc_52w`／`twii_pos` 走 `px_rows()` 的三層備援，實際命中哪一層每天可能不同，所以它們的 `src` 寫成「三層備援」而不指名單一來源。要顯示當次真正的來源，得比照 `senti` 的 `sub` 做法由引擎生成——目前沒做，這是刻意的取捨（台股卡片沒有 `sub` 欄位）。

十檔月營收籃 `TW_BASKET`（依營收加權）：`2330 台積電`、`2317 鴻海`、`2382 廣達`、`3231 緯創`、`6669 緯穎`、`3017 奇鋐`、`2308 台達電`、`3661 世芯-KY`、`3443 創意`、`2345 智邦`。

**台灣是全球 AI 硬體的出貨速度計**：月營收比美國財報早 1–2 個月，是需求裂縫最早的實體訊號。這是 L3 季頻落後問題的三個解方之一。

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

**兩個既有的例外，實作上與這條契約有出入，先記在這裡**：整層指標全部無效時 `dims` 會填 `50.0`（而不是 `null`）；`debt` 找不到 ≥330 天前的基期時，會拿最新值當基期（該公司年增以 0% 計入合計）而不是跳過該公司。兩者都不會被 `healthcheck.py` 抓到，改引擎時順手處理掉。

### 5.2 函式地圖

| 區塊 | 函式 | 備註 |
|---|---|---|
| 基礎 | `http_get` `pw` `vix_score` `zone` | `zone(None)` 回 `"pending"`；`http_get` 對 timeout／連線失敗／5xx 重試 2 次（間隔 2 秒），4xx 不重試 |
| 總經 | `fred(series, days=620)` `fred_back(obs, back_days)` `fred_latest_and_back(series, back_days, days=620)` | `fredgraph.csv`；要同時取多個回看期時用 `fred()` 抓一次再 `fred_back()` 取值，不要重複抓（`fred_latest_and_back` 現在也只是這兩者的組合） |
| 價格 | `px_rows(ysym, ssym=None, rng="4y")` → **三層備援** `yf_chart`(yfinance) → `yahoo_chart`(raw API) → `stooq` | Stooq 在 Actions runner 被擋，只當最後備援 |
| 統計 | `series_stats` `gsy_stats` | `gsy_stats` 需 ≥505 筆算 `ret24`、≥758 筆算 `accel`、≥505 筆算 `vol1y`（`volchg` 用） |
| 估值/情緒 | `multpl_cape` `slickcharts_mag7` `aaii_sentiment` `cboe_putcall` `cnn_fear_greed` | `aaii_sentiment` 持續在 Actions 端被擋；`cboe_putcall` 時好時壞；`cnn_fear_greed` 2026-08-10 新接入、Actions 端成敗未實測（皆見 §9）|
| 信用 | `orcl_bond_yield` | Public.com 報價頁。`hyoas`／`ccc` 取不到 91 天基期時**直接 fail 沿用舊值**，不用 0bp 的假變化計分 |
| 季報 | `edgar_rows` `to_quarters` `bucket` `refresh_edgar` `rpo_backlog` | 見 5.3。另有幾個藏在實作裡的門檻：`rpo_backlog` 若前期端點與目標日相差 >75 天就跳過該公司；`debt` 年增要求回看 ≥330 天；**`fcf` 的 YoY 在基期 TTM FCF ≤0 時沿用舊值**（負基期會把 −10B→+5B 這種改善算成 −150% 的滿熱分） |
| 台灣 | `tw_monthly_rev` `tw_bwibbu` `tw_margin_balance` `tw_index_today` `taifex_tsmc_weight` `tw_customs_export_yoy` | 見 5.4 |
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
| 大盤／電子指數 | `https://openapi.twse.com.tw/v1/exchangeReport/MI_INDEX` |
| 台積電指數權重 | `https://www.taifex.com.tw/cht/9/futuresQADetail` ← **擋機器人，只能人工每月更新** |
| 海關出口 | `https://opendata.customs.gov.tw/data/6053/csv.csv` |

兩條**來源格式防呆**：海關 CSV **自行排序、不信任列序**；TWSE 電子指數用**精確名匹配**（保留子字串備援）。兩者都是來源改版時會靜默給錯值的地方。

`elec_rel` 與 `tw_margin` 需要 `idx_hist`／`margin_hist` 累積滿 **21 個交易日**才算得出來；未滿時 `score` 為 `null`、`disp` 顯示「序列累積中 n/21」。兩份歷史各保留最近 90 筆。

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
dims       { L1, L2, L3 }               層分數
dimMeta    { L1:{name,w,note}, L2:{...}, L3:{...} }   w 加總必須 = 1.0
zones      [ {max,label,color} × 5 ]
indicators [ 22 × {id, dim, name, value, disp, score, zone, anchors, dir,
                   asof, fresh, src, url, note, qual, sub?} ]
             fresh 目前**引擎一律寫 "ok"**，從來不會變成 "stale"；前端那個
             「⚠ 資料延遲」徽章因此是死碼。要它活起來得先定義每個指標各自的
             過期門檻（比照 QUAL_MAXAGE），本次刻意不做——見 MAINTENANCE §6.13
             dir 是**給人看的方向說明字串**（"越高越熱"、"越負越熱"、
             "質化評分（0-100）"…），純展示、不參與計分。方向相反的指標走
             **§3.2 的兩套慣例之一**（取負號／遞減錨點），不要照 dir 另寫邏輯
triggers   [ 7 × {id, name, state(0/1), value, note, asof, prog} ]
             prog＝距門檻進度 0–100%（現值÷門檻，夾在 0–100），由引擎逐日重算；
             megaipo 是人工旗標無連續量，prog 恆為 null。它是展示欄位，
             不參與任何計分（觸發器本來就不進綜合溫度，§3.5）。
             2026-08-10 新增——引擎第一次跑新版之前，舊 data.json 沒有這個鍵，
             前端遇缺就不畫進度條
quadrant   { heat, support, regime }
tw         { heat, subs:{動能,估值,籌碼,基本面}, subWeights:{同上四鍵:權重},
             items[10], revTable[10],
             revMonth, officialPE{代號:{pe,pb}}, idx_hist[≤90], margin_hist[≤90] }
             items 每筆 {id,name,value,disp,score,note,src,url,asof}——**沒有 zone**，
             燈號由前端 zoneOf(score) 現算（讀 i.zone 會拿到 undefined）
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

**第四處**：`index.html` 內嵌的 `<script id="dashboard-data">` 是 fetch 失敗時的離線退路快照。它不需要每天更新，但**改 schema 或改版時必須重新灌一次**，否則離線開啟會退回舊架構的頁面（v1→v2 期間就發生過，退路快照停在六維 54.1）。**重灌時把內嵌那份的 `history` 裁到最後 60 筆**（頁面體積考量；`healthcheck.py` 超過 60 筆會 WARN，**0 筆也會 WARN**——那代表重灌時把陣列灌空了）。`healthcheck.py` 另比對它的 `meta.version`、v2 必要區塊、`history` 筆數，以及 `composite`／`meta.built` 是否與 `data.json` 明顯脫節。

**第五處，而且最常被漏掉：`healthcheck.py` 自己。** 它為了能獨立驗算，硬寫了幾組常數——`LAYER_N`（各層指標項數）、`QUAL`（質化指標集合）、`TRIG`（觸發器 id）、`KNOWN_FAIL`（已知失效來源白名單）、`QUAL_MAXAGE`（質化 `asof` 的過期門檻，見 §4.5）。**加減指標、改層歸屬、換觸發器、或某個來源恢復／新壞掉時，這個檔案也要改。** 它是把關每週交付的工具（FAIL 必須是 0），所以漏改它的下場不是靜靜少畫一塊，而是整條每週流程被自己的檢查擋住。

不過**這幾組常數的嚴厲程度不一樣**，別記成一律 FAIL：`QUAL`、`TRIG`、`KNOWN_FAIL` 對不上是 **FAIL**（擋住交付），`QUAL_MAXAGE` 與 `index.html` 的 `QUALF` 分級對不上也是 **FAIL**（`asof` 單純超過門檻則是 WARN），`LAYER_N` 與 `data.json` 對不上只是 **WARN**。這個差別是刻意的——FAIL 那幾組不一致必然代表有人漏改，而層人數本來就會因為「刻意增減指標」而變動，那時該提醒的是「記得回頭改 §4 各層表與 §4.5 的 28.9%」，不是把人擋在門外。

**但 `LAYER_N` 有第二個用途，那個是 FAIL**：`index.html` 那句「N 項指標依三層頻率分組」也拿它對帳，數字對不上直接擋住交付。理由是那句話是**寫給使用者看的**，錯了就是在頁面上說謊，跟「內部常數暫時落後」不是同一件事。所以增減指標時，`index.html` 那個數字是**必改**的，不是提醒。

---

## 7. 自動化：GitHub Actions

`.github/workflows/update.yml`

- 排程 `cron: '30 22 * * 1-5'`（UTC）＝ **台北 06:30 週二～週六**（美股收盤後）。另有 `workflow_dispatch` 手動觸發，以及 `push` 到 `main`（`paths-ignore: ['data.json']`）——推程式碼會跑一次，推資料不會，避免自我觸發迴圈。
- `permissions: contents: write, pages: write`
- 步驟：checkout → Python 3.12 → `pip install requests yfinance` → 跑更新 → commit `data.json` → **明確要求 Pages 重建**
- **最後一步不可刪**：

  ```
  POST https://api.github.com/repos/{repo}/pages/builds
  ```

  用 `GITHUB_TOKEN` 推送的 commit **不會**自動觸發 Pages 佈建（GitHub 的防迴圈設計）。少了這一步，`data.json` 明明更新了，網站卻停在舊值——這正是 2026-07-18 那次事故的成因。使用者在**本機**以自己的憑證（gh／PAT）推送則會正常觸發——每週覆核的發布走的就是這條（§8.3 的交付流程），不需要這一步。

- 前端採 **fetch-first**：`index.html` 先抓 `data.json`（`cache: "no-store"`），失敗才退回內嵌的 `#dashboard-data`。因此**日常更新只需要改 `data.json`，不必動 `index.html`**。

---

## 8. 每週質化覆核（人機分工）

排程任務：**「AI 泡沫監控：每週質化覆核與發布（v2）」**，cron `0 1 * * 1`（UTC）＝ **台北每週一 09:00**，開啟推播。

### 8.1 機器負責（GitHub Actions，每交易日）

L1 除 `narrative` 外全部、L2 除三項質化外全部、L3 除 `cloudrev`／`tokens` 外全部、台灣除 `tsmc_weight` 外全部，以及 `events`、`triggers`。

`dims`、`composite`、`quadrant`、`tw.subs`／`tw.heat`、`history` 這幾個**導出欄位**每交易日也由引擎重算一次，但它們**不是「機器專屬」**：每週覆核只要動了任何質化分數，就必須依 §8.4 自己重算同一組欄位並補一筆 `history`，否則頁面會停在上一次自動更新的值、跟改過的指標自相矛盾。「機器每天會算」不等於「人可以不算」——下一次自動更新可能是隔天早上，中間這段時間線上就是錯的。

### 8.2 人（每週覆核排程）負責

`narrative`、`circular`、`weakcredit`、`vc`、`tokens`、`cloudrev`（財報季）、`params`（`nvda_eps` 財報季——**NVDA 財年止於 1 月底，財報在 2／5／8／11 月下旬**，與三大雲的 1／4／7／10 月底錯開一個月；`megaipo_done` 事件；`ngdp_nominal` 年度，Fed SEP 的實質 GDP 中位數＋PCE 中位數）、`tw.items` 的 `tsmc_weight`（每月）。

`stage` **整塊**都是人維護的：`stage.checklist` 六項的 `state`／`evi`、`stage.note`，以及**`stage.current`（1–4 的小數）、`stage.label`、`stages[]` 的 `active`／`done`**。checklist 勾選數變了而 `current` 沒動，是最常見的漏更新。

**`stage` 算改完的條件**：六項的 `state` 與 `evi` 都重新看過一次（沒有新證據就明講維持原判，`evi` 不必重寫）；`stage.note` 的「點亮 X／6」等於六項 `state` 的實算和（**半格算 0.5**）；`current`、`label`、`stages[]` 的 `active`／`done` 三者互相對得上，也對得上點亮數。三項全過才算完成。機器只檢查得到其中一部分：`healthcheck.py` 會驗「點亮 X／6」這句與實算相符，也會驗 `stages` 剛好四階、剛好一階 `active`、`int(current)` 等於 active 的 `n`、`done` 只在 `n <` active 時為真。**沒有機器看得到的是 `evi` 的內容與 `label` 的文字**——那兩樣只能靠你自己重讀一次。

**改 `params` 不會立刻反映在頁面上。** `params.nvda_eps` 要等下一次引擎跑 `nvdape` 才會換算成新的本益比；`params.ngdp_nominal`／`megaipo_done` 要等下一次引擎重評 `triggers` 才會改變點亮狀態——而 `triggers` 不在 §8.3 的白名單裡，所以覆核當下**讓 `triggers` 保持引擎寫入的樣子**——為了讓畫面一致而手改 `state`，就是在製造假資料。正確做法是改完 `params` 就放著，在摘要裡註明「已更新 `params.X`，將於下一個交易日的自動更新生效」。唯一的例外是 `megaipo_done`：它同時要在 `stage.checklist` 反映，而 `stage` 本來就是人維護的。

**上週的基準從哪裡來。** `history` 每筆存 `date`、`composite`、三個層分數、`quad` 與 `trig`（2026-08-10 起）——**沒有 `regime`**。所以：上週 `composite` 看 `history` 倒數第二筆；上週 `regime` 要拿倒數第二筆的 `quad`（`[support, heat]`）自己套 §3.3 的規則反推；觸發器點亮數在 2026-08-10 之後的筆直接讀 `trig`，更早的筆沒有這個欄位，只能在**動手前**先把當下的 `triggers` 記下來當基準（排程流程第 1 步就是為此存在）。改完再回頭數，差額才是「本週新點亮」。

### 8.3 覆核只動 §8.2 那張清單

> **人這一輪要碰的欄位，就是這兩份的聯集**：§8.2 那張清單（六項質化分數、`params`、`tsmc_weight`、`stage` 整塊），加上 §8.4 收尾七步會寫到的每一個欄位（`zone`、`dims`、`composite`、`quadrant`、`tw.subs`／`tw.heat`、`history` 附加一筆、`meta.built`／`meta.builtTime`）。
> **這兩份以外的一律沿用引擎寫入的值**——`events`、`triggers`，以及 §8.1 所有自動指標的 `value`／`score`／`asof`。這是硬護欄：在覆核容器裡重抓它們，拿到的是空值或殘值，然後蓋掉每日管線的好資料。

原因是覆核容器的網路有**兩條路，能力不一樣**，這點常被誤記成「容器只放行 GitHub」：

| 路徑 | 實測結果（2026-08 逐一實測） | 意義 |
|---|---|---|
| Bash 的 `curl`／`requests`（引擎走這條） | 只通得到 `github.com` 與 `raw.githubusercontent.com`——而且 **git 只有讀，push 被 git proxy 擋**（見下方「發布」）。**連 `gundamnboy.github.io` 都不通**（回 http=000），`api.github.com` 根路徑 200 但 repo 端點 403，`example.com` 不通，FRED／Stooq／SEC EDGAR／TAIFEX 一律連線失敗 | 在覆核工作階段裡**跑不動 `update_data.py`**，也不能自己 `curl` 補數字 |
| `WebSearch`／`WebFetch`（走 Anthropic 的抓取服務） | **可以連到外部網站**，包括 FRED、TAIFEX，以及 `github.io` 上的 `data.json` | 質化研究（§8.2）與 `tsmc_weight` 月更靠這條；維護工作階段代使用者驗證線上時也走這條（見下） |

所以「不自己重抓」的真正理由不是「連不到網路」，而是：**能連到網路的那條路（WebFetch）拿不到引擎要的東西**。WebFetch 讀 `fredgraph.csv` 這類 CSV／JSON 端點會回傳 binary 亂碼，讀網頁則是經過摘要的文字——兩者都不能取代引擎的數值抓取，硬要用只會抓到殘值或讀錯數字，然後把每日管線抓到的好值蓋掉。

#### 發布：雲端推不上去，改為交付（2026-08-10 起）

**雲端工作階段（覆核排程與維護）已無法 push 這個 repo。** 2026-07 起平台的 git proxy 擋掉所有授權清單外的推送，回 403「not in this session's authorized repository set」——**自備 PAT 也無效**，proxy 在 GitHub 看到憑證之前就先擋下（上游回報 anthropics/claude-code#76248，未修）。這不是故障：**不要重試、不要找繞路、不要索取或使用 token**（原本存放於排程 prompt 的 PAT 已於 2026-08-10 移除並應撤銷）。

發布因此改為**人機協作**：

1. 覆核／維護工作階段在 `/tmp` 的 clone 內 commit（身分 `GunDamnBoy` / `haonung.chiang@gmail.com`），`git format-patch -1 --stdout` 產出 patch，連同 `data-YYYY-MM-DD.json`（檔名格式固定，見下）與內嵌新資料的離線 HTML 一起 `SendUserFile` 交付。
2. 使用者在本機執行 `bubble-publish`（zsh 函數，位於 `~/Projects/ai-bubble-monitor` 的 clone：抓 `~/Downloads` 最新的 `data-*.json` → 蓋 `data.json` → 跑 `healthcheck.py` 當關卡 → commit → push）。**只改 `data.json` 的覆核走這條**；動到程式或文件的維護改動交 `.patch`，使用者 `git am` 後推送。
3. 本機推送用使用者自己的 gh 憑證，會正常觸發 Pages 重建（§7）。

**發布後的線上驗證不再由覆核排程做**（它交付完就結束了）。維護工作階段代使用者驗證時用 WebFetch 抓 `data.json` 回報 `meta.built`／`composite`／`quadrant.regime`——注意**沒有任何已驗證有效的 cache-buster**（`?t=` 與多斜線都實測無效），且**同一個工作階段內同一個 URL 一小時抓不了第二次**（擋在抓取工具，不是 Pages）；完整對策與「換檔名」技巧見 `MAINTENANCE.md` §4 與 §6.10；`raw.githubusercontent.com` 只證明 commit 進去了，證明不了 Pages 已重建。

`events` 若真的漏了重大結構性事件，最多**補 1–2 條**（附 url），不要整批重寫。

**注意「重抓」與「重算」的差別**：`quadrant`、`dims`、`composite`、`tw.subs`／`tw.heat` 都是從指標分數**導出**的，質化分數一改就必須跟著重算（見 §8.4）。它們在 §8.3 的白名單裡（走 §8.4 那半）——把它們當成不可動的欄位，反而會讓頁面自相矛盾。

### 8.4 覆核收尾一定要做的重算

改完質化分數後用 Python 重算並寫回，順序固定：

1. 被改動指標的 `zone`（依 §3.4 的 `<33 / 33–67 / 67–84 / ≥84` 界，分數改了燈號沒改就是不一致，`healthcheck.py` 會抓）
2. 層分數 `dims`（該層非 null 指標等權平均）
3. `composite`（Σ 層權重 × 層分數）
4. `quadrant` 的 `heat`／`support`／`regime`
5. `tw.subs`／`tw.heat`（null 子群剔除後重新歸一）
6. `history` 附加一筆（同日去重，含 `quad` 與 `trig`＝觸發器點亮數）
7. **`meta.built` 改成今天、`meta.builtTime` 改成 `YYYY-MM-DD（每週質化覆核）`**

第 7 步不能省。`healthcheck.py` 硬性要求 `history` 最後一筆的日期等於 `meta.built`；覆核在週一附加一筆今天的 `history`，而 `meta.built` 還停在上週五自動更新的日期，就會直接 FAIL 卡住交付。

**但 `meta.lastAutoRun` 絕對不要動。** 它描述的是「最後一次**自動**更新」的成敗，人工覆核不是自動更新；改了會讓 `AAII` 這類已知失效來源的追蹤斷掉。

**`asof` 的通則：一律填資料本身的日期，不是覆核日**——引擎的 `set_trig` docstring 與 §4.5 的過期 WARN 都建立在這條上（把 `asof` 蓋成今天＝對使用者謊報新鮮度）。

**只改指標分數而不重算，頁面會顯示彼此矛盾的數字。** 收尾跑一次 `healthcheck.py`，它會把上面每一項重算後與存檔比對，**FAIL 必須是 0 才可以交付**。

交付流程見 §8.3「發布」：commit 訊息 `data: weekly qualitative review YYYY-MM-DD`，產出 patch＋`data-YYYY-MM-DD.json`＋離線 HTML（內嵌快照的 `history` 裁到最後 60 筆，見 §6 的快照段），SendUserFile 交給使用者本機推送。**不使用、不索取任何 token。**

推播摘要格式：綜合溫度與上週比較、`regime` 變化、觸發器點亮數變化、跨區指標、檢查清單變化、本週焦點 2–3 條、網站連結，末行提醒「下載 `data-YYYY-MM-DD.json` 後執行 `bubble-publish` 發布」。溫度週變動 ≥5、任一指標轉紅、或觸發器新點亮 → 開頭標「⚠ 警示」；**「還沒發布」是流程常態，不算警示**。

---

## 9. 已知失效來源與降級行為

| 來源 | 追蹤 | 狀況 | 目前處置 |
|---|---|---|---|
| AAII 情緒調查 | `attempt("AAII")` | Actions runner 持續被擋 | `senti` 少一個輸入，不報錯 |
| CBOE 個股 Put/Call | `attempt("CBOE putcall")` | **時好時壞**（2026-08-04 成功，之前多次失敗） | 成功就進 `senti`，失敗就退出當次平均 |
| CNN Fear & Greed | `attempt("CNN FearGreed")` | 2026-08-10 新接入；端點以 WebFetch 驗證過活著，**Actions runner 能否連上未實測** | `senti` 的第四輸入（0–100 直讀）；失敗就退出當次平均。若 streak 連續成功 ≥15 次，把本列與 `KNOWN_FAIL` 一起移除 |
| TAIFEX 台積電權重 | `attempt("TW 台積電權重")` | 擋機器人 | 由每週覆核人工更新（種子值 44.78%，2026-07-31） |
| Stooq | **無**（`px_rows()` 內部第三層備援，沒有自己的 `attempt()`） | Actions runner 被擋 | 已降為價格三層備援的最後一層 |
| 美國商務部資料中心營建支出 | **無**（還沒有程式碼） | 需免費 API 金鑰 | 未納入；接入條件與勘查結果見 `MAINTENANCE.md` §5 |

「追蹤」欄位是刻意加的：**後兩列在定義上永遠不會出現在 `ok` 或 `fail` 任一邊**，因為 `meta.lastAutoRun` 的字串來自 `attempt()` 的標籤。下面那條退場規則對它們不適用，別去 `ok` 裡找它們然後困惑。

**這張表要跟 `healthcheck.py` 的 `KNOWN_FAIL` 白名單一致**（機器會比對；白名單裡有、這張表沒有的會 FAIL）。

**反方向以前沒有機器能抓**——某個來源恢復正常之後，它會安靜地留在白名單裡，下次真的壞掉就只會是 WARN 而不是 FAIL。過去這條規則寫成「表上列的來源若已連續數週出現在 `ok` 裡就移除」，但 `data.json` 只保留最後一次自動更新，「連續數週」根本查不到，等於寫了卻執行不了。現在引擎會累計 `meta.lastAutoRun.streak`（成功 +1、失敗歸零），**連續成功 ≥15 次引擎執行（`healthcheck.py` 的 `OK_STREAK_RETIRE`）就 WARN**，提醒把該來源從這張表與 `KNOWN_FAIL` 一起移除。

**「15 次」是執行次數不是三週**：workflow 除了 cron 還有 `workflow_dispatch` 與推程式碼觸發，同日重跑也會重複累加（`history` 有同日去重、`streak` 沒有）。所以 15 次是「至少三週」的下限，不是日曆意義上的三週——它的用途是提醒你回來看一眼，不是自動下結論。

**`senti` 的輸入數會浮動**（穩定的只有 VIX），情緒面因此偏鈍。2026-08-10 已照「加一個不擋機器人的情緒源」的方向接入 CNN Fear & Greed，Actions 端通不通由 streak 見真章。仍然**不要把 `senti` 拿掉**——拿掉等於改了 L1 的權重結構。

---

## 10. 變更紀錄

**本節只留索引。** 一句話寫改了什麼，「為什麼改」與事故經過在 `MAINTENANCE.md` 第 6 節，逐行差異看 `git log`。**規則本身一律寫在上面的章節——來這裡找規則就是找錯地方。**

| 版本 | 日期 | 改了什麼 | 為什麼／事故經過 |
|---|---|---|---|
| **v2.1.2** | 2026-08-17 | 前端補上四個缺欄位防禦（`charts.debt.note`、指標卡與總表的 `zone`、`tw.heat` 的「null／100」），並拆掉五處寫死判語（`vc` 誤標 L3、「不同調」與 `evalNvdaCmp` 打架、無條件宣稱與論文結論一致、`evalStagePhase` 撐不到第三／四階段、2026Q1 驗算數字改為現算）；§3.4 兩組界改為正面表述；`healthcheck.py` 的 `find_repo` 不再無條件掃家目錄（在使用者 Mac 上會掛死、`--repo` 形同虛設）；§8.3 由禁令改為白名單、§6 的「幾處一組」去掉數字、§8.2 補 `stage` 的完成條件；`fresh` 死欄位與兩個既有回退寫進規格 | `MAINTENANCE.md` §6.13 |
| **v2.1.1** | 2026-08-17 | 文件瘦身：本節由敘事改為索引；只寫在本節裡的三個實作門檻搬進 §5.2；`skills/bubble-maintain/` 縮成指標；修掉六處已被自己推翻的抄本與兩個指錯的交叉引用 | `MAINTENANCE.md` §6.12 |
| **v2.1.0** | 2026-08-10 | 發布改人機協作（雲端交付 patch／`data-YYYY-MM-DD.json`／離線 HTML，使用者本機推送）；PAT 移出排程 prompt；`asof` 統一填資料本身的日期；引擎健壯化（重試、原子寫檔、負基期防呆、缺 91 天基期即 fail）；healthcheck 的「今天」改用台北日並補掉三個「抓不到就靜默跳過」的洞；前端補畫 CCC／Oracle 磚塊、hero 變化徽章、觸發器距門檻進度條；新增 `senti` 的 CNN F&G 第四輸入、`triggers[].prog`、`history[].trig` | `MAINTENANCE.md` §6.11 |
| **v2.0.4** | 2026-08-06 | 把「子群從 `null` 補齊那天 `tw.heat` 會不連續跳、方向可上可下」寫成通則交給 `healthcheck.py` 算（§4.6），不在文件裡寫死當下的模擬值 | `MAINTENANCE.md` §4、§6.10 |
| **v2.0.3** | 2026-08-04 | 刪掉「多打斜線」這個 cache-buster——它是事後歸因；改為明說目前只有「換檔名」可靠 | `MAINTENANCE.md` §6.10 |
| **v2.0.2** | 2026-08-04 | 第二輪子代理比對：頁面上寫死的敘述與數字（分區界線 5 份、觸發器項數 3 份、台股子群權重 2 份…）全部改為從 `data.json` 現算；`senti`／`tw.items` 的 `src`／`url` 改由引擎依當次成功的來源生成；新增 `meta.lastAutoRun.streak`，讓 §9 的退場規則第一次變成可執行 | `MAINTENANCE.md` §6.8、§6.9 |
| **v2.0.1** | 2026-08-04 | 第一輪比對：補掉 `NaN`／缺鍵／v1 殘值；排程 prompt 由「整份複製規格」改為流程骨架＋指向本檔；新增 `healthcheck.py` 與 `MAINTENANCE.md` | `MAINTENANCE.md` §6.7 |
| **v2** | 2026-08-04 | 三層頻率架構取代 v1 六維：L1／L2／L3 = 35／35／30、象限（heat × support）與軌跡、7 項引爆觸發器、季頻落後三解（初步季 nowcast／RPO／台灣月營收）、台灣供應鏈擴為 10 項 | `MAINTENANCE.md` §6.1 |
| **v1** | 2026-07-17 | 以中金〈如何監測 AI 泡沫?〉四維為起點的六維 21 指標；核心數字經 SEC EDGAR 原始 XBRL 獨立驗證（2026Q1 五大雲廠 Capex/OCF = 94.0%，與原文吻合） | `MAINTENANCE.md` §6.1 |
