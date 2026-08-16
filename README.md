# Decode Economic News / 财经新闻因果解码与A股预测

中文 | [English](#english)

## 中文

`decode-economic-news` 是一个面向财经新闻、产业政策、公司事件、A股板块、个股和ETF展望的 Codex Skill。它把新闻原稿、市场动量、美股/韩股映射、A股资金与情绪、回测和风险门禁组合成可复核的研究流程。

它学习的是“反常现象 → 数据 → 利益与约束 → 深层原因 → 传导 → 影响”的分析结构，不复制任何博主的标志性表达。

### 主要能力

- 新闻原稿与官方披露优先的因果分析
- 根据事件时钟动态决定先看新闻、外盘还是本地动量
- A股与美股、韩股同板块或同产业变量映射
- 科技、半导体、创新药、新能源、消费、金融、军工、周期等多板块预测
- ETF成份暴露、资金、折溢价和期权定位分析
- 5日/20日趋势信号、选股、扩展窗口回测和条件荐股
- Reuters/Bloomberg/FT 主动新闻雷达与逐站覆盖门禁
- 板块分数独立走样本检验；样本、单调性或当前分桶不合格时自动 `abstain`
- API、浏览器和缓存降级的数据采集流程

### 仓库结构

```text
.
├── SKILL.md                  # Codex Skill 入口与工作流
├── agents/openai.yaml        # Codex 界面元数据
├── references/               # 方法、数据源、门禁与输出规范
├── scripts/                  # 采集、分析、回测、复盘与安装工具
├── skill-dependencies.json   # 可机器读取的依赖声明
└── README.md                 # 使用与安装说明
```

仓库根目录就是 Skill 根目录，不需要再进入额外的 `skills/decode-economic-news/` 子目录。

### 强制依赖

本 Skill 依赖 `a-stock-data`，用于A股行情、基本面、资金流、公告、市场情绪和ETF期权数据。

| 项目 | 要求 | 说明 |
|---|---|---|
| Python | 3.10+ | 核心脚本仅使用标准库 |
| `a-stock-data` | 3.3.0+ | 必须安装并通过名称/版本校验 |
| Python数据包 | `mootdx>=0.10 requests pandas stockstats` | 完整调用 `a-stock-data` 数据层时需要 |

依赖声明位于 `skill-dependencies.json`。上游项目为 [simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data)。

### 安装

在本 Skill 根目录运行以下命令。

#### 情况一：目标环境已经安装 `a-stock-data`

```bash
python3 scripts/install.py
```

安装器会校验 `${CODEX_HOME:-~/.codex}/skills/a-stock-data/SKILL.md`，然后安装当前 Skill。

#### 情况二：从本地副本安装依赖，推荐用于可复现或离线安装

```bash
python3 scripts/install.py \
  --a-stock-data-source /absolute/path/to/a-stock-data
```

路径既可以是 `a-stock-data` 目录，也可以直接指向它的 `SKILL.md`。

如果收到的是离线 bundle，解压后 `decode-economic-news/` 与 `a-stock-data/` 会位于同一级目录。进入 `decode-economic-news/` 后直接运行 `python3 scripts/install.py`，安装器会自动识别同级依赖。

#### 情况三：明确允许从上游 GitHub 拉取依赖

```bash
python3 scripts/install.py --fetch-a-stock-data
```

该选项不会被默认启用。安装报告会记录下载文件的 SHA-256。由于 `main` 分支可变，正式分发前应审核该哈希对应的内容。

#### 安装完整A股 Python 数据依赖

```bash
python3 scripts/install.py \
  --fetch-a-stock-data \
  --install-python-deps
```

`--install-python-deps` 会使用运行安装器的同一个 Python 解释器执行 `pip install`。如 Codex 使用虚拟环境，请先激活该环境。

#### 自定义 Codex 目录

```bash
python3 scripts/install.py \
  --codex-home /absolute/path/to/codex-home \
  --a-stock-data-source /absolute/path/to/a-stock-data
```

#### 预演，不写入文件

```bash
python3 scripts/install.py \
  --a-stock-data-source /absolute/path/to/a-stock-data \
  --dry-run
```

### 安装器行为

1. 校验 Python 版本和 `skill-dependencies.json`。
2. 校验或安装 `a-stock-data`，依赖缺失时拒绝安装主 Skill。
3. 排除 `.env`、密钥、缓存、`work/` 和 `__pycache__/`。
4. 在目标目录创建临时副本并校验 `SKILL.md`。
5. 原子替换目标 Skill；已有版本被移动到 `skills/.backups/<skill>/<timestamp>/`，避免被当成重复 Skill 加载。
6. 输出 `skill.install-report/1` JSON，包含路径、版本、SHA-256、备份和缺失包。

可使用 `--report install-report.json` 保存报告。报告不写入密钥或代理凭据。

### 验证

```bash
cd "${CODEX_HOME:-$HOME/.codex}/skills/decode-economic-news/scripts"
python3 test_pipeline.py
python3 build_a_share_outlook_plan.py \
  --code 588080 --horizon 20d --session after_close \
  --event-state unknown --output /tmp/588080-plan.json
python3 list_browser_news_sites.py --tier core --topic '588080 最新事件' \
  --output /tmp/588080-browser-plan.json
python3 backtest_sector_signal.py work/588080-history.json \
  --horizon 20 --output /tmp/588080-signal-backtest.json
```

### 快速使用

安装后可以直接对 Codex 提问：

- “如何看待588080未来20日走势？”
- “参考美股和韩股，分析A股半导体板块是否接受外盘信号。”
- “用博主的因果流程解释这条创新药新闻，并筛选条件关注标的。”
- “为什么新闻是利好但板块反而下跌？”

### 配置与密钥

- `FRED_API_KEY`：FRED 数据，可选
- `SEC_USER_AGENT`：SEC EDGAR 请求身份，使用SEC时需要
- `IWENCAI_API_KEY`：问财语义搜索，可选
- `GDELT_PROXY_URL`、`CROSS_MARKET_PROXY_URL`：运行时代理，可选

仅通过环境变量或密钥管理器注入敏感信息。不要把密钥、Cookie、代理账号或浏览器配置写进 Skill、README、命令历史或安装报告。

### 数据与投资边界

行情、资金流、新闻情绪、外盘映射和模型分数都是证据或信号，不是收益保证。输出应包含观察日、周期、数据覆盖、比较基准、情景、失效条件和复核日。本项目不执行交易，也不替代适当性评估或持牌投资建议。

---

## English

`decode-economic-news` is a Codex Skill for economic news, industrial policy, company events, A-share sectors, named stocks, and ETF outlooks. It combines original-source research, market momentum, U.S./Korean read-through, A-share positioning, walk-forward backtests, and publication gates in a reproducible workflow.

It reproduces the analytical structure—contradiction, evidence, incentives and constraints, structural cause, transmission, and impact—without copying any creator's signature wording.

### Capabilities

- Causal analysis led by original releases and official disclosures
- Event-clock routing that determines whether news, overseas markets, or local momentum comes first
- U.S./Korean sector and shared-variable read-through for A-shares
- Multi-sector forecasts covering technology, semiconductors, innovative drugs, new energy, consumer, finance, defense, and cyclicals
- ETF exposure, flow, premium/discount, and option-positioning analysis
- 5-day/20-day trend signals, screening, expanding walk-forward backtests, and gated conditional recommendations
- Proactive Reuters/Bloomberg/FT radar with explicit per-publisher coverage gates
- Separate walk-forward validation of sector scores with mandatory `abstain` for sparse, non-monotonic, or neutral signals
- Reproducible API, browser, cache, and degraded-source workflows

### Repository layout

```text
.
├── SKILL.md                  # Codex Skill entry point and workflow
├── agents/openai.yaml        # Codex interface metadata
├── references/               # Methods, sources, gates, and output contracts
├── scripts/                  # Collection, analysis, backtest, review, and install tools
├── skill-dependencies.json   # Machine-readable dependency declaration
└── README.md                 # Installation and usage guide
```

The repository root is the Skill root; no extra `skills/decode-economic-news/` wrapper is required.

### Required dependency

This Skill requires `a-stock-data` for A-share prices, fundamentals, fund flow, announcements, market mood, and ETF options.

| Item | Requirement | Notes |
|---|---|---|
| Python | 3.10+ | Core scripts use the standard library |
| `a-stock-data` | 3.3.0+ | Must be installed and pass name/version validation |
| Python packages | `mootdx>=0.10 requests pandas stockstats` | Needed for the full `a-stock-data` adapter set |

The machine-readable declaration is `skill-dependencies.json`. The reviewed upstream project is [simonlin1212/a-stock-data](https://github.com/simonlin1212/a-stock-data).

### Installation

Run commands from this Skill's root directory.

#### If `a-stock-data` is already installed

```bash
python3 scripts/install.py
```

The installer validates `${CODEX_HOME:-~/.codex}/skills/a-stock-data/SKILL.md` before installing this Skill.

#### Reproducible/offline installation from a local dependency copy

```bash
python3 scripts/install.py \
  --a-stock-data-source /absolute/path/to/a-stock-data
```

The path may point to the `a-stock-data` directory or directly to its `SKILL.md`.

In the offline bundle, `decode-economic-news/` and `a-stock-data/` are sibling directories. After extraction, enter `decode-economic-news/` and run `python3 scripts/install.py`; the installer discovers the sibling dependency automatically.

#### Explicitly fetch the reviewed upstream dependency

```bash
python3 scripts/install.py --fetch-a-stock-data
```

Network fetching is never enabled implicitly. The report records the downloaded file's SHA-256. Because the upstream `main` branch is mutable, review that digest and content before redistribution.

#### Install the full A-share Python package set

```bash
python3 scripts/install.py \
  --fetch-a-stock-data \
  --install-python-deps
```

`--install-python-deps` runs `pip install` through the same Python interpreter that runs the installer. Activate the environment Codex will use first.

#### Custom Codex home

```bash
python3 scripts/install.py \
  --codex-home /absolute/path/to/codex-home \
  --a-stock-data-source /absolute/path/to/a-stock-data
```

#### Dry run

```bash
python3 scripts/install.py \
  --a-stock-data-source /absolute/path/to/a-stock-data \
  --dry-run
```

### Installer guarantees

1. Validate Python and `skill-dependencies.json`.
2. Verify or install `a-stock-data`; refuse the main installation when it is missing.
3. Exclude `.env`, secrets, caches, `work/`, and `__pycache__/`.
4. Stage and validate the target `SKILL.md` before replacement.
5. Replace atomically and preserve an existing version under `skills/.backups/<skill>/<timestamp>/`, outside normal Skill discovery.
6. Emit a `skill.install-report/1` JSON report with versions, SHA-256 digests, backups, and missing packages.

Use `--report install-report.json` to save the report. It never records keys or proxy credentials.

### Verification

```bash
cd "${CODEX_HOME:-$HOME/.codex}/skills/decode-economic-news/scripts"
python3 test_pipeline.py
python3 build_a_share_outlook_plan.py \
  --code 588080 --horizon 20d --session after_close \
  --event-state unknown --output /tmp/588080-plan.json
python3 list_browser_news_sites.py --tier core --topic '588080 latest material event' \
  --output /tmp/588080-browser-plan.json
python3 backtest_sector_signal.py work/588080-history.json \
  --horizon 20 --output /tmp/588080-signal-backtest.json
```

### Example prompts

- “What is the 20-day outlook for 588080?”
- “Compare the A-share semiconductor sector with U.S. and Korean peers.”
- “Explain this innovative-drug headline with the creator-derived causal workflow and screen conditional candidates.”
- “Why did the sector fall after apparently positive news?”

### Configuration and secrets

- `FRED_API_KEY`: optional FRED access
- `SEC_USER_AGENT`: required when querying SEC EDGAR
- `IWENCAI_API_KEY`: optional iWencai semantic search
- `GDELT_PROXY_URL`, `CROSS_MARKET_PROXY_URL`: optional runtime-only proxies

Inject secrets only through environment variables or a secret manager. Never store API keys, cookies, authenticated proxy URLs, or browser profiles in the Skill, README, shell history, or installation report.

### Data and investment boundaries

Prices, fund flows, news sentiment, cross-market mappings, and model scores are evidence or signals—not return guarantees. Published outputs must state the as-of date, horizon, coverage, benchmark, scenarios, invalidation conditions, and review date. This project does not execute trades or replace suitability assessment or licensed financial advice.
