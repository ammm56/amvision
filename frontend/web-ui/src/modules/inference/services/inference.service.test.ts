import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiRequest } from '@/shared/api/http-client'
import {
  cancelBatchInferenceTask,
  createBatchInferenceTask,
  deleteBatchInferenceTask,
  getDatasetSampleFileRef,
  inferTaskDeployment,
  saveDirectInferenceRecord,
  type TaskInferenceDebugInput,
} from './inference.service'

vi.mock('@/shared/api/http-client', () => ({ apiRequest: vi.fn() }))

function input(overrides: Partial<TaskInferenceDebugInput>): TaskInferenceDebugInput {
  return {
    taskType: 'detection',
    projectId: 'project-1',
    deploymentInstanceId: 'deployment-1',
    inputUri: 'images/input.jpg',
    inputTransportMode: 'memory',
    scoreThreshold: 0.31,
    topK: 7,
    maskThreshold: 0.52,
    keypointConfidenceThreshold: 0.27,
    saveResultImage: false,
    returnPreviewImageBase64: true,
    ...overrides,
  }
}

async function submittedFormData(overrides: Partial<TaskInferenceDebugInput>): Promise<FormData> {
  vi.mocked(apiRequest).mockResolvedValue({} as never)
  await inferTaskDeployment(input(overrides))
  const options = vi.mocked(apiRequest).mock.calls.at(-1)?.[1]
  expect(options?.body).toBeInstanceOf(FormData)
  return options?.body as FormData
}

describe('inference service task-native parameters', () => {
  beforeEach(() => vi.clearAllMocks())

  it('sends only top_k for classification', async () => {
    const body = await submittedFormData({ taskType: 'classification' })

    expect(body.get('top_k')).toBe('7')
    expect(body.has('score_threshold')).toBe(false)
    expect(body.has('mask_threshold')).toBe(false)
  })

  it('sends score and mask thresholds for segmentation', async () => {
    const body = await submittedFormData({ taskType: 'segmentation' })

    expect(body.get('score_threshold')).toBe('0.31')
    expect(body.get('mask_threshold')).toBe('0.52')
    expect(body.has('top_k')).toBe(false)
  })

  it('sends score and keypoint thresholds for pose', async () => {
    const body = await submittedFormData({ taskType: 'pose' })

    expect(body.get('score_threshold')).toBe('0.31')
    expect(body.get('keypoint_confidence_threshold')).toBe('0.27')
  })

  it.each(['detection', 'obb'] as const)('sends only score threshold for %s', async (taskType) => {
    const body = await submittedFormData({ taskType })

    expect(body.get('score_threshold')).toBe('0.31')
    expect(body.has('top_k')).toBe(false)
    expect(body.has('mask_threshold')).toBe(false)
    expect(body.has('keypoint_confidence_threshold')).toBe(false)
  })

  it('forwards X-Request-Id header and resolves dataset sample file-ref and explicit save', async () => {
    vi.mocked(apiRequest).mockResolvedValue({} as never)
    await inferTaskDeployment(input({ requestId: 'req-custom-1' }))
    expect(vi.mocked(apiRequest).mock.calls.at(-1)?.[1]?.headers).toEqual({
      'X-Request-Id': 'req-custom-1',
    })

    await getDatasetSampleFileRef('ds-1', 'v-1', 's-1')
    expect(vi.mocked(apiRequest).mock.calls.at(-1)?.[0]).toBe(
      '/datasets/ds-1/versions/v-1/samples/s-1/file-ref',
    )

    await saveDirectInferenceRecord({
      projectId: 'project-1',
      requestId: 'req-custom-1',
      taskType: 'detection',
      deploymentInstanceId: 'deployment-1',
      resultPayload: { detection_count: 1 },
    })
    expect(vi.mocked(apiRequest).mock.calls.at(-1)?.[0]).toBe('/inference-records')
  })

  it('supports batch inference creation (upload FormData & dataset JSON), cancel, and delete', async () => {
    vi.mocked(apiRequest).mockResolvedValue({} as never)
    const file = new File(['abc'], 'part.jpg', { type: 'image/jpeg' })

    await createBatchInferenceTask({
      projectId: 'project-1',
      taskType: 'detection',
      deploymentInstanceId: 'deploy-async-1',
      displayName: 'batch-1',
      sourceKind: 'upload',
      files: [file],
    })
    const uploadCall = vi.mocked(apiRequest).mock.calls.at(-1)
    expect(uploadCall?.[0]).toBe('/inference-batches')
    expect(uploadCall?.[1]?.body).toBeInstanceOf(FormData)
    expect((uploadCall?.[1]?.body as FormData).getAll('input_images')).toHaveLength(1)

    await createBatchInferenceTask({
      projectId: 'project-1',
      taskType: 'detection',
      deploymentInstanceId: 'deploy-async-1',
      displayName: 'batch-2',
      sourceKind: 'dataset_version',
      datasetId: 'ds-1',
      datasetVersionId: 'ver-1',
      datasetSplit: 'val',
    })
    const datasetCall = vi.mocked(apiRequest).mock.calls.at(-1)
    expect(datasetCall?.[1]?.body).toMatchObject({
      source_kind: 'dataset_version',
      dataset_id: 'ds-1',
      dataset_version_id: 'ver-1',
      dataset_split: 'val',
    })

    await cancelBatchInferenceTask('batch-2')
    expect(vi.mocked(apiRequest).mock.calls.at(-1)?.[0]).toBe('/inference-batches/batch-2/cancel')

    await deleteBatchInferenceTask('batch-2')
    expect(vi.mocked(apiRequest).mock.calls.at(-1)).toEqual([
      '/inference-batches/batch-2',
      { method: 'DELETE' },
    ])
  })
})
