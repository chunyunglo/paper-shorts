"""The Chinese concept podcast 無聊統計學. There is no fixed season: before each episode a planning pass
reads the show's strategy (strategy.json), the feedback notes (feedback.md) and the record of every earlier
episode, picks the next topic, and updates the running strategy notes. No paper, no news hook. Two friends
talk it through.

plan   Claude decides the next episode from the strategy, the feedback and the history.
make   plan, then Claude writes the two-host Traditional Chinese episode for one topic. A second Claude pass checks
       it for wrong concepts and invented specifics (numbers, companies, studies, quotes); the writer
       fixes what it finds, up to three rounds. Writes out/concept_show/<id>/show.json, script.md and
       meta.json. Nothing here publishes.
voice  see voice.py: Gemini multi-speaker TTS, a few turns per request.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from . import llm

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "out" / "concept_show"
CAST = json.loads((HERE / "cast.json").read_text(encoding="utf-8"))  # show name, hosts, voices: edit cast.json
SHOW = CAST["show"]
MIN_CHARS, MAX_CHARS = 3000, 5200  # spoken characters, about 13-22 minutes at the voices' pace
MIN_LINES, MAX_LINES = 70, 200
HOSTS = {k: {"tts": "gemini", **h} for k, h in CAST["hosts"].items()}
K, A = HOSTS["K"]["name"], HOSTS["A"]["name"]


class Topic(BaseModel):
    id: str
    title: str
    idea: str


def strategy() -> dict:
    return json.loads((HERE / "strategy.json").read_text(encoding="utf-8"))


class Plan(BaseModel):
    topic: Topic = Field(description="The next episode. id: leave as given; title: a short Traditional Chinese "
                                     "title; idea: the one thing the episode makes clear, 1-3 sentences")
    reason: str = Field(description="Why this topic now, in Traditional Chinese, 2-4 sentences: what the history "
                                    "and feedback show and whether this episode builds on, repairs, or explores")
    notes: str = Field(description="The updated running strategy notes in Traditional Chinese, at most 15 short "
                                   "lines: what has been covered, what listeners should already know, what to "
                                   "try or avoid next. Replaces the previous notes")


PLAN_SYSTEM = """你是 podcast《{show}》的節目策劃。這個節目沒有固定的一季清單，每一集開工前由你決定下一集講什麼。你的做法本身就是節目要講的理念：看過去的紀錄和回饋，在「延續有效的方向」和「試一個新的方向」之間取捨，一步一步調整節目的經營策略。

節目要傳達的理念：{theme}
為什麼做這個節目：{why}

原則（必須遵守）：
{principles}

可以參考的方向（不是清單，不必照順序，也可以提出新的）：{ideas}

決定時：
- 回饋裡越新的意見越優先，回饋和原則都比上一次的策略筆記優先。
- 不要重複已經講過的概念，除非是刻意回頭補強，並在 reason 說明。
- 這一集要建立在聽眾已經聽過的內容上，不要跳過還沒講的基礎。"""


def history(d: Path | None) -> tuple[list[dict], str]:
    """Earlier episodes' meta.json files under d (one folder per release) and the newest strategy notes."""
    if not d or not d.is_dir():
        return [], ""
    # Only planned episodes count: the early demos written from a fixed list are left out
    found = sorted(((m, f.parent) for f in d.glob("*/meta.json")
                    if "plan_reason" in (m := json.loads(f.read_text(encoding="utf-8")))),
                   key=lambda mf: mf[0].get("created", ""))
    notes = next((f.read_text(encoding="utf-8") for _, p in reversed(found) if (f := p / "strategy.md").exists()), "")
    return [m for m, _ in found], notes


def plan_prompt(st: dict) -> str:
    return PLAN_SYSTEM.format(show=SHOW, theme=st["theme"], why=st["why"],
                              principles="\n".join(f"- {p}" for p in st["principles"]),
                              ideas="、".join(st.get("ideas", [])))


