<template>
  <div class="page-shell" v-if="run">
    <header class="page-header">
      <div>
        <div class="eyebrow">Step 2</div>
        <h1>{{ run.scenario.market === 'us_equity' ? '美股' : 'A股' }}环境与人群初始化</h1>
      </div>
      <button class="back-btn" @click="router.push('/')">返回场景创建</button>
    </header>

    <section class="summary-grid">
      <div class="summary-card">
        <span class="summary-label">标的</span>
        <strong>{{ run.scenario.stock_name }}</strong>
        <small>{{ run.scenario.ticker }} / {{ run.scenario.sector_name }}</small>
      </div>
      <div class="summary-card">
        <span class="summary-label">环境</span>
        <strong>{{ run.scenario.market_regime }}</strong>
        <small>{{ run.scenario.horizon_days }} 个交易日</small>
      </div>
      <div class="summary-card">
        <span class="summary-label">代理人数</span>
        <strong>{{ run.scenario.agent_count }}</strong>
        <small>{{ run.status }}</small>
      </div>
    </section>

    <section class="panel-grid">
      <div class="panel">
        <div class="panel-header">
          <div>
            <div class="eyebrow">World State</div>
            <h2>平行市场世界</h2>
          </div>
          <button class="primary-btn" :disabled="buildingWorld" @click="handleBuildWorld">
            {{ buildingWorld ? '构建中...' : (worldState.built_at ? '重建 world_state' : '构建 world_state') }}
          </button>
        </div>

        <div v-if="run.scenario.market !== 'us_equity'" class="xueqiu-auth-card">
          <div class="xueqiu-auth-copy">
            <strong>雪球登录状态</strong>
            <span>
              {{ xueqiuStatus.authenticated ? '已认证，将通过浏览器会话抓取真实讨论数据。' : '未认证。建议先打开登录浏览器并完成登录，否则准备阶段会回退到模拟情绪信号。' }}
            </span>
            <span v-if="xueqiuStatus.last_error" class="auth-error">{{ xueqiuStatus.last_error }}</span>
          </div>
          <div class="xueqiu-auth-actions">
            <button class="back-btn" :disabled="authLoading" @click="handleStartAuth">打开雪球登录</button>
            <button class="back-btn" :disabled="authLoading || !xueqiuStatus.browser_open" @click="handleCompleteAuth">我已完成登录</button>
            <button class="back-btn danger" :disabled="authLoading || !xueqiuStatus.authenticated" @click="handleLogout">清除登录态</button>
          </div>
        </div>
        <div v-else class="empty-card">美股使用独立的 CNBC / X / Reddit / 导入新闻与讨论源。基本面已在选股阶段完成，本轮不再建模。</div>

        <div v-if="run.scenario.market !== 'us_equity' && run.preparation_summary?.source_health" class="source-health">
          <span>东方财富资讯: {{ run.preparation_summary.source_health.eastmoney_news_count }}</span>
          <span>雪球模式: {{ run.preparation_summary.source_health.xueqiu_mode }}</span>
          <span>雪球认证: {{ run.preparation_summary.source_health.xueqiu_authenticated ? 'yes' : 'no' }}</span>
        </div>
        <div v-if="worldState.source_health?.providers" class="source-health">
          <span v-for="(status, source) in worldState.source_health.providers" :key="source">{{ source }}: {{ status }}</span>
        </div>

        <CurrentSentimentCard :snapshot="worldState.current_sentiment" />
        <div v-if="worldState.world_summary?.top_narrative" class="world-card">
          <div class="world-copy">
            <strong>{{ worldState.world_summary.top_narrative }}</strong>
            <span>市场风格: {{ worldState.world_summary.dominant_market_style }}</span>
            <small>topics: {{ (worldState.world_summary.topics || []).join(' / ') }}</small>
          </div>
          <div class="world-factors">
            <div v-for="(value, key) in worldState.regime_factors" :key="key" class="factor-pill">
              <span>{{ key }}</span>
              <strong>{{ value }}</strong>
            </div>
          </div>
        </div>
        <div v-else class="empty-card">先构建 world_state，把新闻、讨论和场景变成可演化的市场世界。</div>
      </div>

      <div class="panel">
        <div class="panel-header">
          <div>
            <div class="eyebrow">Prepare</div>
            <h2>资讯、人群与 shock</h2>
          </div>
          <button class="primary-btn" :disabled="preparing || !worldBuilt" @click="handlePrepare">
            {{ preparing ? '准备中...' : (preparedContext.news_items?.length ? '重新准备' : '生成市场上下文') }}
          </button>
        </div>

        <div v-if="preparedContext.news_items?.length" class="news-list">
          <article v-for="item in preparedContext.news_items" :key="item.url || item.title" class="news-item">
            <div class="news-head">
              <strong>{{ item.title }}</strong>
              <span>{{ item.affected_scope }}</span>
            </div>
            <p>{{ item.summary }}</p>
          </article>
        </div>
        <div v-else class="empty-card">准备后会展示所选市场的资讯和情绪输入。</div>
      </div>

      <div class="panel">
        <div class="panel-header">
          <div>
            <div class="eyebrow">Population</div>
            <h2>人群画像分布</h2>
          </div>
        </div>

        <div v-if="populationSummary.archetypes" class="stats-block">
          <div class="stats-grid">
            <div class="stat-box" v-for="(value, key) in populationSummary.archetypes" :key="key">
              <span>{{ key }}</span>
              <strong>{{ value }}</strong>
            </div>
          </div>

          <div class="dimension-grid">
            <div class="dimension-card">
              <span class="dimension-title">年龄</span>
              <div v-for="(value, key) in populationSummary.age_bands" :key="key" class="dimension-row">
                <span>{{ key }}</span><strong>{{ value }}</strong>
              </div>
            </div>
            <div class="dimension-card">
              <span class="dimension-title">风险偏好</span>
              <div v-for="(value, key) in populationSummary.risk_appetite" :key="key" class="dimension-row">
                <span>{{ key }}</span><strong>{{ value }}</strong>
              </div>
            </div>
            <div class="dimension-card">
              <span class="dimension-title">财富阶段</span>
              <div v-for="(value, key) in populationSummary.wealth_stage" :key="key" class="dimension-row">
                <span>{{ key }}</span><strong>{{ value }}</strong>
              </div>
            </div>
          </div>
        </div>
        <div v-else class="empty-card">准备后会显示 500-2000 个模拟交易者的策略分布。</div>
      </div>
    </section>

    <section class="footer-actions">
      <button class="primary-btn wide" :disabled="!readyToSimulate" @click="goToSimulation">
        进入价格仿真
      </button>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import CurrentSentimentCard from '../components/CurrentSentimentCard.vue'
