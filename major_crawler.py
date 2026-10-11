"""
CS:GO / CS2 Major 决赛数据爬虫
数据源：Liquipedia API (via ggpyscraper)

用法：
  python major_crawler.py             # 自动发现 + 补新赛事 + 出报告
  python major_crawler.py --no-crawl  # 只用现有数据出报告
  python major_crawler.py --check     # 只做完整性检查，不抓取

首次使用：
  1. 安装依赖：pip install ggpyscraper regex aiohttp pytz beautifulsoup4 lxml pandas
  2. 设置环境变量 LIQUIPEDIA_USER_AGENT，或在下方 USER_AGENT 里
     把邮箱换成你自己的（Liquipedia 要求真实联系方式）：
       格式示例：CSMajorScraper/1.0 (personal research; you@example.com)

注意：Liquipedia 要求每次 API 请求间隔至少 30 秒。
      本项目默认使用 60 秒（REQUEST_DELAY = 60），更保险。
"""

import os
import re
import sys
import json
import time
import unicodedata

# ============ 依赖自检 ============
_missing = []
try:
    from ggpyscraper.liquipedia_objects import tournament  # noqa: F401
except ImportError:
    _missing.append("ggpyscraper")
try:
    import pandas  # noqa: F401
except ImportError:
    _missing.append("pandas")

if _missing:
    print("=" * 70)
    print("  ✗ 缺少依赖：" + "、".join(_missing))
    print("=" * 70)
    print("\n请先安装：")
    print("  pip install ggpyscraper regex aiohttp pytz "
          "beautifulsoup4 lxml pandas")
    sys.exit(1)


# ============ 配置 ============
# ⚠ 优先读环境变量 LIQUIPEDIA_USER_AGENT；
#   未设置时使用下面的兜底值（请把邮箱改成你自己的）。
#   Liquipedia API 要求提供真实联系方式。
USER_AGENT = os.getenv(
    "LIQUIPEDIA_USER_AGENT",
    "CSMajorScraper/1.0 (personal research; your-email@example.com)"
)

# Liquipedia 官方要求 ≥30 秒，这里用 60 秒更保险
REQUEST_DELAY = 60

# START_PAGE 会被自动发现逻辑覆盖，这里是兜底值
START_PAGE = "Intel Extreme Masters/2026/Cologne"
MAX_EVENTS = 30

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "major_data.json")

TEAM_MAP = {
    "fnc": "fnatic", "fnatic orig": "fnatic",
    "nip": "Ninjas in Pyjamas",
    "ninjas in pyjamas 2012": "Ninjas in Pyjamas",
    "navi": "Natus Vincere",
    "vit": "Vitality", "vitality": "Vitality",
    "vp": "Virtus.pro", "virtus.pro 2012 2": "Virtus.pro",
    "astralis orig": "Astralis", "astralis": "Astralis",
    "faze": "FaZe", "faze clan nov 2021": "FaZe", "faze clan": "FaZe",
    "envy": "EnVyUs", "nv": "EnVyUs", "team envyus orig": "EnVyUs",
    "ldlc": "LDLC", "team ldlc.com 2012": "LDLC",
    "lg": "Luminosity", "luminosity gaming orig": "Luminosity",
    "sk": "SK Gaming", "c9": "Cloud9", "cloud9 orig": "Cloud9",
    "gambit": "Gambit", "gambit esports1": "Gambit",
    "imt": "Immortals", "outsiders": "Outsiders",
    "heroic": "Heroic", "g2": "G2", "ence": "ENCE",
    "avangar": "AVANGAR", "tl": "Team Liquid", "mibr": "MIBR",
    "gamerlegion": "GamerLegion", "furia": "FURIA",
    "mouz": "MOUZ", "spirit": "Spirit", "falcons": "Team Falcons",
    "mongolz": "The MongolZ",
}


# ============ 工具 ============
def team_full(abbr):
    if not abbr:
        return "—"
    return TEAM_MAP.get(str(abbr).strip().lower(), abbr)


def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1
               for c in str(s))


