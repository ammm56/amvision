import { describe, expect, it } from 'vitest'

import {
  appendTrainingMetricPoint,
  appendTrainingRuntimePoint,
  buildLearningRatePointFromProgress,
  buildMetricPointFromProgress,
  buildRuntimePoint,
  getTrainingMetricCapability,
  readOrderedMetricNames,
  readPersistedMetricHistory,
  readPersistedRuntimeHistory,
} from './training-metric-history'

describe('training metric history', () => {
  it('merges a replayed epoch instead of duplicating it', () => {
    const history = appendTrainingMetricPoint(
      [{ epoch: 1, metrics: { loss: 2 } }],
      { epoch: 1, metrics: { loss: 1.5, box_loss: 0.2 } },
    )

    expect(history).toEqual([{
      epoch: 1,
      metrics: { loss: 1.5, box_loss: 0.2 },
    }])
  })

  it('rejects non-finite telemetry values before they reach ECharts', () => {
    const point = buildMetricPointFromProgress({
      epoch: 3,
      train_metrics: {
        loss: 1.2,
        invalid_nan: Number.NaN,
        invalid_inf: Number.POSITIVE_INFINITY,
      },
    }, 'train_metrics')

    expect(point).toEqual({ epoch: 3, metrics: { loss: 1.2 } })
  })

  it('bounds runtime history and filters non-finite resource values', () => {
    const point = buildRuntimePoint(12, '2026-08-10T00:00:00Z', {
      samples_per_second: 48.5,
      gpu_utilization_percent: 77,
      invalid: Number.NaN,
    })

    expect(appendTrainingRuntimePoint([], point)).toEqual([{
      globalStep: 12,
      timestamp: '2026-08-10T00:00:00Z',
      runtime: { samples_per_second: 48.5, gpu_utilization_percent: 77 },
    }])
  })

  it('reads persisted epoch-indexed history and learning rate', () => {
    const payload = {
      epoch_history: [
        { epoch_index: 0, loss: 2.1 },
        { epoch_index: 1, loss: 1.4 },
      ],
    }

    expect(readPersistedMetricHistory(payload)).toEqual([
      { epoch: 1, metrics: { loss: 2.1 } },
      { epoch: 2, metrics: { loss: 1.4 } },
    ])
    expect(buildLearningRatePointFromProgress({ epoch_index: 1, learning_rate: 0.001 })).toEqual({
      epoch: 2,
      value: 0.001,
    })
  })

  it('restores finite runtime history from the durable snapshot', () => {
    expect(readPersistedRuntimeHistory({
      protocol: 'training.runtime-metrics.v1',
      runtime_history: [
        {
          attempt_no: 2,
          global_step: 42,
          timestamp: '2026-08-13T00:00:00Z',
          runtime: {
            samples_per_second: 31.5,
            gpu_utilization_percent: 82,
            invalid: Number.POSITIVE_INFINITY,
            device: 'cuda:0',
          },
        },
      ],
    })).toEqual([{
      attemptNo: 2,
      globalStep: 42,
      timestamp: '2026-08-13T00:00:00Z',
      runtime: { samples_per_second: 31.5, gpu_utilization_percent: 82 },
    }])
  })

  it('aligns validation history with its evaluated epoch list', () => {
    expect(readPersistedMetricHistory({
      evaluated_epochs: [5, 10],
      epoch_history: [
        { map50_95: 0.2 },
        { map50_95: 0.4 },
      ],
    })).toEqual([
      { epoch: 5, metrics: { map50_95: 0.2 } },
      { epoch: 10, metrics: { map50_95: 0.4 } },
    ])
  })

  it('uses task capabilities for stable series ordering', () => {
    const capability = getTrainingMetricCapability('pose')
    const names = readOrderedMetricNames([
      { epoch: 1, metrics: { custom_metric: 1, kpt_loss: 2, loss: 3 } },
    ], capability.trainMetrics)

    expect(names).toEqual(['loss', 'kpt_loss', 'custom_metric'])
    expect(readOrderedMetricNames([
      { epoch: 1, metrics: { sample_count: 35, map50_95: 0.5, map50: 0.7 } },
    ], getTrainingMetricCapability('detection').validationMetrics, false)).toEqual([
      'map50_95',
      'map50',
    ])
  })
})
