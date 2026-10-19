<template>
  <section v-if="snapshot?.as_of" class="sentiment-card">
    <h2>起点情绪：{{ snapshot.label }}</h2>
    <p>快照时间 {{ snapshot.as_of }} · {{ modes[snapshot.source_mode] || snapshot.source_mode }}</p>
    <div class="sentiment-values">
      <span v-for="(label, key) in channelLabels" :key="key">
        {{ label }}
        <strong>{{ snapshot.channels?.[key]?.sentiment_score ?? '--' }}</strong>
        <small>{{ modes[snapshot.channels?.[key]?.source_mode] || '缺失' }}</small>
        <small>来源：{{ (snapshot.channels?.[key]?.sources || []).join(' / ') || '无' }}</small>
      </span>
      <span>综合情绪 <strong>{{ snapshot.sentiment_score }}</strong></span>
      <span>个股讨论 <strong>{{ snapshot.stock_discussion_sentiment }}</strong></span>
      <span>板块讨论 <strong>{{ snapshot.sector_discussion_sentiment }}</strong></span>
      <span>新闻 <strong>{{ snapshot.news_sentiment }}</strong></span>
      <span>讨论样本 <strong>{{ snapshot.discussion_samples }}</strong></span>
      <span>近期价格变化 <strong>{{ (snapshot.price_momentum * 100).toFixed(2) }}%</strong></span>
    </div>
    <p>大盘、个股与板块来自各自的检索与样本；新闻默认从发布时间起 72 小时线性衰减至零。后续曲线来自模拟。</p>
    <p v-if="snapshot.market_cycle">大盘周期候选：{{ snapshot.market_cycle.label }} · 来源 {{ snapshot.market_cycle.source }}。阶段为启发式描述，不保证反转。</p>
    <ul v-if="snapshot.warnings?.length">
      <li v-for="warning in snapshot.warnings" :key="warning">{{ warning }}</li>
    </ul>
  </section>
</template>

<script setup>
defineProps({ snapshot: Object })
const modes = { observed: '真实讨论样本 + 新闻', news_proxy: '仅新闻代理', market_breadth: '市场宽度观测', insufficient: '数据不足' }
const channelLabels = { market: '大盘情绪', stock: '个股情绪', sector: '板块情绪' }
</script>

<style scoped>
.sentiment-card { padding: 20px; margin-bottom: 18px; border-radius: 20px; background: #fffdf3; border: 1px solid #d8d2ad; }
.sentiment-card h2 { margin: 0 0 10px; }
.sentiment-card p, li { font-size: 0.9rem; line-height: 1.6; overflow-wrap: anywhere; }
.sentiment-values { display: flex; flex-wrap: wrap; gap: 14px; }
.sentiment-values span { display: grid; gap: 4px; }
.sentiment-card ul { padding-left: 20px; color: #795414; }
</style>
