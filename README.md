# 行為解碼 Behavior Decoded · paper-shorts

這個 repo 讓 AI 自己經營一個頻道，不需要人工審核：

- **短片**（週一到週六）：每天挑一篇「用計算方法研究人類行為」的新論文，做成中文、英文、巴西葡語三支直式短影音。中英文在台灣晚上 7 點、葡語在巴西晚上 7 點上到 YouTube Shorts、Instagram Reels 和 Threads。
- **長片 Behavior Decoded Tonight**（每週五）：主持人 Kai 和來賓 Anne 的深夜脫口秀，5–8 分鐘講一篇論文，上到同一個 YouTube 頻道，見 [podcast/README.md](podcast/README.md)。
- **把關**（取代人工審核）：另一個 Claude 對照論文逐句查核腳本；影片做好後檢查長度、聲音、黑畫面，再抽畫面給 Claude 看（字被切掉、缺字、語言錯、數字和腳本不符、角色或畫面壞掉）。任何一關沒過，那天就不上片，並開 issue 通知你。
- **自由發文**：每天由 Claude 決定要不要發，把已經做過的論文接上時事或補充重點：Threads 純文字（每天最多 2 則）、IG 圖文輪播（每週最多 3 則）。同樣先查核、圖片先給 Claude 看過才發。
- **經營**：每支影片底下第一則留言附論文 citation；每 4 小時自動回覆留言（每次都會通知你檢查結果）；每天讀後台數據（觀看、觀看時長、留存、新增訂閱、IG／Threads insights），每週由 Claude 寫經營策略，選論文和寫腳本時會參考。

The channel runs itself with no human review: daily trilingual shorts (Mon–Sat) and a weekly English talk show, each script fact-checked against the paper by a second Claude pass and each video checked by Claude looking at its frames, with comments answered every 4 hours and channel analytics read daily to steer what comes next.

## 流程 How it works

| 步驟 | 做法 | 程式 |
|---|---|---|
| 選論文 | arXiv（cs.SI、cs.CY、physics.soc-ph、econ.GN、cs.HC）＋ Nature Human Behaviour、Nature Computational Science、PNAS、Science Advances、EPJ Data Science、Journal of Computational Social Science 的 RSS，去掉做過的，由 Claude 挑一篇；也讀本週新聞頭條（台灣、美國、巴西、科技、科學），品質相近時優先挑和時事有關的 | `shorts/papers.py`、`shorts/news.py` |
| 寫腳本 | Claude 讀論文全文 PDF（arXiv，或透過 Unpaywall 找到的開放取用版本；讀不到全文的論文不選），寫 6–9 個場景，每句都有中文旁白和英文字幕，並指定畫面類型；有連到時事時，開場從那則新聞切入（只講到標題的程度，不編細節） | `shorts/script.py` |
| 配音 | 中文：Google Chirp3 HD Charon（`cmn-CN-Chirp3-HD-Charon`）；英文：Google Chirp3 HD Aoede（`en-US-Chirp3-HD-Aoede`）。選定的聲音失敗時整支改用備援聲音；再疊一層程式產生的背景音 | `shorts/tts.py` |
| 畫面 | 依頭像配色的「資料軌跡」風格：人群點陣、網路擴散、步驟流程、長條、時間線、散佈圖、對比卡，逐格繪製後用 ffmpeg 輸出 1080×1920 | `shorts/visuals.py`、`shorts/render.py` |
| 查核 | 另一個 Claude 對照論文逐句查核（數字、因果說法、中英文一致、時事連結），有問題就改，最多兩輪；還不過就那天不上片 | `shorts/script.py` `fact_check` |
| 看畫面 | 每種語言抽 8 張畫面給 Claude 看，有明顯問題就不上片（`VISUAL_CHECK=off` 可關掉） | `shorts/look.py` |
| 上傳 | 影片先放到 GitHub Release，IG 和 Threads 從那個網址抓；YouTube 直接上傳並標示 AI 生成內容 | `shorts/publish/` |
| 留言 | 一般問答／稱讚：用留言者的語言根據論文摘要回覆；垃圾留言：隱藏；敏感或學術爭議：不回覆，私下通知（長片和自由發文的留言也一起處理）。值得參考的回饋（想看的主題、看不懂的地方、有趣的角度）由 Claude 改寫成一句摘要存到 `state` 分支 `feedback.jsonl`（不存原文和留言者），選論文、寫腳本和自由發文時會參考 | `shorts/comments.py` |
| 後台數據 | 每天讀所有貼文的數字存到 `state` 分支 `analytics/`（`report.md` 可直接看），每週 Claude 寫 `strategy.md`，選論文和寫腳本時會讀；舊的策略都留在 `strategy_log.md` | `shorts/analytics.py` |
| 決策紀錄 | 每次發文後重寫 [`data/decisions.md`](data/decisions.md)：每篇短影音、脫口秀、自由發文為什麼發、參考了哪些數據或觀眾回饋（改寫，不引用原文），最新的在最上面 | `shorts/journal.py` |

## 排程 Workflows

