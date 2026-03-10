<template>
  <div class="chart-card">
    <div class="chart-header">
      <span class="chart-title">{{ title }}</span>
      <span class="chart-meta">{{ latestLabel }}</span>
    </div>
    <svg :viewBox="`0 0 ${width} ${height}`" class="chart-svg" preserveAspectRatio="none">
      <defs>
        <linearGradient :id="gradientId" x1="0%" x2="0%" y1="0%" y2="100%">
          <stop offset="0%" :stop-color="color" stop-opacity="0.35" />
          <stop offset="100%" :stop-color="color" stop-opacity="0.02" />
        </linearGradient>
      </defs>
      <path :d="areaPath" :fill="`url(#${gradientId})`" />
      <path :d="linePath" :stroke="color" stroke-width="2.5" fill="none" stroke-linecap="round" />
      <line
        v-for="guide in guides"
        :key="guide.y"
        x1="0"
        :x2="width"
        :y1="guide.y"
        :y2="guide.y"
        class="grid-line"
      />
    </svg>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  title: { type: String, required: true },
  points: { type: Array, default: () => [] },
  metricKey: { type: String, required: true },
  color: { type: String, default: '#0f766e' },
  width: { type: Number, default: 560 },
  height: { type: Number, default: 220 }
})

const gradientId = `chart-gradient-${Math.random().toString(36).slice(2)}`

const normalized = computed(() => {
  if (!props.points.length) return []
  const values = props.points.map((point) => Number(point[props.metricKey] ?? 0))
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  return props.points.map((point, index) => {
    const x = props.points.length === 1 ? props.width / 2 : (index / (props.points.length - 1)) * props.width
    const value = Number(point[props.metricKey] ?? 0)
    const y = props.height - ((value - min) / range) * (props.height - 16) - 8
    return { x, y, value }
  })
})

const linePath = computed(() => {
  if (!normalized.value.length) return ''
  return normalized.value
    .map((point, index) => `${index === 0 ? 'M' : 'L'} ${point.x.toFixed(2)} ${point.y.toFixed(2)}`)
    .join(' ')
})

const areaPath = computed(() => {
  if (!normalized.value.length) return ''
  const first = normalized.value[0]
  const last = normalized.value[normalized.value.length - 1]
  return `${linePath.value} L ${last.x.toFixed(2)} ${props.height} L ${first.x.toFixed(2)} ${props.height} Z`
})

const guides = computed(() => {
  return [0.2, 0.5, 0.8].map((ratio) => ({ y: props.height * ratio }))
})

const latestLabel = computed(() => {
  if (!normalized.value.length) return '--'
  const latest = normalized.value[normalized.value.length - 1].value
  return Number.isInteger(latest) ? `${latest}` : latest.toFixed(2)
})
</script>

<style scoped>
.chart-card {
  border: 1px solid rgba(15, 118, 110, 0.16);
  border-radius: 24px;
  padding: 18px;
  background:
    radial-gradient(circle at top left, rgba(15, 118, 110, 0.12), transparent 42%),
    linear-gradient(180deg, rgba(255, 255, 255, 0.98), rgba(243, 247, 245, 0.98));
}

.chart-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.chart-title {
  font-size: 0.95rem;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #134e4a;
}

.chart-meta {
  font-size: 0.82rem;
  color: #0f766e;
}

.chart-svg {
  width: 100%;
  height: 220px;
  overflow: visible;
}

.grid-line {
  stroke: rgba(15, 118, 110, 0.12);
  stroke-dasharray: 5 5;
}
</style>
