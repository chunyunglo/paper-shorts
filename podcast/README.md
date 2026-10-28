# Behavior Decoded Tonight

把一篇論文做成深夜脫口秀風格的長影片：主持人 Kai 坐在主持桌，來賓 Anne 是「駐站資料科學家」，有開場獨白、觀眾笑聲、掌聲和樂隊音效。全部用開源工具在沒有 GPU 的雲端機器上跑，不用付費的虛擬人服務。每週自動做一集、自動上片，不經人工審核（見下方「自動經營」）。

A late-night-talk-show style video about one paper, built only with open tools on a CPU machine. One episode a week is made and published automatically, with no human review (see below).

## 流程 How it works

| 步驟 | 做法 | 檔案 |
|---|---|---|
| 腳本 | 每句一列：誰講、台詞，加上表情（`emo`）、手勢（`gest`）、和上一句的間隔（`gap`）、對方附和（`back`）、觀眾笑聲（`laugh`，0–1）、掌聲（`applause`，秒）、對鏡頭講（`toCamera`）、畫面資料卡（`card`）；`["SFX", "sting", …]` 是樂隊開場 | `episodes/ep01_en.json` |
| 配音 | Gemini 3.8 Flash TTS（secret `GEMINI_API_KEY`）：Kai 用 Achird（和短片同一個聲音）、Anne 用 Erinome。沒有 key 時改用 Supertonic 3（MIT，sherpa-onnx 在 CPU 上跑）的 voice 5 和 voice 2 | `build_audio.py` |
| 音效 | 觀眾聲用 Freesound 上的 CC0 錄音（可商用、免標示）：笑聲是 Kinoton 的九段情境喜劇笑聲，依長度挑最合適的一段、不連續重複，大笑時再疊一段錯開的；掌聲是 nervousneal 的小型觀眾掌聲，取穩定段落加上原錄音的收尾。樂隊開場是程式合成的鼓點加銅管 | `crowd.py`、`sfx.py`、`assets/crowd/` |
| 嘴型 | 每位主持人自己的音軌，每格算音量和頻譜，換成 VRM 的 aa/ih/ou/ee/oh | `build_audio.py` |
| 角色 | VRoid Studio 的 CC0 模型（pixiv，經 OpenGameArt）：Kai 是 Sakurada Fumiriya，Anne 是 Sendagaya Shino，載入時換上 Kai 的長褲和鞋子；`setup.sh` 會下載 | `setup.sh`、`web/src/main.js` |
| 動作 | 坐姿、兩段式手臂 IK（Kai 手放桌上、Anne 手放腿上）、講話時跟著語音重音點頭和比手勢、長句自然抬手；觀眾笑時有自己的節奏（頭往後仰、身體前傾、肩膀抖、瞇眼、手摸胸口或拍桌）、對方說笑話時微笑、眨眼、看對方或看鏡頭、頭髮物理 | `web/src/main.js` |
| 攝影棚 | three.js 程式建模：落地窗外三層城市夜景和橋、木條牆和 LED、霓虹招牌、燈架和光束、弧形主持桌、絲絨單人沙發、邊桌檯燈、地球儀和桌上麥克風，加上光暈後製 | `web/src/main.js` |
| 鏡頭和字幕 | 開場搖臂鏡頭、獨白正面鏡頭、依講話的人切近景、短句和笑聲切全景；資料卡、字幕、名牌和片頭片尾用 HTML 疊上 | `web/src/main.js`、`web/index.html` |
| 算圖 | Chromium 在 Xvfb 下用 Mesa llvmpipe 算 1080p，一格約 0.5 秒（4 核 CPU），4.7 分鐘約 75 分鐘 | `web/render.mjs`、`render.sh` |

## 自動經營 Running on its own

`.github/workflows/podcast.yml`，每週五 04:00 UTC（台灣中午）開始，repo variable `PODCAST_AUTO=true` 才會自動跑：

