<template>
  <div class="page-shell" v-if="results && run">
    <header class="page-header">
      <div>
        <div class="eyebrow">Step 4</div>
        <h1>{{ run.scenario.stock_name }} 结果面板</h1>
      </div>
      <button class="ghost-btn" @click="router.push({ name: 'MarketSimulation', params: { runId } })">返回仿真</button>
    </header>

    <section class="metrics-grid">
      <div class="metric-card" v-for="metric in metricCards" :key="metric.label">
        <span>{{ metric.label }}</span>
        <strong>{{ metric.value }}</strong>
      </div>
    </section>

    <section class="chart-grid">
      <MarketLineChart title="Price Path" :points="results.series" metric-key="price" color="#0f766e" />
      <MarketLineChart title="Sentiment" :points="results.series" metric-key="market_sentiment" color="#ea580c" />
      <MarketLineChart title="Xueqiu Buzz" :points="results.series" metric-key="xueqiu_buzz" color="#b45309" />
      <MarketLineChart title="Volume" :points="results.series" metric-key="volume" color="#1d4ed8" />
    </section>

    <section class="results-grid">
      <article class="panel narrative">
        <div class="panel-header">
          <div>
            <div class="eyebrow">Narrative</div>
            <h2>市场解释</h2>
          </div>
        </div>
        <pre>{{ results.narrative_report }}</pre>
      </article>

      <article class="panel">
        <div class="panel-header">
          <div>
            <div class="eyebrow">Events</div>
            <h2>关键事件锚点</h2>
          </div>
        </div>
        <div class="event-list">
          <div v-for="event in results.event_markers" :key="`${event.tick_index}-${event.label}`" class="event-item">
            <strong>T{{ event.tick_index }}</strong>
            <span>{{ event.label }}</span>
            <small>impact {{ event.impact_score }}</small>
          </div>
        </div>
      </article>

      <article class="panel">
        <div class="panel-header">
          <div>
            <div class="eyebrow">Population</div>
            <h2>代理人结构</h2>
          </div>
        </div>
        <div class="population-list">
          <div v-for="(count, key) in results.population_summary.archetypes" :key="key" class="population-item">
            <span>{{ key }}</span>
            <strong>{{ count }}</strong>
          </div>
        </div>
      </article>

      <article class="panel">
        <div class="panel-header">
          <div>
            <div class="eyebrow">World State</div>
            <h2>平行市场主线</h2>
          </div>
        </div>
        <div class="event-list">
          <div class="event-item">
            <strong>{{ results.world_state?.world_summary?.top_narrative || '暂无主线' }}</strong>
            <span>市场风格 {{ results.world_state?.world_summary?.dominant_market_style || '--' }}</span>
            <small>{{ (results.world_state?.world_summary?.topics || []).join(' / ') }}</small>
          </div>
          <div
            v-for="narrative in results.world_state?.dominant_narratives || []"
            :key="narrative.label"
            class="event-item"
          >
            <strong>{{ narrative.label }}</strong>
            <span>{{ narrative.scope }} / {{ narrative.stance }}</span>
            <small>intensity {{ narrative.intensity }}</small>
          </div>
        </div>
      </article>

      <article class="panel analyst">
        <div class="panel-header">
          <div>
            <div class="eyebrow">Analyst Chat</div>
            <h2>仿真分析师</h2>
          </div>
        </div>

        <div class="chat-log">
          <div v-for="entry in chatLog" :key="entry.id" class="chat-item" :class="entry.role">
            <span class="chat-role">{{ entry.role === 'user' ? '你' : '分析师' }}</span>
            <p>{{ entry.content }}</p>
          </div>
        </div>

        <div class="chat-composer">
          <textarea v-model="question" rows="3" placeholder="问分析师：这轮走势是谁主导的？" />
          <button class="primary-btn" :disabled="chatting || !question.trim()" @click="handleAsk">
            {{ chatting ? '分析中...' : '发送问题' }}
          </button>
        </div>
      </article>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import MarketLineChart from '../components/MarketLineChart.vue'
