import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import PlatformBaseModelPickerDialog from './PlatformBaseModelPickerDialog.vue'
import type {
  PlatformBaseModelDetail,
  PlatformBaseModelSummary,
} from '../services/model.service'

function model(
  modelId: string,
  modelName: string,
  modelScale: string,
): PlatformBaseModelSummary {
  return {
    model_id: modelId,
    scope_kind: 'platform',
    model_name: modelName,
    model_type: modelName,
    task_type: 'detection',
    model_scale: modelScale,
    metadata: {},
    version_count: 1,
    build_count: 0,
    available_versions: [],
  }
}

const models = [
  model('rfdetr-l', 'rfdetr', 'l'),
  model('rfdetr-m', 'rfdetr', 'm'),
  model('yolo11-s', 'yolo11', 's'),
  model('yolo11-m', 'yolo11', 'm'),
]

function detail(summary: PlatformBaseModelSummary): PlatformBaseModelDetail {
  return {
    ...summary,
    versions: [{
      model_version_id: `mv-${summary.model_id}`,
      source_kind: 'pretrained-reference',
      file_ids: [],
      metadata: {},
      files: [],
    }],
    builds: [],
  }
}

function mountDialog(overrides: Record<string, unknown> = {}) {
  return mount(PlatformBaseModelPickerDialog, {
    props: {
      open: true,
      loading: false,
      detailLoading: false,
      mode: 'training',
      title: '选择训练基础模型',
      closeLabel: '关闭',
      taskTypeOptions: [{ label: 'detection', value: 'detection' }],
      selectedTaskType: 'detection',
      modelListTitle: '模型选择',
      modelNameLabel: '模型名称',
      detailTitle: '版本与使用',
      detailLoadingLabel: '正在加载模型详情',
      currentSelectionLabel: '当前选择',
      versionSelectionLabel: '继续训练版本',
      versionsTitle: '可用版本',
      extraVersionsTitle: '项目训练版本',
      scaleLabel: '参数量',
      applyModelLabel: '使用当前模型',
      applyTrainingVersionLabel: '选择此版本继续训练',
      applyConversionVersionLabel: '用于转换',
      emptyTitle: '暂无模型',
      emptyDescription: '没有可用模型',
      detailEmptyTitle: '先选择模型',
      detailEmptyDescription: '选择后显示详情',
      emptyVersionsTitle: '暂无版本',
      emptyVersionsDescription: '登记后显示',
      models,
      selectedModelId: 'rfdetr-m',
      selectedModelDetail: detail(models[1]),
      ...overrides,
    },
  })
}

describe('PlatformBaseModelPickerDialog', () => {
  it('keeps the dialog header compact without description or task type label', () => {
    const wrapper = mountDialog()

    expect(wrapper.find('.model-picker-shell__description').exists()).toBe(false)
    expect(wrapper.find('.model-picker-shell__label').exists()).toBe(false)
  })

  it('groups platform models by model name before showing parameter sizes', () => {
    const wrapper = mountDialog()

    const families = wrapper.findAll('.platform-model-family')
    expect(families).toHaveLength(2)
    expect(families.map((item) => item.find('strong').text())).toEqual(['rfdetr', 'yolo11'])
    expect(families.map((item) => item.text())).toEqual(['rfdetr', 'yolo11'])
    expect(wrapper.findAll('.platform-model-scale')).toHaveLength(2)
    expect(wrapper.findAll('.platform-model-scale').map((item) => item.text())).toEqual(['m', 'l'])
    expect(wrapper.find('.model-picker-shell__count').text()).toBe('2')
  })

  it('numbers model selection and version actions as one four-step flow', () => {
    const wrapper = mountDialog()

    expect(wrapper.findAll('.platform-model-selection__step').map((item) => item.text()))
      .toEqual(['1', '2', '3', '4'])
    expect(wrapper.text()).toContain('当前选择')
    expect(wrapper.text()).toContain('继续训练版本')
    expect(wrapper.find('.platform-model-version-action').text()).toBe('选择此版本继续训练')
  })

  it('preserves the selected parameter size when switching model names', async () => {
    const wrapper = mountDialog()

    await wrapper.findAll('.platform-model-family')[1].trigger('click')

    expect(wrapper.emitted('select-model')).toEqual([['yolo11-m']])
  })

  it('emits the concrete model id when a parameter size is selected', async () => {
    const wrapper = mountDialog()
    const largeScale = wrapper
      .findAll('.platform-model-scale')
      .find((item) => item.find('strong').text() === 'l')

    expect(largeScale).toBeDefined()
    await largeScale?.trigger('click')

    expect(wrapper.emitted('select-model')).toEqual([['rfdetr-l']])
  })

  it('shows a stable loading state while the selected model detail changes', () => {
    const wrapper = mountDialog({
      detailLoading: true,
      selectedModelDetail: null,
    })

    expect(wrapper.find('.platform-model-detail__spinner').exists()).toBe(true)
    expect(wrapper.text()).toContain('正在加载模型详情')
  })
})
