# CS:GO / CS2 Major 决赛数据爬虫

爬取 Liquipedia 上 2013–2026 全部 CS:GO / CS2 Major 决赛数据，
存入 SQLite 数据库，提供多种查询接口。

---

## 项目简介

本项目通过 Liquipedia API 抓取历届 CS Major 决赛数据，
包括赛事名、冠军、亚军、比分、地图明细、MVP 等信息，
并将数据持久化到 SQLite 数据库中，支持多种条件查询。

**数据规模**：24 届 Major（2013–2026），含 61 张决赛地图、20 位 MVP 选手。

---

## 技术栈

- **Python 3.9+**
- **ggpyscraper** — Liquipedia API 封装库
- **SQLite** — 数据库存储（含外键、索引）
- **pandas** — 数据处理（解析比赛 DataFrame）
- **regex / aiohttp / pytz / beautifulsoup4 / lxml** — ggpyscraper 的依赖

---

## 项目结构
- `major_crawler.py` — 爬虫主程序（三层兜底路径：main / subpage / prizepool）
- `major_db.py` — 数据库模块（导入 + 7 种查询）
- `major_data.json` — 原始数据（JSON 缓存）
- `majors.db` — SQLite 数据库（由 `major_db.py init` 生成）
- `requirements.txt` — 依赖列表
- `README.md` — 本文件

---

## 使用方法

1. 抓取数据

   首次使用前，打开 `major_crawler.py`，把 `USER_AGENT` 里的邮箱换成你自己的（Liquipedia API 要求提供真实联系方式）：

   ```python
   USER_AGENT = "CSMajorScraper/1.0 (personal research; your_email@example.com)"
   ```

   然后运行：

   ```bash
   python major_crawler.py             # 自动发现新赛事 + 补漏 + 出报告
   python major_crawler.py --no-crawl  # 只用现有数据出报告
   python major_crawler.py --check     # 只做完整性检查，不抓取
   ```

   速率限制：Liquipedia 要求每次 API 请求间隔至少 30 秒。  
   首次抓取全部赛事约需 60–90 分钟，支持断点续传。

2. 导入数据库

   ```bash
   python major_db.py init
   ```

   生成 `majors.db`，并从 `major_data.json` 导入全部数据。  
   已存在的记录会走 UPDATE 分支（可重复执行）。

3. 查询

   ```bash
   python major_db.py list            # 全部赛事
   python major_db.py champions       # 冠军排行榜
   python major_db.py mvp             # MVP 排行榜
   python major_db.py year 2020 2024  # 按年份范围查询
   python major_db.py team Astralis   # 某队的所有决赛
   python major_db.py player ZywOo    # 某选手的 MVP 记录
   python major_db.py map Mirage      # 某地图的出现记录
   python major_db.py stats           # 统计概要
   ```

---

## 数据说明

- 数据来源：Liquipedia — https://liquipedia.net/counterstrike
- 许可协议：CC-BY-SA 3.0（使用时请注明来源）
- 覆盖范围：2013 DreamHack Winter 至 2026 IEM Cologne，共 24 届（可迭代更新）
- 比分视角：所有比分均为冠军视角（X-Y 表示冠军得分-亚军得分）

---


## JSON 缓存字段

| 字段 | 说明 |
| --- | --- |
| `title` | 赛事全名 |
| `year` | 赛事年份 |
| `date` | 决赛日期 |
| `winner` | 冠军队伍 |
| `runner_up` | 亚军队伍 |
| `score` | 决赛比分（冠军视角） |
| `mvp_player` | MVP 选手 |
| `mvp_team` | MVP 所在队伍 |

## 数据库设计

### majors 表（主表）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键，自增 |
| `page` | TEXT | 赛事页面名（唯一约束） |
| `title` | TEXT | 赛事全名 |
| `year` | INTEGER | 年份 |
| `date` | TEXT | 决赛日期 |
| `winner` | TEXT | 冠军队伍（已映射为全名） |
| `runner_up` | TEXT | 亚军队伍 |
| `score` | TEXT | 决赛比分（冠军视角） |
| `mvp_player` | TEXT | MVP 选手 |
| `mvp_team` | TEXT | MVP 所在队伍 |
| `is_cancelled` | INTEGER | 是否取消（0/1） |
| `source_path` | TEXT | 抓取路径（main/subpage/prizepool） |

### maps 表（子表，与 majors 一对多）

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | INTEGER | 主键，自增 |
| `major_id` | INTEGER | 外键 → `majors.id` |
| `map_order` | INTEGER | 第几张地图 |
| `map_name` | TEXT | 地图名 |
| `score_winner` | INTEGER | 冠军方得分 |
| `score_loser` | INTEGER | 亚军方得分 |

### 索引

| 索引名 | 用途 |
| --- | --- |
| `idx_majors_year` | 按年份查询 |
| `idx_majors_winner` | 按冠军查询 |
| `idx_majors_mvp` | 按 MVP 查询 |
| `idx_maps_name` | 按地图名查询 |

---

## 爬虫实现要点

采用三层兜底路径抓取决赛数据，兼容 Liquipedia 各年代的页面结构：

- `main` — 主页面 `get_results()` 直接返回决赛数据（2023+）
- `subpage` — 主页面仅有 `{{Stage|XXX}}` 引用，需抓取子页面（2021–2022）
- `prizepool` — 从 `{{prize pool slot|place=1}}` 模板提取冠亚军（2013–2019）

此外还实现了：

- 自动发现新赛事：从 `mvp_raw` 里的 `valvemajor-highlighted` 标记反推所有 Major
- 完整性检查：对比 MVP 页面与已抓数据，自动识别缺失赛事
- 增量更新：只抓新增赛事，已缓存赛事跳过
- 取消赛事识别：检测 `{{Cancelled Tournament}}` 模板

---

## 已知限制
- 2020 ESL One Rio 因 COVID-19 取消，数据库中标记为 cancelled。

- MVP 数据依赖 HLTV/MVP_Awards 页面，若该页面改版可能失效。

- 抓取依赖 Liquipedia API 速率限制，每次请求间隔至少 30 秒。

- 早期赛事队伍名经过映射（如 nip → Ninjas in Pyjamas），映射表在 `major_crawler.py` / `major_db.py` 的 `TEAM_MAP` 中。

---

## 免责声明
本项目仅用于学习和研究目的。数据来源于 Liquipedia，
遵循 CC-BY-SA 3.0 许可协议。使用时请注明数据来源。

---

