<template>
  <div class="market-home">
    <section class="hero">
      <div class="hero-copy">
        <div class="eyebrow">MARKET CROWD LAB</div>
        <h1>A股与美股，独立市场环境下的群体情绪推演。</h1>
        <p>
          输入已筛选的股票、板块、市场环境和代理人数量，选择对应市场的新闻与社交来源，
          先构建一个由新闻、讨论和价格带驱动的平行市场 world_state，再让 500-2000 名代理人在 5 分钟 tick 上共同演化价格、成交与情绪。
        </p>
      </div>

      <div class="hero-panel">
        <div class="panel-title">默认人群分布</div>
        <div class="mix-grid">
          <div v-for="item in mixCards" :key="item.key" class="mix-card">
            <span class="mix-label">{{ item.label }}</span>
            <span class="mix-value">{{ form.trader_mix_overrides[item.key] }}%</span>
          </div>
        </div>
      </div>
    </section>

    <section class="workspace">
      <div class="form-card">
        <div class="card-header">
          <div>
            <div class="section-eyebrow">Step 1</div>
            <h2>建立市场场景</h2>
          </div>
          <span class="status-chip">{{ files.length ? `${files.length} 份补充材料` : '可选上传研究/新闻' }}</span>
        </div>

        <div class="grid">
          <label class="field">
            <span>市场业务模块</span>
            <select v-model="form.market" @change="changeMarket">
              <option value="cn_equity">A股</option>
              <option value="us_equity">US Equities（已做基本面筛选）</option>
            </select>
          </label>
          <label class="field">
            <span>股票代码</span>
            <input v-model="form.ticker" :placeholder="form.market === 'us_equity' ? 'NVDA / AAPL' : '600519 / SH600519'" />
          </label>
          <label class="field">
            <span>股票名称</span>
            <input v-model="form.stock_name" :placeholder="form.market === 'us_equity' ? 'NVIDIA' : '贵州茅台'" />
          </label>
          <label class="field">
            <span>行业/板块</span>
            <input v-model="form.sector_name" :placeholder="form.market === 'us_equity' ? 'semiconductors' : '白酒 / 食品饮料'" />
          </label>
          <label class="field">
            <span>大盘情绪检索词（独立于个股）</span>
            <input v-model="form.market_keyword" :placeholder="form.market === 'us_equity' ? 'S&P 500' : 'A股 / 沪深300'" />
          </label>
          <label class="field">
            <span>初始价格（{{ form.market === 'us_equity' ? 'USD' : 'CNY' }}）</span>
            <input v-model.number="form.starting_price" type="number" min="0.1" step="0.01" />
          </label>
          <label class="field">
            <span>流通盘规模</span>
            <select v-model="form.float_shares_band">
              <option value="small">small</option>
              <option value="mid">mid</option>
              <option value="large">large</option>
              <option value="mega">mega</option>
            </select>
          </label>
          <label class="field">
            <span>市场环境</span>
            <select v-model="form.market_regime">
              <option value="bullish">bullish</option>
              <option value="neutral">neutral</option>
              <option value="bearish">bearish</option>
              <option value="volatile">volatile</option>
            </select>
          </label>
          <label class="field">
            <span>交易日天数</span>
            <input v-model.number="form.horizon_days" type="number" min="1" max="5" />
          </label>
          <label class="field">
            <span>代理人数</span>
            <input v-model.number="form.agent_count" type="number" min="500" max="2000" step="100" />
          </label>
        </div>

        <template v-if="form.market === 'us_equity'">
          <p>只模拟新闻、社交情绪和交易反馈；不再进行基本面打分。使用纽约时间，完整常规交易日为 78 个 tick。</p>
          <label class="field">
            <span>数据模式</span>
            <select v-model="form.data_mode">
              <option value="import_only">仅导入数据（可复现，无网络请求）</option>
              <option value="live_and_imported">实时 + 导入（CNBC / 已配置的 X、Reddit、授权新闻源）</option>
            </select>
          </label>
          <label class="field textarea">
            <span>美股新闻与社交种子（JSON 对象）</span>
            <textarea v-model="usSeedsText" rows="7" placeholder='{"news_items":[],"social_posts":[{"source":"reddit","scope":"ticker","text":"$NVDA bullish breakout","published_at":"2026-10-19T10:00:00-04:00"}]}' />
            <small>Bloomberg、Robinhood Social 可通过导入接入。请填写原始发布时间；不会绕过付费或登录限制。</small>
          </label>
        </template>

        <label class="field textarea">
          <span>行情快照时间（可选；留空为构建世界时）</span>
          <input v-model="snapshotTime" placeholder="2026-10-19T15:00:00+08:00" />
        </label>
        <label class="field textarea">
          <span>近期行情（可选，JSON 数组）</span>
          <textarea v-model="recentPricesText" rows="5" placeholder='[{"timestamp":"2026-10-19T14:55:00+08:00","close":100,"volume":12000}]' />
          <small>按时间递增；价格使用所选市场货币，成交量单位股。建议时间带时区；行情用于起点动量。</small>
        </label>

        <label class="field textarea">
          <span>补充说明</span>
          <textarea v-model="form.notes" rows="5" placeholder="例如：市场对消费修复预期升温，但担心高估值兑现压力。" />
        </label>
        <label class="field textarea">
          <span>大盘宽度数据（可选，JSON 数组；不使用个股数据代替）</span>
          <textarea v-model="marketBreadthText" rows="4" placeholder='[{"timestamp":"2026-10-19T15:00:00+08:00","advancers":3000,"decliners":1800,"limit_up":70,"limit_down":10,"promotion_rate":0.55,"source":"你的复盘数据源"}]' />
          <small>用于大盘周期候选判断。美股使用上涨/下跌家数；A股另使用涨跌停数和可选晋级率。请使用同一股票池。</small>
        </label>

        <div class="mix-section">
          <div class="mix-header">
            <span>代理人结构覆盖</span>
            <button class="ghost-btn" @click="resetMix">恢复默认</button>
          </div>
          <div class="sliders">
            <label v-for="item in mixCards" :key="item.key" class="slider-row">
              <span>{{ item.label }}</span>
              <input v-model.number="form.trader_mix_overrides[item.key]" type="range" min="0" max="60" />
              <strong>{{ form.trader_mix_overrides[item.key] }}%</strong>
            </label>
          </div>
          <div class="mix-note" :class="{ invalid: mixTotal !== 100 }">
            当前总和 {{ mixTotal }}%。系统按权重归一化运行，建议维持 100%。
          </div>
        </div>

        <div class="upload-box" @click="fileInput?.click()">
          <input ref="fileInput" type="file" multiple accept=".pdf,.md,.markdown,.txt" hidden @change="handleFileChange" />
          <div class="upload-copy">
            <span class="upload-title">可选上传补充材料</span>
            <span class="upload-hint">研究报告、公告摘要、访谈纪要都可作为 shock builder 的补充输入。</span>
          </div>
          <div class="file-pills">
            <span v-for="file in files" :key="file.name + file.size" class="file-pill">
              {{ file.name }}
            </span>
          </div>
        </div>

        <div v-if="error" class="error-box">{{ error }}</div>

        <div class="actions">
          <button class="primary-btn" :disabled="submitting || !canSubmit" @click="handleCreateRun">
            {{ submitting ? '初始化中...' : '创建市场推演' }}
          </button>
        </div>
      </div>

      <div class="history-card">
        <div class="card-header">
          <div>
            <div class="section-eyebrow">Recent Runs</div>
            <h2>最近市场场景</h2>
          </div>
        </div>

        <div class="history-list">
          <button
            v-for="run in recentRuns"
            :key="run.run_id"
            class="history-item"
            @click="openRun(run)"
          >
            <div>
              <strong>{{ run.scenario.stock_name }}</strong>
              <div class="history-meta">{{ run.scenario.ticker }} / {{ run.scenario.market_regime }}</div>
            </div>
            <span class="history-status">{{ run.status }}</span>
          </button>
          <div v-if="!recentRuns.length" class="empty-state">还没有市场推演记录。</div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createMarketRun, getMarketProfiles, listMarketRuns, uploadMarketDocuments } from '../api/market'