def plan(hist_dir: Path | None = None, request: str = "") -> Plan:
    st = strategy()
    metas, notes = history(hist_dir)
    feedback = (HERE / "feedback.md").read_text(encoding="utf-8") if (HERE / "feedback.md").exists() else ""
    n = len({m.get("title") for m in metas}) + 1
    past = "\n".join(f"- {m.get('created', '')[:10]}《{m.get('title')}》概念：{m.get('topic', {}).get('title')}；"
                      f"帶走的一句話：{m.get('one_liner', '')}" for m in metas) or "（還沒有任何一集）"
    text = (f"已經做過的集數：\n{past}\n\n上一次的策略筆記：\n{notes or '（沒有）'}\n\n回饋：\n{feedback or '（沒有）'}"
            + (f"\n\n這次的指定要求（優先）：{request}" if request else "")
            + f"\n\n請決定第 {n} 集。topic.id 填 ep{n:02d}。")
    p = llm.ask(Plan, plan_prompt(st), text)
    p.topic.id = f"ep{n:02d}"
    return p


class Line(BaseModel):
    spk: Literal["K", "A"] = Field(description="K = Una, A = Natasha")
    text: str = Field(description="What is spoken, Traditional Chinese as used in Taiwan, written for "
                                  "text-to-speech, at most 120 characters")


class Episode(BaseModel):
    title: str = Field(description="Episode title in Traditional Chinese, at most 24 characters")
    one_liner: str = Field(description="The one idea a listener should walk away with, one sentence")
    lines: list[Line] = Field(description="The whole episode in order")
    description: str = Field(description="Show notes in Traditional Chinese, 3-5 sentences")
    examples: list[str] = Field(description="Each example or scenario used in the episode, one short phrase "
                                            "each, marked 假設 if it is a made-up illustration")


SYSTEM = """你在寫台灣中文 podcast《{show}》的一集。節目只有聲音，就是兩個朋友在聊天，大約 15 到 20 分鐘。

節目要傳達的理念：{theme}。人的直覺一次只看得到兩三個變數，資料可以同時看幾百個；能在這麼多維度裡快速探索、\
找到人想不到的組合，才是資料科學真正的力量。只是把固定規則做得更快的自動化（例如照腳本回答的客服機器人）\
是規則自動化；讓系統自己在大量組合裡一直搜尋、一直調整的，才是探索自動化。這個節目是一檔理念節目：\
每集把一個概念講透，讓聽眾換一種方式看待資料和 AI。不是教學課、不是問答服務，也不是論文介紹。

這一集的概念：「{title}」。要講清楚的核心：{idea}

怎麼講：
1. 開場：{k}用一個日常、具體的畫面帶出今天的概念，一兩句帶到節目，像朋友打招呼一樣自然。不要從「老闆的煩惱」開始。
2. 先讓直覺說話：用一兩個變數的想法去理解這個情境，聽起來很合理。
3. 展開維度（招牌段落）：一次加一個維度，讓聽眾聽到結論怎麼跟著變，直到直覺跟不上。用聲音就聽得懂的比喻，\
例如房間、地圖、調音台的旋鈕、找路，不要用需要看圖才懂的說法。
4. 把概念說清楚：用白話定義，再講一個常見的誤解，以及它錯在哪。
5. 這和自動化的關係：這個概念放進一個持續運作的系統裡，會變成什麼樣子；是探索自動化還是規則自動化。\
可以舉不同領域的例子（生活、零售、餐飲、製造、交通、醫療排班、內容平台等），生意情境只是其中一種例子。
6. 有來有往的討論：兩人可以有不同看法，例如{k}覺得經驗也很重要，{a}同意經驗在什麼時候有用、什麼時候會騙人。\
讓討論有張力，但最後回到同一個理解。
7. 收尾：一句帶得走的想法，說節目會繼續從不同角度談同一個理念（不要承諾具體的下一集題目）。

兩個人：{k}{k_persona}；{a}{a_persona}。\
她們是朋友，沒有主持人和專家之分，不要用職稱介紹彼此；兩人輪流發問、輪流解釋，常互相接話、補充、反駁，不是一問一答。\
要淺：聽眾沒有統計背景，一集只講懂一件事，不用公式和符號，術語能不用就不用。

事實的規則（最重要）：
- 不要引用任何具體的研究、論文、調查、統計數字或百分比，也不要說「研究顯示」「有數據指出」。
- 不要說出任何真實公司、品牌、產品或真實人物的具體做法、數字或內部細節；也不要編造任何人說過的話。\
可以用泛稱，例如「影音平台」「連鎖超商」「外送平台」。
- 需要數字時，只能用明確標示為假設的情境（「假設一家店有……」「舉個例子，如果……」），而且數字要簡單、合理。
- 數學和統計的概念要正確，例如組合數怎麼成長、巧合為什麼會出現、相關不等於因果，不要為了好懂而講錯。

語言規則：台灣用語、繁體中文、口語。句子要短，有來有往；多數句子在 40 字以內，偶爾到 100 字。\
寫給語音合成讀：不要表情符號、括號、項目符號、網址、英文縮寫堆疊；百分比寫成「百分之 30」；\
必要的英文術語第一次出現時用中文解釋。全集口語字數 {min_c} 到 {max_c} 字（不含標點），{min_l} 到 {max_l} 句，{k}開場。\
不開涉及真實人物、政治、族群、悲劇的玩笑。"""

