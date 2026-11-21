import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { i18n } from '@/platform/i18n'

const charts = vi.hoisted(() => ({ instances: [] as Array<{ setOption: ReturnType<typeof vi.fn>; resize: ReturnType<typeof vi.fn>; dispose: ReturnType<typeof vi.fn> }> }))
vi.mock('echarts/core', () => ({
  use: vi.fn(),
  init: vi.fn(() => {
    const instance = { setOption: vi.fn(), resize: vi.fn(), dispose: vi.fn() }
    charts.instances.push(instance)
    return instance
  }),
}))
import TrainingMetricsCharts from './TrainingMetricsCharts.vue'

describe('training chart theme', () => {
  afterEach(() => {
    document.documentElement.removeAttribute('data-theme')
    document.documentElement.style.removeProperty('--am-text-muted')
    document.documentElement.style.removeProperty('--am-border')
    charts.instances.length = 0
    vi.restoreAllMocks()
  })

  it('redraws chart labels and grid when the theme changes', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(300)
    document.documentElement.dataset.theme = 'light'
    document.documentElement.style.setProperty('--am-text-muted', '#64676a')
    document.documentElement.style.setProperty('--am-border', '#dddddd')
    const wrapper = mount(TrainingMetricsCharts, {
      props: { taskType: 'detection', trainHistory: [], validationHistory: [], learningRateHistory: [], runtimeHistory: [], runtimeEmptyText: '—' },
      global: { plugins: [i18n] },
    })
    await flushPromises()
    const chart = charts.instances[0]!
    expect(chart.setOption.mock.lastCall?.[0].legend.textStyle.color).toBe('#64676a')
    document.documentElement.style.setProperty('--am-text-muted', '#b0b2b4')
    document.documentElement.style.setProperty('--am-border', '#3d3a39')
    document.documentElement.dataset.theme = 'dark'
    await flushPromises()
    const option = chart.setOption.mock.lastCall?.[0]
    expect(option.legend.textStyle.color).toBe('#b0b2b4')
    expect(option.yAxis.axisLabel.color).toBe('#b0b2b4')
    expect(option.yAxis.splitLine.lineStyle.color).toBe('#3d3a39')
    wrapper.unmount()
    expect(chart.dispose).toHaveBeenCalled()
  })

  it('formats training tooltip values without rounding the plotted data', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(300)
    const wrapper = mount(TrainingMetricsCharts, {
      props: {
        taskType: 'detection',
        trainHistory: [{ epoch: 1, metrics: { loss: 0.123456 } }],
        validationHistory: [],
        learningRateHistory: [{ epoch: 1, value: 0.000012345 }],
        runtimeHistory: [{ globalStep: 1, timestamp: '', runtime: { step_time_ms: 19.6789 } }],
        runtimeEmptyText: '—',
      },
      global: { plugins: [i18n] },
    })
    await flushPromises()
    const [train, , learningRate, runtime] = charts.instances.map(chart => chart.setOption.mock.lastCall?.[0])
    expect(train.tooltip.valueFormatter([1, 0.123456])).toEqual(['1', '0.123'])
    expect(train.yAxis.axisLabel.formatter(0.9884, 0)).toBe('0.9884')
    expect(train.yAxis.axisLabel.formatter(0.9884, 5)).toBe('0.9884')
    expect(train.xAxis.axisLabel.formatter(1.5)).toBe('')
    expect(train.series[0].data).toEqual([[1, 0.123456]])
    expect(learningRate.tooltip.formatter([{ value: [1, 0.000012345] }])).toContain('1.234e-5')
    const stepTime = runtime.series.find((series: { name: string }) => series.name === 'step_time_ms')
    expect(stepTime.tooltip.valueFormatter([1, 19.6789])).toEqual(['1', '20'])
    expect(stepTime.data).toEqual([[1, 19.6789]])
    wrapper.unmount()
  })

  it('plots reported detection losses and distinguishes the best validation from the latest', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(400)
    const wrapper = mount(TrainingMetricsCharts, {
      props: {
        compact: true,
        taskType: 'detection',
        bestEpoch: 5,
        primaryMetric: 'val_map50_95',
        trainHistory: [
          { epoch: 5, metrics: { loss: 1.34 } },
          { epoch: 12, metrics: { loss: 1.1 } },
        ],
        validationHistory: [
          { epoch: 5, metrics: { loss: 0.9, map50_95: 0.809 } },
          { epoch: 8, metrics: { loss: 0.87 } },
          { epoch: 10, metrics: { loss: 0.85, map50_95: 0.804 } },
        ],
        learningRateHistory: [],
        runtimeHistory: [],
        runtimeEmptyText: '—',
      },
      global: { plugins: [i18n] },
    })
    await flushPromises()
    const [loss, validation] = charts.instances.map(chart => chart.setOption.mock.lastCall?.[0])
    expect(loss.xAxis.max).toBe(12)
    expect(validation.xAxis.max).toBe(12)
    expect(loss.series.map((series: { name: string }) => series.name)).toEqual(['train loss', 'val loss'])
    expect(loss.series[1].data).toEqual([[5, 0.9], [8, 0.87], [10, 0.85]])
    expect(wrapper.findAll('h3')[1].text()).toContain('mAP50–95')
    expect(validation.series[0].data).toEqual([[5, 0.809], [10, 0.804]])
    expect(validation.series[0].markLine.data).toEqual([{ xAxis: 5 }])
    expect(validation.series[0].markPoint.label.show).toBe(false)
    expect(validation.series[0].markPoint.data).toEqual([{ coord: [5, 0.809] }, { coord: [10, 0.804] }])
    expect(wrapper.get('.training-chart-scores').text()).toMatch(/最佳\s+0.809.*最新\s+0.804/)
    wrapper.unmount()
  })

  it('shows classification accuracy without inferring validation loss or an unrecorded best point', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(400)
    const wrapper = mount(TrainingMetricsCharts, {
      props: {
        compact: true,
        taskType: 'classification',
        bestEpoch: 8,
        primaryMetric: 'val_top1_accuracy',
        trainHistory: [{ epoch: 10, metrics: { loss: 0.000017 } }],
        validationHistory: [{ epoch: 10, metrics: { top1_accuracy: 1 } }],
        learningRateHistory: [],
        runtimeHistory: [],
        runtimeEmptyText: '—',
      },
      global: { plugins: [i18n] },
    })
    await flushPromises()
    const [loss, validation] = charts.instances.map(chart => chart.setOption.mock.lastCall?.[0])
    expect(wrapper.findAll('h3')[1].text()).toContain('Top-1 Accuracy')
    expect(wrapper.text()).toContain('1.7e-5')
    expect(loss.series.map((series: { name: string }) => series.name)).toEqual(['train loss'])
    expect(validation.series[0].markLine).toBeUndefined()
    expect(validation.series[0].markPoint.data).toMatchObject([{ coord: [10, 1] }])
    wrapper.unmount()
  })

  it.each([
    ['segmentation', 'val_map50_95', { map50_95: 0.4, mask_map50_95: 0.4, bbox_map50_95: 0.6 }, 'Mask mAP50–95'],
    ['segmentation', 'val_map50_95', { map50_95: 0.4, mask_map50_95: 0, bbox_map50_95: 0.4 }, 'Box mAP50–95'],
    ['segmentation', 'val/segm_mAP_50_95', { 'val/segm_mAP_50_95': 0.4 }, 'Mask mAP50–95'],
    ['pose', 'val_oks_ap50_95', { oks_ap50_95: 0.4, map50_95: 0.6 }, 'OKS AP50–95'],
    ['obb', 'val_map50_95', { map50_95: 0.4, rotated_map50_95: 0.4 }, 'Rotated mAP50–95'],
  ] as const)('plots the %s primary metric (%s) and the real validation loss', async (taskType, primaryMetric, metrics, label) => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(400)
    const wrapper = mount(TrainingMetricsCharts, {
      props: {
        compact: true,
        taskType,
        primaryMetric,
        bestEpoch: 5,
        trainHistory: [{ epoch: 1, metrics: { 'train/loss_epoch': 1.3 } }],
        validationHistory: [
          { epoch: 2, metrics: { ...metrics, 'val/loss': 1.1 } },
          { epoch: 5, metrics: { ...metrics, 'val/loss': 0.95 } },
        ],
        learningRateHistory: [],
        runtimeHistory: [],
        runtimeEmptyText: '—',
      },
      global: { plugins: [i18n] },
    })
    await flushPromises()
    const [loss, validation] = charts.instances.map(chart => chart.setOption.mock.lastCall?.[0])
    expect(wrapper.findAll('h3').map(heading => heading.text())).toEqual(['训练与验证损失', `验证集 ${label}`])
    expect(loss.series[1].data).toEqual([[2, 1.1], [5, 0.95]])
    expect(validation.series[0].data).toEqual([[2, 0.4], [5, 0.4]])
    expect(validation.series[0].markLine.data).toEqual([{ xAxis: 5 }])
    wrapper.unmount()
  })

  it('shows only diagnostic charts in the expanded task status', async () => {
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockReturnValue(400)
    const wrapper = mount(TrainingMetricsCharts, {
      props: {
        diagnosticsOnly: true,
        taskType: 'classification',
        trainHistory: [],
        validationHistory: [],
        learningRateHistory: [{ epoch: 1, value: 0.0002 }],
        runtimeHistory: [],
        runtimeEmptyText: '—',
      },
      global: { plugins: [i18n] },
    })
    await flushPromises()
    expect(charts.instances).toHaveLength(4)
    const chart = charts.instances[0].setOption.mock.lastCall?.[0]
    expect(chart.series[0].data).toEqual([[1, 0.0002]])
    expect(chart.legend.show).toBe(false)
    const tooltip = chart.tooltip.formatter([{ value: [1, 0.0002] }])
    expect(tooltip).toContain('0.0002')
    expect(tooltip).not.toContain('learning_rate')
    wrapper.unmount()
  })
})
