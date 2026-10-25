# 行為解碼 Behavior Decoded · paper-shorts

每週一到週六（週日休息），自動挑一篇「用計算方法研究人類行為」的新論文，做成中文、英文、巴西葡語三支直式短影音，下午先給頻道主審核。中英文在台灣晚上 7 點、葡語在巴西晚上 7 點上傳到 YouTube Shorts、Instagram Reels 和 Threads，每支影片底下第一則留言會附上論文 citation，並每小時自動整理留言。

Monday to Saturday (Sunday off) this repo picks one new computational human-behavior paper, makes Chinese, English and Brazilian Portuguese 9:16 explainers, asks the owner to approve them in the afternoon, posts zh/en at 19:00 Taiwan time and pt at 19:00 Brasília time, adds the full citation as the first comment under each post, and triages comments every hour.

## 流程 How it works

| 步驟 | 做法 | 程式 |
|---|---|---|
| 選論文 | arXiv（cs.SI、cs.CY、physics.soc-ph、econ.GN、cs.HC）＋ Nature Human Behaviour、Nature Computational Science、PNAS、Science Advances、EPJ Data Science、Journal of Computational Social Science 的 RSS，去掉做過的，由 Claude 挑一篇；也讀本週新聞頭條（台灣、美國、巴西、科技、科學），品質相近時優先挑和時事有關的 | `shorts/papers.py`、`shorts/news.py` |
| 寫腳本 | Claude 讀論文（arXiv 讀全文 PDF，期刊讀摘要），寫 6–9 個場景，每句都有中文旁白和英文字幕，並指定畫面類型；有連到時事時，開場從那則新聞切入（只講到標題的程度，不編細節） | `shorts/script.py` |
| 配音 | 中文：Google Chirp3 HD Charon（`cmn-CN-Chirp3-HD-Charon`）；英文：Google Chirp3 HD Aoede（`en-US-Chirp3-HD-Aoede`）。選定的聲音失敗時整支改用備援聲音；再疊一層程式產生的背景音 | `shorts/tts.py` |
| 畫面 | 依頭像配色的「資料軌跡」風格：人群點陣、網路擴散、步驟流程、長條、時間線、散佈圖、對比卡，逐格繪製後用 ffmpeg 輸出 1080×1920 | `shorts/visuals.py`、`shorts/render.py` |
| 上傳 | 影片先放到 GitHub Release，IG 和 Threads 從那個網址抓；YouTube 直接上傳並標示 AI 生成內容 | `shorts/publish/` |
| 留言 | 一般問答／稱讚：用留言者的語言根據論文摘要回覆；垃圾留言：隱藏；敏感或學術爭議：不回覆，私下通知 | `shorts/comments.py` |

## 排程 Workflows

| Workflow | 時間 | 開關 |
|---|---|---|
| `revise.yml` | 你在審核 issue 留言寫修改意見時（不是 OK、也不是「不要上」）自動觸發：Claude 改腳本、重做三支影片，在 issue 貼新版本 | 只有 repo 擁有者的留言會觸發 |
| `suggest.yml` | （目前暫停，只能手動執行）原本週一到週六 19:30（台灣）：找和當天論文相關的中文和英文公開 Threads 貼文，各起草最多 3 則以研究發現為主的留言，寄到你的信箱。**不會自動貼**，你自己決定要不要貼 | 需要 Threads 的 `threads_keyword_search` 權限才會自動找貼文；沒有的話信裡會附搜尋連結和通用草稿 |
| `publish.yml` | 週一到六 14:00 做影片並開審核 issue；19:00 上中英文（台灣時間）；巴西 19:00（台灣隔天 06:00）上葡語。手動：`mode=delete` 刪掉某集的貼文，`episode=` 重做某集 | repo variable `AUTO_PUBLISH=true` 才會自動跑。在審核 issue 回「OK」或「沒問題」才會上片，沒回就跳過 |
| `comments.yml` | 每小時 | repo variable `AUTO_REPLY=true` 才會自動跑；手動執行預設只分類不動作 |
| `maintenance.yml` | 每週一 | 續期 IG/Threads token 並寫回 Secrets；重新啟用排程，避免 GitHub 60 天無活動自動停用 |
| `sample.yml` | 手動，或 commit 訊息含 `[sample]` | 只產生樣片，放在 pre-release，不上傳任何平台 |

開關在 [Settings → Variables](../../settings/variables/actions)。

## Secrets

| 名稱 | 用途 |
|---|---|
| `ANTHROPIC_API_KEY` | 選論文、寫腳本、分類與回覆留言 |
| `GOOGLE_TTS_API_KEY` | 配音 |
| `YOUTUBE_CLIENT_ID` / `YOUTUBE_CLIENT_SECRET` / `YOUTUBE_REFRESH_TOKEN` | YouTube 上傳與留言 |
| `IG_USER_ID` / `IG_ACCESS_TOKEN` | Instagram Reels 與留言 |
| `THREADS_USER_ID` / `THREADS_ACCESS_TOKEN` | Threads 貼文與回覆 |
| `GH_PAT` | 把續期後的 token 寫回 Secrets；在私人 repo 開通知 issue |
| `ALERT_EMAIL_USER` / `ALERT_EMAIL_APP_PASSWORD` / `ALERT_EMAIL_TO` | 選用：用 Gmail 寄敏感留言通知 |

敏感留言：詳細內容放在私人 repo `paper-shorts-inbox` 的 issue（或 email），再由 Actions bot 在這個 repo 開一則只含連結的 issue，GitHub 才會通知你（自己的 token 開的 issue 不會通知自己）。私人 repo 名稱可用 variable `ALERT_REPO` 改。

配音聲音用 repo variable `TTS_VOICE_ZH`、`TTS_VOICE_EN` 設定（Google 聲音名稱，或結尾是 `Neural` 的 Edge 聲音）。

## 隱私 Privacy

這個 repo 是公開的，所以 Actions 紀錄只會印出數量，不會印留言內容、留言者名稱、token 或完整網址。已處理留言的紀錄存在 `state` 分支，只存雜湊值。詳見 [PRIVACY.md](PRIVACY.md)。

## 本機測試 Local

```bash
pip install -r requirements.txt pytest
python -m pytest -q tests
TTS_PROVIDER=silent python -m shorts make --paper-json tests/fixtures/paper.json --script-json tests/fixtures/script.json
```
需要 Noto Sans CJK 字型（Ubuntu：`fonts-noto-cjk`）和 ffmpeg。