import { chatWithMarketAnalyst, getMarketRun, getMarketRunResults } from '../api/market'

const route = useRoute()
const router = useRouter()
const runId = route.params.runId

const run = ref(null)
const results = ref(null)
const question = ref('')
const chatting = ref(false)
const chatLog = ref([])

const metricCards = computed(() => {
  const metrics = results.value?.metrics || {}
  return [
    { label: '区间收益', value: `${metrics.total_return_pct ?? '--'}%` },
    { label: '最大回撤', value: `${metrics.max_drawdown_pct ?? '--'}%` },
    { label: '波动代理值', value: `${metrics.realized_volatility_pct ?? '--'}%` },
    { label: '期末价格', value: metrics.ending_price ?? '--' }
  ]
})

const loadData = async () => {
  const [runResponse, resultsResponse] = await Promise.all([
    getMarketRun(runId),
    getMarketRunResults(runId)
  ])
  run.value = runResponse.data
  results.value = resultsResponse.data
}

const handleAsk = async () => {
  chatting.value = true
  const message = question.value.trim()
  chatLog.value.push({ id: `${Date.now()}-user`, role: 'user', content: message })
  question.value = ''
  try {
    const response = await chatWithMarketAnalyst(runId, message)
    chatLog.value.push({ id: `${Date.now()}-assistant`, role: 'assistant', content: response.data.answer })
  } finally {
    chatting.value = false
  }
}

onMounted(loadData)
</script>

<style scoped>
.page-shell {
  min-height: 100vh;
  padding: 28px;
  background: linear-gradient(180deg, #f7faf8, #edf5f2);
  color: #072723;
}

.page-header,
.metrics-grid,
.chart-grid,
.results-grid {
  max-width: 1360px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 18px;
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

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

.metric-card,
.panel {
  border-radius: 24px;
  padding: 20px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(7, 39, 35, 0.08);
}

.metric-card span {
  display: block;
  font-size: 0.8rem;
  color: rgba(7, 39, 35, 0.62);
  text-transform: uppercase;
  letter-spacing: 0.12em;
}

.metric-card strong {
  display: block;
  margin-top: 8px;
  font-size: 1.55rem;
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

.results-grid {
  display: grid;
  grid-template-columns: 1.05fr 0.95fr;
  gap: 16px;
}

.results-grid .panel:nth-child(1) {
  grid-column: 1 / span 2;
}

.panel-header {
  margin-bottom: 16px;
}

.narrative pre {
  white-space: pre-wrap;
  line-height: 1.8;
  font-family: inherit;
}

.event-list,
.population-list,
.chat-log {
  display: grid;
  gap: 10px;
}

.event-item,
.population-item,
.chat-item {
  border-radius: 16px;
  padding: 14px;
  background: rgba(244, 248, 246, 0.95);
}

.event-item {
  display: grid;
  gap: 4px;
}

.population-item {
  display: flex;
  justify-content: space-between;
}

.analyst {
  display: grid;
  gap: 14px;
}

.chat-item.user {
  background: rgba(15, 118, 110, 0.12);
}

.chat-role {
  display: block;
  margin-bottom: 6px;
  font-size: 0.8rem;
  color: rgba(7, 39, 35, 0.62);
}

.chat-composer textarea {
  width: 100%;
  border-radius: 16px;
  border: 1px solid rgba(15, 118, 110, 0.16);
  padding: 14px;
  margin-bottom: 10px;
  background: rgba(248, 251, 249, 0.95);
}

@media (max-width: 980px) {
  .metrics-grid,
  .chart-grid,
  .results-grid {
    grid-template-columns: 1fr;
  }

  .results-grid .panel:nth-child(1) {
    grid-column: auto;
  }
}
</style>