| Workflow | 時間 | 開關 |
|---|---|---|
| `revise.yml` | 你在「今晚上片」issue 留言寫修改意見時（不是 OK、也不是「不要上」）自動觸發：Claude 改腳本、重做三支影片，在 issue 貼新版本 | 只有 repo 擁有者的留言會觸發 |
| `suggest.yml` | （目前暫停，只能手動執行）原本週一到週六 19:30（台灣）：找和當天論文相關的中文和英文公開 Threads 貼文，各起草最多 3 則以研究發現為主的留言，寄到你的信箱。**不會自動貼**，你自己決定要不要貼 | 需要 Threads 的 `threads_keyword_search` 權限才會自動找貼文；沒有的話信裡會附搜尋連結和通用草稿 |
| `publish.yml` | 週一到六 14:00 做影片（含 AI 查核和看畫面）並開「今晚上片」issue；19:00 上中英文（台灣時間）；巴西 19:00（台灣隔天 06:00）上葡語。手動：`mode=delete` 刪掉某集的貼文，`episode=` 重做某集 | repo variable `AUTO_PUBLISH=true` 才會自動跑。預設不用審核：每天開一則「今晚上片」issue 當紀錄，沒回覆就照常上片，回「不要上」才會擋下。想恢復人工審核，設 variable `REVIEW_REQUIRED=true` |
| `comments.yml` | 每 4 小時（台灣 00:23、04:23、08:23、12:23、16:23、20:23）；每次跑完在「留言檢查紀錄」issue 留一行數字通知你（不含留言內容） | repo variable `AUTO_REPLY=true` 才會自動跑；手動執行預設只分類不動作 |
| `maintenance.yml` | 每週一 | 續期 IG/Threads token 並寫回 Secrets；重新啟用排程，避免 GitHub 60 天無活動自動停用 |
| `podcast.yml` | 每週五 04:00 UTC | 長片 Behavior Decoded Tonight：自動選論文、寫對話、AI 查核、渲染、檢查、排程上 YouTube，不經人工審核。repo variable `PODCAST_AUTO=true` 才會自動跑，見 [podcast/README.md](podcast/README.md) |
| `analytics.yml` | 每天 09:30（台灣） | 讀所有貼文的後台數字，存到 `state` 分支 `analytics/report.md`，每週由 Claude 寫經營策略 |
| `social.yml` | 每天 11:30（台灣） | 自由發文：Threads 純文字、IG 圖文。repo variable `SOCIAL_AUTO=true` 才會自動跑；手動執行預設只產生草稿和圖片（放 pre-release），不發。上限用 `MAX_THREADS_PER_DAY`、`MAX_IG_PER_WEEK` 改 |
| `sample.yml` | 手動，或 commit 訊息含 `[sample]` | 只產生樣片，放在 pre-release，不上傳任何平台 |

開關在 [Settings → Variables](../../settings/variables/actions)：`AUTO_PUBLISH`、`PODCAST_AUTO`、`AUTO_REPLY`、`SOCIAL_AUTO` 設成 `true` 才會自動跑；`REVIEW_REQUIRED=true` 恢復人工審核；`VISUAL_CHECK=off` 關掉看畫面；`PODCAST_DAY`（0＝週一）和 `PODCAST_HOUR_UTC` 改長片上片時間（預設週五 12:00 UTC＝台灣 20:00）。

## Secrets

| 名稱 | 用途 |
|---|---|
| `ANTHROPIC_API_KEY` | 選論文、寫腳本、查核、看畫面、分類與回覆留言、寫經營策略 |
| `GEMINI_API_KEY` | 配音（Gemini 3.8 Flash TTS，要開付費；免費方案一天只有 10 次） |
| `GOOGLE_TTS_API_KEY` | 選用：Gemini 配音失敗時的備用配音 |
| `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` / `YOUTUBE_REFRESH_TOKEN` | YouTube 上傳、留言和後台數據（refresh token 要有 `youtube.force-ssl` 和 `yt-analytics.readonly` 兩個權限） |
| `PODCAST_YOUTUBE_*` | 選用：長片要上到另一個頻道時才設，沒設就用上面那組 |
| `IG_USER_ID` / `IG_ACCESS_TOKEN` | Instagram Reels 與留言 |
| `THREADS_USER_ID` / `THREADS_ACCESS_TOKEN` | Threads 貼文與回覆 |
| `GH_PAT` | 把續期後的 token 寫回 Secrets；在私人 repo 開通知 issue |
| `ALERT_EMAIL_USER` / `ALERT_EMAIL_APP_PASSWORD` / `ALERT_EMAIL_TO` | 選用：用 Gmail 寄敏感留言通知 |

敏感留言：詳細內容放在私人 repo `paper-shorts-inbox` 的 issue（或 email），再由 Actions bot 在這個 repo 開一則只含連結的 issue，GitHub 才會通知你（自己的 token 開的 issue 不會通知自己）。私人 repo 名稱可用 variable `ALERT_REPO` 改。

有 `GEMINI_API_KEY` 時，短片中英文都用 Gemini 的 Achird（和 podcast 主持人 Kai 同一個聲音）。沒有這把 key 時，才用 repo variable `TTS_VOICE_ZH`、`TTS_VOICE_EN` 設定的聲音（Google 聲音名稱，或結尾是 `Neural` 的 Edge 聲音）。

## 隱私 Privacy

這個 repo 是公開的，所以 Actions 紀錄只會印出數量，不會印留言內容、留言者名稱、token 或完整網址。已處理留言的紀錄存在 `state` 分支，只存雜湊值。詳見 [PRIVACY.md](PRIVACY.md)。

## 本機測試 Local

```bash
pip install -r requirements.txt pytest
python -m pytest -q tests
TTS_PROVIDER=silent python -m shorts make --paper-json tests/fixtures/paper.json --script-json tests/fixtures/script.json
```
需要 Noto Sans CJK 字型（Ubuntu：`fonts-noto-cjk`）和 ffmpeg。
