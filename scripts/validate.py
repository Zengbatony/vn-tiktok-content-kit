#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
validate.py —— 短视频口播脚本质检（结构 / 字幕 / 合规 / 槽位 / 对照）

所有规则都从脚本库里的 `config` 块读取，代码里不含任何行业预设。
换形态（几镜、怎么交替、每秒念几个音节、禁哪些词）只改 config，不动代码。

用法：
    python validate.py --lib scripts_lib.json
    python validate.py --lib scripts_lib.json --banned extra.txt        # 追加禁用词
    python validate.py --lib scripts_lib.json --config cfg.json         # 外部 config 覆盖库内

退出码：0 = 全过；1 = 有 error（修完再出片）；2 = 库文件读不了。
"""
import argparse
import json
import re
import sys
import unicodedata

# config 缺省值：全部中性，不预设任何形态或行业
DEFAULTS = {
    "structure": {"segment_seconds": 2.0, "shot_count": None, "pattern": ""},
    "speech": {"rate": 3.6, "max_text_ratio": 1900, "slot_slack": 1.35},
    "compliance": {
        "banned": [],
        "case_sensitive": [],
        "required_context": [],
        "max_hashtags": 5,
        "required_overlay": "",
        "digit_note_keyword": "",
    },
    "require_zh": False,
}

# 越南语去音标后与禁用词同形、但语义无关的固定搭配。匹配前先中和，否则必假阳性。
# 例：bắt đầu từ（从…开始）→ "bat dau tu" 内含 "dau tu"（đầu tư 投资），两者毫无关系。
NEUTRALIZE = [
    "bat dau tu",
    "bat dau tuong",
    "dau tuong",
]

# 否定词（越南语）。禁用词只出现在否定语境里时语义不违规，降级为提醒。
NEG = ["khong", "chang", "chua", "dung", "dau co", "chả"]


def deep_merge(base, over):
    """两层层级合并：over 覆盖 base，未出现的键保留缺省。"""
    out = {}
    for k, v in base.items():
        if isinstance(v, dict):
            sub = over.get(k) if isinstance(over.get(k), dict) else {}
            out[k] = deep_merge(v, sub)
        else:
            out[k] = over.get(k, v)
    for k, v in over.items():
        out.setdefault(k, v)
    return out


def strip_accents(s):
    s = s.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def norm(s):
    return re.sub(r"\s+", " ", strip_accents(s.lower())).strip()


def syl(text):
    return len([w for w in (text or "").split() if w])


def occurrences(hay, needle):
    if not needle:
        return []
    out, i = [], hay.find(needle)
    while i != -1:
        out.append(i)
        i = hay.find(needle, i + 1)
    return out


def negated(hay, idx, window=16):
    pre = hay[max(0, idx - window):idx]
    return any(n in pre for n in NEG)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", required=True)
    ap.add_argument("--banned", default="", help="额外禁用词文件，一行一个")
    ap.add_argument("--config", default="", help="外部 config（JSON），覆盖库内 config")
    a = ap.parse_args()

    try:
        lib = json.load(open(a.lib, encoding="utf-8"))
    except Exception as e:
        print("❌ 读不了脚本库：", e)
        return 2

    cfg = deep_merge(DEFAULTS, lib.get("config") or {})
    if a.config:
        try:
            cfg = deep_merge(cfg, json.load(open(a.config, encoding="utf-8")))
        except Exception as e:
            print("❌ 读不了 config：", e)
            return 2

    seg_s = float(cfg["structure"].get("segment_seconds") or 2.0)
    shots = cfg["structure"].get("shot_count")
    pattern = (cfg["structure"].get("pattern") or "").upper()
    rate = float(cfg["speech"].get("rate") or 3.6)
    ratio = float(cfg["speech"].get("max_text_ratio") or 1900)
    slack = float(cfg["speech"].get("slot_slack") or 1.35)

    banned = list(cfg["compliance"].get("banned") or [])
    if a.banned:
        banned += [x.strip() for x in open(a.banned, encoding="utf-8") if x.strip()]
    case_sensitive = cfg["compliance"].get("case_sensitive") or []
    ctx_rules = cfg["compliance"].get("required_context") or []
    max_tags = int(cfg["compliance"].get("max_hashtags") or 5)
    overlay = cfg["compliance"].get("required_overlay") or ""
    digit_kw = cfg["compliance"].get("digit_note_keyword") or ""
    require_zh = bool(lib.get("config", {}).get("require_zh", cfg.get("require_zh")))

    scripts = lib["scripts"]
    errors, warns = [], []
    print(f"=== 脚本库 {lib.get('version','?')} · {len(scripts)} 条 ===")
    if not shots and not pattern:
        print("（未在 config.structure 声明 shot_count / pattern，跳过镜头结构校验）")
    if not banned and not ctx_rules:
        print("（未在 config.compliance 配置禁用词，跳过词表校验）")
    print()

    for s in scripts:
        sid = s["id"]
        segs = s["segments"]
        tag = f"[{sid}]"

        # 闸1 结构：镜头数 + 人像(P)/卡片(C) 排列
        if shots and len(segs) != int(shots):
            errors.append(f"{tag} 镜头数 {len(segs)}，config 要求 {shots}")
        pat = "".join("C" if g.get("card") else "P" for g in segs)
        if pattern and pat != pattern:
            errors.append(f"{tag} 排列 {pat}，config 要求 {pattern}")

        # 闸2 字幕：字号 × 字符数 不超屏
        for i, g in enumerate(segs, 1):
            size = g.get("size", 84)
            limit = ratio / size
            for key in ("l1", "l2"):
                t = g.get(key) or ""
                if t and len(t) > limit:
                    errors.append(f"{tag} 段{i} {key} 共 {len(t)} 字符，size={size} 上限 {limit:.0f}：「{t}」")

        # 闸3 卡片镜不宜带字幕
        for i, g in enumerate(segs, 1):
            if g.get("card") and (g.get("l1") or g.get("l2")):
                warns.append(f"{tag} 段{i} 是卡片却带字幕，会稀释冲击")

        # 闸4 词表：整条去音标后匹配（防 diacritic 规避）
        blob = json.dumps(s, ensure_ascii=False)
        nb = norm(blob)
        nb_scan = nb
        for fp in NEUTRALIZE:
            nb_scan = nb_scan.replace(norm(fp), " " * len(fp))
        for w in banned:
            hits = occurrences(nb_scan, norm(w))
            if not hits:
                continue
            if all(negated(nb_scan, i) for i in hits):
                warns.append(f"{tag} 出现「{w}」但处于否定语境（仍会露在画面上，建议改写）")
            else:
                errors.append(f"{tag} 命中禁用词「{w}」")
        for w in case_sensitive:
            if w in blob:
                errors.append(f"{tag} 命中禁用词「{w}」（区分大小写）")

        # 闸4b 语境词：某些词本身合法，但必须落在指定语境里
        for rule in ctx_rules:
            word = norm(rule.get("word") or "")
            if not word or word not in nb_scan:
                continue
            bad = [c for c in (rule.get("conflict_with") or []) if norm(c) in nb_scan]
            good = [c for c in (rule.get("any_of") or []) if norm(c) in nb_scan]
            if bad:
                errors.append(f"{tag} 出现「{rule.get('word')}」且同时命中 {bad}："
                              f"{rule.get('conflict_message') or '判定为违规用法'}")
            elif not good:
                warns.append(f"{tag} 出现「{rule.get('word')}」但缺少语境词 {rule.get('any_of') or []}："
                             f"{rule.get('context_message') or '可能被误判，建议补足语境'}")

        # 闸5 标签：数量上限 + 单个不含空格
        tags = s.get("hashtags", [])
        if len(tags) > max_tags:
            errors.append(f"{tag} hashtag {len(tags)} 个，上限 {max_tags}")
        for t in tags:
            if " " in t.strip():
                errors.append(f"{tag} 标签「{t}」含空格，会被切成无效标签")

        # 闸6 语音槽位：本镜 + 后续连续无文本镜，够不够把这句念完
        has = [bool((g.get("say1") or g.get("l1") or "").strip()) for g in segs]
        for i, g in enumerate(segs):
            if not has[i]:
                continue
            span, j = 1, i + 1
            while j < len(segs) and not has[j]:
                span += 1
                j += 1
            slot = span * seg_s
            text = g.get("say1") or g.get("l1") or ""
            need = syl(text) / rate
            if need > slot * slack:
                warns.append(f"{tag} 段{i+1} 槽位 {slot:.1f}s，需约 {need:.1f}s（{syl(text)} 音节），会被赶或截断")

        # 闸7 对照：每个有口播的镜头都要有对照句（config.require_zh 开启时才查）
        n_vo = sum(1 for g in segs if g.get("say1"))
        zh = s.get("zh_lines") or []
        if require_zh and len(zh) < n_vo:
            errors.append(f"{tag} 有 {n_vo} 句口播，但 zh_lines 只有 {len(zh)} 句对照")

        # 闸8 数字：口播含数字时提示核实
        if re.search(r"\d", " ".join(g.get("say1", "") for g in segs)):
            if digit_kw and digit_kw in (s.get("note_zh") or ""):
                pass
            else:
                warns.append(f"{tag} 口播里有数字，发布前核实依据"
                             + (f"（确认后在 note_zh 标注「{digit_kw}」即可消警）" if digit_kw else ""))

        total = sum(syl(g.get("say1")) for g in segs if not g.get("card")) / rate
        print(f"{tag} {len(segs)}镜 {pat}  净口播 {total:.1f}s  成片约 {total + 1.5:.0f}s  「{s['topic_vi'][:34]}」")

    print("\n" + "=" * 60)
    if errors:
        print(f"❌ 错误 {len(errors)} 项：")
        for e in errors:
            print("  -", e)
    else:
        print("✅ 结构 / 字幕 / 词表 / 标签 / 槽位 / 对照 全部通过")
    if warns:
        print(f"\n⚠️ 提醒 {len(warns)} 项（不阻塞，但建议逐条看）：")
        for w in warns:
            print("  -", w)
    if overlay:
        print(f"\n法定/平台标注：每条须常驻「{overlay}」")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
