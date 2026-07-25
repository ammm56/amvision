import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it } from 'vitest'

import { i18n, setI18nLocale } from '@/platform/i18n'
import type {
  DeploymentSourceModelDetail,
  DeploymentSourceModelSummary,
} from '@/modules/models/services/model.service'
import DeploymentSourcePickerDialog from './DeploymentSourcePickerDialog.vue'

function model(
  modelId: string,
  modelName: string,
  modelType: string,
  modelScale: string,
  scopeKind = 'project',
): DeploymentSourceModelSummary {
  return {
    model_id: modelId,
    scope_kind: scopeKind,
    model_name: modelName,
    model_type: modelType,
    task_type: 'detection',
    model_scale: modelScale,
    metadata: {},
    version_count: 1,
    build_count: 1,
    available_versions: [],
  }
}

const trainedYolo11S = model('yolo11-s-a', 'pcb-slot-a', 'yolo11', 's')
const trainedYolo11SSecond = model('yolo11-s-b', 'pcb-slot-b', 'yolo11', 's')
const trainedYolo11M = model('yolo11-m-a', 'package-inspection', 'yolo11', 'm')
const trainedYolo26S = model('yolo26-s-a', 'surface-defect', 'yolo26', 's')
const platformYolo11 = model('platform-yolo11-s', 'yolo11', 'yolo11', 's', 'platform-base')

const models = [
  trainedYolo11S,
  trainedYolo11SSecond,
  trainedYolo11M,
  trainedYolo26S,
  platformYolo11,
]

const selectedDetail: DeploymentSourceModelDetail = {
  ...trainedYolo11S,
  versions: [
    {
      model_version_id: 'mv-yolo11-s-a',
      source_kind: 'training-output',
      file_ids: [],
      metadata: {},
      files: [],
    },
  ],
  builds: [
    {
      model_build_id: 'build-yolo11-s-a',
      source_model_version_id: 'mv-yolo11-s-a',
      build_format: 'openvino-ir',
      runtime_backend: 'openvino',
      runtime_precision: 'fp32',
      file_ids: [],
      metadata: {},
      files: [],
    },
  ],
}

function mountDialog(overrides: Record<string, unknown> = {}) {
  return mount(DeploymentSourcePickerDialog, {
    props: {
      open: true,
      loading: false,
      detailLoading: false,
      taskType: 'detection',
      taskTypeOptions: [{ label: 'detection', value: 'detection' }],
      models,
      selectedModelId: trainedYolo11S.model_id,
      selectedModelDetail: selectedDetail,
      selectedBuildId: '',
      devices: null,
      ...overrides,
    },
    global: { plugins: [i18n] },
  })
}

describe('DeploymentSourcePickerDialog', () => {
  beforeEach(() => {
    setI18nLocale('zh-CN')
  })

  it('uses the compact four-step deployment selection layout', () => {
    const wrapper = mountDialog()

    expect(wrapper.find('.model-picker-shell').classes()).toContain('is-compact')
    expect(wrapper.find('.model-picker-shell__description').exists()).toBe(false)
    expect(wrapper.find('.model-picker-shell__label').exists()).toBe(false)
    expect(wrapper.findAll('.deployment-model-selection__step').map((item) => item.text()))
      .toEqual(['1', '2', '3', '4'])
    expect(wrapper.text()).toContain('模型分类')
    expect(wrapper.text()).toContain('训练模型与部署')
    expect(wrapper.text()).toContain('转换模型')
  })

  it('groups project training outputs by model type and parameter size', () => {
    const wrapper = mountDialog()

    expect(wrapper.findAll('.deployment-model-family').map((item) => item.text()))
      .toEqual(['yolo11', 'yolo26'])
    expect(wrapper.findAll('.deployment-model-scale').map((item) => item.text()))
      .toEqual(['s', 'm'])
    expect(wrapper.findAll('.deployment-trained-model').map((item) => item.text()))
      .toEqual(['pcb-slot-ayolo11-s-a构建 1', 'pcb-slot-byolo11-s-b构建 1'])
    expect(wrapper.find('.model-picker-shell__count').text()).toBe('2')
    expect(wrapper.text()).not.toContain('platform-yolo11-s')
  })

  it('preserves the selected parameter size when switching model types', async () => {
    const wrapper = mountDialog()

    await wrapper.findAll('.deployment-model-family')[1].trigger('click')

    expect(wrapper.emitted('select-model')).toEqual([[trainedYolo26S.model_id]])
  })

  it('selects a concrete training model after model type and parameter size', async () => {
    const wrapper = mountDialog()

    await wrapper.findAll('.deployment-trained-model')[1].trigger('click')
    await wrapper.findAll('.deployment-model-scale')[1].trigger('click')

    expect(wrapper.emitted('select-model')).toEqual([
      [trainedYolo11SSecond.model_id],
      [trainedYolo11M.model_id],
    ])
  })

  it('only exposes converted ModelBuild records as deployment sources', () => {
    const wrapper = mountDialog()

    expect(wrapper.text()).toContain('转换完成的模型')
    expect(wrapper.text()).not.toContain('可直接部署的 ModelVersion')
    expect(wrapper.findAll('.deployment-source-action').map((item) => item.text()))
      .toEqual(['用于部署'])
  })

  it('shows a stable loading state while converted models refresh', () => {
    const wrapper = mountDialog({
      detailLoading: true,
      selectedModelDetail: null,
    })

    expect(wrapper.find('.deployment-source-detail__spinner').exists()).toBe(true)
    expect(wrapper.text()).toContain('正在加载转换模型')
  })
})
