<template>
  <div class="training-charts-grid" :class="{ 'training-charts-grid--compact': compact }">
    <article v-if="!diagnosticsOnly" class="training-chart-card">
      <div class="training-chart-heading">
        <h3>{{ lossTitle }}</h3>
        <span v-if="latestTrainLoss !== undefined">{{ zh ? '最新训练损失' : 'Latest training loss' }} <strong>{{ formatTrainingMetric(latestTrainLoss) }}</strong></span>
      </div>
      <div ref="trainChartElement" class="training-chart-canvas" />
      <span v-if="trainHistory.length === 0 && !validationLossKey" class="training-chart-empty">{{ metricsEmptyText || t('common.noValue') }}</span>
      <p v-if="compact && validationHistory.length && !validationLossKey" class="training-chart-note">
        {{ zh ? '这次训练未记录验证损失' : 'Validation loss was not recorded for this run' }}
      </p>
    </article>
    <article v-if="!diagnosticsOnly" class="training-chart-card">
      <div class="training-chart-heading">
        <h3>{{ primaryMetricLabel ? `${zh ? '验证集' : 'Validation'} ${primaryMetricLabel}` : t('trainingDetail.charts.validationMetrics') }}</h3>
        <div v-if="validationSummary.length" class="training-chart-scores">
          <span v-for="score in validationSummary" :key="score.label" :title="checkpointLabel(score.epoch, false)">
            {{ score.label }} <strong>{{ score.value }}</strong>
          </span>
        </div>
      </div>
      <div ref="validationChartElement" class="training-chart-canvas" />
      <span v-if="validationHistory.length === 0" class="training-chart-empty">{{ metricsEmptyText || t('common.noValue') }}</span>
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
import { formatLearningRate, formatModelNumber, formatSmallModelNumber, formatTrainingMetric, modelChartValueFormatter } from '../model-number-format'
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  type TooltipComponentOption,
} from 'echarts/components'
import { init, use, type ECharts, type EChartsCoreOption } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { workbenchFontFamily } from '@/shared/ui/canvas-font'

import type { ModelTaskType } from '../services/model.service'
import {
  formatTrainingMetricLabel,
  getTrainingMetricCapability,
  readOrderedMetricNames,
  type TrainingMetricPoint,
  type TrainingRuntimePoint,
  type TrainingScalarPoint,
} from '../training-metric-history'

use([LineChart, GridComponent, TooltipComponent, LegendComponent, MarkLineComponent, MarkPointComponent, DataZoomComponent, CanvasRenderer])

const props = defineProps<{
  taskType: ModelTaskType
  trainHistory: TrainingMetricPoint[]
  validationHistory: TrainingMetricPoint[]
  learningRateHistory: TrainingScalarPoint[]
  runtimeHistory: TrainingRuntimePoint[]
  runtimeEmptyText: string
  metricsEmptyText?: string
  compact?: boolean
  diagnosticsOnly?: boolean
  bestEpoch?: number
  primaryMetric?: string | null
}>()

