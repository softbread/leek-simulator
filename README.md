# Leek Simulator

面向 **A股与美股** 的多智能体市场情绪与价格路径推演系统，借鉴 MiroFish 的「现实种子 → 数字世界 → 群体演化」思路。

输入新闻、讨论、近期价量和市场环境，先构建并保存 `world_state` 与当前情绪快照，再让 500-2000 名具有不同策略、风险偏好、资金和记忆的交易者互动。交易需求通过价格冲击模型形成后续价格路径，而不是直接把新闻情绪画成价格曲线。

**这是情景模拟工具，不是经过预测准确率验证的荐股系统。** 当前交易者使用规则驱动的 ABM 策略，并非 1000 个独立调用 LLM 的投资者；可选 LLM 用于结果解读与分析师问答。

## 两个市场模块

| 配置 | A股 `cn_equity` | 美股 `us_equity` |
| --- | --- | --- |
| 场景 | 默认市场，单只股票 + 板块 + 大盘上下文 | 独立业务模块，模拟已完成外部基本面筛选的股票 |
| 货币 / 时区 | CNY / Asia/Shanghai | USD / America/New_York，支持夏令时 |
| 每日步数 | 48 个 5 分钟 tick，含午休 | 78 个 5 分钟 tick，常规交易时段 |
| 新闻 | 东方财富股票、行业与大盘资讯 | CNBC RSS；Bloomberg 等授权新闻导入或自有 feed |
| 社交情绪 | 用户登录后的雪球讨论 | X、Reddit；Robinhood Social 等授权讨论导入 |
| 默认策略 | 动量 30%、宏观新闻 25%、基本面 20%、均值回归 15%、被动 10% | 动量 40%、宏观新闻 20%、社交逆向 15%、均值回归 15%、被动 10% |
| 基本面 | 保留原有策略因素 | 不生成基本面交易者，不计算估值贡献 |
| 价格限制 | 简化的每日 ±10% 限制 | 无 A股式固定日涨跌幅限制，保留每 tick 数值边界 |

默认每次运行 **1000 名交易者、3 个交易日**，支持 500-2000 人、1-5 日与策略权重覆盖。人群与策略比例是内置模拟假设，不是经过校准的真实投资者分布。

## 情绪与世界模型

- **大盘、板块、个股分开建模。** 大盘使用独立关键词与可选市场宽度数据；个股使用股票相关资讯、讨论和价量，避免把个股热度当成整个市场的情绪。
- **先观测，再模拟。** 时间戳化的起点情绪、历史价量与数据来源会保存；未来情绪和价格属于模拟输出，不冒充实时观测。
- **新闻影响会过期。** 默认从原始发布时间起线性衰减，72 个自然小时后归零；重新导入不会重置新闻年龄。可通过新闻元数据 `sentiment_lifetime_hours` 覆盖。这是模型假设，不是所有新闻的普遍规律。
- **交易者读取世界模型。** 每轮经历 `observe → decide → act → remember`，结合世界因素、个人持仓与记忆、上一轮同伴信念作出买卖或持有决策。
- **价格与情绪相互反馈。** 模型考虑资金容量、盈亏体验、隔夜冲动和群体信念变化；情绪周期由状态推断，不按固定时钟强制切换。
- **美股更强调个股社交情绪。** 当前个股观测采用社交 85% / 新闻 15% 的实验权重；英语文本使用关键词、否定与显式讽刺标记等启发式处理，不等同于完整语义理解。

详见 [情绪周期模型](docs/sentiment-cycle-model.md) 与 [1000 人群体思考趋势实验](docs/experiments/1000-agent-thinking-trend.md)。

## 快速开始

### 1. 环境与依赖

需要 Node.js 20.19+（或 22.12+）、Python 3.11/3.12 和 `uv`。在仓库根目录执行：

```bash
npm run setup:all
cp .env.example .env
```

不使用 LLM 时，将 `.env` 中的 `LLM_API_KEY` 留空或删除，**不要保留示例占位密钥**。分析师会回退到规则摘要。当前市场主流程不需要 Zep 或 OASIS，旧版相关配置不必填写。

如需 LLM 分析师，配置兼容 OpenAI SDK 的服务：

```env
LLM_API_KEY=your_real_api_key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus
```

### 2. 安装雪球浏览器（仅 A股真实讨论采集需要）

```bash
cd backend
uv run playwright install chromium
cd ..
```

美股模块和独立导入样例无需雪球登录或 Chromium。

### 3. 启动

```bash
npm run dev
```

