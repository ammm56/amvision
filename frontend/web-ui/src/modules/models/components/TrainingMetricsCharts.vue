<template>
  <div class="training-charts-grid">
    <article class="training-chart-card">
      <h3>{{ t('trainingDetail.charts.trainMetrics') }}</h3>
      <div ref="trainChartElement" class="training-chart-canvas" />
      <span v-if="trainHistory.length === 0" class="training-chart-empty">{{ t('common.noValue') }}</span>
    </article>
    <article class="training-chart-card">
      <h3>{{ t('trainingDetail.charts.validationMetrics') }}</h3>
      <div ref="validationChartElement" class="training-chart-canvas" />
      <span v-if="validationHistory.length === 0" class="training-chart-empty">{{ t('common.noValue') }}</span>
    </article>
    <article class="training-chart-card training-chart-card--wide">
      <h3>{{ t('trainingDetail.charts.learningRate') }}</h3>
      <div ref="learningRateChartElement" class="training-chart-canvas training-chart-canvas--small" />
      <span v-if="learningRateHistory.length === 0" class="training-chart-empty">{{ t('common.noValue') }}</span>
    </article>
    <article class="training-chart-card">
      <h3>{{ t('trainingDetail.charts.runtimePerformance') }}</h3>
      <div ref="runtimeChartElement" class="training-chart-canvas training-chart-canvas--small" />
      <span v-if="runtimeHistory.length === 0" class="training-chart-empty">{{ t('common.noValue') }}</span>
    </article>
    <article class="training-chart-card">
      <h3>{{ t('trainingDetail.charts.gpuResources') }}</h3>
      <div ref="gpuChartElement" class="training-chart-canvas training-chart-canvas--small" />
      <span v-if="!hasGpuHistory" class="training-chart-empty">{{ t('common.noValue') }}</span>
    </article>
    <article class="training-chart-card training-chart-card--wide">
      <h3>{{ t('trainingDetail.charts.stageTiming') }}</h3>
      <div ref="stageChartElement" class="training-chart-canvas training-chart-canvas--small" />
      <span v-if="!hasStageHistory" class="training-chart-empty">{{ t('common.noValue') }}</span>
    </article>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  TooltipComponent,
} from 'echarts/components'
import { init, use, type ECharts, type EChartsCoreOption } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'

import type { ModelTaskType } from '../services/model.service'
import {
  getTrainingMetricCapability,
  readOrderedMetricNames,
  type TrainingMetricPoint,
  type TrainingRuntimePoint,
  type TrainingScalarPoint,
} from '../training-metric-history'

use([LineChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, CanvasRenderer])

const props = defineProps<{
  taskType: ModelTaskType
  trainHistory: TrainingMetricPoint[]
  validationHistory: TrainingMetricPoint[]
  learningRateHistory: TrainingScalarPoint[]
  runtimeHistory: TrainingRuntimePoint[]
}>()

const { t } = useI18n()
const trainChartElement = ref<HTMLElement | null>(null)
const validationChartElement = ref<HTMLElement | null>(null)
const learningRateChartElement = ref<HTMLElement | null>(null)
const runtimeChartElement = ref<HTMLElement | null>(null)
const gpuChartElement = ref<HTMLElement | null>(null)
const stageChartElement = ref<HTMLElement | null>(null)
const capability = computed(() => getTrainingMetricCapability(props.taskType))
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

onMounted(async () => {
  await nextTick()
  trainChart = initializeChart(trainChartElement.value)
  validationChart = initializeChart(validationChartElement.value)
  learningRateChart = initializeChart(learningRateChartElement.value)
  runtimeChart = initializeChart(runtimeChartElement.value)
  gpuChart = initializeChart(gpuChartElement.value)
  stageChart = initializeChart(stageChartElement.value)
  renderCharts()
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
  ],
  renderCharts,
  { deep: true },
)

onBeforeUnmount(() => {
  resizeObserver?.disconnect()
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
  return init(element, undefined, { renderer: 'canvas' })
}

function renderCharts(): void {
  trainChart?.setOption(buildMetricOption(
    props.trainHistory,
    capability.value.trainMetrics,
    true,
  ), true)
  validationChart?.setOption(buildMetricOption(
    props.validationHistory,
    capability.value.validationMetrics,
    false,
  ), true)
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
  return {
    animation: false,
    color: ['#0f8a68', '#3b82f6', '#f59e0b', '#8b5cf6'],
    tooltip: { trigger: 'axis' },
    legend: { type: 'scroll', top: 0, left: 0, textStyle: { fontSize: 11 } },
    grid: { left: 60, right: 60, top: 48, bottom: 42 },
    xAxis: {
      type: 'value',
      min: 1,
      minInterval: 1,
      name: input.xName,
      nameLocation: 'middle',
      nameGap: 28,
    },
    yAxis: [
      { type: 'value', scale: true, name: input.leftAxisName },
      { type: 'value', scale: true, name: input.rightAxisName },
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
  return buildBaseOption(metricNames.map((name) => ({
    name,
    type: 'line',
    showSymbol: history.length <= 80,
    symbolSize: 5,
    connectNulls: false,
    data: history.map((point) => [point.epoch, point.metrics[name] ?? null]),
  })))
}

function buildLearningRateOption(history: TrainingScalarPoint[]): EChartsCoreOption {
  return buildBaseOption([{
    name: 'learning_rate',
    type: 'line',
    showSymbol: history.length <= 80,
    symbolSize: 5,
    data: history.map((point) => [point.epoch, point.value]),
  }])
}

function buildBaseOption(series: unknown[]): EChartsCoreOption {
  return {
    animation: false,
    color: ['#0f8a68', '#3b82f6', '#f59e0b', '#ef4444', '#8b5cf6', '#06b6d4'],
    tooltip: { trigger: 'axis' },
    legend: { type: 'scroll', top: 0, left: 0, textStyle: { fontSize: 11 } },
    grid: { left: 54, right: 18, top: 48, bottom: 42 },
    xAxis: { type: 'value', min: 1, minInterval: 1, name: 'epoch', nameLocation: 'middle', nameGap: 28 },
    yAxis: { type: 'value', scale: true },
    dataZoom: series.length > 0 ? [{ type: 'inside', filterMode: 'none' }] : [],
    series,
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
