# 無聊統計學（中文理念 podcast）

一條獨立的線，和每日短片（`shorts/`）分開。每集講一個概念，不從論文出發：
資料科學是在高維度空間裡快速探索的能力，建立在這種探索上的自動化才是 AI 轉型的本質。

| 步驟 | 做法 |
|---|---|
| 名稱 | `cast.json`：節目名稱、兩個人的名字、個性、聲音，以及配音的口音和語氣。換名字只改這個檔案 |
| 主題 | 沒有固定的一季清單。每集開工前，Claude 讀 `strategy.json`（理念、為什麼做這個節目、原則、可參考的方向）、`feedback.md`（你的回饋，最新的寫最上面）和之前每一集的紀錄與策略筆記，決定下一集講什麼，並更新策略筆記。想調整方向就改 `feedback.md` |
| 寫稿 | Claude 寫 Una 和 Natasha 兩個朋友的聊天，15–20 分鐘，講得淺，一集只講懂一件事 |
| 查核 | 另一個 Claude 檢查觀念有沒有講錯，以及有沒有編造的數字、研究、公司或人說的話；例子裡的數字必須標明是假設。有問題就改，最多三輪，還不過就不出 |
| 配音 | `concept_show/voice.py`，Gemini 3.8 Flash TTS 雙人模式（Una：Despina、Natasha：Sulafat），整集 2 到 3 次請求，每次至少間隔 8 秒，一次執行最多 25 次。也可以在 `cast.json` 用文字設計聲音，但那樣要一句一次請求 |
| 輸出 | 放在 GitHub pre-release `concept-demo-N`：稿子、`plan.md`（為什麼選這一集）、`strategy.md`（更新後的策略筆記）、MP3。這一步不會公開任何東西 |
| 上架 | 每週自動：配音完成後接著建立正式 release `boring-epNN`，重建 `docs/boring-stats/feed.xml`（GitHub Pages，封面 `docs/boring-stats/cover.png`）。RSS 送到 Spotify、Apple Podcasts、KKBOX 一次之後，新集數會自動同步。`cast.json` 的 `feed` 還沒填聯絡信箱之前，這一步會跳過（不算失敗） |
| 數據 | 每集 MP3 在 release 上的下載次數。寫稿前流程會讀回來，連同上架天數一起給決定下一集的那一步參考 |

執行：每週一 16:30（台灣時間）自動跑完整條：決定下一集、寫稿、查核、配音、上架。也可以手動 Actions → **Concept podcast demo** → Run workflow（可在 request 填這集想講的方向，空白就讓流程自己決定），
或在 `claude/*` 分支的 commit 訊息加 `[concept-show]`。本機：`python -m concept_show plan` 只看下一集的決定，`python -m concept_show make` 決定並寫稿。

寫稿和配音是兩個分開的 job，自動接著跑：`script` 寫好稿子先存到 pre-release，`voice` 再從 pre-release 拿稿子配音。
配音失敗時只重跑 `voice`（Re-run failed jobs，或 Run workflow 填 `release=concept-demo-N`），不會再花一次寫稿的錢；
已經配好的句子有快取，重跑會從停下的地方接著配。

需要的 Secrets：`ANTHROPIC_API_KEY`、`GEMINI_API_KEY`。
