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
    expect(learningRate.tooltip.valueFormatter(0.000012345)).toBe('1.234e-5')
    const stepTime = runtime.series.find((series: { name: string }) => series.name === 'step_time_ms')
    expect(stepTime.tooltip.valueFormatter([1, 19.6789])).toEqual(['1', '20'])
    expect(stepTime.data).toEqual([[1, 19.6789]])
    wrapper.unmount()
  })
})
