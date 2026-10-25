# 行為解碼 Podcast（試做）

兩位虛擬主持人坐在攝影棚聊一篇論文的長影片。全部用開源工具，在沒有 GPU 的雲端機器上跑，不用付費的虛擬人服務。還沒接上每日排程。

A long-form, two-host talk-show video about one paper, built only with open tools on a CPU machine. Not wired into the publishing schedule yet.

## 流程 How it works

| 步驟 | 做法 | 檔案 |
|---|---|---|
| 腳本 | 每句一列：誰講、台詞，加上表情（`emo`）、手勢（`gest`）、和上一句的間隔（`gap`，短的就是搶話）、對方的附和（`back`，例如「嗯嗯」疊在這句中間）、畫面上的資料卡（`card`） | `episodes/ep01.json` |
| 配音 | Kokoro v1.1 中英模型（Apache-2.0，經 sherpa-onnx 在 CPU 上跑），小安用 speaker 10、阿凱用 65 | `build_audio.py` |
| 嘴型 | 從每位主持人自己的音軌，每格算音量和頻譜，換成 VRM 的 aa/ih/ou/ee/oh 五個嘴型 | `build_audio.py` |
| 角色 | VRM 範例模型（VRM Public License 1.0，可商用、可修改）：小安是 pixiv 的 VRM1_Constraint_Twist_Sample，阿凱是 VirtualCast 的 Seed-san（要標示作者） | `setup.sh` 下載 |
| 動作 | 坐姿、手用兩段式 IK 放在桌上、講話時手勢和點頭、聽的人在對方講完或附和時點頭、對方開玩笑時微笑、隨機眨眼、看向對方或偶爾看鏡頭、頭髮物理 | `web/src/main.js` |
| 攝影棚 | three.js 程式建模：木條牆、吸音棉、霓虹招牌、書架、植物、立燈、桌上麥克風、牆上電視 | `web/src/main.js` |
| 鏡頭和字幕 | 依講話的人切近景、短句和偶爾切雙人；資料卡、字幕、片頭片尾用 HTML 疊在畫面上 | `web/src/main.js`、`web/index.html` |
| 算圖 | Chromium 在 Xvfb 下用 Mesa llvmpipe 算 1280×720 再放大到 1080p，一格約 0.55 秒（4 核 CPU），5.6 分鐘約 1.5 小時 | `web/render.mjs`、`render.sh` |

## 跑一次 Run

```bash
podcast/setup.sh                                   # 模型和套件
python podcast/build_audio.py podcast/episodes/ep01.json
Xvfb :99 -screen 0 1920x1080x24 &
podcast/render.sh                                  # -> podcast/out/episode.mp4
```

只看幾張靜態畫面：`cd podcast/web && DISPLAY=:99 node render.mjs stills 6 20 60`。

## 授權 Credits

- 阿凱的模型 Seed-san © VirtualCast, Inc.，影片說明欄需要標示。
- 小安的模型 VRM1_Constraint_Twist_Sample © pixiv Inc.，不需標示。
- Kokoro TTS（hexgrad）Apache-2.0；sherpa-onnx Apache-2.0；three.js MIT；three-vrm MIT。