const router = useRouter()
const fileInput = ref(null)
const files = ref([])
const recentRuns = ref([])
const submitting = ref(false)
const error = ref('')
const snapshotTime = ref('')
const recentPricesText = ref('')
const marketBreadthText = ref('')
const usSeedsText = ref('')
const marketProfiles = ref([])

const defaultMix = {
  fomo_momentum: 30,
  macro_news: 25,
  fundamental: 20,
  mean_reversion: 15,
  passive_retail: 10
}

const form = ref({
  market: 'cn_equity',
  data_mode: 'live_and_imported',
  ticker: '600519',
  stock_name: '贵州茅台',
  sector_name: '白酒',
  market_keyword: 'A股',
  starting_price: 1397,
  float_shares_band: 'mega',
  market_regime: 'volatile',
  horizon_days: 3,
  agent_count: 1000,
  notes: '',
  trader_mix_overrides: { ...defaultMix }
})

const cnMixCards = [
  { key: 'fomo_momentum', label: 'FOMO / 动量' },
  { key: 'macro_news', label: '宏观新闻追逐' },
  { key: 'fundamental', label: '基本面交易' },
  { key: 'mean_reversion', label: '均值回归' },
  { key: 'passive_retail', label: '低频散户' }
]
const mixCards = computed(() => form.value.market === 'us_equity'
  ? cnMixCards.filter(item => item.key !== 'fundamental').concat([{ key: 'social_contrarian', label: '社交逆向交易' }])
  : cnMixCards)

