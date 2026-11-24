import { describe, expect, it } from 'vitest'
import { modelVersionMetric } from './model-version-metrics'
import type { PlatformBaseModelVersionSummary } from './services/model.service'

const version: PlatformBaseModelVersionSummary = {
  model_version_id: 'best-version', source_kind: 'training-output', file_ids: [], metadata: {
    metrics_summary: { best_metric_name: 'map50_95', best_metric_value: 0.628358 },
    training_config: { max_epochs: 80 },
  },
}
const task = {
  task_type: 'detection', model_type: 'yolo11', progress: {}, events: [],
  state: 'succeeded', model_version_id: 'best-version', best_metric_name: 'map50_95', best_metric_value: 0.628358,
  training_summary: {
    validation_metrics_payload: {
      epoch_history: [{ epoch: 68, map50_95: 0.628 }, { epoch: 72, map50_95: 0.628358 }, { epoch: 80, map50_95: 0.62 }],
    },
  },
} satisfies NonNullable<Parameters<typeof modelVersionMetric>[1]>

describe('model version metrics', () => {
  it('uses the version snapshot even when the training task is unavailable', () => {
    expect(modelVersionMetric(version, null)).toEqual({ name: 'map50_95', value: 0.628358, epoch: undefined, maxEpochs: 80 })
  })

  it('does not inherit best-checkpoint metrics for another registered version from the same task', () => {
    expect(modelVersionMetric({ ...version, model_version_id: 'manual-version', metadata: {} }, task)).toBeNull()
  })

  it('uses a recorded, unambiguous epoch that matches the saved metric', () => {
    expect(modelVersionMetric(version, task)?.epoch).toBe(72)
    const repeated = { ...task, training_summary: { validation_metrics_payload: {
      epoch_history: [{ epoch: 68, map50_95: 0.628358 }, { epoch: 72, map50_95: 0.628358 }],
    } } }
    expect(modelVersionMetric(version, repeated)?.epoch).toBeUndefined()
  })

  it('uses registered metrics files when a historical task did not expose the epoch history', () => {
    const report = {
      best_metric_name: 'map50_95', best_metric_value: 0.628358,
      max_epochs: 80, epoch_history: [{ epoch: 72, val_map50_95: 0.628358 }],
    }
    expect(modelVersionMetric(version, null, report)?.epoch).toBe(72)
  })

  it('uses the same first best epoch as legacy YOLO classification training when scores tie', () => {
    const classifier = {
      ...task, task_type: 'classification', best_metric_name: 'val_top1_accuracy', best_metric_value: 1,
      training_summary: { max_epochs: 100 },
    }
    const trainedVersion = {
      ...version, metadata: { metrics_summary: { best_metric_name: 'val_top1_accuracy', best_metric_value: 1 } },
    }
    const validationMetrics = {
      evaluated_epochs: [25, 30, 35],
      epoch_history: [{ top1_accuracy: 0.99 }, { top1_accuracy: 1 }, { top1_accuracy: 1 }],
    }
    expect(modelVersionMetric(trainedVersion, classifier, undefined, { validationMetrics })?.epoch).toBe(30)
    expect(modelVersionMetric(trainedVersion, classifier, undefined, { validationMetrics, checkpointEpoch: 35 })?.epoch).toBe(35)
    expect(modelVersionMetric({ ...trainedVersion, model_version_id: 'other-version' }, classifier, undefined,
      { validationMetrics, checkpointEpoch: 35 })?.epoch).toBeUndefined()
  })
})