def pad(s, w):
    s = str(s)
    return s + " " * max(0, w - width(s))


def clean(s):
    s = str(s or "")
    s = re.sub(r"&#\d+;", "", s)
    s = s.replace("&nbsp;", " ").replace("\u200b", "")
    return s.strip()


def year_of(d):
    m = re.search(r"(\d{4})", d or "")
    return int(m.group(1)) if m else 0


def clean_date(raw):
    s = re.sub(r"\{\{.*?\}\}", "", str(raw or "")).strip()
    return s.split(" - ")[0].strip()


def clean_page_name(raw):
    return raw.split("{{!}}")[0].strip() if raw else None


def normalize_page_name(name):
    """'Intel_Extreme_Masters/2026/Rio' → 'Intel Extreme Masters/2026/Rio'"""
    if not name:
        return name
    return name.replace("_", " ").strip()


# ============ 数据存取 ============
def migrate_keys(data):
    """把 events 里的旧 key 统一 normalize（下划线 → 空格）"""
    events = data.get("events", {})
    new_events = {}
    changed = False

    for k, v in events.items():
        nk = normalize_page_name(k)
        if nk != k:
            changed = True
            v["page"] = nk
            if nk in new_events and "final" not in v:
                continue
        new_events[nk] = v

    if changed:
        data["events"] = new_events
        save(data)
        print(f"  [迁移] events key 规范化：{len(events)} → {len(new_events)}")
    return data


def load():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            data = json.load(f)
        data = migrate_keys(data)
        return data
    return {"events": {}}