const changeMarket = () => {
  form.value.ticker = ''
  form.value.stock_name = ''
  form.value.sector_name = ''
  form.value.starting_price = 0
  form.value.market_keyword = form.value.market === 'us_equity' ? 'S&P 500' : 'A股'
  form.value.data_mode = form.value.market === 'us_equity' ? 'import_only' : 'live_and_imported'
  snapshotTime.value = ''
  recentPricesText.value = ''
  marketBreadthText.value = ''
  files.value = []
  resetMix()
}

const canSubmit = computed(() => {
  return form.value.ticker && form.value.stock_name && form.value.sector_name && form.value.starting_price > 0
})

const mixTotal = computed(() => {
  return Object.values(form.value.trader_mix_overrides).reduce((sum, value) => sum + Number(value || 0), 0)
})

const handleFileChange = (event) => {
  files.value = Array.from(event.target.files || [])
}

const resetMix = () => {
  const weights = marketProfiles.value.find(item => item.market === form.value.market)?.archetypes
  form.value.trader_mix_overrides = weights ? Object.fromEntries(Object.entries(weights).map(([key, value]) => [key, Math.round(value * 100)]))
    : form.value.market === 'us_equity' ? { fomo_momentum: 40, macro_news: 20, social_contrarian: 15, mean_reversion: 15, passive_retail: 10 } : { ...defaultMix }
}

const loadRuns = async () => {
  try {
    const response = await listMarketRuns()
    recentRuns.value = response.data || []
  } catch (err) {
    console.warn('load runs failed', err)
  }
}

const openRun = (run) => {
  if (run.status === 'completed') {
    router.push({ name: 'MarketResults', params: { runId: run.run_id } })
    return
  }
  if (run.status === 'running') {
    router.push({ name: 'MarketSimulation', params: { runId: run.run_id } })
    return
  }
  router.push({ name: 'MarketConfig', params: { runId: run.run_id } })
}

const handleCreateRun = async () => {
  submitting.value = true
  error.value = ''
  try {
    const recentPrices = recentPricesText.value.trim() ? JSON.parse(recentPricesText.value) : []
    if (!Array.isArray(recentPrices)) throw new Error('近期行情必须是 JSON 数组')
    const marketSnapshot = { recent_prices: recentPrices }
    if (marketBreadthText.value.trim()) {
      const breadth = JSON.parse(marketBreadthText.value)
      if (!Array.isArray(breadth)) throw new Error('大盘宽度数据必须是 JSON 数组')
      marketSnapshot.market_breadth = breadth
    }
    if (snapshotTime.value.trim()) marketSnapshot.as_of = snapshotTime.value.trim()
    let optionalUploadIds = []
    if (files.value.length) {
      const uploadResponse = await uploadMarketDocuments(files.value)
      optionalUploadIds = (uploadResponse.data || []).map((item) => item.upload_id)
    }

    const response = await createMarketRun({
      ...form.value,
      seed_inputs: form.value.market === 'us_equity' && usSeedsText.value.trim() ? JSON.parse(usSeedsText.value) : {},
      market_snapshot: marketSnapshot,
      optional_upload_ids: optionalUploadIds
    })
    router.push({ name: 'MarketConfig', params: { runId: response.data.run_id } })
  } catch (err) {
    error.value = err.message || '创建市场推演失败'
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await loadRuns()
  try {
    const response = await getMarketProfiles()
    marketProfiles.value = response.data
  } catch (error) { console.warn('market profiles unavailable', error) }
})
</script>

