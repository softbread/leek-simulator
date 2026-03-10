# Leek Simulator

面向 A 股场景的多智能体市场推演系统。

此项目借用了MiroFish关于“通用图谱/舆情推演”的代码，切换为“单股票 + 板块上下文”的 A 股仿真产品：输入股票、板块、市场环境和代理人数，系统会构造 500-2000 名带不同年龄、风险偏好、财富阶段和交易策略的代理人，并输出价格路径、成交、情绪、关键事件和分析师解读。

## 核心能力

- 单次运行模拟 1 只 A 股标的，叠加 1 个行业/板块上下文
- 代理人规模 500-2000，默认 1000
- 代理人默认覆盖 5 类策略：
  - FOMO / 动量散户
  - 宏观新闻追逐者
  - 基本面交易者
  - 均值回归型抄底者
  - 低频被动散户
- 东方财富资讯接入：
  - 抓取股票与板块的最新资讯，转为市场 shock
- 雪球情绪接入：
  - 通过浏览器登录态抓取真实讨论数据
  - 如果未登录或抓取失败，会自动回退到基于新闻上下文的情绪代理信号
- 输出结果包含：
  - Price Path
  - Volume
  - Sentiment
  - Xueqiu Buzz
  - Population Summary
  - Narrative Report
  - Analyst Chat

## 当前工作流

1. 创建市场场景
   - 填写 ticker、股票名、板块、初始价格、市场环境、交易日天数、代理人数
   - 可选上传研究报告/公告摘要/纪要作为额外输入
2. 初始化市场环境
   - 抓取东方财富资讯
   - 连接雪球登录态并抓取讨论情绪
   - 生成代理人群体画像和 market shock
3. 运行仿真
   - 以 5 分钟 tick 离散推进
   - 聚合代理人的 buy / sell / hold 行为，映射为价格影响
4. 查看结果
   - 图表、关键事件、群体构成、Narrative Report 和 Analyst Chat

## 技术实现

### 后端

- Flask API
- Python agent-based price-impact engine
- 东方财富资讯 JSONP 接口
- 雪球浏览器登录态抓取
- 可选 LLM 市场分析师

### 前端

- Vue 3
- Vite
- Axios
- SVG 折线图组件

## 目录概览

- `backend/app/api/market.py`
  - 市场仿真 API
- `backend/app/services/market_simulation.py`
  - 东方财富 / 雪球数据归一化、代理人生成、仿真引擎、报告与问答
- `backend/app/services/xueqiu_browser.py`
  - 雪球登录浏览器与 headless 抓取会话
- `backend/app/models/market.py`
  - 运行状态、场景、上传文件和结果持久化
- `frontend/src/views/Home.vue`
  - 市场场景创建页
- `frontend/src/views/MarketConfigView.vue`
  - 数据源与人群初始化页
- `frontend/src/views/MarketSimulationView.vue`
  - 仿真执行页
- `frontend/src/views/MarketResultsView.vue`
  - 结果与分析师页

## 环境要求

- Node.js 20.19+ 推荐
  - 当前 Vite 7 对 20.19 以下版本会给出警告
- Python 3.11 或 3.12
- `uv`
- Chromium 浏览器内核
  - 用于雪球登录与后续 headless 抓取

## 快速开始

### 1. 安装依赖

```bash
npm run setup
cd backend && uv sync
cd ..
```

### 2. 安装 Playwright Chromium

这是雪球登录/抓取所必需的步骤。

```bash
cd backend
uv run playwright install chromium
cd ..
```

### 3. 配置环境变量

复制 `.env.example` 到 `.env`。

LLM 不是必需的；如果不配置，分析师会使用规则摘要回答。

```env
LLM_API_KEY=your_api_key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
LLM_MODEL_NAME=qwen-plus
```

### 4. 启动服务

```bash
npm run dev
```

地址：

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:5001`

## 雪球登录说明

### 为什么需要登录

雪球对服务端直连抓取有较强的 WAF/登录限制。当前实现改为：

1. 用户先在本机弹出的浏览器窗口中登录雪球
2. 后端保存登录后的 `storage_state`
3. 后续抓取通过 headless Chromium 复用该登录态执行

这样可以显著提高真实讨论数据抓取的稳定性。

### 使用方式

在“市场环境与人群初始化”页面：

1. 点击“打开雪球登录”
2. 在弹出的浏览器窗口里完成雪球登录
3. 回到页面点击“我已完成登录”
4. 再点击“生成市场上下文”

如果未登录：

- 系统仍可运行
- 但雪球情绪会退回到基于新闻与场景的代理信号，不是真实抓取数据

### 登录态存储位置

登录态默认保存在：

- `backend/uploads/xueqiu_auth/storage_state.json`
- `backend/uploads/xueqiu_auth/session_meta.json`

如果需要清除登录态，可以在页面中点击“清除登录态”。

## API 概览

### 市场场景

- `POST /api/market/runs`
- `GET /api/market/runs`
- `GET /api/market/runs/:run_id`

### 准备与运行

- `POST /api/market/runs/:run_id/prepare`
- `POST /api/market/runs/:run_id/start`
- `GET /api/market/runs/:run_id/status`
- `GET /api/market/runs/:run_id/results`
- `POST /api/market/runs/:run_id/chat`

### 文件上传

- `POST /api/market/uploads`

### 雪球登录态

- `GET /api/market/xueqiu/auth/status`
- `POST /api/market/xueqiu/auth/start`
- `POST /api/market/xueqiu/auth/complete`
- `POST /api/market/xueqiu/auth/logout`

## 测试

后端核心测试：

```bash
cd backend
uv run pytest tests/test_market_simulation.py
```

前端构建检查：

```bash
cd frontend
npm run build
```

## 注意事项

- 东方财富资讯是 live 抓取，返回结果会随时间变化
- 雪球真实抓取依赖浏览器登录态和 Chromium 安装
- 如果 Playwright 未安装，页面会提示无法打开雪球登录浏览器
- 如果未配置 LLM，Analyst Chat 会自动回退为规则回答
