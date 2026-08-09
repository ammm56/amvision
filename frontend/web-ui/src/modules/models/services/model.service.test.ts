import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiRequest } from '@/shared/api/http-client'
import { listTrainingParameterSchemas } from './model.service'

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