import {
  buildMarketWorld,
  completeXueqiuAuth,
  getMarketRun,
  getXueqiuAuthStatus,
  logoutXueqiuAuth,
  prepareMarketRun,
  startXueqiuAuth
} from '../api/market'

const route = useRoute()
const router = useRouter()
const run = ref(null)
const preparing = ref(false)
const buildingWorld = ref(false)
const authLoading = ref(false)
const xueqiuStatus = ref({
  authenticated: false,
  browser_open: false,
  last_error: null
})

const preparedContext = computed(() => run.value?.prepared_context || {})
const worldState = computed(() => run.value?.world_state || {})
const populationSummary = computed(() => preparedContext.value.population_summary || run.value?.preparation_summary?.population_summary || {})
const worldBuilt = computed(() => Boolean(worldState.value?.built_at))
const readyToSimulate = computed(() => ['ready', 'running', 'completed'].includes(run.value?.status))

const loadRun = async () => {
  const response = await getMarketRun(route.params.runId)
  run.value = response.data
}

const loadAuthStatus = async () => {
  try {
    const response = await getXueqiuAuthStatus()
    xueqiuStatus.value = response.data
  } catch (error) {
    xueqiuStatus.value = {
      ...xueqiuStatus.value,
      last_error: error.message || '获取雪球登录状态失败'
    }
  }
}

const handleBuildWorld = async () => {
  buildingWorld.value = true
  try {
    const response = await buildMarketWorld(route.params.runId)
    run.value = response.data
  } finally {
    buildingWorld.value = false
  }
}

const handlePrepare = async () => {
  preparing.value = true
  try {
    const response = await prepareMarketRun(route.params.runId)
    run.value = response.data
    if (run.value?.scenario.market !== 'us_equity') await loadAuthStatus()
  } finally {
    preparing.value = false
  }
}

const handleStartAuth = async () => {
  authLoading.value = true
  try {
    const response = await startXueqiuAuth()
    xueqiuStatus.value = response.data
  } catch (error) {
    xueqiuStatus.value = {
      ...xueqiuStatus.value,
      last_error: error.message || '打开雪球登录浏览器失败'
    }
  } finally {
    authLoading.value = false
  }
}

const handleCompleteAuth = async () => {
  authLoading.value = true
  try {
    const response = await completeXueqiuAuth()
    xueqiuStatus.value = response.data
  } catch (error) {
    xueqiuStatus.value = {
      ...xueqiuStatus.value,
      last_error: error.message || '确认雪球登录失败'
    }
  } finally {
    authLoading.value = false
  }
}

const handleLogout = async () => {
  authLoading.value = true
  try {
    const response = await logoutXueqiuAuth()
    xueqiuStatus.value = response.data
  } catch (error) {
    xueqiuStatus.value = {
      ...xueqiuStatus.value,
      last_error: error.message || '清除雪球登录态失败'
    }
  } finally {
    authLoading.value = false
  }
}