def save(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============ Liquipedia 访问 ============
def t_new(page):
    from ggpyscraper.liquipedia_objects import tournament
    return tournament.Tournament(
        game="counterstrike", name=page, user=USER_AGENT)


def get_results(page):
    try:
        return t_new(page).get_results()
    except ValueError as e:
        if "concatenate" in str(e):
            return None
        raise
    except Exception as e:
        print(f"    ✗ get_results: {type(e).__name__}: {e}")
        return None


def get_raw(page):
    try:
        return t_new(page).get_raw_str()
    except Exception as e:
        print(f"    ✗ get_raw_str: {type(e).__name__}: {e}")
        return None


# ============ 解析：比赛 DataFrame ============
def num(row, col):
    if col not in row.index:
        return 0
    try:
        f = float(row[col])
        return int(f) if f == f else 0
    except (ValueError, TypeError):
        return 0


def parse_df(df):
    if df is None or df.empty:
        return None
    sl = df["stage"].astype(str).str.lower()
    finals = df[sl.str.contains("final", na=False)
                & ~sl.str.contains("semi|quarter", na=False)
                & (sl != "results")]
    if finals.empty:
        return None

    r0 = finals.iloc[0]
    t1 = str(r0["opponent_1"]).strip()
    t2 = str(r0["opponent_2"]).strip()

    m1, m2, maps = 0, 0, []
    for _, r in finals.iterrows():
        s1 = (num(r, "t1t") + num(r, "t1ct")
              + num(r, "o1t1t") + num(r, "o1t1ct")
              + num(r, "o2t1t") + num(r, "o2t1ct"))
        s2 = (num(r, "t2t") + num(r, "t2ct")
              + num(r, "o1t2t") + num(r, "o1t2ct")
              + num(r, "o2t2t") + num(r, "o2t2ct"))
        if s1 == 0 and s2 == 0:
            continue
        if s1 > s2:
            m1 += 1
        else:
            m2 += 1
        # maps 里存的是 t1得分-t2得分 顺序
        maps.append(f"{r['map']} {s1}-{s2}")

    if not maps:
        return None
    return {"t1": t1, "t2": t2, "score": f"{m1}-{m2}",
            "winner": t1 if m1 > m2 else t2,
            "date": clean_date(r0["date"]), "maps": maps}


# ============ 解析：prize pool 兜底 ============
def parse_prizepool(raw):
    if not raw:
        return None
    for m in re.finditer(
            r"\{\{prize pool slot\s*\|\s*place\s*=\s*1\b", raw):
        seg = raw[m.start():m.start() + 1500]
        m2 = re.search(
            r"\|\s*([a-zA-Z0-9][a-zA-Z0-9 _\-]*?)\s*"
            r"\|\s*lastvs1\s*=\s*([a-zA-Z0-9][a-zA-Z0-9 _\-]*?)\s*"
            r"\|\s*lastscore1\s*=\s*(\d+)\s*"
            r"\|\s*lastvsscore1\s*=\s*(\d+)", seg)
        if not m2:
            continue
        w, l = m2.group(1).strip(), m2.group(2).strip()
        ws, ls = int(m2.group(3)), int(m2.group(4))
        if 0 <= ws <= 5 and 0 <= ls <= 5:
            return {"t1": w, "t2": l, "score": f"{ws}-{ls}",
                    "winner": w, "maps": [], "date": ""}
    return None


# ============ 解析：Stage 子页面 ============
def extract_stages(raw):
    s = set()
    for m in re.finditer(r"\{\{Stage\|([^}|]+)", raw):
        s.add(m.group(1).strip())
    for m in re.finditer(r"\{\{PAGENAME\}\}/([^|\n}\]]+)", raw):
        x = m.group(1).strip()
        if any(k in x.lower() for k in ["champion", "playoff", "final"]):
            s.add(x)
    for m in re.finditer(
            r"\[\[[^\]|]*/(Champions[^\]|]*|Playoffs?[^\]|]*|Playoff[^\]|]*)\]\]",
            raw):
        s.add(m.group(1).strip())
    r = list(s)
    r.sort(key=lambda x: 0 if any(
        k in x.lower() for k in ["champion", "playoff", "final"]) else 1)
    return r


# ============ 解析：MVP ============
def extract_mvp(raw, page):
    def norm(s):
        return s.split("|")[0].replace("_", " ").strip().lower()
    target = norm(page)
    for line in raw.split("\n"):
        if not line.strip().startswith("|"):
            continue
        parts = [p.strip() for p in line.split("||")]
        if len(parts) < 5:
            continue
        m = re.search(r"\[\[([^\]|]+)", parts[0])
        if not m or norm(m.group(1)) != target:
            continue
        pm = re.search(r"'''\[\[(?:[^\]|]*\|)?([^\]|]+)\]\]'''", parts[4])
        if not pm:
            pm = re.search(r"'''([^']+)'''", parts[4])
        tm = re.search(r"\{\{TeamIcon\|([^}|]+)", parts[3])
        return {"player": pm.group(1).strip() if pm else "",
                "team": tm.group(1).strip() if tm else ""}
    return None


# ============ 自动发现 Major（从 mvp_raw） ============
def extract_majors_from_mvp(mvp_raw):
    if not mvp_raw:
        return []

    majors = []
    lines = mvp_raw.split("\n")

    for i, line in enumerate(lines):
        if "valvemajor-highlighted" not in line:
            continue
        for j in range(i + 1, min(i + 4, len(lines))):
            data_line = lines[j]
            if not data_line.startswith("|") or "[[" not in data_line:
                continue

            pm = re.search(r"\[\[([^\]|]+)", data_line)
            if not pm:
                continue
            raw_page = pm.group(1).strip()
            page = normalize_page_name(raw_page)

            dm = re.search(r"\|\|\s*(\d{4}-\d{2}-\d{2})", data_line)
            pmm = re.search(r"'''\[\[(?:[^\]|]*\|)?([^\]|]+)\]\]'''",
                            data_line)
            if not pmm:
                pmm = re.search(r"'''([^']+)'''", data_line)
            tm = re.search(r"\{\{TeamIcon\|([^}|]+)", data_line)

            majors.append({
                "page": page,
                "raw_page": raw_page,
                "date": dm.group(1) if dm else "",
                "player": pmm.group(1).strip() if pmm else "",
                "team": tm.group(1).strip() if tm else "",
            })
            break

    seen = set()
    uniq = []
    for m in majors:
        if m["page"] in seen:
            continue
        seen.add(m["page"])
        uniq.append(m)

    uniq.sort(key=lambda x: x["date"], reverse=True)
    return uniq


def check_completeness(data):
    events = data.get("events", {})
    all_majors = extract_majors_from_mvp(data.get("mvp_raw", ""))
    known = {normalize_page_name(k) for k in events.keys()}

    missing = [m for m in all_majors if m["page"] not in known]
    return {
        "all": all_majors,
        "missing": missing,
        "latest": all_majors[0]["page"] if all_majors else None,
    }


# ============ 增量更新 MVP ============
def refresh_mvp_raw_if_needed(data, missing_pages):
    mvp_raw = data.get("mvp_raw", "")
    stale = False

    for p in missing_pages:
        if not extract_mvp(mvp_raw, p):
            stale = True
            break

    if not stale:
        return False

    print("    mvp_raw 可能已过期，重新抓取...")
    mr = get_raw("HLTV/MVP_Awards")
    if mr and len(mr) > 10000:
        data["mvp_raw"] = mr
        save(data)
        print(f"    ✓ {len(mr)} 字符")
        return True
    print("    ✗ 抓取失败，保留旧数据")
    return False


def refresh_mvp(data):
    events = data.get("events", {})
    missing = [p for p, e in events.items()
               if e.get("path") != "cancelled" and not e.get("mvp")]

    if not missing:
        print("    所有赛事 MVP 已完整")
        return

    print(f"    有 {len(missing)} 个赛事缺少 MVP，尝试匹配...")

    mvp_raw = data.get("mvp_raw", "")
    matched = 0

    for p in missing:
        m = extract_mvp(mvp_raw, p)
        if m:
            events[p]["mvp"] = m
            matched += 1
            print(f"      ✓ {p}: {m.get('player', '?')}")

    if matched:
        save(data)
        print(f"    新增 {matched} 个 MVP")

    still = [p for p in missing if not events[p].get("mvp")]
    if still:
        print(f"    ⚠ {len(still)} 个赛事在 mvp_raw 里找不到：")
        for p in still:
            print(f"        - {p}")


# ============ 抓取 ============
def crawl(refresh=False, only_pages=None):
    data = load()
    if refresh:
        data = {"events": {}}
    events = data.setdefault("events", {})

    print("=" * 78)
    print("  阶段 1：抓取决赛数据")
    print("=" * 78)

    # 补漏模式
    if only_pages:
        for page in only_pages:
            page = normalize_page_name(page)
            print(f"\n{'━'*70}\n[补漏] {page}\n{'━'*70}")
            e = events.get(page, {"page": page})
            crawl_single(page, e, events)
            save(data)
        return

    # 遍历模式
    page = normalize_page_name(START_PAGE)
    visited = set()

    while page and page not in visited and len(visited) < MAX_EVENTS:
        # 遍历前再 normalize 一次，防止 previous 里残留旧格式
        page = normalize_page_name(page)
        if page in visited:
            break
        visited.add(page)

        if page in events and events[page].get("done") and not refresh:
            print(f"\n[{len(visited)}] {page}  [缓存]")
            prev = events[page].get("previous")
            page = normalize_page_name(prev) if prev else None
            continue

        print(f"\n{'━'*70}\n[{len(visited)}] {page}\n{'━'*70}")
        e = events.get(page, {"page": page})
        crawl_single(page, e, events)
        save(data)

        # next page 也 normalize
        prev = e.get("previous")
        if prev:
            prev = normalize_page_name(prev)
        if not prev or prev == page:
            print(f"\n  已到最早一届")
            break
        page = prev
        time.sleep(REQUEST_DELAY)


def crawl_single(page, e, events):
    print(f"    [1] get_results")
    df = get_results(page)
    time.sleep(REQUEST_DELAY)

    raw = get_raw(page)
    if raw:
        m = re.search(r"\|\s*name\s*=\s*([^\n|]+)", raw)
        if m:
            e["title"] = m.group(1).strip()
        else:
            e["title"] = e.get("title", page)

        pm = re.search(r"\|\s*previous\s*=\s*([^\n|]+)", raw)
        if pm:
            e["previous"] = normalize_page_name(
                clean_page_name(pm.group(1).strip()))

        if "{{Cancelled Tournament" in raw or \
           "{{Cancelled tournament" in raw:
            e["path"] = "cancelled"
            e["done"] = True
            events[page] = e
            print(f"    ⚠ 已取消")
            return

    time.sleep(REQUEST_DELAY)

    final = parse_df(df) if df is not None else None
    if final:
        e["path"] = "main"
        e["final"] = final

    if not final and raw:
        stages = extract_stages(raw)
        if stages:
            print(f"    [2] Stage 子页面: {stages}")
            for st in stages:
                sp = f"{page}/{st}"
                print(f"        → {sp}")
                time.sleep(REQUEST_DELAY)
                f2 = parse_df(get_results(sp))
                if f2:
                    e["path"] = "subpage"
                    e["subpage_used"] = sp
                    e["final"] = f2
                    final = f2
                    break

    if not final and raw:
        print(f"    [3] prize pool")
        fd = parse_prizepool(raw)
        if fd:
            e["path"] = "prizepool"
            e["final"] = fd
            final = fd

    if not e.get("previous"):
        time.sleep(REQUEST_DELAY)
        try:
            info = t_new(page).get_info()
            e["previous"] = normalize_page_name(
                clean_page_name(info.get("previous", "")) or "")
            if info.get("name"):
                e["title"] = info["name"]
        except Exception:
            pass

    if final:
        print(f"    ✓ [{e['path']}] {final['t1']} "
              f"{final['score']} {final['t2']} → {final['winner']}")
    else:
        print(f"    ✗ 未找到")
        e["path"] = "failed"

    e["done"] = True
    events[page] = e


# ============ 补地图 ============
def fill_maps(data, refresh=False):
    print("\n" + "=" * 78)
    print("  阶段 3：补地图")
    print("=" * 78)

    events = data.get("events", {})
    SUBPAGE_CANDIDATES = [
        "Champions Stage",
        "Playoffs",
        "Playoff Stage",
        "Championship Stage",
        "Final Stage",
    ]

    targets = [p for p, e in events.items()
               if e.get("path") == "prizepool"]

    if not targets:
        print("    没有需要补地图的赛事")
        return

    print(f"    发现 {len(targets)} 个 prizepool 路径的赛事")

    for p in targets:
        e = events[p]
        if e.get("maps_detail") and not refresh:
            print(f"    {p}  [缓存]")
            continue

        print(f"    {p}")
        found = False

        for sub in SUBPAGE_CANDIDATES:
            sp = f"{p}/{sub}"
            print(f"        尝试 {sub}")
            time.sleep(REQUEST_DELAY)
            df = get_results(sp)
            if df is None or df.empty:
                continue

            sl = df["stage"].astype(str).str.lower()
            gf = df[sl.str.contains("grand final", na=False)]
            if gf.empty:
                gf = df[sl.str.contains("final", na=False)
                        & ~sl.str.contains("semi|quarter", na=False)]
            if gf.empty:
                continue

            maps = []
            for _, r in gf.iterrows():
                s1 = (num(r, "t1t") + num(r, "t1ct")
                      + num(r, "o1t1t") + num(r, "o1t1ct")
                      + num(r, "o2t1t") + num(r, "o2t1ct"))
                s2 = (num(r, "t2t") + num(r, "t2ct")
                      + num(r, "o1t2t") + num(r, "o1t2ct")
                      + num(r, "o2t2t") + num(r, "o2t2ct"))
                if s1 == 0 and s2 == 0:
                    continue
                maps.append(f"{r['map']} {s1}-{s2}")

            if maps:
                e["maps_detail"] = {"maps": maps}
                print(f"            ✓ {' | '.join(maps)}")
                save(data)
                found = True
                break

        if not found:
            print(f"        ✗ 所有候选子页面都没找到地图")


# ============ 报告 ============
def normalize_map(m, winner_is_t1=True):
    """
    把 '地图 X-Y' 转成冠军视角。
    m: "Cobblestone 11-16" —— 原数据里 X=t1得分, Y=t2得分
    winner_is_t1: 冠军是否是原数据里的 t1
    返回 "地图 X-Y"，X=冠军得分, Y=亚军得分
    """
    mm = re.match(r"(\S.*?)\s+(\d+)-(\d+)$", m.strip())
    if not mm:
        return m
    n, s1, s2 = mm.group(1), int(mm.group(2)), int(mm.group(3))
    if not winner_is_t1:
        s1, s2 = s2, s1
    return f"{n} {s1}-{s2}"


def build_records():
    data = load()
    events = data.get("events", {})
    recs = []

    for p, e in events.items():
        if e.get("path") == "cancelled":
            recs.append({"page": p, "year": 2020,
                         "event": clean(e.get("title", p)),
                         "date": "", "winner": "Cancelled",
                         "runner_up": "—", "score": "—",
                         "maps": "COVID-19 取消",
                         "mvp": "—", "mvp_team": "—"})
            continue
        if "final" not in e:
            continue
        fd = e["final"]
        t1, t2 = team_full(fd["t1"]), team_full(fd["t2"])
        w = team_full(fd["winner"])
        try:
            a, b = fd["score"].split("-")
            if fd["winner"] == fd["t1"]:
                ru, ws = t2, f"{a}-{b}"
            else:
                ru, ws = t1, f"{b}-{a}"
        except Exception:
            ru = t2 if fd["winner"] == fd["t1"] else t1
            ws = fd["score"]

        date = clean(fd.get("date", ""))
        mvp = e.get("mvp") or {}
        y = year_of(date) or year_of(e.get("title", ""))

        # 地图转冠军视角：比较用原始值（避免 team_full 映射冲突）
        winner_is_t1 = (str(fd["winner"]).strip().lower()
                        == str(fd["t1"]).strip().lower())

        md = e.get("maps_detail") or {}
        maps_raw = md.get("maps") or fd.get("maps") or []
        maps = [normalize_map(m, winner_is_t1) for m in maps_raw]

        recs.append({
            "page": p, "year": y,
            "event": clean(e.get("title", p)),
            "date": date, "winner": w, "runner_up": ru,
            "score": ws,
            "maps": " | ".join(maps) if maps else "—",
            "mvp": mvp.get("player", "—"),
            "mvp_team": team_full(mvp.get("team", "—")),
        })
    recs.sort(key=lambda x: (x["year"], x["date"]))
    return recs


def print_report(recs):
    print("\n" + "═" * 118)
    print("  CS:GO / CS2 Major 决赛总览")
    print("═" * 118)

    cols = [("年份", 6), ("赛事", 44), ("冠军", 18),
            ("比分", 6), ("亚军", 18), ("MVP", 14)]
    total = sum(w for _, w in cols)
    print("".join(pad(n, w) for n, w in cols))
    print("─" * total)

    for r in recs:
        if r["winner"] == "Cancelled":
            print("".join([pad(r["year"], 6), pad(r["event"][:42], 44),
                           pad("[取消]", 18), pad("—", 6),
                           pad("—", 18), pad("—", 14)]))
            continue
        print("".join([pad(r["year"], 6), pad(r["event"][:42], 44),
                       pad(r["winner"][:16], 18), pad(r["score"], 6),
                       pad(r["runner_up"][:16], 18),
                       pad(r["mvp"][:12], 14)]))

    print("═" * total)
    print(f"\n共 {len(recs)} 届\n")

    print("═" * 118)
    print("  决赛地图明细")
    print("  （比分均为冠军视角：X-Y = 冠军得分-亚军得分）")
    print("═" * 118)
    for r in recs:
        if r["winner"] == "Cancelled":
            continue
        print(f"\n  {r['year']}  {r['event']}")
        print(f"    冠军 {r['winner']} {r['score']} {r['runner_up']}")
        print(f"    MVP: {r['mvp']} ({r['mvp_team']})")
        print(f"    地图: {r['maps']}")


# ============ 完整性报告 ============
def print_completeness(data, info=None):
    if info is None:
        info = check_completeness(data)
    all_majors = info["all"]
    missing = info["missing"]

    print("=" * 78)
    print("  完整性检查")
    print("=" * 78)

    if not all_majors:
        print("  ⚠ 未从 mvp_raw 里发现任何 Major")
        print("    可能 class 名 'valvemajor-highlighted' 变了")
        return

    print(f"  Liquipedia MVP 页面标记的 Major: {len(all_majors)} 个")
    print(f"  已抓取: {len(all_majors) - len(missing)} 个")

    if missing:
        print(f"\n  发现 {len(missing)} 个未抓取的 Major：")
        for m in missing:
            print(f"    - {m['page']}  ({m['date']}, MVP={m['player']})")
    else:
        print(f"  ✓ 所有 Major 数据已完整")

    events = data.get("events", {})
    mvp_pages = {normalize_page_name(m["page"]) for m in all_majors}
    extra = [p for p in events
             if normalize_page_name(p) not in mvp_pages
             and events[p].get("path") != "cancelled"]
    if extra:
        print(f"\n  已抓取但不在 mvp_raw 列表里的赛事 ({len(extra)} 个)：")
        for p in extra:
            print(f"    - {p}")


# ============ 入口 ============
def main():
    # 邮箱自检：占位符没改就拒绝运行
    if "your-email@example.com" in USER_AGENT:
        print("=" * 70)
        print("  ⚠ 请先设置你的联系方式")
        print("=" * 70)
        print("\n方式一（推荐）：设置环境变量")
        print("  Linux / macOS:")
        print("    export LIQUIPEDIA_USER_AGENT="
              "\"CSMajorScraper/1.0 (personal research; you@example.com)\"")
        print("  Windows (PowerShell):")
        print("    $env:LIQUIPEDIA_USER_AGENT="
              "\"CSMajorScraper/1.0 (personal research; you@example.com)\"")
        print("\n方式二：直接修改 major_crawler.py 里的 USER_AGENT 默认值")
        print("\nLiquipedia API 要求提供真实联系方式。")
        return

    no_crawl = "--no-crawl" in sys.argv
    check_only = "--check" in sys.argv
    has_cache = os.path.exists(DATA_FILE)

    if not no_crawl and not check_only and not has_cache:
        print("=" * 70)
        print("  ⚠ 未找到 major_data.json")
        print("=" * 70)
        print("\n将从最新赛事开始，抓取 2013-2026 全部 Major 决赛数据。")
        print(f"预计耗时 60-90 分钟（每次 API 请求间隔 {REQUEST_DELAY} 秒）。")
        print("\n中途可以 Ctrl+C 中断，下次运行会从断点继续。")
        print()
        try:
            input("按回车开始抓取，或按 Ctrl+C 退出... ")
        except KeyboardInterrupt:
            print("\n已取消。")
            return

    data = load()
    info = check_completeness(data)
    print_completeness(data, info)

    if check_only:
        return

    only_pages = None

    if info["missing"]:
        missing_pages = [m["page"] for m in info["missing"]]
        if not no_crawl:
            refresh_mvp_raw_if_needed(data, missing_pages)
            # 更新过 mvp_raw 后重新计算
            info = check_completeness(data)
        only_pages = [m["page"] for m in info["missing"]]

    if not no_crawl:
        if only_pages and len(only_pages) <= 5:
            print(f"\n补漏 {len(only_pages)} 个赛事")
            crawl(only_pages=only_pages)
        else:
            if info["latest"]:
                global START_PAGE
                START_PAGE = info["latest"]
            print(f"\n从 {START_PAGE} 开始遍历")
            crawl(refresh=False)

        # 关键：crawl 内部有自己的 data 并 save 过，
        # 这里必须重新 load，避免用旧快照覆盖磁盘数据
        data = load()
        fill_maps(data)

        print("\n" + "=" * 78)
        print("  阶段 2：MVP")
        print("=" * 78)
        data = load()
        refresh_mvp(data)

    recs = build_records()
    print_report(recs)
    print(f"\n数据文件：{DATA_FILE}")
    print("✓ 全部完成")


if __name__ == "__main__":
    main()