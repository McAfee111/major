"""
Major 数据库模块
- 从 major_data.json 导入 SQLite
- 提供多种查询功能
用法：
  python major_db.py init            # 从 JSON 导入数据库
  python major_db.py list            # 全部赛事
  python major_db.py champions       # 冠军排行榜
  python major_db.py mvp             # MVP 排行榜
  python major_db.py year 2020 2024  # 年份范围
  python major_db.py team Astralis   # 某队的所有决赛（支持歧义拆分与自动纠错）
  python major_db.py player ZywOo    # 某选手的 MVP（支持字母数字映射）
  python major_db.py map Mirage      # 某地图的出现记录（支持 de_ 前缀过滤）
  python major_db.py stats           # 统计概要
"""

import os
import re
import sys
import json
import sqlite3
import unicodedata

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(SCRIPT_DIR, "major_data.json")
DB_FILE = os.path.join(SCRIPT_DIR, "majors.db")

# === 读取队伍映射字典 ===
TEAM_MAP_FILE = os.path.join(SCRIPT_DIR, "teams.json")
try:
    with open(TEAM_MAP_FILE, encoding="utf-8") as f:
        TEAM_MAP = json.load(f)
except FileNotFoundError:
    print(f"✗ 未找到 {TEAM_MAP_FILE}，请确保它与数据库脚本在同一目录。")
    sys.exit(1)
except json.JSONDecodeError as e:
    print(f"✗ 解析 {TEAM_MAP_FILE} 失败，请检查 JSON 格式。错误信息：{e}")
    sys.exit(1)


# ============ 选手别名字典 ============
# 只有涉及数字替换字母（0->o, 1->i/l）的选手，才需要放进这里
# 纯字母选手靠大小写清洗就能完美匹配，无需写在这里
PLAYER_ALIASES = {
    "monesy": "m0nesy",    # 0 -> o
    "simple": "s1mple",    # 1 -> i
    "device": "dev1ce",    # 1 -> i
}


# ============ 地图别名字典 ============
# 数据库里通常存的是完整拼写（如 Dust II），这里把常见缩写和特殊写法统一映射
# 注意：清洗时我们会删掉空格，所以 "dust ii" 会变成 "dustii"
MAP_ALIASES = {
    "d2": "dust2",
    "dust": "dust2",
    "dustii": "dust2",        # 兼容用户输入 Dust II
    "cbble": "cobblestone",
    "cbl": "cobblestone",
    "cobble": "cobblestone",
    "op": "overpass",
    "inf": "inferno",
    "mrg": "mirage",
    "anc": "ancient",
    "anb": "anubis",
    "vrt": "vertigo",
    "cch": "cache",
}


def team_full(abbr):
    """缩写 → 全名。无映射时返回原值"""
    if not abbr:
        return abbr
    return TEAM_MAP.get(str(abbr).strip().lower(), abbr)


# ============ 工具 ============
def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1
               for c in str(s))


def pad(s, w):
    s = str(s)
    return s + " " * max(0, w - width(s))


def clean(s):
    """清理 HTML 实体和不可见字符"""
    s = str(s or "")
    s = re.sub(r"&#\d+;", "", s)
    s = s.replace("&nbsp;", " ").replace("\u200b", "")
    return s.strip()


def parse_maps_string(maps_str):
    """
    解析 "Mirage 16-9 | Inferno 16-10" 格式
    返回 [(map_name, score_w, score_l), ...]
    """
    if not maps_str or maps_str == "—":
        return []
    result = []
    for part in maps_str.split("|"):
        m = re.match(r"\s*(\S.*?)\s+(\d+)-(\d+)\s*$", part)
        if m:
            result.append((m.group(1), int(m.group(2)), int(m.group(3))))
    return result


