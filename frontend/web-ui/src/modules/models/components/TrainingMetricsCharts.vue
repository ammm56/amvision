<template>
  <div class="training-charts-grid" :class="{ 'training-charts-grid--compact': compact }">
    <article class="training-chart-card">
      <h3>{{ trainLossKey ? (validationLossKey ? (locale.startsWith('zh') ? '训练与验证损失' : 'Training and validation loss') : (locale.startsWith('zh') ? '训练损失' : 'Training loss')) : t('trainingDetail.charts.trainMetrics') }}</h3>
      <div ref="trainChartElement" class="training-chart-canvas" />
      <span v-if="trainHistory.length === 0" class="training-chart-empty">{{ t('common.noValue') }}</span>
    </article>
    <article class="training-chart-card">
      <h3>{{ primaryMetricLabel ? `${locale.startsWith('zh') ? '验证集' : 'Validation'} ${primaryMetricLabel}` : t('trainingDetail.charts.validationMetrics') }}</h3>
      <div ref="validationChartElement" class="training-chart-canvas" />
      <span v-if="validationHistory.length === 0" class="training-chart-empty">{{ t('common.noValue') }}</span>
    </article>
    <article v-if="!compact" class="training-chart-card training-chart-card--wide">
      <h3>{{ t('trainingDetail.charts.learningRate') }}</h3>
      <div ref="learningRateChartElement" class="training-chart-canvas training-chart-canvas--small" />
      <span v-if="learningRateHistory.length === 0" class="training-chart-empty">{{ t('common.noValue') }}</span>
    </article>
    <article v-if="!compact" class="training-chart-card">
      <h3>{{ t('trainingDetail.charts.runtimePerformance') }}</h3>
      <div ref="runtimeChartElement" class="training-chart-canvas training-chart-canvas--small" />
      <span v-if="runtimeHistory.length === 0" class="training-chart-empty">{{ runtimeEmptyText }}</span>
    </article>
    <article v-if="!compact" class="training-chart-card">
      <h3>{{ t('trainingDetail.charts.gpuResources') }}</h3>
      <div ref="gpuChartElement" class="training-chart-canvas training-chart-canvas--small" />
      <span v-if="!hasGpuHistory" class="training-chart-empty">{{ runtimeHistory.length === 0 ? runtimeEmptyText : t('common.noValue') }}</span>
    </article>
    <article v-if="!compact" class="training-chart-card training-chart-card--wide">
      <h3>{{ t('trainingDetail.charts.stageTiming') }}</h3>
      <div ref="stageChartElement" class="training-chart-canvas training-chart-canvas--small" />
      <span v-if="!hasStageHistory" class="training-chart-empty">{{ runtimeHistory.length === 0 ? runtimeEmptyText : t('common.noValue') }}</span>
    </article>
  </div>
</template>

<script setup lang="ts">
import { formatLearningRate, formatModelNumber, formatSmallModelNumber, modelChartValueFormatter } from '../model-number-format'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
} from 'echarts/components'
import { init, use, type ECharts, type EChartsCoreOption } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { workbenchFontFamily } from '@/shared/ui/canvas-font'

import type { ModelTaskType } from '../services/model.service'
import {
  getTrainingMetricCapability,
  readOrderedMetricNames,
  type TrainingMetricPoint,
  type TrainingRuntimePoint,
  type TrainingScalarPoint,
} from '../training-metric-history'

use([LineChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, DataZoomComponent, CanvasRenderer])

const props = defineProps<{
  taskType: ModelTaskType
  trainHistory: TrainingMetricPoint[]
  validationHistory: TrainingMetricPoint[]
  learningRateHistory: TrainingScalarPoint[]
  runtimeHistory: TrainingRuntimePoint[]
  runtimeEmptyText: string
  compact?: boolean
  bestEpoch?: number
  primaryMetric?: string | null
}>()

const { t, locale } = useI18n()
const trainChartElement = ref<HTMLElement | null>(null)
const validationChartElement = ref<HTMLElement | null>(null)
const learningRateChartElement = ref<HTMLElement | null>(null)
const runtimeChartElement = ref<HTMLElement | null>(null)
const gpuChartElement = ref<HTMLElement | null>(null)
const stageChartElement = ref<HTMLElement | null>(null)
const capability = computed(() => getTrainingMetricCapability(props.taskType))
const lossKey = (history: TrainingMetricPoint[]) => props.compact
  ? ['loss', 'total_loss'].find(name => history.some(point => Object.hasOwn(point.metrics, name)))
  : undefined
