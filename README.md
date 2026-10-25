# 行為解碼 Behavior Decoded · paper-shorts

每週兩次，自動挑一篇「用計算方法研究人類行為」的新論文，做成中英雙語的一分鐘直式短影音，上傳到 YouTube Shorts、Instagram Reels 和 Threads，並每小時自動整理留言。

Twice a week this repo picks one new computational human-behavior paper, turns it into a bilingual 9:16 explainer, posts it to YouTube Shorts, Instagram Reels and Threads, and triages comments every hour.

## 流程 How it works

| 步驟 | 做法 | 程式 |
|---|---|---|
| 選論文 | arXiv（cs.SI、cs.CY、physics.soc-ph、econ.GN、cs.HC）＋ Nature Human Behaviour、Nature Computational Science、PNAS、Science Advances、EPJ Data Science、Journal of Computational Social Science 的 RSS，去掉做過的，由 Claude 挑一篇 | `shorts/papers.py` |
| 寫腳本 | Claude 讀論文（arXiv 讀全文 PDF，期刊讀摘要），寫 6–9 個場景，每句都有中文旁白和英文字幕，並指定畫面類型 | `shorts/script.py` |
| 配音 | Google Cloud TTS（`cmn-TW-Wavenet-A`），沒有金鑰時改用 Edge TTS；再疊一層程式產生的背景音 | `shorts/tts.py` |
| 畫面 | 依頭像配色的「資料軌跡」風格：人群點陣、網路擴散、步驟流程、長條、時間線、散佈圖、對比卡，逐格繪製後用 ffmpeg 輸出 1080×1920 | `shorts/visuals.py`、`shorts/render.py` |
| 上傳 | 影片先放到 GitHub Release，IG 和 Threads 從那個網址抓；YouTube 直接上傳並標示 AI 生成內容 | `shorts/publish/` |
| 留言 | 一般問答／稱讚：用留言者的語言根據論文摘要回覆；垃圾留言：隱藏；敏感或學術爭議：不回覆，私下通知 | `shorts/comments.py` |

## 排程 Workflows

| Workflow | 時間 | 開關 |
|---|---|---|
| `publish.yml` | 每週二、五 09:00（台灣） | repo variable `AUTO_PUBLISH=true` 才會自動跑；也可手動執行，勾選 publish 才會上傳 |
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

敏感留言通知預設會在私人 repo `paper-shorts-inbox` 開 issue（GitHub 會寄 email 給你）。repo 名稱可用 variable `ALERT_REPO` 改。

## 隱私 Privacy

這個 repo 是公開的，所以 Actions 紀錄只會印出數量，不會印留言內容、留言者名稱、token 或完整網址。已處理留言的紀錄存在 `state` 分支，只存雜湊值。詳見 [PRIVACY.md](PRIVACY.md)。

## 本機測試 Local

```bash
pip install -r requirements.txt pytest
python -m pytest -q tests
TTS_PROVIDER=silent python -m shorts make --paper-json tests/fixtures/paper.json --script-json tests/fixtures/script.json
```
需要 Noto Sans CJK 字型（Ubuntu：`fonts-noto-cjk`）和 ffmpeg。