const goToSimulation = () => {
  router.push({ name: 'MarketSimulation', params: { runId: route.params.runId } })
}

onMounted(async () => {
  await loadRun()
  if (run.value?.scenario.market !== 'us_equity') await loadAuthStatus()
})
</script>

<style scoped>
.page-shell {
  min-height: 100vh;
  padding: 28px;
  background: linear-gradient(180deg, #f4f8f6, #eaf0ed);
  color: #072723;
}

.page-header,
.summary-grid,
.panel-grid,
.footer-actions {
  max-width: 1360px;
  margin: 0 auto;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 24px;
}

.eyebrow {
  font-size: 0.76rem;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: #0f766e;
}

.page-header h1 {
  margin-top: 8px;
  font-size: clamp(2rem, 3vw, 3.2rem);
}

.back-btn,
.primary-btn {
  border: none;
  border-radius: 16px;
  padding: 13px 16px;
  cursor: pointer;
}

.back-btn {
  background: rgba(255, 255, 255, 0.82);
}

.primary-btn {
  background: linear-gradient(135deg, #0f766e, #0b5c55);
  color: white;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
  margin-bottom: 20px;
}

.summary-card,
.panel {
  border-radius: 26px;
  padding: 22px;
  background: rgba(255, 255, 255, 0.92);
  border: 1px solid rgba(7, 39, 35, 0.08);
}

.summary-label {
  display: block;
  font-size: 0.78rem;
  color: rgba(7, 39, 35, 0.62);
  text-transform: uppercase;
  letter-spacing: 0.14em;
}

.summary-card strong {
  display: block;
  margin-top: 8px;
  font-size: 1.6rem;
}

.summary-card small {
  display: block;
  margin-top: 6px;
  color: rgba(7, 39, 35, 0.7);
}

.panel-grid {
  display: grid;
  grid-template-columns: 1.1fr 0.9fr;
  gap: 18px;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 18px;
}

.source-health {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 16px;
  color: #115e59;
  font-size: 0.92rem;
}

.world-card {
  display: grid;
  gap: 14px;
  margin-bottom: 16px;
  padding: 16px 18px;
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(15, 118, 110, 0.08), rgba(255, 255, 255, 0.9));
}

.world-copy {
  display: grid;
  gap: 4px;
}

.world-copy small {
  color: rgba(7, 39, 35, 0.62);
}

.world-factors {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.factor-pill {
  display: grid;
  gap: 2px;
  min-width: 120px;
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.85);
}

.factor-pill span {
  font-size: 0.75rem;
  color: rgba(7, 39, 35, 0.6);
}

.xueqiu-auth-card {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 18px;
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(255, 244, 199, 0.42), rgba(255, 255, 255, 0.86));
  margin-bottom: 16px;
}

.xueqiu-auth-copy {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-width: 70%;
  color: rgba(7, 39, 35, 0.74);
}

.xueqiu-auth-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: flex-start;
  justify-content: flex-end;
}

.auth-error {
  color: #b91c1c;
}

.danger {
  color: #b91c1c;
}

.news-list {
  display: grid;
  gap: 12px;
}

.news-item {
  border: 1px solid rgba(15, 118, 110, 0.12);
  border-radius: 18px;
  padding: 16px;
  background: rgba(248, 251, 249, 0.95);
}

.news-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
}

.news-head span {
  font-size: 0.8rem;
  color: #0f766e;
  text-transform: uppercase;
}

.news-item p {
  color: rgba(7, 39, 35, 0.72);
  line-height: 1.6;
}

.empty-card {
  padding: 24px;
  border-radius: 20px;
  background: rgba(15, 118, 110, 0.06);
  color: rgba(7, 39, 35, 0.72);
}

.stats-grid,
.dimension-grid {
  display: grid;
  gap: 12px;
}

.stats-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
  margin-bottom: 16px;
}

.stat-box,
.dimension-card {
  padding: 16px;
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(255, 244, 199, 0.48), rgba(255, 255, 255, 0.82));
}

.stat-box span,
.dimension-title {
  color: rgba(7, 39, 35, 0.65);
  font-size: 0.82rem;
}

.stat-box strong {
  display: block;
  margin-top: 10px;
  font-size: 1.45rem;
}

.dimension-row {
  display: flex;
  justify-content: space-between;
  margin-top: 10px;
}

.footer-actions {
  margin-top: 20px;
}

.wide {
  width: 100%;
  padding: 16px;
  font-size: 1rem;
  font-weight: 700;
}

@media (max-width: 980px) {
  .summary-grid,
  .panel-grid {
    grid-template-columns: 1fr;
  }

  .xueqiu-auth-card {
    flex-direction: column;
  }

  .xueqiu-auth-copy {
    max-width: none;
  }
}
</style>