const trainLossKey = computed(() => lossKey(props.trainHistory))
const validationLossKey = computed(() => lossKey(props.validationHistory))
const primaryMetricKey = computed(() => {
  if (!props.compact || !props.primaryMetric) return undefined
  const names = [props.primaryMetric, props.primaryMetric.replace(/^val[_/]/, '')]
  return names.find(name => props.validationHistory.some(point => Object.hasOwn(point.metrics, name)))
})
const primaryMetricLabel = computed(() => primaryMetricKey.value === 'map50_95' ? 'mAP50–95' : primaryMetricKey.value)
const hasGpuHistory = computed(() => props.runtimeHistory.some((point) => (
  'gpu_utilization_percent' in point.runtime
  || 'gpu_memory_allocated_bytes' in point.runtime
  || 'gpu_memory_reserved_bytes' in point.runtime
)))
const hasStageHistory = computed(() => props.runtimeHistory.some((point) => (
  'forward_loss_host_time_ms' in point.runtime
  || 'backward_optimizer_host_time_ms' in point.runtime
  || 'batch_compute_host_time_ms' in point.runtime
)))
let trainChart: ECharts | null = null
let validationChart: ECharts | null = null
let learningRateChart: ECharts | null = null
let runtimeChart: ECharts | null = null
let gpuChart: ECharts | null = null
let stageChart: ECharts | null = null
let resizeObserver: ResizeObserver | null = null
let themeObserver: MutationObserver | null = null

onMounted(async () => {
  await nextTick()
  trainChart = initializeChart(trainChartElement.value)
  validationChart = initializeChart(validationChartElement.value)
  learningRateChart = initializeChart(learningRateChartElement.value)
  runtimeChart = initializeChart(runtimeChartElement.value)
  gpuChart = initializeChart(gpuChartElement.value)
  stageChart = initializeChart(stageChartElement.value)
  renderCharts()
  if (typeof MutationObserver !== 'undefined') {
    themeObserver = new MutationObserver(renderCharts)
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  }
  const observedElements = [
    trainChartElement.value,
    validationChartElement.value,
    learningRateChartElement.value,
    runtimeChartElement.value,
    gpuChartElement.value,
    stageChartElement.value,
  ].filter((element): element is HTMLElement => element !== null)
  if (typeof ResizeObserver !== 'undefined' && observedElements.length > 0) {
    resizeObserver = new ResizeObserver(() => {
      trainChart?.resize()
      validationChart?.resize()
      learningRateChart?.resize()
      runtimeChart?.resize()
      gpuChart?.resize()
      stageChart?.resize()
    })
    observedElements.forEach((element) => resizeObserver?.observe(element))
  }
})

watch(
  () => [
    props.taskType,
    props.trainHistory,
    props.validationHistory,
    props.learningRateHistory,
    props.runtimeHistory,
    props.bestEpoch,
    props.primaryMetric,
  ],
  renderCharts,
  { deep: true },
)

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
  themeObserver?.disconnect()
  trainChart?.dispose()
  validationChart?.dispose()
  learningRateChart?.dispose()
  runtimeChart?.dispose()
  gpuChart?.dispose()
  stageChart?.dispose()
})

function initializeChart(element: HTMLElement | null): ECharts | null {
  // jsdom 没有可用的 canvas 布局；浏览器中容器宽度大于零时再初始化。
  if (element === null || element.clientWidth <= 0) return null
  return init(element, { textStyle: { fontFamily: workbenchFontFamily() } }, { renderer: 'canvas' })
}

function renderCharts(): void {
  const best = props.bestEpoch
  trainChart?.setOption(trainLossKey.value ? buildBaseOption([
    metricLine('train loss', props.trainHistory, trainLossKey.value, best),
    ...(validationLossKey.value ? [{ ...metricLine('val loss', props.validationHistory, validationLossKey.value), itemStyle: { color: chartVisual().text } }] : []),
  ]) : buildMetricOption(props.trainHistory, capability.value.trainMetrics, true), true)
  validationChart?.setOption(primaryMetricKey.value
    ? buildBaseOption([metricLine(primaryMetricLabel.value ?? primaryMetricKey.value, props.validationHistory, primaryMetricKey.value, best)])
    : buildMetricOption(props.validationHistory, capability.value.validationMetrics, false), true)
  learningRateChart?.setOption(buildLearningRateOption(props.learningRateHistory), true)
  runtimeChart?.setOption(buildRuntimePerformanceOption(props.runtimeHistory), true)
  gpuChart?.setOption(buildGpuResourceOption(props.runtimeHistory), true)
  stageChart?.setOption(buildStageTimingOption(props.runtimeHistory), true)
}

