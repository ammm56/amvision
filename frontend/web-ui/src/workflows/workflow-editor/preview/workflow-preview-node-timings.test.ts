import { describe, expect, it } from 'vitest'

import {
  buildPreviewNodeDurationIndex,
  formatPreviewNodeDuration,
} from './workflow-preview-node-timings'

describe('workflow Preview node timings', () => {
  it('重复执行节点只保留最后一轮耗时并忽略无效耗时', () => {
    const durations = buildPreviewNodeDurationIndex([
      { node_id: 'classify', duration_ms: 8.24 },
      { node_id: 'classify', duration_ms: 9.31 },
      { node_id: 'decode', duration_ms: 4 },
      { node_id: 'invalid', duration_ms: -1 },
      { node_id: '', duration_ms: 10 },
    ])

    expect(durations.get('classify')).toBeCloseTo(9.31)
    expect(durations.get('decode')).toBe(4)
    expect(durations.has('invalid')).toBe(false)
  })

  it('把 for-each 单轮调用 id 映射回画布节点并保留最后一轮耗时', () => {
    const durations = buildPreviewNodeDurationIndex([
      { node_id: 'iterate_end[1].classify', duration_ms: 8.24 },
      { node_id: 'iterate_end[2].classify', duration_ms: 9.31 },
      { node_id: 'iterate_end[2].payload_to_value', duration_ms: 0.04 },
      { node_id: 'iterate_end', duration_ms: 24.8 },
    ])

    expect(durations.get('classify')).toBeCloseTo(9.31)
    expect(durations.get('payload_to_value')).toBeCloseTo(0.04)
    expect(durations.get('iterate_end')).toBeCloseTo(24.8)
  })

  it('使用一位小数显示毫秒耗时', () => {
    expect(formatPreviewNodeDuration(17.55)).toBe('17.6 ms')
    expect(formatPreviewNodeDuration(0)).toBe('0.0 ms')
  })
})