- 前端：[localhost:3000](http://localhost:3000)
- 后端：[localhost:5001](http://localhost:5001)

## 每只股票需要准备什么

| 输入 | 用途 |
| --- | --- |
| 市场、ticker、股票名、板块 | 选择市场规则及股票、行业查询范围 |
| 初始价格、流通规模档位 | 设置价格起点与合成流动性；当前不自动获取实时股价 |
| 市场环境、模拟天数、人数、随机种子 | 设置情景假设与可复现参数；市场环境不是实测情绪 |
| 快照时间、近期价量 | 可选的起点观测；时间戳应带时区，成交量单位为股 |
| 大盘关键词、市场宽度 | 独立的大盘情绪输入；可选涨跌家数等观测 |
| 新闻与社交讨论 | 构建有来源、时间和作用范围的情绪信号 |
| 上传材料、策略比例覆盖 | 可选的额外种子与人群配置 |

详细字段、格式与示例见 [A股 / 情绪快照设置指南](docs/share-setup-guide.md) 和 [美股设置指南](docs/us-equity-setup.md)。上传材料是可选补充，不需要先构建通用知识图谱。

## 运行流程

1. **场景设置：** 选择 A股或 US Equities，输入股票、价格、市场假设和观测种子。切换市场会重置股票输入与策略比例。
2. **构建世界：** 获取或导入数据，检查来源状态，保存 `world_state` 与情绪快照。这一步在 `prepare` 和 `start` 之前执行。
3. **人群准备：** 基于已保存的世界生成代理人、事件冲击与运行上下文，确认人群配置。
4. **运行模拟：** 按 5 分钟推进，聚合交易需求、更新价格与持仓，并记录世界演化和交易者记忆。
5. **结果与问答：** 查看价格、成交量、情绪与社交热度、回撤和波动、策略表现、事件归因、群体信念与代表性代理人记忆；分析师问答基于该次运行的存储数据。

界面分为场景设置、世界与人群配置、实时模拟、结果与聊天四个页面。

## 数据源设置

### A股：东方财富与雪球

东方财富提供新闻补充；雪球用于大盘、板块和个股讨论情绪。真实雪球采集需要用户主动登录：

1. 在配置页点击「打开雪球登录」。
2. 在本机弹出的可见浏览器中自行完成登录。
3. 回到页面点击「我已完成登录」。
4. 构建 `world_state`，查看情绪快照与来源状态，再生成市场上下文并运行。

后续抓取通过 **headless Chromium** 复用登录态，不需要把密码交给系统。登录或抓取不可用时，可使用标记为 `news_proxy` 的新闻代理信号继续运行；它不是真实雪球情绪，不能据此声称已测得当前散户观点。

登录态保存在 `backend/uploads/xueqiu_auth/storage_state.json` 与 `session_meta.json`。这些文件含敏感会话信息，不应提交或分享；可在页面中清除登录态。远程部署需要另行解决可见浏览器登录访问。

### 美股：新闻与社交分开接入

主页选择 **US Equities**。基本面筛选在系统外完成；本模块只接收筛选后的 ticker，研究情绪、交易行为与价格演化。

| 来源 | 当前支持范围 |
| --- | --- |
| CNBC | 尽力获取 Top News RSS，不保证每只股票都有报道 |
| Bloomberg | 规范化新闻导入，或用户自己的授权 feed 服务；不是内置 Bloomberg 公共 API |
| X | 使用服务端 bearer token 查询近期讨论 |
| Reddit | 使用服务端 OAuth access token 查询讨论 |
| Robinhood Social | 授权导出内容导入；没有实现原生 API 连接器 |

可选连接器在根目录 `.env` 配置，密钥只放后端：

```env
US_X_BEARER_TOKEN=
US_REDDIT_ACCESS_TOKEN=
US_REDDIT_USER_AGENT=LeekSimulator/0.1 (market research)
US_NEWS_FEED_URL=
US_NEWS_FEED_TOKEN=
```

令牌申请与更新需在系统外完成。自有新闻服务应返回与选定股票、板块或大盘相关的 `{"news_items": [...]}`。

美股界面默认 `import_only`，可粘贴含 `news_items` / `social_posts` 的种子 JSON，数据源不会联网；选择 `live_and_imported` 才启用可用连接器。缺失权限或上游失败会记录来源状态，不会伪造社交帖子。美股模块不调用东方财富或雪球。

请保留原始发布时间、来源及 `market` / `sector` / `ticker` 范围，示例格式见 [美股设置指南](docs/us-equity-setup.md)。

## 架构与 MiroFish 适配

后端使用 Flask，前端使用 Vue 3 / Vite。共享仿真核心 `market_sim` 仅依赖 Python 标准库，市场差异与网络采集分别隔离：

```text
backend/
  market_sim/                  世界、情绪、交易者、记忆、价格引擎、结果
    adapters/mirofish.py        MiroFish Python / 子进程适配接口
  markets/
    cn_equity/                 A股规则与默认配置
    us_equity/                 美股规则与英语社交文本处理
  app/
    api/market.py              HTTP 接口
    services/market/           数据源、生命周期、持久化、分析师
    services/xueqiu_browser.py 雪球交互登录与无头抓取
    models/market.py           运行与上传存储
  examples/                    可独立运行的规范化种子示例
frontend/src/views/            场景、配置、模拟、结果页面
docs/                         输入指南、模型说明、上游对照与实验
```

适配器支持逐轮执行、重置、导出和替换交易策略；**不会自动注册成上游 MiroFish 的平台插件**。接入宿主需要显式连接，详见 [市场环境架构](docs/market-architecture.md) 与 [MiroFish 代码对照](docs/mirofish-upstream.md)。

运行数据保存在 `backend/uploads/market_runs/<run_id>/`，包括 `world_state.json`、`sentiment_snapshot.json`、`prepared_context.json`、`world_timeline.json`、`agent_states.json`、`action_ledger.json`、`world_final.json` 和 `results.json`。重新构建世界会清除该次运行的下游结果；情景对比应创建不同运行。

固定随机种子和**相同的已保存输入**可复现结果；重新抓取实时新闻不保证得到相同输入。

## 独立运行与验证

以下命令从仓库根目录开始，使用规范化示例，不抓取实时数据：

```bash
cd backend
uv run python -m market_sim examples/market_mirofish.json --output /tmp/market-run.json
uv run python -m market_sim examples/us_equity.json --output /tmp/us-equity-result.json
uv run python scripts/check_thinking_trend.py --agents 1000 --output /tmp/leek-thinking-trend.json
uv run pytest tests
cd ..
npm run build
```

美股示例使用合成历史输入运行 1000 人、3 个交易日（234 tick），不是对示例股票的真实预测。群体趋势实验用于检查规则代理人的信念传播与行为差异，不能证明预测准确率或人类级思考能力。

## API 概览

| 方法与路径 | 用途 |
| --- | --- |
| `GET /api/market/profiles` | 市场规则与默认配置 |
| `POST /api/market/runs` | 创建场景，接受 `market`、`data_mode`、`seed_inputs` 等配置 |
| `GET /api/market/runs` | 运行列表 |
| `GET /api/market/runs/:run_id` | 场景与运行详情 |
| `POST /api/market/runs/:run_id/build-world` | 构建并保存世界与起点情绪 |
| `POST /api/market/runs/:run_id/prepare` | 生成交易者与运行上下文 |
| `POST /api/market/runs/:run_id/start` | 开始模拟 |
| `GET /api/market/runs/:run_id/status` | 执行进度 |
| `GET /api/market/runs/:run_id/results` | 图表序列、指标与报告 |
| `POST /api/market/runs/:run_id/chat` | 运行数据驱动的分析师问答 |
| `GET /api/market/runs/:run_id/timeline` | 世界演化时间线 |
| `GET /api/market/runs/:run_id/agents/:agent_id` | 代理人状态与记忆 |
| `POST /api/market/uploads` | 上传可选种子材料 |
| `GET /api/market/xueqiu/auth/status` | 雪球登录状态 |
| `POST /api/market/xueqiu/auth/start` | 打开登录浏览器 |
| `POST /api/market/xueqiu/auth/complete` | 保存登录会话 |
| `POST /api/market/xueqiu/auth/logout` | 清除登录会话 |

## 模型边界

- 当前不模拟完整订单簿、真实交易对手、完整费用及交收约束；代理人资金与流动性参数是合成假设。
- A股统一 ±10% 日限制不能代表所有板块与特殊股票规则；美股不模拟真实熔断规则、盘前盘后、期权或借券做空。
- 跳过周末，但没有完整交易所节假日及提前收盘日历。
- 文本情绪是启发式估计，来源覆盖、重复内容、采集时间与登录权限都会影响结果；缺失或代理信号必须与真实观测区分。
- LLM 可用于解读，但不会把规则模拟变成经验证的市场预测。结果仅供研究、情景比较与模型实验。

项目基于 MiroFish 代码演化，保留上游归属；许可证为 [AGPL-3.0](LICENSE)。
