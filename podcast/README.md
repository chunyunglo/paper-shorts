# Behavior Decoded Tonight（試做）

把一篇論文做成深夜脫口秀風格的長影片：主持人 Kai 坐在主持桌，來賓 Anne 是「駐站資料科學家」，有開場獨白、觀眾笑聲、掌聲和樂隊音效。全部用開源工具在沒有 GPU 的雲端機器上跑，不用付費的虛擬人服務，還沒接上每日排程。

A late-night-talk-show style video about one paper, built only with open tools on a CPU machine. Not wired into the publishing schedule yet.

## 流程 How it works

| 步驟 | 做法 | 檔案 |
|---|---|---|
| 腳本 | 每句一列：誰講、台詞，加上表情（`emo`）、手勢（`gest`）、和上一句的間隔（`gap`）、對方附和（`back`）、觀眾笑聲（`laugh`，0–1）、掌聲（`applause`，秒）、對鏡頭講（`toCamera`）、畫面資料卡（`card`）；`["SFX", "sting", …]` 是樂隊開場 | `episodes/ep01_en.json` |
| 配音 | Supertonic 3（MIT，sherpa-onnx 在 CPU 上跑）：Kai 用 voice 5、Anne 用 voice 2。中文集可改用 Kokoro | `build_audio.py` |
| 音效 | 程式合成：鼓點加銅管的開場、掌聲、用 TTS 笑聲疊出來的觀眾笑聲，再加房間殘響 | `sfx.py` |
| 嘴型 | 每位主持人自己的音軌，每格算音量和頻譜，換成 VRM 的 aa/ih/ou/ee/oh | `build_audio.py` |
| 角色 | VRoid Studio 官方範例 AvatarSample_C（Kai）和 AvatarSample_A（Anne），pixiv 允許商用與修改 | `setup.sh` 下載 |
| 動作 | 坐姿、兩段式手臂 IK（Kai 手放桌上、Anne 手放腿上）、講話手勢和點頭、觀眾笑時一起笑、對方說笑話時微笑、眨眼、看對方或看鏡頭、頭髮物理 | `web/src/main.js` |
| 攝影棚 | three.js 程式建模：落地窗外三層城市夜景和橋、木條牆和 LED、霓虹招牌、燈架和光束、弧形主持桌、絲絨單人沙發、邊桌檯燈、地球儀和桌上麥克風，加上光暈後製 | `web/src/main.js` |
| 鏡頭和字幕 | 開場搖臂鏡頭、獨白正面鏡頭、依講話的人切近景、短句和笑聲切全景；資料卡、字幕、名牌和片頭片尾用 HTML 疊上 | `web/src/main.js`、`web/index.html` |
| 算圖 | Chromium 在 Xvfb 下用 Mesa llvmpipe 算 1080p，一格約 0.5 秒（4 核 CPU），4.7 分鐘約 75 分鐘 | `web/render.mjs`、`render.sh` |

## 跑一次 Run

```bash
podcast/setup.sh
python podcast/build_audio.py podcast/episodes/ep01_en.json
Xvfb :99 -screen 0 1920x1080x24 &
podcast/render.sh                       # -> podcast/out/episode.mp4
```

只看幾張靜態畫面：`cd podcast/web && DISPLAY=:99 node render.mjs stills 4 36 70`。

## 授權 Credits

- 角色：VRoid Studio sample models AvatarSample_A／C © pixiv Inc.（依 VRoid 範例模型使用條件，可商用、可修改）。
- 配音：Supertonic 3 © Supertone Inc.（MIT）；Kokoro（Apache-2.0）；sherpa-onnx（Apache-2.0）。
- three.js、three-vrm：MIT。
