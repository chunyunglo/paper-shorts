# 生意有數（暫定）· 中文理念 podcast

一條獨立的線，和每日短片（`shorts/`）分開。每集講一個概念，不從論文出發：
資料科學是在高維度空間裡快速探索的能力，建立在這種探索上的自動化才是 AI 轉型的本質。

| 步驟 | 做法 |
|---|---|
| 主題 | `topics.json` 的第一季主題清單，每集一個概念。直接改這個檔案就能換題目或加題目 |
| 寫稿 | Claude 寫阿凱和安妮兩人的對談（討論夥伴，不是一問一答），15–20 分鐘，有固定的「展開維度」段落 |
| 查核 | 另一個 Claude 檢查觀念有沒有講錯，以及有沒有編造的數字、研究、公司或人說的話；例子裡的數字必須標明是假設。有問題就改，最多三輪，還不過就不出 |
| 配音 | `podcast/build_audio.py`，Gemini TTS（阿凱 Achird、安妮 Erinome），輸出響度標準化的 MP3 |
| 輸出 | 放在 GitHub pre-release `concept-demo-N`，**不發布到任何平台** |

執行：Actions → **Concept podcast demo** → Run workflow（可填主題 id，例如 `s1e03`），
或在 `claude/*` 分支的 commit 訊息加 `[concept-show]`。本機寫稿：`python -m concept_show make --topic s1e01`。

寫稿和配音是兩個分開的 job，自動接著跑：`script` 寫好稿子先存到 pre-release，`voice` 再從 pre-release 拿稿子配音。
配音失敗時只重跑 `voice`（Re-run failed jobs，或 Run workflow 填 `release=concept-demo-N`），不會再花一次寫稿的錢；
已經配好的句子有快取，重跑會從停下的地方接著配。

需要的 Secrets：`ANTHROPIC_API_KEY`、`GEMINI_API_KEY`。
