<template>
  <div class="page-shell" v-if="run">
    <header class="page-header">
      <div>
        <div class="eyebrow">Step 3</div>
        <h1>价格与情绪共振仿真</h1>
      </div>
      <div class="header-actions">
        <button class="ghost-btn" @click="router.push({ name: 'MarketConfig', params: { runId } })">返回环境配置</button>
        <button class="primary-btn" :disabled="starting || run.status === 'running'" @click="handleStart">
          {{ run.status === 'running' ? '运行中...' : starting ? '启动中...' : '开始仿真' }}
        </button>
      </div>
    </header>

    <section class="progress-card">
      <div>
        <span class="progress-label">当前阶段</span>
        <strong>{{ run.current_phase }}</strong>
      </div>
      <div>
        <span class="progress-label">Tick</span>
        <strong>{{ status.current_tick || 0 }} / {{ status.total_ticks || totalTicks }}</strong>
      </div>
      <div>
        <span class="progress-label">进度</span>
        <strong>{{ status.progress_percent || 0 }}%</strong>
      </div>
      <div>
        <span class="progress-label">最新价格</span>
        <strong>{{ status.current_price || run.scenario.starting_price }}</strong>
      </div>
    </section>

    <section class="chart-grid">
      <MarketLineChart title="Price Path" :points="liveSeries" metric-key="price" color="#0f766e" />
      <MarketLineChart title="Crowd Sentiment" :points="liveSeries" metric-key="market_sentiment" color="#ea580c" />
      <MarketLineChart title="社交热度（模拟）" :points="liveSeries" metric-key="xueqiu_buzz" color="#b45309" />
      <MarketLineChart title="Volume" :points="liveSeries" metric-key="volume" color="#1d4ed8" />
    </section>

    <section class="events-panel">
      <div class="panel-header">
        <div>
          <div class="eyebrow">Live Feed</div>
          <h2>最近市场动作</h2>
        </div>
        <button v-if="run.status === 'completed'" class="primary-btn" @click="openResults">查看结果与分析师</button>
      </div>
      <div class="event-list">
        <div v-for="(tick, index) in [...liveSeries].reverse()" :key="`${tick.tick_index}-${index}`" class="event-item">
          <div class="event-meta">
            <strong>T{{ tick.tick_index }}</strong>
            <span>价格 {{ tick.price }}</span>
            <span>涨跌 {{ tick.return_pct }}</span>
          </div>
          <div class="event-actions">
            <span v-for="action in tick.top_actions?.slice(0, 4)" :key="`${tick.tick_index}-${action.agent_id}-${action.action}`" class="action-pill">
              {{ action.agent_name }} · {{ action.action }}
            </span>
          </div>
        </div>
        <div v-if="!liveSeries.length" class="empty-card">仿真开始后，这里会滚动出现价格与主导行为样本。</div>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MarketLineChart from '../components/MarketLineChart.vue'
import { getMarketRun, getMarketRunStatus, startMarketRun } from '../api/market'

const route = useRoute()
const router = useRouter()
const runId = route.params.runId
const run = ref(null)
const starting = ref(false)
const pollTimer = ref(null)

const status = computed(() => run.value?.simulation_summary || {})
const liveSeries = computed(() => status.value.live_series || [])
const totalTicks = computed(() => (run.value?.scenario?.horizon_days || 3) * (run.value?.world_summary?.ticks_per_day || (run.value?.scenario?.market === 'us_equity' ? 78 : 48)))

const loadRun = async () => {
  const response = await getMarketRun(runId)
  run.value = response.data
}

const pollStatus = async () => {
  const response = await getMarketRunStatus(runId)
  run.value = {
    ...(run.value || {}),
    ...response.data
  }
  if (run.value.status === 'completed' && pollTimer.value) {
    clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

const ensurePolling = () => {
  if (pollTimer.value) return
  pollTimer.value = setInterval(pollStatus, 1800)
}

const handleStart = async () => {
  starting.value = true
  try {
    await startMarketRun(runId)
    await pollStatus()
    ensurePolling()
  } finally {
    starting.value = false
  }
}

const openResults = () => {
  router.push({ name: 'MarketResults', params: { runId } })
}

onMounted(async () => {
  await loadRun()
  if (run.value.status === 'running') {
    ensurePolling()
    await pollStatus()
  }
})

onBeforeUnmount(() => {
  if (pollTimer.value) clearInterval(pollTimer.value)
})
</script>

<style scoped>
.page-shell {
  min-height: 100vh;
  padding: 28px;
  background: linear-gradient(180deg, #f7faf8, #eef5f3);
  color: #072723;
}

.page-header,
.progress-card,
.chart-grid,
.events-panel {
  max-width: 1360px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  gap: 18px;
  align-items: flex-start;
  margin-bottom: 20px;
}

.eyebrow {
  font-size: 0.76rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #0f766e;
}

.page-header h1,
.panel-header h2 {
  margin-top: 8px;
}

.header-actions {
  display: flex;
  gap: 12px;
}

.ghost-btn,
.primary-btn {
  border: none;
  border-radius: 16px;
  padding: 13px 16px;
  cursor: pointer;
}

.ghost-btn {
  background: rgba(255, 255, 255, 0.85);
}

.primary-btn {
  background: linear-gradient(135deg, #0f766e, #0b5c55);
  color: white;
}

.progress-card {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 18px;
}

.progress-card > div,
.events-panel {
  border-radius: 22px;
  padding: 18px 20px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(7, 39, 35, 0.08);
}

.progress-label {
  display: block;
  font-size: 0.76rem;
  color: rgba(7, 39, 35, 0.62);
  text-transform: uppercase;
  letter-spacing: 0.12em;
}

.progress-card strong {
  display: block;
  margin-top: 8px;
  font-size: 1.4rem;
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 18px;
}

.events-panel {
  padding: 24px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.event-list {
  display: grid;
  gap: 12px;
}

.event-item {
  padding: 14px;
  border-radius: 18px;
  background: rgba(244, 248, 246, 0.95);
  border: 1px solid rgba(15, 118, 110, 0.1);
}

.event-meta {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.event-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}

.action-pill {
  padding: 6px 10px;
  border-radius: 999px;
  background: rgba(15, 118, 110, 0.1);
  font-size: 0.82rem;
}

.empty-card {
  padding: 24px;
  border-radius: 18px;
  background: rgba(15, 118, 110, 0.06);
}

@media (max-width: 980px) {
  .progress-card,
  .chart-grid {
    grid-template-columns: 1fr;
  }

  .page-header,
  .panel-header {
    flex-direction: column;
  }
}
</style>
