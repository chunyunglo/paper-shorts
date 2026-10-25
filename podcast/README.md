# Behavior Decoded Tonight（試做）

把一篇論文做成深夜脫口秀風格的長影片：主持人 Kai 坐在主持桌，來賓 Anne 是「駐站資料科學家」，有開場獨白、觀眾笑聲、掌聲和樂隊音效。全部用開源工具在沒有 GPU 的雲端機器上跑，不用付費的虛擬人服務，還沒接上每日排程。

A late-night-talk-show style video about one paper, built only with open tools on a CPU machine. Not wired into the publishing schedule yet.

## 流程 How it works

| 步驟 | 做法 | 檔案 |
|---|---|---|
| 腳本 | 每句一列：誰講、台詞，加上表情（`emo`）、手勢（`gest`）、和上一句的間隔（`gap`）、對方附和（`back`）、觀眾笑聲（`laugh`，0–1）、掌聲（`applause`，秒）、對鏡頭講（`toCamera`）、畫面資料卡（`card`）；`["SFX", "sting", …]` 是樂隊開場 | `episodes/ep01_en.json` |
| 配音 | Supertonic 3（MIT，sherpa-onnx 在 CPU 上跑）：Kai 用 voice 5、Anne 用 voice 2。中文集可改用 Kokoro | `build_audio.py` |
| 音效 | 觀眾笑聲和掌聲用 ESC-50 的真人錄音疊成：每次笑聲混 20–40 個遠近不同的人，後排的加低通和殘響；樂隊開場是程式合成的鼓點加銅管 | `sfx.py` |
| 嘴型 | 每位主持人自己的音軌，每格算音量和頻譜，換成 VRM 的 aa/ih/ou/ee/oh | `build_audio.py` |
| 角色 | 自己在 Blender（bpy）裡做：MakeHuman 人體和表情（MPFB2），西裝、襯衫、領帶、皮鞋、頭髮和皮膚貼圖都是程式產生，再匯出成 VRM 1.0。外型設定在 `kai.json`、`anne.json` | `characters/build.py` |
| 動作 | 坐姿、兩段式手臂 IK（Kai 手放桌上、Anne 手放腿上）、講話時跟著語音重音點頭和比手勢、長句自然抬手；觀眾笑時有自己的節奏（頭往後仰、身體前傾、肩膀抖、瞇眼、手摸胸口或拍桌）、對方說笑話時微笑、眨眼、看對方或看鏡頭、頭髮物理 | `web/src/main.js` |
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

- 角色：MakeHuman 基礎人體、表情和眼睛（CC0）；MPFB2（GPL-3.0，只在建模時用，不隨影片散布）；VRM Add-on for Blender（MIT）。
- 觀眾聲：ESC-50（K. J. Piczak，CC BY-NC 3.0）。**限非商業使用**，正式發布前要用 `CROWD_DIR` 換成有授權的觀眾音效包。
- 配音：Supertonic 3 © Supertone Inc.（MIT）；Kokoro（Apache-2.0）；sherpa-onnx（Apache-2.0）。
- three.js、three-vrm：MIT。
