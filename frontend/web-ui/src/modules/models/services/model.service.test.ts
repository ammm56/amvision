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
    numeric_fields: [{
      key: 'mosaic_scale_min',
      schema_path: 'augmentation.mosaic_scale.minimum',
      value_kind: 'float',
      minimum: 0.01,
      maximum: 10,
      step: 0.01,
      decimals: 2,
      default_value: 0.5,
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