function buildRuntimePerformanceOption(history: TrainingRuntimePoint[]): EChartsCoreOption {
  return buildDualAxisOption({
    xName: 'step',
    leftAxisName: 'samples/s',
    rightAxisName: 'ms',
    series: [
      buildRuntimeSeries(history, 'samples_per_second', 0),
      buildRuntimeSeries(history, 'steps_per_second', 0),
      buildRuntimeSeries(history, 'step_time_ms', 1),
    ],
  })
}

function buildGpuResourceOption(history: TrainingRuntimePoint[]): EChartsCoreOption {
  return buildDualAxisOption({
    xName: 'step',
    leftAxisName: '%',
    rightAxisName: 'GiB',
    series: [
      buildRuntimeSeries(history, 'gpu_utilization_percent', 0),
      buildRuntimeSeries(history, 'gpu_memory_used_percent', 0),
      buildRuntimeSeries(history, 'gpu_memory_allocated_bytes', 1, bytesToGib),
      buildRuntimeSeries(history, 'gpu_memory_reserved_bytes', 1, bytesToGib),
    ],
  })
}

function buildStageTimingOption(history: TrainingRuntimePoint[]): EChartsCoreOption {
  return buildDualAxisOption({
    xName: 'step',
    leftAxisName: 'ms',
    rightAxisName: 'ms',
    series: [
      buildRuntimeSeries(history, 'forward_loss_host_time_ms', 0),
      buildRuntimeSeries(history, 'backward_optimizer_host_time_ms', 0),
      buildRuntimeSeries(history, 'batch_compute_host_time_ms', 1),
    ],
  })
}

function buildRuntimeSeries(
  history: TrainingRuntimePoint[],
  name: string,
  yAxisIndex: number,
  transform: (value: number) => number = (value) => value,
): Record<string, unknown> {
  return {
    name,
    type: 'line',
    yAxisIndex,
    tooltip: { valueFormatter: modelChartValueFormatter(value => formatModelNumber(value, name.endsWith('_ms') ? 0 : 2)) },
    showSymbol: history.length <= 80,
    symbolSize: 4,
    connectNulls: false,
    data: history.map((point) => {
      const value = point.runtime[name]
      return [point.globalStep, value === undefined ? null : transform(value)]
    }),
  }
}

function buildDualAxisOption(input: {
  xName: string
  leftAxisName: string
  rightAxisName: string
  series: Record<string, unknown>[]
}): EChartsCoreOption {
  const visual = chartVisual()
  return {
    animation: false,
    color: visual.palette,
    textStyle: { color: visual.text, fontFamily: workbenchFontFamily() },
    tooltip: { trigger: 'axis' },
    legend: { type: 'scroll', top: 0, left: 0, textStyle: { fontSize: 11, color: visual.text }, pageTextStyle: { color: visual.text } },
    grid: { left: 60, right: 60, top: 48, bottom: 42 },
    xAxis: {
      type: 'value',
      min: 1,
      minInterval: 1,
      name: input.xName,
      nameLocation: 'middle',
      nameGap: 28,
      ...visual.axis,
    },
    yAxis: [
      ...[input.leftAxisName, input.rightAxisName].map(name => ({
        type: 'value', scale: true, name, ...visual.axis,
        minInterval: name === 'ms' ? 1 : undefined,
        axisLabel: { ...visual.axis.axisLabel, formatter: (value: number) => formatModelNumber(value, name === 'ms' ? 0 : 2) },
      })),
    ],
    dataZoom: input.series.length > 0 ? [{ type: 'inside', filterMode: 'none' }] : [],
    series: input.series,
  }
}

function bytesToGib(value: number): number {
  return Number((value / (1024 ** 3)).toFixed(4))
}

