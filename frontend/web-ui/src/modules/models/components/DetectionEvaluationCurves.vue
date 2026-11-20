<template>
  <section class="curve-layout">
    <div class="curve-toolbar">
      <span>{{ zh ? `指标候选最低分 ${scoreFloor}` : `Metric score floor ${scoreFloor}` }}</span>
      <Button size="sm" @click="downloadEvaluationJson(`${taskId}-curves.json`, data)"><Download :size="16" />{{ zh ? '下载曲线数据' : 'Download curve data' }}</Button>
    </div>
    <div v-if="data.series.length" class="curve-grid">
      <article class="resource-section">
        <h3>Precision–Recall {{ zh ? '曲线' : 'curve' }} <small>IoU = {{ data.iou_threshold.toFixed(2) }}</small></h3>
        <div ref="precisionPlot" class="curve-plot" role="img" aria-label="Precision–Recall" />
      </article>
      <article class="resource-section">
        <h3>F1–Confidence {{ zh ? '曲线' : 'curve' }} <small>{{ workingPoint }}</small></h3>
        <div ref="confidencePlot" class="curve-plot" role="img" :aria-label="`F1–Confidence · ${workingPoint}`" />
      </article>
    </div>
    <p v-else role="status">{{ zh ? '此报告没有可绘制曲线的标注。' : 'The report has no annotations for curves.' }}</p>
    <article v-if="data.confusion.length" class="resource-section">
      <h3>{{ zh ? '工作点混淆矩阵' : 'Working-point confusion matrix' }}</h3>
      <EvaluationConfusionMatrix :labels="names" :rows="rows" :zh="zh" />
    </article>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Download } from '@lucide/vue'
import { LineChart } from 'echarts/charts'
import { GridComponent, LegendComponent, MarkLineComponent, TooltipComponent } from 'echarts/components'
import { init, use, type ECharts } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { loadCanvasFont, workbenchFontFamily } from '@/shared/ui/canvas-font'
import { formatSmallModelNumber, modelChartValueFormatter } from '../model-number-format'
import Button from '@/shared/ui/components/Button.vue'
import { downloadEvaluationJson, type DetectionEvaluationCurves } from '../services/model-evaluation.service'
import EvaluationConfusionMatrix from './EvaluationConfusionMatrix.vue'

use([LineChart, GridComponent, LegendComponent, MarkLineComponent, TooltipComponent, CanvasRenderer])
const props = defineProps<{ data: DetectionEvaluationCurves; taskId: string; zh: boolean }>()
const precisionPlot = ref<HTMLElement | null>(null)
const confidencePlot = ref<HTMLElement | null>(null)
const scoreFloor = computed(() => formatSmallModelNumber(props.data.score_floor))
const workingPoint = computed(() => `${props.zh ? '工作点' : 'Operating point'} ${formatSmallModelNumber(props.data.working_point)}`)
const classNames = computed(() => props.data.series.map(row => row.class_name))
const names = computed(() => [...props.data.labels.map(label => label.name), props.zh ? '背景' : 'Background'])
const rows = computed(() => {
  const positions = new Map<number | null, number>(props.data.labels.map((label, index) => [label.id, index]))
  positions.set(null, props.data.labels.length)
  const result = names.value.map(() => names.value.map(() => 0))
  for (const cell of props.data.confusion) {
    const row = positions.get(cell.actual)
    const col = positions.get(cell.predicted)
    if (row !== undefined && col !== undefined) result[row][col] = cell.count
  }
  return result
})
let pr: ECharts | undefined
let f1: ECharts | undefined
function draw(): void {
  const style = getComputedStyle(document.documentElement)
  const color = style.getPropertyValue('--am-text-muted').trim()
  const border = style.getPropertyValue('--am-border').trim()
  const axis = {
    type: 'value', min: 0, max: 1, interval: 0.2,
    axisLabel: { color, formatter: (value: number) => value.toFixed(1) },
    nameTextStyle: { color }, splitLine: { lineStyle: { color: border } },
  }
  const common = {
    animation: false,
    color: ['#00bd83', '#f58729', '#6499ee', '#ac7de8', '#08a9c7'],
    textStyle: { fontFamily: workbenchFontFamily() },
    grid: { left: 50, right: 16, top: 24, bottom: 67 },
    legend: { type: 'scroll', bottom: 0, data: classNames.value, textStyle: { color } },
    tooltip: {
      trigger: 'axis', confine: true,
      backgroundColor: style.getPropertyValue('--am-surface-raised').trim(),
      borderColor: border, textStyle: { color: style.getPropertyValue('--am-text').trim() },
      valueFormatter: modelChartValueFormatter(value => value.toFixed(3)),
    },
  }
  const xAxis = (name: string) => ({ ...axis, name, nameLocation: 'middle', nameGap: 31 })
  const yAxis = (name: string) => ({ ...axis, name, nameLocation: 'middle', nameGap: 36 })
  pr?.setOption({
    ...common, xAxis: xAxis('Recall'), yAxis: yAxis('Precision'),
    series: props.data.series.map(row => ({
      name: row.class_name, type: 'line', showSymbol: false, step: 'end',
      data: row.precision_recall.map((value, index) => [index / 100, value]),
    })),
  }, { replaceMerge: ['series'] })
  f1?.setOption({
    ...common, xAxis: xAxis('Confidence'), yAxis: yAxis('F1'),
    series: [
      ...props.data.series.map(row => ({
        name: row.class_name, type: 'line', showSymbol: false,
        data: row.f1_confidence.map((value, point) => [props.data.confidence[point], value]),
      })),
      {
        id: 'operating-point', type: 'line', data: [], silent: true,
        markLine: {
          silent: true, symbol: 'none', lineStyle: { color, type: 'dashed' },
          label: {
            show: true, position: 'insideEndTop', rotate: 0,
            formatter: formatSmallModelNumber(props.data.working_point), color,
          },
          data: [{ xAxis: props.data.working_point }],
        },
      },
    ],
  }, { replaceMerge: ['series'] })
}

watch([precisionPlot, confidencePlot], ([precision, confidence], _, onCleanup) => {
  if (!precision || !confidence) return
  pr = init(precision)
  f1 = init(confidence)
  draw()
  const resize = new ResizeObserver(() => { pr?.resize(); f1?.resize() })
  resize.observe(precision)
  resize.observe(confidence)
  const theme = new MutationObserver(draw)
  theme.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
  onCleanup(() => {
    resize.disconnect()
    theme.disconnect()
    pr?.dispose()
    f1?.dispose()
    pr = undefined
    f1 = undefined
  })
}, { flush: 'post' })
watch(() => props.data, draw, { flush: 'post' })
watch(classNames, names => { void loadCanvasFont(names.join(' ')).then(draw) }, { immediate: true })
</script>

<style scoped>
.curve-layout { display:grid; gap:14px; min-width:0; }
.curve-toolbar { display:flex; flex-wrap:wrap; justify-content:flex-end; align-items:center; gap:12px; color:var(--am-text-muted); }
.curve-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; }
.curve-grid > article { min-width:0; padding:14px 12px; }
.curve-layout h3 { display:flex; align-items:baseline; flex-wrap:wrap; gap:4px 10px; margin:0 0 8px; }
.curve-layout h3 small { color:var(--am-text-muted); font-size:var(--am-type-caption); font-weight:400; }
.curve-plot { min-width:0; height:clamp(245px, 35vh, 346px); overflow:hidden; }
@media (max-width:820px) { .curve-grid { grid-template-columns:minmax(0,1fr); } }
</style>