const { t, locale } = useI18n()
const zh = computed(() => locale.value.startsWith('zh'))
const trainChartElement = ref<HTMLElement | null>(null)
const validationChartElement = ref<HTMLElement | null>(null)
const learningRateChartElement = ref<HTMLElement | null>(null)
const runtimeChartElement = ref<HTMLElement | null>(null)
const gpuChartElement = ref<HTMLElement | null>(null)
const stageChartElement = ref<HTMLElement | null>(null)
const capability = computed(() => getTrainingMetricCapability(props.taskType))
const trainLossKey = computed(() => readCompactMetric(props.trainHistory, ['loss', 'total_loss', 'train/loss_epoch', 'train/loss']))
const validationLossKey = computed(() => readCompactMetric(props.validationHistory, ['loss', 'total_loss', 'val_loss', 'val/loss']))
const lossTitle = computed(() => {
  if (trainLossKey.value && validationLossKey.value) return zh.value ? '训练与验证损失' : 'Training and validation loss'
  if (trainLossKey.value) return zh.value ? '训练损失' : 'Training loss'
  if (validationLossKey.value) return zh.value ? '验证损失' : 'Validation loss'
  return t('trainingDetail.charts.trainMetrics')
})
const latestTrainLoss = computed(() => {
  const key = trainLossKey.value
  return key ? latestMetricPoint(props.trainHistory, key)?.metrics[key] : undefined
})
const checkpointMetricKey = computed(() => {
  const name = props.primaryMetric
  if (name && !/^train[_/]/.test(name)) {
    return readCompactMetric(props.validationHistory, [name, name.replace(/^val[_/]/, '')])
  }
  return undefined
})
const primaryMetricKey = computed(() => {
  return checkpointMetricKey.value
    ?? readCompactMetric(props.validationHistory, capability.value.validationMetrics.filter(name => name !== 'loss'))
})
const primaryMetricLabel = computed(() => {
  const key = primaryMetricKey.value
  return key ? formatTrainingMetricLabel(key, props.taskType, props.validationHistory) : undefined
})
const validationBestPoint = computed(() => {
  const key = checkpointMetricKey.value
  const epoch = props.bestEpoch
  return key && epoch !== undefined
    ? props.validationHistory.find(point => point.epoch === epoch && Number.isFinite(point.metrics[key]))
    : undefined
})
const validationLatestPoint = computed(() => {
  const key = primaryMetricKey.value
  const point = key ? latestMetricPoint(props.validationHistory, key) : undefined
  return point?.epoch === validationBestPoint.value?.epoch ? undefined : point
})
const validationSummary = computed(() => {
  const key = primaryMetricKey.value
  const best = validationBestPoint.value
  const latest = validationLatestPoint.value
  if (!key) return []
  return [
    ...(best ? [{ label: zh.value ? '最佳' : 'Best', value: formatTrainingMetric(best.metrics[key]), epoch: best.epoch }] : []),
    ...(latest ? [{ label: zh.value ? '最新' : 'Latest', value: formatTrainingMetric(latest.metrics[key]), epoch: latest.epoch }] : []),
  ]
})
const compactLastEpoch = computed(() => props.compact
  ? Math.max(props.trainHistory.at(-1)?.epoch ?? 0, props.validationHistory.at(-1)?.epoch ?? 0)
  : undefined)
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
    locale.value,
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

function readCompactMetric(history: TrainingMetricPoint[], names: readonly string[]): string | undefined {
  return props.compact ? names.find(name => history.some(point => Number.isFinite(point.metrics[name]))) : undefined
}

function latestMetricPoint(history: TrainingMetricPoint[], key: string): TrainingMetricPoint | undefined {
  for (let index = history.length - 1; index >= 0; index -= 1) {
    const point = history[index]
    if (Number.isFinite(point.metrics[key])) return point
  }
  return undefined
}