# ============ 数据库建表 ============
SCHEMA = """
CREATE TABLE IF NOT EXISTS majors (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    page          TEXT UNIQUE NOT NULL,
    title         TEXT,
    year          INTEGER,
    date          TEXT,
    winner        TEXT,
    runner_up     TEXT,
    score         TEXT,
    mvp_player    TEXT,
    mvp_team      TEXT,
    is_cancelled  INTEGER DEFAULT 0,
    source_path   TEXT
);

CREATE TABLE IF NOT EXISTS maps (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    major_id      INTEGER NOT NULL,
    map_order     INTEGER,
    map_name      TEXT,
    score_winner  INTEGER,
    score_loser   INTEGER,
    FOREIGN KEY (major_id) REFERENCES majors(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_majors_year   ON majors(year);
CREATE INDEX IF NOT EXISTS idx_majors_winner ON majors(winner);
CREATE INDEX IF NOT EXISTS idx_majors_mvp    ON majors(mvp_player);
CREATE INDEX IF NOT EXISTS idx_maps_name     ON maps(map_name);
"""


def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_tables(conn):
    conn.executescript(SCHEMA)
    conn.commit()


# ============ 导入 ============
def sync_from_json():
    """从 major_data.json 导入/更新数据库"""
    if not os.path.exists(DATA_FILE):
        print(f"✗ 未找到 {DATA_FILE}")
        print("  请先运行 major_crawler.py 生成数据")
        return

    with open(DATA_FILE, encoding="utf-8") as f:
        data = json.load(f)

    events = data.get("events", {})
    if not events:
        print("✗ JSON 里没有 events 数据")
        return

    conn = get_conn()
    init_tables(conn)

    inserted, updated, skipped = 0, 0, 0

    for page, e in events.items():
        cur = conn.execute(
            "SELECT id FROM majors WHERE page = ?", (page,))
        row = cur.fetchone()

        is_cancelled = 1 if e.get("path") == "cancelled" else 0
        title = clean(e.get("title", page))

        if is_cancelled:
            year = 2020
            date = ""
            winner = "Cancelled"
            runner_up = "—"
            score = "—"
            mvp_player = "—"
            mvp_team = "—"
        elif "final" in e:
            fd = e["final"]
            date = fd.get("date", "")
            ym = re.search(r"(\d{4})", date) or \
                 re.search(r"(\d{4})", title)
            year = int(ym.group(1)) if ym else 0

            # 队伍名走 team_full 映射
            winner = team_full(fd["winner"])
            if fd["winner"] == fd["t1"]:
                runner_up = team_full(fd["t2"])
            else:
                runner_up = team_full(fd["t1"])

            # === 比分转成冠军视角 ===
            score = fd["score"]
            if fd["winner"] != fd["t1"]:
                parts = str(score).split("-")
                if len(parts) == 2:
                    score = f"{parts[1]}-{parts[0]}"

            mvp = e.get("mvp") or {}
            mvp_player = mvp.get("player", "")
            mvp_team = team_full(mvp.get("team", "")) if mvp.get("team") else ""

        else:
            skipped += 1
            continue

        source_path = e.get("path", "")

        if row:
            conn.execute("""
                UPDATE majors SET
                    title=?, year=?, date=?, winner=?, runner_up=?,
                    score=?, mvp_player=?, mvp_team=?,
                    is_cancelled=?, source_path=?
                WHERE page=?
            """, (title, year, date, winner, runner_up, score,
                  mvp_player, mvp_team, is_cancelled, source_path, page))
            major_id = row["id"]
            updated += 1
            conn.execute("DELETE FROM maps WHERE major_id=?", (major_id,))
        else:
            cur = conn.execute("""
                INSERT INTO majors
                    (page, title, year, date, winner, runner_up,
                     score, mvp_player, mvp_team, is_cancelled, source_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (page, title, year, date, winner, runner_up, score,
                  mvp_player, mvp_team, is_cancelled, source_path))
            major_id = cur.lastrowid
            inserted += 1

        # 插入地图
        maps_str = ""
        if not is_cancelled:
            md = e.get("maps_detail") or {}
            maps_list = md.get("maps") or e.get("final", {}).get("maps") or []
            maps_str = " | ".join(maps_list)
        for i, (mname, sw, sl) in enumerate(
                parse_maps_string(maps_str), 1):
            conn.execute("""
                INSERT INTO maps
                    (major_id, map_order, map_name, score_winner, score_loser)
                VALUES (?, ?, ?, ?, ?)
            """, (major_id, i, mname, sw, sl))

    conn.commit()
    conn.close()

    print(f"✓ 数据库同步完成：{DB_FILE}")
    print(f"  新增 {inserted} 条，更新 {updated} 条，跳过 {skipped} 条")


# ============ 查询 ============
def q_list(conn):
    rows = conn.execute("""
        SELECT year, title, winner, score, runner_up, mvp_player
        FROM majors WHERE is_cancelled = 0
        ORDER BY year, date
    """).fetchall()

    print("\n" + "═" * 100)
    print(f"  历届 Major 决赛（共 {len(rows)} 届）")
    print("═" * 100)

    cols = [("年份", 6), ("赛事", 42), ("冠军", 20),
            ("比分", 6), ("亚军", 20), ("MVP", 14)]
    total = sum(w for _, w in cols)
    print("".join(pad(n, w) for n, w in cols))
    print("─" * total)

    for r in rows:
        print("".join([
            pad(r["year"], 6),
            pad(r["title"][:40], 42),
            pad(r["winner"][:18], 20),
            pad(r["score"], 6),
            pad(r["runner_up"][:18], 20),
            pad(r["mvp_player"][:12], 14),
        ]))
    print("═" * total)


def q_champions(conn):
    rows = conn.execute("""
        SELECT winner, COUNT(*) as cnt
        FROM majors WHERE is_cancelled = 0
        GROUP BY winner
        ORDER BY cnt DESC, winner
    """).fetchall()

    print("\n" + "═" * 50)
    print("  冠军排行榜")
    print("═" * 50)
    print(f"{pad('排名', 6)}{pad('战队', 28)}{pad('次数', 8)}")
    print("─" * 50)
    for i, r in enumerate(rows, 1):
        print(f"{pad(i, 6)}{pad(r['winner'], 28)}{pad(r['cnt'], 8)}")
    print("═" * 50)


def q_mvp(conn):
    rows = conn.execute("""
        SELECT mvp_player, COUNT(*) as cnt
        FROM majors
        WHERE is_cancelled = 0 AND mvp_player != ''
        GROUP BY mvp_player
        ORDER BY cnt DESC, mvp_player
    """).fetchall()

    print("\n" + "═" * 50)
    print("  MVP 排行榜")
    print("═" * 50)
    print(f"{pad('排名', 6)}{pad('选手', 28)}{pad('次数', 8)}")
    print("─" * 50)
    for i, r in enumerate(rows, 1):
        print(f"{pad(i, 6)}{pad(r['mvp_player'], 28)}{pad(r['cnt'], 8)}")
    print("═" * 50)


def q_year(conn, y1, y2):
    # === 防呆保护：校验输入是否为有效数字 ===
    try:
        y1_int = int(y1)
        y2_int = int(y2)
    except ValueError:
        print(f"\n  ⚠ 无效的年份格式「{y1}」或「{y2}」，请输入纯数字（如 2020 2024）。")
        return

    # 保证范围是从小到大，防止用户输入 year 2024 2020 查不出来
    if y1_int > y2_int:
        y1_int, y2_int = y2_int, y1_int

    rows = conn.execute("""
        SELECT year, title, winner, score, runner_up, mvp_player
        FROM majors
        WHERE is_cancelled = 0 AND year BETWEEN ? AND ?
        ORDER BY year
    """, (y1_int, y2_int)).fetchall()

    if not rows:
        print(f"\n  {y1_int}–{y2_int} 年之间没有任何 Major 记录。")
        return

    print(f"\n  {y1_int}–{y2_int} 年的 Major（{len(rows)} 届）")
    print("─" * 100)
    cols = [("年份", 6), ("赛事", 42), ("冠军", 20),
            ("比分", 6), ("亚军", 20), ("MVP", 14)]
    print("".join(pad(n, w) for n, w in cols))
    print("─" * 100)
    
    for r in rows:
        print("".join([
            pad(r["year"], 6),
            pad(r["title"][:40], 42),
            pad(r["winner"][:18], 20),
            pad(r["score"], 6),
            pad(r["runner_up"][:18], 20),
            pad(r["mvp_player"][:12], 14),
        ]))


def _query_and_print_team(conn, clean_name, display_name):
    # === 把传入的 clean_name 也做一次清洗 ===
    clean_name = re.sub(r'[^a-z0-9]', '', clean_name.lower())
    
    rows = conn.execute("""
        SELECT year, title, winner, score, runner_up, mvp_player,
               CASE
                   WHEN REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LOWER(winner), ' ', ''), 'team', ''), '.', ''), '_', ''), '-', '') LIKE ? THEN '冠军'
                   ELSE '亚军'
               END as role
        FROM majors
        WHERE is_cancelled = 0
          AND (
              REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LOWER(winner), ' ', ''), 'team', ''), '.', ''), '_', ''), '-', '') LIKE ? 
              OR 
              REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(LOWER(runner_up), ' ', ''), 'team', ''), '.', ''), '_', ''), '-', '') LIKE ?
          )
        ORDER BY year
    """, (f"%{clean_name}%", f"%{clean_name}%", f"%{clean_name}%")).fetchall()

    if not rows:
        print(f"\n  未找到包含「{display_name}」的记录")
        return

    real_team_name = display_name
    for r in rows:
        if r["role"] == "冠军":
            real_team_name = r["winner"]
            break
    else:
        if rows:
            real_team_name = rows[0]["runner_up"]

    print(f"\n  「{real_team_name}」的 Major 决赛记录（{len(rows)} 场）")
    print("─" * 100)
    cols = [("年份", 6), ("赛事", 42), ("角色", 8), ("比分", 6), ("对手", 22), ("MVP", 14)]
    print("".join(pad(n, w) for n, w in cols))
    print("─" * 100)
    
    for r in rows:
        opponent = r["runner_up"] if r["role"] == "冠军" else r["winner"]
        display_score = r["score"]
        if r["role"] == "亚军" and "-" in display_score:
            parts = display_score.split("-")
            if len(parts) == 2:
                display_score = f"{parts[1]}-{parts[0]}"

        print("".join([
            pad(r["year"], 6), pad(r["title"][:40], 42), pad(r["role"], 8),
            pad(display_score, 6), pad(opponent[:20], 22), pad(r["mvp_player"][:12], 14),
        ]))


def q_team(conn, team):
    # 1. 终极脱敏：转小写，剔除所有非字母数字（单引号、下划线、空格全没）
    raw_query = re.sub(r'[^a-z0-9]', '', str(team).lower())
    
    # 2. 首次映射：尝试直接查字典
    query_mapped = TEAM_MAP.get(raw_query, raw_query)
    
    # 3. 二次清洗（剥离 team 前缀）
    if isinstance(query_mapped, str):
        query_clean = re.sub(r'[^a-z0-9]', '', query_mapped.lower())
        
        # 安全剥离前缀（比 replace 安全）
        if query_clean.startswith("team"):
            query_clean = query_clean[4:]
            
        # 如果剥离后在字典里，再映射一次
        if query_clean in TEAM_MAP:
            query_mapped = TEAM_MAP[query_clean]
            if isinstance(query_mapped, str):
                query_clean = re.sub(r'[^a-z0-9]', '', query_mapped.lower())
                if query_clean.startswith("team"):
                    query_clean = query_clean[4:]
                    
    # 4. 核心判断：如果是列表，说明遇到了歧义缩写（如 nv）
    if isinstance(query_mapped, list):
        print(f"\n  💡 提示：在 CS 社区中，「{team}」可能指代 {' 或 '.join(query_mapped)}，为您分别展示：")
        for target_team in query_mapped:
            _query_and_print_team(conn, target_team, target_team)
        return

    # 5. 防呆保护
    if not query_clean:
        print(f"\n  无效的战队名「{team}」，请输入具体的战队名称（如 Astralis）。")
        return

    # 6. 极短词拦截
    if len(query_clean) < 3 and query_clean not in TEAM_MAP and raw_query not in TEAM_MAP:
        print(f"\n  ⚠ 搜索词「{team}」过短，容易匹配到多个不相关战队。")
        print(f"  请输入更完整的战队名称（如 NaVi 或 ENCE）。")
        return

    # 7. 正常调用
    _query_and_print_team(conn, query_clean, team)


def q_player(conn, player):
    # 1. 输入清洗：转小写，去除前后空格
    query = str(player).strip().lower()
    
    # 2. 别名映射：解决 m0NESY / s1mple 等特殊拼写问题
    query_mapped = PLAYER_ALIASES.get(query, query)

    # === 防呆保护：如果清洗后变成空字符串，直接拦截 ===
    if not query_mapped:
        print(f"\n  无效的选手名「{player}」，请输入具体的选手名称（如 ZywOo）。")
        return
    # ===================================================

    # 3. SQL 查询：通过 LOWER() 抹平大小写差异
    rows = conn.execute("""
        SELECT year, title, mvp_team, mvp_player
        FROM majors
        WHERE is_cancelled = 0 AND LOWER(mvp_player) LIKE ?
        ORDER BY year
    """, (f"%{query_mapped}%",)).fetchall()

    if not rows:
        print(f"\n  未找到「{player}」的 MVP 记录")
        return

    # 4. 从数据库中提取真实的拼写用于显示
    real_name = rows[0]["mvp_player"]

    # 5. 简洁输出：标题用数据库里的原版拼写，不用用户输入的
    print(f"\n  「{real_name}」的 MVP 记录（{len(rows)} 次）")
    print("─" * 100)
    for r in rows:
        print(f"  {r['year']}  {r['title']}  ({r['mvp_team']})")


def q_map(conn, map_name):
    # 1. 输入清洗：转小写、去掉 "de_" 前缀、去掉所有空格
    query = str(map_name).strip().lower().replace("de_", "").replace(" ", "")
    
    # 2. 查地图别名（把 d2 替换成 dust2，把 op 替换成 overpass）
    query_clean = MAP_ALIASES.get(query, query)

    # 3. 防呆保护
    if not query_clean:
        print(f"\n  无效的地图名「{map_name}」，请输入具体的地图名称（如 Mirage）。")
        return

    if len(query_clean) < 2:
        print(f"\n  ⚠ 搜索词「{map_name}」过短，请输入更完整的地图名称。")
        return

    # 4. SQL 查询：先转小写(LOWER)，再去空格，再去 de_ 前缀，最后把 dustii 统一成 dust2
    rows = conn.execute("""
        SELECT m.year, m.title, mp.map_order,
               mp.score_winner, mp.score_loser,
               m.winner, m.runner_up, mp.map_name
        FROM maps mp
        JOIN majors m ON mp.major_id = m.id
        WHERE REPLACE(REPLACE(REPLACE(LOWER(mp.map_name), ' ', ''), 'de_', ''), 'dustii', 'dust2') LIKE ?
        ORDER BY m.year
    """, (f"%{query_clean}%",)).fetchall()

    if not rows:
        print(f"\n  未找到包含「{map_name}」的记录")
        return

    real_map_name = rows[0]["map_name"]

    print(f"\n  「{real_map_name}」出现的决赛地图（{len(rows)} 次）")
    print("─" * 100)
    cols = [("年份", 6), ("赛事", 40), ("地图", 12),
            ("冠军方", 8), ("亚军方", 8), ("结果", 22)]
    print("".join(pad(n, w) for n, w in cols))
    print("─" * 100)
    
    for r in rows:
        result = f"{r['winner']} {r['score_winner']}-{r['score_loser']}"
        print("".join([
            pad(r["year"], 6),
            pad(r["title"][:38], 40),
            pad(r["map_name"][:10], 12),
            pad(r["score_winner"], 8),
            pad(r["score_loser"], 8),
            pad(result[:20], 22),
        ]))


def q_stats(conn):
    total = conn.execute(
        "SELECT COUNT(*) FROM majors WHERE is_cancelled = 0"
    ).fetchone()[0]
    cancelled = conn.execute(
        "SELECT COUNT(*) FROM majors WHERE is_cancelled = 1"
    ).fetchone()[0]
    teams = conn.execute(
        "SELECT COUNT(DISTINCT winner) FROM majors WHERE is_cancelled = 0"
    ).fetchone()[0]
    mvps = conn.execute(
        "SELECT COUNT(DISTINCT mvp_player) FROM majors "
        "WHERE is_cancelled = 0 AND mvp_player != ''"
    ).fetchone()[0]
    maps = conn.execute("SELECT COUNT(*) FROM maps").fetchone()[0]
    year_range = conn.execute(
        "SELECT MIN(year), MAX(year) FROM majors WHERE is_cancelled = 0"
    ).fetchone()

    top_winner = conn.execute("""
        SELECT winner, COUNT(*) as cnt FROM majors
        WHERE is_cancelled = 0
        GROUP BY winner ORDER BY cnt DESC LIMIT 1
    """).fetchone()

    top_mvp = conn.execute("""
        SELECT mvp_player, COUNT(*) as cnt FROM majors
        WHERE is_cancelled = 0 AND mvp_player != ''
        GROUP BY mvp_player ORDER BY cnt DESC LIMIT 1
    """).fetchone()

    top_map = conn.execute("""
        SELECT map_name, COUNT(*) as cnt FROM maps
        GROUP BY map_name ORDER BY cnt DESC LIMIT 1
    """).fetchone()

    print("\n" + "═" * 50)
    print("  数据统计概要")
    print("═" * 50)
    print(f"  Major 总数:      {total} 届")
    print(f"  已取消:          {cancelled} 届 (2020 Rio)")
    print(f"  年份跨度:        {year_range[0]} – {year_range[1]}")
    print(f"  夺冠战队数:      {teams} 支")
    print(f"  MVP 选手数:      {mvps} 人")
    print(f"  决赛地图总数:    {maps} 张")
    print("─" * 50)
    if top_winner:
        print(f"  夺冠最多:        {top_winner['winner']} ({top_winner['cnt']} 次)")
    if top_mvp:
        print(f"  MVP 最多:        {top_mvp['mvp_player']} ({top_mvp['cnt']} 次)")
    if top_map:
        print(f"  最常出现地图:    {top_map['map_name']} ({top_map['cnt']} 次)")
    print("═" * 50)


# ============ 入口 ============
def main():
    args = sys.argv[1:]

    if not args:
        print(__doc__)
        return

    cmd = args[0]

    # 初始化数据库单独处理（内部会自己建表并导入）
    if cmd == "init":
        sync_from_json()
        return

    # 检查数据库是否存在
    if not os.path.exists(DB_FILE):
        print(f"✗ 数据库不存在：{DB_FILE}")
        print("  请先运行：python major_db.py init")
        return

    # 建立数据库连接
    conn = get_conn()
    init_tables(conn)

    try:
        if cmd == "list":
            q_list(conn)
            
        elif cmd == "champions":
            q_champions(conn)
            
        elif cmd == "mvp":
            q_mvp(conn)
            
        elif cmd == "year":
            if len(args) < 3:
                print("用法：python major_db.py year 2020 2024")
                return
            # 修复：直接把字符串传进去，q_year 内部会处理防呆和数字转换
            q_year(conn, args[1], args[2])
            
        elif cmd == "team":
            if len(args) < 2:
                print("用法：python major_db.py team Astralis")
                return
            # 把后面的词拼起来，比如 ["TEAM", "aStRalis"] -> "TEAM aStRalis"
            q_team(conn, " ".join(args[1:]))
            
        elif cmd == "player":
            if len(args) < 2:
                print("用法：python major_db.py player ZywOo")
                return
            q_player(conn, " ".join(args[1:]))
            
        elif cmd == "map":
            if len(args) < 2:
                print("用法：python major_db.py map Mirage")
                return
            q_map(conn, " ".join(args[1:]))
            
        elif cmd == "stats":
            q_stats(conn)
            
        else:
            print(f"未知命令：{cmd}")
            print(__doc__)
            
    finally:
        # 无论执行成功还是报错，最后都稳妥地关闭数据库连接
        conn.close()


if __name__ == "__main__":
    main()