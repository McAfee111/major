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
- `major_crawler.py` — 爬虫主程序（含三层兜底、物理限速、断点续传测谎仪）
- `major_db.py` — 数据库模块（导入 + 智能防呆模糊查询）
- `check_ip.py` — 网络排障单发测试脚本（防 429 封禁）
- `teams.json` — 战队别名映射配置文件（实现数据与逻辑解耦）
- `major_data.json` — 原始数据（JSON 缓存，自带完美全量数据）
- `majors.db` — SQLite 数据库（由 `major_db.py init` 生成）
- `requirements.txt` — 依赖列表
- `README.md` — 本文件

---

## 使用方法

1. 网络排障指南（极其重要，必看！）

   **为什么需要这一步？**
   > Liquipedia 的反爬风控非常严格。如果你使用的是**校园网、公共公司网络、或者被多人在用的 VPN/代理节点**，极大概率会一上来就遇到 `429 Too Many Requests` 封禁报错（IP 连坐惩罚）。
   >
   > **在正式耗时 90 分钟挂机抓取前，强烈建议先测一下你的网络环境是否干净**。

   我们为你准备了一个单发测试脚本。请确保已经**设置了 `LIQUIPEDIA_USER_AGENT` 环境变量**（见上方步骤），然后在终端运行：

   ```bash
   python check_ip.py
   ```
   如果输出 **✅ 测试成功！**，说明你的网络环境很干净，可以放心运行 `python major_crawler.py` 进行全量抓取。

   如果输出 **❌ 测试失败：您的 IP 已被封禁**，请立即停止运行爬虫，否则会延长封禁时间。请尝试以下方案：

 - 关闭电脑 WiFi，使用手机 5G/4G 热点给电脑连网（推荐，成功率 99%）。
 - 切换你的梯子/代理软件的节点（尽量选冷门节点）。
 - 如果不急，静置等待 24 小时，系统会自动解封。

   （注：本项目仓库已自带 major_data.json 全量数据，即使不联网抓取，也可直接运行 python major_db.py init 导入数据库查询。）

2. 抓取数据

   首次使用前，必须设置环境变量 `LIQUIPEDIA_USER_AGENT`（Liquipedia API 要求提供真实的联系方式）。

   **Windows (PowerShell):**
   ```powershell
   $env:LIQUIPEDIA_USER_AGENT="CSMajorScraper/1.0 (your_email@example.com)"
    ```

   **Windows (CMD)**:

   ```cmd
   set LIQUIPEDIA_USER_AGENT=CSMajorScraper/1.0 (your_email@example.com)
   ```

   **Linux / macOS**:

   ```bash
   export LIQUIPEDIA_USER_AGENT="CSMajorScraper/1.0 (your_email@example.com)"
   ```

   **注意**：请将括号里的邮箱替换为你真实的邮箱地址。如果未设置该环境变量，程序会触发安全拦截并自动退出。

   设置完成后，运行：

   ```bash
   python major_crawler.py             # 自动发现新赛事 + 补漏 + 出报告
   python major_crawler.py --no-crawl  # 只用现有数据出报告
   python major_crawler.py --check     # 只做完整性检查，不抓取
   ```

   速率限制：Liquipedia 要求每次 API 请求间隔至少 30 秒。
   首次抓取全部赛事约需 **60–90** 分钟，支持断点续传。

3. 导入数据库

   ```bash
   python major_db.py init
   ```

   生成 `majors.db`，并从 `major_data.json` 导入全部数据。  
   已存在的记录会走 UPDATE 分支（可重复执行）。

4. 查询

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
- 数据存储：JSON 缓存和 SQLite 数据库中的比分，统一为「冠军视角」（X-Y 表示冠军得分-亚军得分）。
- 终端查询：
  - `list` / `year` 等全局列表：默认展示「冠军视角」。
  - `map` 地图查询：按列拆分为「冠军方得分」与「亚军方得分」，直观展示。
  - `team` 战队查询：系统会**自动推断视角**。如果你查询的队伍是亚军，终端显示的比分将自动反转为「该队得分-对手得分」。

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

由于 Liquipedia 从 2013 年至今经历了多次网页模板重构，本项目采用**三层智能兜底路径**抓取决赛数据，确保跨年代兼容：

- **`main`（主页面解析）**：调用 `get_results()` 直接提取表格中的决赛数据。适用于绝大多数新赛事（如 2023 年及以后）。
- **`subpage`（子页面解析）**：当主页面只有 `{{Stage|XXX}}` 的引用时触发。程序会自动提取子页面名并抓取（如 2021–2022）。**针对 2018/2019 年等隐藏引用的老页面，内置了强制暴力兜底机制，彻底解决老赛事断供问题。**
- **`prizepool`（奖池模板兜底）**：当表格解析全部失败时，通过正则从底层 `{{prize pool slot|place=1}}` 模板中强行提取冠亚军信息。适用于古早赛事（如 2013–2019），且采用了智能边界截断，不受模板长度限制。

此外还实现了：

- **绝对物理限速**：底层封装 `throttle()` 节流阀，强制保证每次 API 请求间隔严格 ≥60 秒，彻底杜绝 429 封禁。
- **断点续传“测谎仪”**：自动识别历史上的失败记录，无视缓存的 `done` 标记进行重试；如果网页结构出现变更（如新增赛事），可无缝增量抓取。
- **老页面暴力兜底**：对于 2018/2019 等正则无法提取子页面的赛事，程序内置了优先级备用路径列表（如 `Champions Stage`、`Playoffs` 等），按顺序自动尝试，直至成功命中并补齐数据。
- **防爆级数据落盘**：`load`/`save` 读写分离，使用 `.tmp` 文件配合 `os.replace()` 实现原子写入，断电不丢数据。
- **精细化异常分类**：自定义 `FetchError` 与 `EmptyDataError`，网络断线与空数据精准隔离，防止死循环。
- **智能防呆查询**：数据库端支持大小写免感、符号脱敏、缩写映射（如 `Teamtl`）、亚军比分视角反转。
- **自动发现与取消识别**：从 `valvemajor-highlighted` 标记反推新赛事；自动检测并标记 `Cancelled Tournament` 模板。

---

## 已知限制

- 2020 ESL One Rio 因 COVID-19 取消，数据库中标记为 `cancelled`。

- MVP 数据依赖 HLTV/MVP_Awards 页面，若该页面彻底改版可能失效。

- 抓取受限于 Liquipedia 的 60 秒限速，首次全量抓取约需 **60-90** 分钟。

---

## 免责声明
本项目仅用于学习和研究目的。数据来源于 Liquipedia，
代码部分采用 MIT License；数据部分遵循 CC-BY-SA 3.0 协议,使用时请注明数据来源。

---

