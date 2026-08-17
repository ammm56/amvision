import { describe, expect, it } from 'vitest'

import {
  buildPreviewNodeDurationIndex,
  formatPreviewNodeDuration,
} from './workflow-preview-node-timings'

describe('workflow Preview node timings', () => {
  it('按 node_id 累加重复执行记录并忽略无效耗时', () => {
    const durations = buildPreviewNodeDurationIndex([
      { node_id: 'classify', duration_ms: 8.24 },
      { node_id: 'classify', duration_ms: 9.31 },
      { node_id: 'decode', duration_ms: 4 },
      { node_id: 'invalid', duration_ms: -1 },
      { node_id: '', duration_ms: 10 },
    ])

    expect(durations.get('classify')).toBeCloseTo(17.55)
    expect(durations.get('decode')).toBe(4)
    expect(durations.has('invalid')).toBe(false)
  })

  it('使用一位小数显示毫秒耗时', () => {
    expect(formatPreviewNodeDuration(17.55)).toBe('17.6 ms')
    expect(formatPreviewNodeDuration(0)).toBe('0.0 ms')
  })
})