function renderCharts(): void {
  const lossSeries = []
  if (trainLossKey.value) {
    lossSeries.push(metricLine('train loss', props.trainHistory, trainLossKey.value, props.bestEpoch))
  }
  if (validationLossKey.value) {
    const color = chartVisual().text
    lossSeries.push({
      ...metricLine('val loss', props.validationHistory, validationLossKey.value, trainLossKey.value ? undefined : props.bestEpoch),
      lineStyle: { color },
      itemStyle: { color },
    })
  }
  trainChart?.setOption(lossSeries.length
    ? buildBaseOption(lossSeries)
    : buildMetricOption(props.trainHistory, capability.value.trainMetrics, true), true)
  const validationKey = primaryMetricKey.value
  validationChart?.setOption(validationKey
    ? buildBaseOption([{
      ...metricLine(`val ${primaryMetricLabel.value}`, props.validationHistory, validationKey, validationBestPoint.value?.epoch),
      markPoint: validationMarkers(validationKey),
    }])
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
    tooltip: { trigger: 'axis', ...visual.tooltip },
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

function checkpointLabel(epoch: number, best: boolean): string {
  if (best) return zh.value ? `最佳轮次 ${epoch}` : `Best epoch ${epoch}`
  return zh.value ? `第 ${epoch} 轮` : `Epoch ${epoch}`
}

function validationMarkers(key: string): Record<string, unknown> {
  const visual = chartVisual()
  const points = [validationBestPoint.value, validationLatestPoint.value]
  return {
    silent: true,
    symbol: 'circle',
    symbolSize: 8,
    label: { show: false },
    itemStyle: { color: visual.palette[0], borderColor: visual.surface, borderWidth: 1.5 },
    data: points.flatMap(point => point ? [{ coord: [point.epoch, point.metrics[key]] }] : []),
  }
}

function metricLine(name: string, history: TrainingMetricPoint[], key: string, epoch?: number) {
  const metric = history.find(point => point.epoch === epoch)?.metrics[key]
  const markLine = epoch != null && Number.isFinite(metric) ? {
    silent: true, symbol: 'none', lineStyle: { type: 'dashed', color: chartVisual().text },
    label: { position: 'insideEndTop', rotate: 0, color: chartVisual().text, textBorderWidth: 0,
      formatter: checkpointLabel(epoch, true) },
    data: [{ xAxis: epoch }],
  } : undefined
  const plotHistory = props.compact ? history.filter(point => Number.isFinite(point.metrics[key])) : history
  return {
    name,
    type: 'line',
    showSymbol: plotHistory.length <= 80,
    symbolSize: 5,
    connectNulls: false,
    data: plotHistory.map((point) => [point.epoch, point.metrics[key] ?? null]),
    markLine,
  }
}

function buildLearningRateOption(history: TrainingScalarPoint[]): EChartsCoreOption {
  const option = buildBaseOption([{
    type: 'line',
    showSymbol: history.length <= 80,
    symbolSize: 5,
    data: history.map((point) => [point.epoch, point.value]),
  }])
  const { valueFormatter, ...tooltipOptions } = option.tooltip
  const tooltip: TooltipComponentOption = {
    ...tooltipOptions,
    formatter(params) {
      const point = Array.isArray(params) ? params[0] : params
      const value = point?.value
      if (!Array.isArray(value)) return ''
      const [epoch, rate] = value
      if (typeof epoch !== 'number' || typeof rate !== 'number') return ''
      return `${zh.value ? `第 ${epoch} 轮` : `Epoch ${epoch}`} · ${formatLearningRate(rate)}`
    },
  }
  return { ...option, legend: { show: false }, tooltip, grid: { ...option.grid, top: 20 } }
}

function buildBaseOption(series: unknown[]) {
  const visual = chartVisual()
  const lastEpoch = compactLastEpoch.value
  const axisMax = lastEpoch && lastEpoch > 1 ? lastEpoch : undefined
  return {
    animation: false,
    color: visual.palette,
    textStyle: { color: visual.text, fontFamily: workbenchFontFamily() },
    tooltip: { trigger: 'axis' as const, ...visual.tooltip, valueFormatter: modelChartValueFormatter(formatTrainingMetric) },
    legend: {
      type: 'scroll', top: 0, left: props.compact ? 'auto' : 0, right: props.compact ? 0 : 'auto',
      icon: props.compact ? 'circle' : undefined,
      itemWidth: props.compact ? 8 : undefined,
      itemHeight: props.compact ? 8 : undefined,
      textStyle: { fontSize: 11, color: visual.text }, pageTextStyle: { color: visual.text },
    },
    grid: { left: 54, right: 23, top: 48, bottom: 42 },
    xAxis: { type: 'value', min: 1, max: axisMax, minInterval: 1, name: 'epoch', nameLocation: 'middle', nameGap: 28, ...visual.axis,
      axisLabel: { ...visual.axis.axisLabel, hideOverlap: true, formatter: (value: number) => Number.isInteger(value) ? String(value) : '' } },
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
  const foreground = styles.getPropertyValue('--am-text').trim() || (dark ? '#eeeeee' : '#242424')
  const surface = styles.getPropertyValue('--am-surface-soft').trim() || (dark ? '#222222' : '#ffffff')
  return {
    text,
    foreground,
    surface,
    tooltip: { backgroundColor: surface, borderColor: border, textStyle: { color: foreground }, confine: true },
    palette: dark ? ['#00d696', '#75b4ff', '#ffc35c', '#ff8181', '#bba1ff', '#4de1f1'] : ['#0f8a68', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'],
    axis: { axisLabel: { color: text }, nameTextStyle: { color: text }, axisLine: { lineStyle: { color: border } }, splitLine: { lineStyle: { color: border } } },
  }
}
</script>

<style scoped>
.training-chart-heading { display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:4px 12px; }
.training-chart-scores { display:flex; flex-wrap:wrap; gap:4px 12px; }
.training-chart-note { margin:0; color:var(--am-text-muted); font-size:12px; }
.training-chart-heading span { color:var(--am-text-muted); font-size:12px; font-variant-numeric:tabular-nums; }
.training-chart-heading strong { margin-inline-start:4px; color:var(--am-text); }
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
