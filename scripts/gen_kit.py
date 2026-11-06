#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_kit.py —— 口播脚本 JSON → 内容包 / 投喂包

一次产出两套交付物：
    内容包/   md，给人看（分镜表、双对照、画面提示词、卡片规格、验收）
    投喂包/   txt，给模型吃（无 markdown、分区块，可直接整段粘贴）

镜头数、每镜秒数、语速、人物设定、配色、标注文案全部从库内 `config` 读取，
代码里不含任何形态与行业预设。

用法：
    python gen_kit.py --lib scripts_lib.json --out ./交付
    python gen_kit.py --lib scripts_lib.json --out ./交付 --only S01,S07
    python gen_kit.py --lib scripts_lib.json --out ./交付 --no-feed     # 只要内容包
"""
import argparse
import json
import os
import re

CFG = {}


def cfg(path, default=None):
    cur = CFG
    for k in path.split("."):
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur if cur not in (None, "") else default


SEG = 2.0                       # 每镜基准秒数（main 里按 config 覆盖）
RATE = 3.6                      # 语速，音节/秒（main 里按 config 覆盖）
ACCENT = "#FACC15"              # 强调色（main 里按 config 覆盖）

SHOT_ZH = {
    "close": "近景，胸部以上，脸占画面上三分之一",
    "half": "半身，腰部以上",
    "gest": "半身，腰部以上，双手在身前自然比划",
}
SHOT_EN = {
    "close": "medium close-up, chest and up, face occupying about one third of the frame",
    "half": "medium shot from the waist up",
    "gest": "medium shot from the waist up, hands gesturing naturally in front of the body",
}
MOVE_ZH = {"in": "镜头缓慢推近", "out": "镜头缓慢拉远", "in2": "镜头轻微推近", "out2": "镜头轻微拉远"}
MOVE_EN = {"in": "slow dolly in", "out": "slow dolly out", "in2": "subtle push in", "out2": "subtle pull out"}

PERF_ZH = [
    "直视镜头，表情认真，像在提一个开场问题",
    "略微侧身，像在解释一件事",
    "一只手抬起比划，说到关键处",
    "点头强调，语气肯定",
    "看向镜头，放松地微笑收尾",
]
PERF_EN = [
    "looking straight into the lens, serious, opening a question",
    "slightly turned, as if explaining something",
    "one hand raised in a gesture, making a key point",
    "nodding for emphasis, confident tone",
    "looking at the camera, relaxed smile to close",
]

# 缺省人物/场景设定：故意留空占位，由 config.render.character_zh / _en 填入
CHAR_DEFAULT_ZH = "（在此填写人物与场景：人物年龄气质、服装、环境、光线、画幅。整片保持一致。无字幕，无水印。）"
CHAR_DEFAULT_EN = ("(describe the person and scene here: age and presence, wardrobe, setting, lighting, "
                   "aspect ratio. Keep identical across the whole video. No subtitles, no watermark.)")

TYPE_ZH = {
    "convert": "转化（指向主页链接）", "follow": "涨粉（指向关注）", "engage": "互动（指向评论）",
    "save": "收藏（指向保存）", "trust": "建信任（不推销）", "flow": "流程演示（收藏）",
    "science": "科普纠错（收藏/关注）", "compare": "横评（评论引流）",
}


def card_rule(kind):
    """卡片排版规格。颜色取 config.render.accent_color。"""
    return {
        "bigword": ("大字卡", f"主词占屏宽 82%，字号拉到刚好放满一行为止（约 200–240px）；"
                             f"副行 96px、强调色 {ACCENT}；主词纯白；整体垂直居中偏上 120px。"),
        "list": ("列表卡", f"标题 64px 强调色 {ACCENT}，居中，距顶部 300px；三条条目各 120px 纯白，左对齐，"
                          f"行距 200px，条目前加 8px 强调色竖条。"),
        "strike": ("划线否定卡", "上词纯白 140px，其上叠加 12px 红色 #EF4444 横线（贯穿整词）；"
                              f"下词强调色 {ACCENT} 120px；叉号置于顶部居中，不压字。"),
        "check": ("勾选清单卡", f"标题 64px 强调色 {ACCENT} 居中，距顶 300px；三条各 110px 纯白，"
                              f"条目前置强调色方框勾号，左对齐，行距 190px。"),
        "compare": ("左右对比卡", f"左右两栏各占 44% 宽，中间留 6% 间隔；栏标题 72px 强调色 {ACCENT}；"
                               "正文 64px 纯白，左栏顶部加灰色标签、右栏加强调色标签。"),
    }[kind]


def card_bg():
    return cfg("render.card_bg", "竖向渐变 #0F172A → #1E293B，叠 4% 白细网格；安全区上下各留 220px（避开平台顶部与底部 UI）。")


def banned_tail():
    return cfg("render.banned_tail", "合规词表中的禁用词")


def char_zh():
    return cfg("render.character_zh", CHAR_DEFAULT_ZH)


def char_en():
    return cfg("render.character_en", CHAR_DEFAULT_EN)


def overlay():
    return cfg("compliance.required_overlay", "")


# ── 基础工具 ────────────────────────────────────────────────
def syl(text):
    return len([w for w in re.split(r"\s+", (text or "").strip()) if w])


def net_seconds(s):
    return sum(syl(x.get("say1")) for x in s["segments"] if not x.get("card")) / RATE


def zh_of(s):
    """逐句对照。优先用 zh_lines，没有就退回 voiceover_zh，仍没有就留空。"""
    z = s.get("zh_lines")
    if z:
        return z
    v = s.get("voiceover_zh")
    return [v] if v else []


def srt_time(t):
    h, m, sec = int(t // 3600), int((t % 3600) // 60), t % 60
    return f"{h:02d}:{m:02d}:{int(sec):02d},{int(round((sec - int(sec)) * 1000)):03d}"


def shot_list(segs, want_card):
    """返回卡片镜或人像镜的镜号列表，用于标题里动态写「第 x／y 镜」。"""
    idx = [i for i, g in enumerate(segs, 1) if bool(g.get("card")) == want_card]
    return "／".join(str(i) for i in idx) if idx else "无"


def card_brief_zh(card):
    k = card["kind"]
    if k == "bigword":
        return f"**{card.get('a','')}** ／ {card.get('b','')}"
    if k == "strike":
        return f"~~{card.get('a','')}~~ → {card.get('b','')}"
    items = "；".join(str(x) for x in (card.get("items") or []))
    if card.get("left") or card.get("right"):
        return f"{card.get('left','')} ⇄ {card.get('right','')}"
    return f"{card.get('title','')}｜{items}" if card.get("title") else items


def card_lines(card):
    k = card["kind"]
    if k == "bigword":
        return [("主行（超大，纯白）", card.get("a", "")), ("副行（强调色）", card.get("b", ""))]
    if k == "strike":
        return [("被否定（纯白＋红划线）", card.get("a", "")), ("替代（强调色）", card.get("b", ""))]
    if k == "compare":
        return [("左栏", card.get("left", "")), ("右栏", card.get("right", ""))]
    out = []
    if card.get("title"):
        out.append(("标题（强调色）", card["title"]))
    for i, it in enumerate(card.get("items") or [], 1):
        out.append((f"第 {i} 条（纯白）", str(it)))
    return out


def card_prompt_zh(card):
    k = card["kind"]
    bg = "纯色渐变底，无人物"
    if k == "bigword":
        return (f"{bg}，无背景装饰。画面中央两行大字：第一行「{card.get('a','')}」（纯白，超大，占屏宽约 82%）；"
                f"第二行「{card.get('b','')}」（强调色 {ACCENT}）。字体为无衬线粗体，声调符号完整清晰。")
    if k == "strike":
        return (f"{bg}。画面上方「{card.get('a','')}」为纯白大字，其上叠加一条粗红色横线贯穿整词（表示否定）；"
                f"下方「{card.get('b','')}」为强调色 {ACCENT}。无衬线粗体。")
    if k == "compare":
        return (f"{bg}。左右两栏对比：「{card.get('left','')}」在左、「{card.get('right','')}」在右，"
                f"均为纯白无衬线粗体，栏标题用强调色 {ACCENT}。")
    items = "；".join(str(x) for x in (card.get("items") or []))
    style = "每条前置强调色竖条" if k == "list" else "每条前置强调色方框勾号"
    return (f"{bg}。顶部标题「{card.get('title','')}」为强调色 {ACCENT}；下方三行条目分别为「{items}」，"
            f"纯白色，{style}，左对齐。无衬线粗体，声调符号完整清晰。")


def card_prompt_en(card):
    k = card["kind"]
    bg = "Flat dark gradient background, no people"
    if k == "bigword":
        return (f"{bg}, no decoration. Two large centred lines: line one \"{card.get('a','')}\" pure white, extra large, "
                f"about 82% of frame width; line two \"{card.get('b','')}\" accent {ACCENT}. "
                "Bold sans-serif, diacritics fully legible.")
    if k == "strike":
        return (f"{bg}. Upper word \"{card.get('a','')}\" pure white large type with a thick red strike-through; "
                f"lower word \"{card.get('b','')}\" accent {ACCENT}. Bold sans-serif.")
    if k == "compare":
        return (f"{bg}. Two columns: \"{card.get('left','')}\" left, \"{card.get('right','')}\" right, "
                f"pure white bold sans-serif, column titles in accent {ACCENT}.")
    items = "; ".join(str(x) for x in (card.get("items") or []))
    return (f"{bg}. Title \"{card.get('title','')}\" accent {ACCENT}; three lines below: \"{items}\", "
            "pure white, left aligned. Bold sans-serif, diacritics fully legible.")


# ── 内容包（md，给人看） ────────────────────────────────────
def content_md(s):
    segs, zh = s["segments"], zh_of(s)
    net = net_seconds(s)
    vi_lines, rows = [], []
    n_card = sum(1 for g in segs if g.get("card"))
    n_p = len(segs) - n_card

    for i, g in enumerate(segs, 1):
        t0, t1 = (i - 1) * SEG, i * SEG
        if g.get("card"):
            rows.append((i, f"{t0:.1f}–{t1:.1f}s", f"图文卡 · {card_rule(g['card']['kind'])[0]}", "静止", "—", "—", "—"))
            continue
        sub = " ⏎ ".join(x for x in (g.get("l1", ""), g.get("l2", "")) if x)
        say = g.get("say1", "")
        z = zh[len(vi_lines)] if len(vi_lines) < len(zh) else ""
        if say:
            vi_lines.append(say)
        rows.append((i, f"{t0:.1f}–{t1:.1f}s", f"人像 · {SHOT_ZH[g['img']]}", MOVE_ZH[g["move"]],
                     sub or "—", say or "—", z or "—"))

    L = [f"# {s['id']} · {s['topic_vi']}", "",
         f"- **中文选题**：{s['topic_zh']}",
         f"- **内容支柱**：{s['pillar']}",
         f"- **目标**：{TYPE_ZH.get(s['type'], s['type'])}",
         f"- **核心角度**：{s.get('angle_zh','')}",
         f"- **成片规格**：{cfg('render.canvas','1080×1920')} 竖屏 ／ {len(segs)} 镜 × {SEG:.1f} 秒 ／ "
         f"人像 {n_p} 段 + 图文卡 {n_card} 张", "",
         "> 本文件只有内容：口播、分镜、画面提示词、卡片文字、发布信息。",
         "> 配音与成片在外部工具完成，统一标准见 `00_制作要求书.md`。", "", "---", "",
         "## 一、口播稿", "",
         f"整条 **{sum(syl(x) for x in vi_lines)} 个音节**，按 {RATE} 音节/秒念完约 **{net:.1f} 秒**；"
         f"成片建议 **{net + 1.5:.0f} 秒**，不要为凑时长放慢语速。", "",
         "**整段（录音／TTS 直接读这段）**：", "", "> " + " ".join(vi_lines), "",
         "**逐句（按镜头槽位断句）**：", "",
         "| # | 对应镜头 | 原文 | 中文意思 | 音节 |", "|---|---|---|---|---|"]
    k = 0
    for i, g in enumerate(segs, 1):
        if g.get("card") or not g.get("say1"):
            continue
        k += 1
        L.append(f"| {k} | 第 {i} 镜 | {g['say1']} | {zh[k-1] if k-1 < len(zh) else '（缺中文对照，请补 zh_lines）'} | {syl(g['say1'])} |")
    L += ["", "> 断句：逗号停 0.15 秒，句号停 0.25 秒。首尾两镜各只有一镜时长，不要在那里加词。", "", "---", "",
          "## 二、分镜表", "",
          "| 镜 | 时间码 | 画面 | 运镜 | 屏幕字幕 | 口播 | 中文意思 |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append("| " + " | ".join(str(x) for x in r) + " |")
    L += ["", f"> 时间码按「每镜 {SEG:.1f} 秒」基准。**成片总长以口播为准**，按比例缩放；"
              "硬约束只有一条：卡片镜不要压到 1 秒以下。",
          "> 字幕与口播解耦：字幕只放关键词，口播走完整整句。",
          "> 卡片镜不放字幕——画面本身即信息。", "", "---", "",
          f"## 三、人像镜头提示词（第 {shot_list(segs, False)} 镜）", "",
          (f"{n_p} 段都用**同一份人物设定**做图生视频，服装、发型、背景、光位不得改动，否则剪辑时会跳。" if n_p else "本片无人像镜头。"), ""]
    pi = 0
    for i, g in enumerate(segs, 1):
        if g.get("card"):
            continue
        pz, pe = PERF_ZH[pi % len(PERF_ZH)], PERF_EN[pi % len(PERF_EN)]
        pi += 1
        t0, t1 = (i - 1) * SEG, i * SEG
        L += [f"### 第 {i} 镜 · {t0:.1f}–{t1:.1f}s　｜　口播：{g.get('say1','')}", "",
              "**中文提示词**", "", "```",
              f"{char_zh()}\n景别：{SHOT_ZH[g['img']]}。\n表演：{pz}。\n运镜：{MOVE_ZH[g['move']]}。\n"
              f"时长 {SEG:.1f} 秒（工具只给更长就按更长生成，剪辑时截取）。", "```", "",
              "**English prompt**", "", "```",
              f"{char_en()}\nShot: {SHOT_EN[g['img']]}. Performance: {pe}.\nCamera: {MOVE_EN[g['move']]}.\n"
              f"{SEG:.1f} seconds.", "```", ""]

    L += ["---", "", f"## 四、卡片文字（第 {shot_list(segs, True)} 镜）", "", f"统一底色：{card_bg()}", ""]
    cn = 0
    for i, g in enumerate(segs, 1):
        if not g.get("card"):
            continue
        cn += 1
        c, t0 = g["card"], (i - 1) * SEG
        kind, rule = card_rule(c["kind"])
        L += [f"### 卡 {cn} · 第 {i} 镜 · {t0:.1f}–{t0+SEG:.1f}s · {kind}", "", "| 元素 | 文字 |", "|---|---|"]
        for label, txt in card_lines(c):
            L.append(f"| {label} | {txt} |")
        L += ["", f"排版：{rule}", ""]

    L += ["---", "", "## 五、发布信息", "",
          f"**标题**：{s['title']}", "",
          f"**Hashtag**（{len(s['hashtags'])} 个，上限 {cfg('compliance.max_hashtags', 5)}）：{' '.join(s['hashtags'])}", "",
          "**Caption**（复制进发布框）：", "", "```",
          s["title"], "", " ".join(vi_lines), "", " ".join(s["hashtags"]), "```", "",
          "---", "", "## 六、验收清单", "",
          f"- [ ] {cfg('render.canvas','1080×1920')} 竖屏，无黑边、无拉伸；时长 {net + 0.8:.0f}–{net + 2.5:.0f} 秒",
          f"- [ ] {n_p} 个人像段的衣服、发型、背景、光位完全一致，切换时人不跳",
          "- [ ] 口播与字幕文字一致",
          f"- [ ] {sum(syl(x) for x in vi_lines)} 个音节全部念完，最后一句没有被切掉",
          f"- [ ] {n_card} 张卡片文字与第四节逐字一致（大小写、声调符号不能错）",
          "- [ ] 卡片在画面上停留 ≥ 1.5 秒",
          f"- [ ] 全片无 {banned_tail()}"]
    if overlay():
        L.append(f"- [ ] 画面常驻 `{overlay()}` 标识")
    L.append("")
    if s.get("note_zh"):
        L += ["---", "", "## 制作备注", "", s["note_zh"], ""]
    return "\n".join(L)


# ── 投喂包（txt，给模型） ───────────────────────────────────
def prompt_zh(s):
    net = net_seconds(s)
    segs = s["segments"]
    L = [f"# {s['id']}　{s['topic_vi']}", f"# 中文选题：{s['topic_zh']}", "",
         "═" * 60, "【角色设定｜所有镜头通用，不要改】", "═" * 60, char_zh(), "",
         "═" * 60, "【分镜｜逐镜生成时，每镜都带上上面的角色设定】", "═" * 60, ""]
    pi = 0
    for i, g in enumerate(segs, 1):
        t0, t1 = (i - 1) * SEG, i * SEG
        if g.get("card"):
            L += [f"—— 镜头 {i}｜{t0:.1f}–{t1:.1f}s｜图文卡（无人物）——", card_prompt_zh(g["card"]), ""]
            continue
        L += [f"—— 镜头 {i}｜{t0:.1f}–{t1:.1f}s｜人像 ——",
              f"景别：{SHOT_ZH[g['img']]}。",
              f"动作与表情：{PERF_ZH[pi % len(PERF_ZH)]}。",
              f"运镜：{MOVE_ZH[g['move']]}。",
              f"台词（口型需同步）：{g.get('say1','')}", ""]
        pi += 1
    L += ["═" * 60, "【整条一次性生成版｜工具支持多镜头时用这段】", "═" * 60,
          f"一条约 {net:.0f} 秒竖屏短视频，共 {len(segs)} 个镜头，单镜约 {SEG:.1f} 秒"
          "（以台词念完为准，不要为凑时长放慢语速）。", "",
          char_zh() + "全片同一人物、同一服装、同一场景、同一光位，不得变化。", ""]
    pi = 0
    for i, g in enumerate(segs, 1):
        if g.get("card"):
            L.append(f"{i}. 图文卡，深色渐变底，{card_brief_zh(g['card'])}。无人物。")
        else:
            L.append(f"{i}. 人像，{SHOT_ZH[g['img']]}，{PERF_ZH[pi % len(PERF_ZH)]}，{MOVE_ZH[g['move']]}。"
                     f"台词：{g.get('say1','')}")
            pi += 1
    L += ["", "═" * 60, "【技术参数】", "═" * 60,
          f"画幅 {cfg('render.canvas','1080×1920')}｜25 或 30 fps｜总长以口播为准，约 {net:.0f} 秒｜无字幕｜无水印",
          f"口播语言：{cfg('render.speech_lang','越南语 vi-VN')}，"
          f"{cfg('render.voice','男声，中低音，语速偏慢')}，每句之间留 0.2 秒停顿。", ""]
    return "\n".join(L)


def prompt_en(s):
    net = net_seconds(s)
    segs = s["segments"]
    L = [f"# {s['id']}　{s['topic_vi']}", f"# Topic (CN): {s['topic_zh']}", "",
         "=" * 60, "[ CHARACTER — keep identical in every shot ]", "=" * 60, char_en(), "",
         "=" * 60, "[ SHOTS — prepend the character block to each shot ]", "=" * 60, ""]
    pi = 0
    for i, g in enumerate(segs, 1):
        t0, t1 = (i - 1) * SEG, i * SEG
        if g.get("card"):
            L += [f"-- Shot {i} | {t0:.1f}-{t1:.1f}s | text card, no character --", card_prompt_en(g["card"]), ""]
            continue
        L += [f"-- Shot {i} | {t0:.1f}-{t1:.1f}s | character --",
              f"Shot size: {SHOT_EN[g['img']]}.",
              f"Action and expression: {PERF_EN[pi % len(PERF_EN)]}.",
              f"Camera: {MOVE_EN[g['move']]}.",
              f"Dialogue (lip-sync required): {g.get('say1','')}", ""]
        pi += 1
    L += ["=" * 60, "[ SINGLE-PASS VERSION — for multi-shot models ]", "=" * 60,
          f"A roughly {net:.0f}-second vertical short video, {len(segs)} shots of about {SEG:.1f} seconds each.", "",
          char_en(), "Same person, same wardrobe, same room, same lighting in every shot.", ""]
    pi = 0
    for i, g in enumerate(segs, 1):
        if g.get("card"):
            L.append(f"{i}. Text card, dark gradient, {card_brief_zh(g['card'])}. No people.")
        else:
            L.append(f"{i}. Character shot, {SHOT_EN[g['img']]}, {PERF_EN[pi % len(PERF_EN)]}, "
                     f"{MOVE_EN[g['move']]}. Dialogue: {g.get('say1','')}")
            pi += 1
    L += ["", "=" * 60, "[ TECHNICAL ]", "=" * 60,
          f"{cfg('render.canvas','1080×1920')} vertical | 25 or 30 fps | no subtitles | no watermark",
          f"Spoken language: {cfg('render.speech_lang_en','Vietnamese (vi-VN)')}, "
          f"{cfg('render.voice_en','male, low-mid register, unhurried')}.", ""]
    return "\n".join(L)


def voice_txt(s):
    lines = []
    for i, g in enumerate(s["segments"], 1):
        if not g.get("card") and g.get("say1"):
            lines.append(((i - 1) * SEG, i * SEG, g["say1"], i))
    n = sum(syl(x[2]) for x in lines)
    L = [f"# {s['id']}　{s['topic_vi']}", "",
         "═" * 60, "【整条口播】", "═" * 60,
         " ".join(x[2] for x in lines), "",
         f"共 {n} 个音节，按 {RATE} 音节/秒念完约 {n / RATE:.1f} 秒。", "",
         "═" * 60, "【逐句｜按镜头断句】", "═" * 60]
    for k, (a, b, t, i) in enumerate(lines, 1):
        L += [f"{k}. 第 {i} 镜（{a:.1f}–{b:.1f}s，{syl(t)} 音节）", t, ""]
    L += ["═" * 60, f"【字幕 SRT｜时间码为 {SEG:.1f} 秒/镜基准，按实际口播微调】", "═" * 60, ""]
    k = 0
    for i, g in enumerate(s["segments"], 1):
        if g.get("card"):
            continue
        sub = [x for x in (g.get("l1"), g.get("l2")) if x]
        if not sub:
            continue
        k += 1
        a, b = (i - 1) * SEG, i * SEG
        L += [str(k), f"{srt_time(a)} --> {srt_time(b)}", "\n".join(sub), ""]
    return "\n".join(L)


def all_in_one(s):
    bar = "█" * 60
    body = [
        prompt_zh(s), "", bar, "【附 A：口播与字幕（配音 / 字幕工具用）】", bar, "",
        voice_txt(s).split("\n", 2)[2], "", bar, "【附 B：交付前自查】", bar,
        f"1. {cfg('render.canvas','1080×1920')} 竖屏，无黑边，时长与口播匹配",
        "2. 所有人像段的衣服、发型、背景、光线完全一致",
        "3. 台词全部念完，无截断，声调符号正确",
        "4. 卡片文字与脚本逐字一致（大小写、声调不能错）",
    ]
    if overlay():
        body.append(f"5. 画面常驻 {overlay()}")
    body += [
        f"6. 全片无 {banned_tail()}",
        "7. 首帧不是黑屏（首帧即封面）", "",
    ]
    return "\n".join(body)


# ── 索引 ────────────────────────────────────────────────────
def write_content_index(scripts, out):
    L = ["# 内容包索引", "",
         "| ID | 标题 | 支柱 | 目标 | 净口播 | 成片 |", "|---|---|---|---|---|---|"]
    for s in scripts:
        net = net_seconds(s)
        L.append(f"| [{s['id']}]({s['id']}_脚本.md) | {s['topic_vi']} | {s['pillar']} | "
                 f"{TYPE_ZH.get(s['type'], s['type']).split('（')[0]} | {net:.1f}s | {net + 1.5:.0f}s |")
    L += ["", f"共 {len(scripts)} 条。成片时长 = 净口播 + 1.5 秒；不要为凑固定秒数放慢语速。", ""]
    open(os.path.join(out, "00_清单.md"), "w", encoding="utf-8").write("\n".join(L))


def write_feed_index(scripts, out):
    L = ["# 投喂包索引", "",
         "每条 4 个文件。**只发一个文件给对方 → 发 `SXX_全量投喂.txt`**。", "",
         "| ID | 全量投喂 | 中文提示词 | 英文提示词 | 口播与字幕 |", "|---|---|---|---|---|"]
    for s in scripts:
        i = s["id"]
        L.append(f"| {i} | {i}_全量投喂.txt | {i}_视频提示词_中文.txt | {i}_视频提示词_EN.txt | {i}_口播与字幕.txt |")
    L += ["", "各工具的喂法差异见项目自带说明。", ""]
    open(os.path.join(out, "00_索引.md"), "w", encoding="utf-8").write("\n".join(L))


def main():
    global CFG, SEG, RATE, ACCENT
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", required=True, help="脚本库 JSON 路径")
    ap.add_argument("--out", required=True, help="输出目录")
    ap.add_argument("--only", default="", help="只做这几条，逗号分隔，如 S01,S07")
    ap.add_argument("--config", default="", help="外部 config（JSON），覆盖库内 config")
    ap.add_argument("--no-content", action="store_true")
    ap.add_argument("--no-feed", action="store_true")
    a = ap.parse_args()

    lib = json.load(open(a.lib, encoding="utf-8"))
    CFG = lib.get("config") or {}
    if a.config:
        over = json.load(open(a.config, encoding="utf-8"))
        for k, v in over.items():
            if isinstance(v, dict) and isinstance(CFG.get(k), dict):
                CFG[k] = {**CFG[k], **v}
            else:
                CFG[k] = v
    SEG = float(cfg("structure.segment_seconds", 2.0))
    RATE = float((CFG.get("speech") or {}).get("rate") or 3.6)
    ACCENT = cfg("render.accent_color", "#FACC15")

    scripts = lib["scripts"]
    if a.only:
        keep = {x.strip().upper() for x in a.only.split(",") if x.strip()}
        scripts = [s for s in scripts if s["id"].upper() in keep]
        if not scripts:
            raise SystemExit(f"--only 没匹配到任何条目：{a.only}")

    if not a.no_content:
        d = os.path.join(a.out, "内容包")
        os.makedirs(d, exist_ok=True)
        for s in scripts:
            open(os.path.join(d, f"{s['id']}_脚本.md"), "w", encoding="utf-8").write(content_md(s))
        write_content_index(scripts, d)
        print("内容包 →", d, f"({len(scripts)} 条)")

    if not a.no_feed:
        d = os.path.join(a.out, "投喂包")
        os.makedirs(d, exist_ok=True)
        for s in scripts:
            for name, fn in (("视频提示词_中文", prompt_zh), ("视频提示词_EN", prompt_en),
                             ("口播与字幕", voice_txt), ("全量投喂", all_in_one)):
                open(os.path.join(d, f"{s['id']}_{name}.txt"), "w", encoding="utf-8", newline="\n").write(fn(s))
        write_feed_index(scripts, d)
        print("投喂包 →", d, f"({len(scripts)} 条 × 4 文件)")


if __name__ == "__main__":
    main()