<style scoped>
.market-home {
  min-height: 100vh;
  padding: 32px;
  background:
    radial-gradient(circle at top left, rgba(15, 118, 110, 0.16), transparent 28%),
    radial-gradient(circle at right 10% top 12%, rgba(234, 179, 8, 0.18), transparent 24%),
    linear-gradient(180deg, #f7faf8 0%, #eef4f2 100%);
  color: #072723;
}

.hero,
.workspace {
  max-width: 1400px;
  margin: 0 auto;
}

.hero {
  display: grid;
  grid-template-columns: 1.4fr 0.9fr;
  gap: 28px;
  margin-bottom: 28px;
}

.hero-copy,
.hero-panel,
.form-card,
.history-card {
  border-radius: 32px;
  border: 1px solid rgba(7, 39, 35, 0.08);
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(14px);
  box-shadow: 0 18px 45px rgba(15, 23, 42, 0.06);
}

.hero-copy {
  padding: 38px;
}

.hero-copy h1 {
  font-size: clamp(2.6rem, 4.2vw, 4.5rem);
  line-height: 1.02;
  letter-spacing: -0.04em;
  margin: 14px 0 18px;
}

.hero-copy p {
  font-size: 1rem;
  line-height: 1.8;
  max-width: 780px;
  color: rgba(7, 39, 35, 0.78);
}

.eyebrow,
.section-eyebrow {
  font-size: 0.78rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #0f766e;
}

.hero-panel {
  padding: 28px;
}

.panel-title {
  font-size: 0.95rem;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: #0f766e;
  margin-bottom: 18px;
}

.mix-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.mix-card {
  padding: 18px;
  border-radius: 20px;
  background: linear-gradient(180deg, rgba(15, 118, 110, 0.1), rgba(15, 118, 110, 0.02));
}

.mix-label {
  display: block;
  font-size: 0.82rem;
  color: rgba(7, 39, 35, 0.75);
}

.mix-value {
  display: block;
  margin-top: 10px;
  font-size: 1.5rem;
  font-weight: 700;
}

.workspace {
  display: grid;
  grid-template-columns: 1.3fr 0.7fr;
  gap: 24px;
}

.form-card,
.history-card {
  padding: 30px;
}

.card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
}

.card-header h2 {
  margin-top: 8px;
  font-size: 1.7rem;
}

.status-chip {
  padding: 10px 14px;
  border-radius: 999px;
  background: rgba(15, 118, 110, 0.12);
  color: #115e59;
  font-size: 0.82rem;
}

.grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.field {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.field span {
  font-size: 0.82rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(7, 39, 35, 0.65);
}

.field input,
.field select,
.field textarea {
  width: 100%;
  border: 1px solid rgba(15, 118, 110, 0.16);
  border-radius: 18px;
  padding: 15px 16px;
  background: rgba(247, 250, 248, 0.95);
  color: #072723;
  font-size: 0.98rem;
}

.textarea {
  margin-top: 18px;
}

.mix-section {
  margin-top: 22px;
  padding: 20px;
  border-radius: 24px;
  background: linear-gradient(180deg, rgba(255, 244, 199, 0.56), rgba(255, 255, 255, 0.6));
}

.mix-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.ghost-btn {
  border: none;
  background: transparent;
  color: #0f766e;
  cursor: pointer;
}

.sliders {
  display: grid;
  gap: 12px;
}

.slider-row {
  display: grid;
  grid-template-columns: 160px 1fr 48px;
  gap: 12px;
  align-items: center;
}

.mix-note {
  margin-top: 14px;
  font-size: 0.88rem;
  color: #166534;
}

.mix-note.invalid {
  color: #b45309;
}

.upload-box {
  margin-top: 22px;
  border: 1px dashed rgba(15, 118, 110, 0.35);
  border-radius: 24px;
  padding: 18px;
  cursor: pointer;
}

.upload-copy {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.upload-title {
  font-weight: 700;
}

.upload-hint {
  font-size: 0.92rem;
  color: rgba(7, 39, 35, 0.65);
}

.file-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 12px;
}

.file-pill {
  padding: 7px 10px;
  border-radius: 999px;
  background: rgba(15, 118, 110, 0.1);
  font-size: 0.84rem;
}

.actions {
  margin-top: 22px;
}

.primary-btn {
  width: 100%;
  border: none;
  border-radius: 18px;
  padding: 16px 18px;
  background: linear-gradient(135deg, #0f766e, #0b5c55);
  color: white;
  font-size: 1rem;
  font-weight: 700;
  cursor: pointer;
}

.primary-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error-box {
  margin-top: 16px;
  padding: 12px 14px;
  border-radius: 14px;
  background: rgba(239, 68, 68, 0.1);
  color: #b91c1c;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.history-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border: 1px solid rgba(15, 118, 110, 0.12);
  border-radius: 20px;
  padding: 16px;
  background: rgba(246, 250, 248, 0.95);
  text-align: left;
  cursor: pointer;
}

.history-meta,
.history-status,
.empty-state {
  color: rgba(7, 39, 35, 0.65);
  font-size: 0.88rem;
}

@media (max-width: 1080px) {
  .hero,
  .workspace {
    grid-template-columns: 1fr;
  }

  .grid {
    grid-template-columns: 1fr;
  }

  .slider-row {
    grid-template-columns: 1fr;
  }
}
</style>