function buildMetricOption(
  history: TrainingMetricPoint[],
  preferredNames: readonly string[],
  includeAdditionalMetrics: boolean,
): EChartsCoreOption {
  const metricNames = readOrderedMetricNames(
    history,
    preferredNames,
    includeAdditionalMetrics,
  )
  return buildBaseOption(metricNames.map(name => metricLine(name, history, name)))
}

function metricLine(name: string, history: TrainingMetricPoint[], key: string, epoch?: number) {
  const metric = history.find(point => point.epoch === epoch)?.metrics[key]
  const markLine = epoch != null && metric !== undefined ? {
    silent: true, symbol: 'none', lineStyle: { type: 'dashed', color: chartVisual().text },
    label: { position: 'insideEndTop', rotate: 0, color: chartVisual().text, textBorderWidth: 0,
      formatter: locale.value.startsWith('zh') ? `最佳轮次 ${epoch}` : `Best epoch ${epoch}` },
    data: [{ xAxis: epoch }],
  } : undefined
  return {
    name,
    type: 'line',
    showSymbol: history.length <= 80,
    symbolSize: 5,
    connectNulls: false,
    data: history.map((point) => [point.epoch, point.metrics[key] ?? null]),
    markLine,
  }
}

function buildLearningRateOption(history: TrainingScalarPoint[]): EChartsCoreOption {
  return buildBaseOption([{
    name: 'learning_rate',
    type: 'line',
    showSymbol: history.length <= 80,
    symbolSize: 5,
    data: history.map((point) => [point.epoch, point.value]),
  }], formatLearningRate)
}

function buildBaseOption(series: unknown[], format: (value: number) => string = formatModelNumber): EChartsCoreOption {
  const visual = chartVisual()
  return {
    animation: false,
    color: visual.palette,
    textStyle: { color: visual.text, fontFamily: workbenchFontFamily() },
    tooltip: { trigger: 'axis', valueFormatter: modelChartValueFormatter(format) },
    legend: { type: 'scroll', top: 0, left: 0, textStyle: { fontSize: 11, color: visual.text }, pageTextStyle: { color: visual.text } },
    grid: { left: 54, right: 18, top: 48, bottom: 42 },
    xAxis: { type: 'value', min: 1, minInterval: 1, name: 'epoch', nameLocation: 'middle', nameGap: 28, ...visual.axis,
      axisLabel: { ...visual.axis.axisLabel, formatter: (value: number) => Number.isInteger(value) ? String(value) : '' } },
    yAxis: { type: 'value', scale: true, ...visual.axis,
      axisLabel: { ...visual.axis.axisLabel, formatter: (value: number) => formatSmallModelNumber(value) } },
    dataZoom: series.length > 0 ? [{ type: 'inside', filterMode: 'none' }] : [],
    series,
  }
}

function chartVisual() {
  const styles = getComputedStyle(document.documentElement)
  const text = styles.getPropertyValue('--am-text-muted').trim() || '#64676a'
  const border = styles.getPropertyValue('--am-border').trim() || '#d9ddda'
  const dark = document.documentElement.dataset.theme === 'dark'
  return {
    text,
    palette: dark ? ['#00d696', '#75b4ff', '#ffc35c', '#ff8181', '#bba1ff', '#4de1f1'] : ['#0f8a68', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'],
    axis: { axisLabel: { color: text }, nameTextStyle: { color: text }, axisLine: { lineStyle: { color: border } }, splitLine: { lineStyle: { color: border } } },
  }
}
</script>

<style scoped>
.training-charts-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.training-chart-card {
  position: relative;
  min-width: 0;
  padding: 12px;
  background: var(--am-surface-soft);
  border: 1px solid var(--am-border);
  border-radius: 8px;
}

.training-chart-card--wide {
  grid-column: 1 / -1;
}

.training-chart-card h3 {
  margin: 0 0 8px;
  color: var(--am-text);
  font-size: 13px;
}

.training-chart-canvas {
  width: 100%;
  height: 300px;
}

.training-chart-canvas--small {
  height: 220px;
}

.training-charts-grid--compact .training-chart-canvas {
  height: 210px;
}

.training-chart-empty {
  position: absolute;
  inset: 50% 0 auto;
  color: var(--am-text-muted);
  text-align: center;
  pointer-events: none;
}

@media (max-width: 960px) {
  .training-charts-grid {
    grid-template-columns: 1fr;
  }

  .training-chart-card--wide {
    grid-column: auto;
  }
}
</style>