| 步驟 | 做法 | 程式 |
|---|---|---|
| 選論文 | 新論文（和短片同一批來源）加上最近 60 天做過短片、還沒做長片的論文，標上各自短片的觀看數；Claude 依頻道數據和經營策略排前五名，取第一篇能讀到全文的（arXiv，或 Unpaywall 找到的開放全文） | `shorts/podcast.py` `pick` |
| 寫腳本 | Claude 讀全文寫 Kai 和 Anne 的對話、表情、手勢、笑聲、掌聲和資料卡（`big`、`stats`、`list`、`quote`、`paper` 五種卡，由腳本決定內容） | `write`、`to_show` |
| 代替人工審核 | 先檢查格式（長度 650–1300 字、卡片都有用到、TTS 讀得出來），再由另一個 Claude 對照論文逐句查核：數字、因果說法、作者沒說過的話、不當玩笑。有問題就改，最多三輪；還不過就整集不上，開 issue 通知 | `validate`、`CHECK_SYSTEM` |
| 渲染 | `build_audio.py` + `render.sh`，GitHub 4 核機器約 1.5–2 小時 | |
| 影片檢查 | 長度和時間軸一致、1920×1080、有聲音且不是靜音、抽 5 格畫面不是黑畫面；再抽 14 張畫面給 Claude 看（字幕和卡片有沒有被切掉、缺字、卡片數字和腳本不符、角色穿模或畫面壞掉）；有明顯問題就不上 | `qa` |
| 上片 | 不帶字幕的乾淨畫面加標題做縮圖，描述含章節時間、論文 citation、AI 生成說明；用 `publishAt` 排程在 `PODCAST_DAY`／`PODCAST_HOUR_UTC`（預設週五 12:00 UTC＝台灣 20:00）公開；第一則留言放 citation；影片也放到 `pod-<集>` release | `publish` |
| 留言 | 每 12 小時的留言流程也會處理長片的留言 | `shorts/comments.py` |
| 後台數據 | `analytics.yml` 每天讀所有短片和長片的數字（YouTube 觀看、讚、留言；有授權時加觀看時長、平均觀看百分比、新增訂閱；IG、Threads insights），存到 `state` 分支的 `analytics/`；每週 Claude 依數據寫 `strategy.md`，選論文和寫腳本時會讀 | `shorts/analytics.py` |

要上到另一個頻道：設定 `PODCAST_YOUTUBE_CLIENT_ID`／`PODCAST_YOUTUBE_CLIENT_SECRET`／`PODCAST_YOUTUBE_REFRESH_TOKEN`，沒設就用短片的 YouTube secrets。要看觀看時長和留存率，YouTube refresh token 需要再加 `https://www.googleapis.com/auth/yt-analytics.readonly` 權限；沒有的話只讀公開數字。

測試：在 `claude/*` 分支 push 一個 commit 訊息含 `[podcast]` 的 commit，或手動執行 workflow（upload 不勾），整集會做完放到 pre-release，不上傳。

## 跑一次 Run

```bash
podcast/setup.sh
python podcast/build_audio.py podcast/episodes/ep01_en.json
Xvfb :99 -screen 0 1920x1080x24 &
podcast/render.sh                       # -> podcast/out/episode.mp4
```

只看幾張靜態畫面：`cd podcast/web && DISPLAY=:99 node render.mjs stills 4 36 70`。

## 授權 Credits

- 角色：VRoid Studio 範例模型 Sakurada Fumiriya、Sendagaya Shino（pixiv，CC0）。`characters/` 裡是之前自己用 Blender／MakeHuman 做角色的程式，目前沒有使用。
- 觀眾聲：Freesound CC0 1.0 錄音，來源與作者見 `assets/crowd/CREDITS.md`。
- 配音：Supertonic 3 © Supertone Inc.（MIT）；Kokoro（Apache-2.0）；sherpa-onnx（Apache-2.0）。
- three.js、three-vrm：MIT。