CHECK_SYSTEM = """你負責查核一集中文理念型 podcast 的腳本。這集沒有參考文獻，所以任何具體的事實宣稱都沒有出處。\
列出每一個實質問題：
- 概念錯誤：數學、統計、機器學習、資料科學的觀念講錯，或為了好懂而簡化到變成錯的；
- 編造或無出處的具體事實：引用研究、調查、統計數字、百分比；真實公司、品牌、產品或人物的具體做法或數字；\
任何人說過的話；
- 情境裡出現具體數字，卻沒有明確標示是假設或舉例；
- 誹謗、仇恨、色情、政治立場，或嘲笑真實人物或族群的內容。
泛稱的常識（例如「影音平台會推薦你可能喜歡的影片」）不算問題。明確標示為假設的情境不算問題。\
不要挑字詞或風格。沒有實質問題就回傳空清單。"""


class Check(BaseModel):
    problems: list[str] = Field(description="Each material problem: quote the line and say what is wrong. "
                                            "Empty if none")


class Fix(BaseModel):
    episode: Episode


def spoken_chars(ep: Episode) -> int:
    return sum(len(re.sub(r"[\s，。？！、；：「」『』…—,.?!;:\"']", "", l.text)) for l in ep.lines)


def validate(ep: Episode) -> list[str]:
    errs = []
    n = spoken_chars(ep)
    if not MIN_CHARS <= n <= MAX_CHARS:
        errs.append(f"spoken length is {n} characters; it must be {MIN_CHARS}-{MAX_CHARS}")
    if not MIN_LINES <= len(ep.lines) <= MAX_LINES:
        errs.append(f"{len(ep.lines)} lines; use {MIN_LINES}-{MAX_LINES}")
    if {l.spk for l in ep.lines} != {"K", "A"}:
        errs.append("both hosts must speak")
    if ep.lines and ep.lines[0].spk != "K":
        errs.append("K opens the episode")
    for i, l in enumerate(ep.lines):
        if len(l.text) > 140:
            errs.append(f"line {i} is too long for one breath ({len(l.text)} characters)")
        if re.search(r"[\U0001F300-\U0001FAFF()\[\]（）]|https?://", l.text):
            errs.append(f"line {i} has emoji, brackets or a URL, which TTS reads badly")
        if re.search(r"研究(顯示|發現|指出)|調查(顯示|發現|指出)|數據(顯示|指出)", l.text):
            errs.append(f"line {i} cites research or data the show cannot source; drop it or make it a labelled "
                        "hypothetical")
    return errs


def system_prompt(topic: Topic, theme: str) -> str:
    return SYSTEM.format(show=SHOW, k=K, a=A, k_persona=HOSTS["K"]["persona"], a_persona=HOSTS["A"]["persona"],
                         theme=theme, title=topic.title, idea=topic.idea, min_c=MIN_CHARS,
                         max_c=MAX_CHARS, min_l=MIN_LINES, max_l=MAX_LINES)


