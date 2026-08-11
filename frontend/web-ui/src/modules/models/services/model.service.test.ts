import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiRequest } from '@/shared/api/http-client'
import { createModelTrainingTask, listTrainingParameterSchemas } from './model.service'

vi.mock('@/shared/api/http-client', () => ({ apiRequest: vi.fn() }))

const apiRequestMock = vi.mocked(apiRequest)

function buildCatalogItem() {
  return {
    task_type: 'detection',
    model_type: 'yolo26',
    schema_name: 'YoloDetectionTrainingParameters',
    parameter_schema: {},
    default_parameters: {},
    capabilities: {
      postprocess_mode: 'end_to_end',
      supports_nms_threshold: false,
      distribution_loss_name: 'l1_loss',
      augmentation_families: ['hsv', 'mosaic', 'mixup', 'affine', 'multi_scale'],
      best_metric_name: 'map50_95',
      best_metric_direction: 'maximize',
    },
    numeric_fields: [{
      key: 'hsv_h',
      schema_path: 'augmentation.hue_gain',
      value_kind: 'float',
      minimum: 0,
      maximum: 0.5,
      step: 0.001,
      decimals: 3,
      default_value: 0.015,
    }],
  }
}

describe('model training parameter schema service', () => {
  beforeEach(() => {
    apiRequestMock.mockReset()
  })

  it('loads the task-scoped numeric parameter catalog with transient read retry', async () => {
    apiRequestMock.mockResolvedValue({ protocol_version: 1, items: [] })

    await expect(listTrainingParameterSchemas('detection', 'yolo26')).resolves.toEqual({
      protocol_version: 1,
      items: [],
    })
    expect(apiRequestMock).toHaveBeenCalledWith('/models/training-parameter-schemas', {
      query: {
        task_type: 'detection',
        model_type: 'yolo26',
      },
      retryTransientRead: true,
    })
  })

  it('rejects a catalog item without numeric field definitions', async () => {
    apiRequestMock.mockResolvedValue({
      protocol_version: 1,
      items: [{ task_type: 'detection', model_type: 'yolo26' }],
    })

    await expect(listTrainingParameterSchemas('detection')).rejects.toThrow(
      '训练参数目录协议不完整',
    )
  })

  it.each([
    { step: 0 },
    { default_value: 0.505 },
    { minimum: Number.NaN },
    { decimals: 13 },
  ])('rejects malformed numeric field metadata: %o', async (override) => {
    const item = buildCatalogItem()
    item.numeric_fields[0] = { ...item.numeric_fields[0]!, ...override }
    apiRequestMock.mockResolvedValue({ protocol_version: 1, items: [item] })

    await expect(listTrainingParameterSchemas('detection')).rejects.toThrow(
      '训练参数目录协议不完整',
    )
  })

  it('accepts a complete and aligned catalog item', async () => {
    const item = buildCatalogItem()
    apiRequestMock.mockResolvedValue({ protocol_version: 1, items: [item] })

    await expect(listTrainingParameterSchemas('detection')).resolves.toEqual({
      protocol_version: 1,
      items: [item],
    })
  })
})

describe('model training execution policy service', () => {
  beforeEach(() => {
    apiRequestMock.mockReset()
    apiRequestMock.mockResolvedValue({ task_id: 'task-1' })
  })

  it('serializes AutoBatch, AMP, checkpoint and validation as one execution policy', async () => {
    await createModelTrainingTask({
      taskType: 'pose',
      projectId: 'project-1',
      modelType: 'yolo11',
      modelScale: 'n',
      outputModelName: 'hand-pose',
      maxEpochs: 200,
      batchMode: 'auto',
      batchSize: 32,
      batchTargetMemoryFraction: 0.6,
      batchMinimumSize: 1,
      batchRecoverOnOom: true,
      batchMaxOomRetries: 3,
      ampMode: 'auto',
      ampDtype: 'auto',
      checkpointInterval: 5,
      checkpointKeepPeriodic: 2,
      evaluationInterval: 5,
      inputWidth: 640,
      inputHeight: 640,
    })

    expect(apiRequestMock).toHaveBeenCalledWith('/models/pose/training-tasks', {
      method: 'POST',
      body: expect.objectContaining({
        execution: {
          max_epochs: 200,
          input_size: { width: 640, height: 640 },
          batch: {
            mode: 'auto',
            size: null,
            target_memory_fraction: 0.6,
            minimum_size: 1,
            maximum_size: null,
            recover_on_oom: true,
            max_oom_retries: 3,
          },
          amp: { mode: 'auto', dtype: 'auto' },
          checkpoint: { interval_epochs: 5, keep_periodic: 2 },
          validation: { interval_epochs: 5 },
        },
      }),
    })
    const body = apiRequestMock.mock.calls[0]?.[1]?.body as Record<string, unknown>
    expect(body).not.toHaveProperty('batch_size')
    expect(body).not.toHaveProperty('precision')
    expect(body).not.toHaveProperty('evaluation_interval')
  })

  it('only sends a concrete batch size for fixed mode', async () => {
    await createModelTrainingTask({
      taskType: 'detection',
      projectId: 'project-1',
      modelType: 'yolov8',
      modelScale: 's',
      outputModelName: 'fixed-batch',
      batchMode: 'fixed',
      batchSize: 8,
      ampMode: 'disabled',
      ampDtype: 'auto',
    })

    const body = apiRequestMock.mock.calls[0]?.[1]?.body as Record<string, any>
    expect(body.execution.batch.size).toBe(8)
    expect(body.execution.amp).toEqual({ mode: 'disabled', dtype: 'auto' })
  })
})
