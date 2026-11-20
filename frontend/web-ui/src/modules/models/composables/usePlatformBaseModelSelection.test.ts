import { ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

import type {
  DeploymentSourceModelSummary,
  PlatformBaseModelDetail,
  PlatformBaseModelSummary,
  PlatformBaseModelVersionSummary,
} from '../services/model.service'

vi.mock('../services/model.service', async (importOriginal) => {
  const original = await importOriginal<typeof import('../services/model.service')>()
  return {
    ...original,
    getPlatformBaseModelDetail: vi.fn(),
  }
})

import { usePlatformBaseModelSelection } from './usePlatformBaseModelSelection'
import { getPlatformBaseModelDetail } from '../services/model.service'

function version(
  modelVersionId: string,
  parentVersionId: string | null,
  options: { checkpoint?: boolean } = {},
): PlatformBaseModelVersionSummary {
  const hasCheckpoint = options.checkpoint !== false
  return {
    model_version_id: modelVersionId,
    version_number: 1,
    source_kind: 'training-output',
    parent_version_id: parentVersionId,
    file_ids: hasCheckpoint ? [`${modelVersionId}-checkpoint`] : [],
    metadata: {},
    checkpoint_file_id: hasCheckpoint ? `${modelVersionId}-checkpoint` : null,
    checkpoint_storage_uri: hasCheckpoint ? `task-runs/${modelVersionId}/best.pt` : null,
    checkpoint_state: hasCheckpoint ? 'present' : 'missing',
  }
}

function sourceModel(
  modelId: string,
  modelName: string,
  versions: PlatformBaseModelVersionSummary[],
  overrides: Partial<DeploymentSourceModelSummary> = {},
): DeploymentSourceModelSummary {
  return {
    model_id: modelId,
    project_id: 'project-1',
    scope_kind: 'project',
    model_name: modelName,
    model_type: 'yolo11',
    task_type: 'classification',
    model_scale: 's',
    metadata: {},
    version_count: versions.length,
    build_count: 0,
    available_versions: versions,
    ...overrides,
  }
}

function selectedBaseModel(): PlatformBaseModelDetail {
  const baseVersion = version('mv-pretrained-yolo11-classification-s', null)
  return {
    model_id: 'model-pretrained-yolo11-classification-s',
    scope_kind: 'platform-base',
    model_name: 'yolo11',
    model_type: 'yolo11',
    task_type: 'classification',
    model_scale: 's',
    metadata: {},
    version_count: 1,
    build_count: 0,
    available_versions: [baseVersion],
    versions: [{ ...baseVersion, files: [] }],
    builds: [],
  }
}

describe('usePlatformBaseModelSelection', () => {
  it('exposes a detail failure and clears it on retry', async () => {
    const baseModel = selectedBaseModel()
    vi.mocked(getPlatformBaseModelDetail).mockRejectedValueOnce(new Error('读取失败')).mockResolvedValueOnce(baseModel)
    const selection = usePlatformBaseModelSelection({ baseModels: ref([baseModel]), sourceModels: ref([]), detailFailedMessage: () => 'failed' })
    await selection.selectBaseModel(baseModel.model_id)
    expect(selection.selectedModelDetailError.value).toBe('读取失败')
    await selection.selectBaseModel(baseModel.model_id)
    expect(selection.selectedModelDetailError.value).toBe('')
    expect(selection.selectedModelDetail.value?.model_id).toBe(baseModel.model_id)
  })
  it('lists matching project versions from the model registry across warm-start generations', () => {
    const baseModel = selectedBaseModel()
    const firstGenerationId = 'model-version-df3198f31449'
    const secondGenerationId = 'model-version-7b501c95c815'
    const sourceModels = ref<DeploymentSourceModelSummary[]>([
      sourceModel(
        'model-pcbpetslot3570',
        'yolo11-s-pcbpetslot3570-20260803193223',
        [version(firstGenerationId, baseModel.versions[0].model_version_id)],
      ),
      sourceModel(
        'model-pcbpetslot4570',
        'yolo11-s-pcbpetslot4570-20260804092556',
        [version(secondGenerationId, firstGenerationId)],
      ),
      sourceModel(
        'model-incomplete',
        'incomplete-output',
        [version('model-version-incomplete', secondGenerationId, { checkpoint: false })],
      ),
      sourceModel(
        'model-other-scale',
        'other-scale-output',
        [version('model-version-other-scale', null)],
        { model_scale: 'm' },
      ),
      sourceModel(
        'model-platform-duplicate',
        'platform-duplicate',
        [version('model-version-platform-duplicate', null)],
        { project_id: null, scope_kind: 'platform-base' },
      ),
    ])
    const selection = usePlatformBaseModelSelection({
      baseModels: ref<PlatformBaseModelSummary[]>([baseModel]),
      sourceModels,
      detailFailedMessage: () => 'failed',
    })

    selection.selectedModelDetail.value = baseModel

    expect(selection.selectedModelDerivedTrainingVersions.value).toEqual([
      {
        model_version_id: firstGenerationId,
        title: 'yolo11-s-pcbpetslot3570-20260803193223',
        subtitle: 'v1',
        checkpoint_storage_uri: `task-runs/${firstGenerationId}/best.pt`,
        checkpoint_state: 'present',
      },
      {
        model_version_id: secondGenerationId,
        title: 'yolo11-s-pcbpetslot4570-20260804092556',
        subtitle: 'v1',
        checkpoint_storage_uri: `task-runs/${secondGenerationId}/best.pt`,
        checkpoint_state: 'present',
      },
    ])
  })
})