def write(topic: Topic, theme: str) -> tuple[Episode, int]:
    system = system_prompt(topic, theme)
    ep = llm.ask(Episode, system, "請寫這一集。")
    for round_ in range(3):
        errs = validate(ep)
        problems = [] if errs else llm.ask(Check, CHECK_SYSTEM, "腳本：\n" + ep.model_dump_json()).problems
        if not errs and not problems:
            print(f"Script passed checks ({spoken_chars(ep)} characters, {len(ep.lines)} lines, "
                  f"round {round_})", flush=True)
            return ep, round_
        print(f"Script round {round_}: {len(errs)} format and {len(problems)} check problems; rewriting",
              flush=True)
        ep = llm.ask(Fix, system, "目前的腳本：\n" + ep.model_dump_json()
                     + "\n\n修正下面每一個問題，其他沒問題的地方不要改：\n- " + "\n- ".join(errs + problems)).episode
    if errs := validate(ep):
        raise SystemExit("Script still has format problems after 3 rewrites: " + "; ".join(errs))
    if problems := llm.ask(Check, CHECK_SYSTEM, "腳本：\n" + ep.model_dump_json()).problems:
        raise SystemExit(f"Script still fails the check after 3 rewrites ({len(problems)} problems)")
    return ep, 3


def to_show(ep: Episode, topic: Topic) -> dict:
    """The saved script: [speaker, text, options] rows, in the same shape as podcast/episodes."""
    return {"show": SHOW, "title": ep.title, "lang": "zh", "hosts": HOSTS, "style": CAST.get("style", ""), "cards": {},
            "paper": {"title": topic.title, "venue": SHOW, "authors": "", "doi": ""},
            "lines": [[l.spk, l.text.strip(), {"gap": 0.35}] for l in ep.lines]}


def script_md(ep: Episode, topic: Topic) -> str:
    names = {k: h["name"] for k, h in HOSTS.items()}
    body = "\n\n".join(f"**{names[l.spk]}**：{l.text}" for l in ep.lines)
    ex = "\n".join(f"  - {e}" for e in ep.examples)
    return (f"# {SHOW}｜{ep.title}\n\n{ep.description}\n\n- 概念：{topic.title}（{topic.id}）\n"
            f"- 帶走的一句話：{ep.one_liner}\n- 用到的例子：\n{ex}\n- 口語字數：{spoken_chars(ep)}，"
            f"{len(ep.lines)} 句\n\n---\n\n{body}\n")


def make(hist_dir: Path | None = None, request: str = "") -> Path:
    p = plan(hist_dir, request)
    topic, theme = p.topic, strategy()["theme"]
    print(f"Topic: {topic.id} {topic.title}", flush=True)
    ep, rounds = write(topic, theme)
    now = datetime.now(timezone.utc)
    out = OUT / f"{now:%Y%m%d-%H%M}-{topic.id}"
    out.mkdir(parents=True, exist_ok=True)
    (out / "show.json").write_text(json.dumps(to_show(ep, topic), ensure_ascii=False, indent=1) + "\n",
                                   encoding="utf-8")
    (out / "script.md").write_text(script_md(ep, topic), encoding="utf-8")
    meta = {"topic": topic.model_dump(), "created": now.isoformat(timespec="seconds"), "title": ep.title,
            "one_liner": ep.one_liner, "description": ep.description, "examples": ep.examples,
            "chars": spoken_chars(ep), "lines": len(ep.lines), "rewrite_rounds": rounds, "model": llm.MODEL}
    (out / "plan.md").write_text(f"# 第 {topic.id[2:]} 集的決定\n\n**{topic.title}**：{topic.idea}\n\n{p.reason}\n",
                                 encoding="utf-8")
    (out / "strategy.md").write_text(p.notes.strip() + "\n", encoding="utf-8")
    meta["plan_reason"] = p.reason
    (out / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"EP_DIR={out}", flush=True)
    return out


def main() -> None:
    ap = argparse.ArgumentParser(prog="python -m concept_show")
    ap.add_argument("cmd", choices=["make", "plan", "voice"])
    ap.add_argument("files", nargs="*", help="voice: <show.json> <out.wav>")
    ap.add_argument("--history", type=Path, help="folder with one sub-folder per earlier episode (meta.json, "
                                                 "strategy.md)")
    ap.add_argument("--request", default="", help="an instruction for this episode's topic, e.g. a concept to cover")
    a = ap.parse_args()
    if a.cmd == "voice":
        from . import voice
        voice.main(*a.files)
    elif a.cmd == "plan":
        p = plan(a.history, a.request)
        print(f"{p.topic.id} {p.topic.title}\n{p.topic.idea}\n\n{p.reason}\n\n{p.notes}")
    else:
        make(a.history, a.request)
