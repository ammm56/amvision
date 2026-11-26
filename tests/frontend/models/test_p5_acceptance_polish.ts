import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { computed, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/platform/i18n'
import ModelPackageExport from '@/modules/models/components/ModelPackageExport.vue'
import ModelPresentationEditor from '@/modules/models/components/ModelPresentationEditor.vue'
import ModelVersionDeleteDialog from '@/modules/models/components/ModelVersionDeleteDialog.vue'
import { useTrainingParameters } from '@/modules/models/composables/useTrainingParameters'

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: {} }),
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
  RouterLink: { template: '<a><slot /></a>' },
}))

vi.mock('@/shared/api/resource-deletion', () => ({
  previewModelVersionDeletion: vi.fn().mockResolvedValue({
    blocked: false,
    revision: 'rev-1',
    has_file_cleanup: false,
    deleted_models: [],
  }),
  submitResourceDeletion: vi.fn(),
}))

vi.mock('@/modules/models/services/model.service', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/modules/models/services/model.service')>()),
  getProjectModelCatalogDetail: vi.fn().mockResolvedValue({
    model_id: 'm1',
    model_name: 'Model A',
    task_type: 'detection',
    model_type: 'yolo11',
    model_scale: 's',
    metadata: {},
  }),
  listModelVersionReferences: vi.fn().mockResolvedValue({ items: [], total: 0 }),
}))

enableAutoUnmount(afterEach)

describe('P5 models localization and polish', () => {
  beforeEach(() => {
    i18n.global.locale.value = 'zh-CN'
  })

  it('localizes task type in ModelVersionDeleteDialog', async () => {
    const wrapper = mount(ModelVersionDeleteDialog, {
      props: {
        open: true,
        projectId: 'p1',
        modelId: 'm1',
        versionId: 'mv-1',
        versionLabel: 'v1',
        modelName: 'Model A',
        taskType: 'detection',
        formats: ['OpenVINO FP32'],
        otherVersionCount: 0,
      },
      global: {
        plugins: [i18n],
        stubs: { Teleport: true },
      },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('目标检测')
    expect(wrapper.text()).not.toContain('detection')
  })

  it('localizes task type in ModelPresentationEditor', async () => {
    const wrapper = mount(ModelPresentationEditor, {
      props: {
        open: true,
        projectId: 'p1',
        model: {
          model_id: 'm1',
          model_name: 'Model A',
          task_type: 'detection',
          scope_kind: 'project',
          model_type: 'yolo11',
          model_scale: 's',
          metadata: {},
        } as never,
      },
      global: {
        plugins: [i18n],
        stubs: {
          SideDrawer: { template: '<div><slot /><slot name="footer" /></div>' },
          Teleport: true,
          ConfirmDialog: true,
        },
      },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('目标检测')
    expect(wrapper.text()).not.toContain('detection')
  })

  it('localizes task type and build formats in ModelPackageExport', () => {
    const wrapper = mount(ModelPackageExport, {
      props: {
        projectId: 'p1',
        name: 'Model A',
        taskType: 'detection',
        version: {
          model_version_id: 'mv-1',
          version_number: 1,
          files: [],
          metadata: {},
        } as never,
        builds: [
          { model_build_id: 'b1', build_format: 'openvino-ir', runtime_precision: 'fp32' },
          { model_build_id: 'b2', build_format: 'onnx-optimized', runtime_precision: 'fp16' },
        ] as never,
        zh: true,
      },
      global: {
        plugins: [i18n],
      },
    })
    const text = wrapper.text()
    expect(text).toContain('目标检测')
    expect(text).toContain('OpenVINO')
    expect(text).toContain('ONNX（优化）')
    expect(text).not.toContain('openvino-ir')
    expect(text).not.toContain('onnx-optimized')
  })

  it('localizes taskType inside trainingModelParameterSectionTitle and falls back safely', () => {
    const selectedTaskType = ref<'detection'>('detection')
    const params = useTrainingParameters({
      selectedTaskType,
      resolvedTrainingModelType: computed(() => 'yolo11'),
      resolvedTrainingModelScale: computed(() => 's'),
      trainingParameterSchema: computed(() => null),
      translate: (key, values) => i18n.global.t(key, values ?? {}),
    })
    expect(params.trainingModelParameterSectionTitle.value).toBe('目标检测 / yolo11 高级参数')

    i18n.global.locale.value = 'en-US'
    expect(params.trainingModelParameterSectionTitle.value).toBe('Detection / yolo11 Advanced Parameters')

    const fallbackParams = useTrainingParameters({
      selectedTaskType,
      resolvedTrainingModelType: computed(() => 'yolo11'),
      resolvedTrainingModelScale: computed(() => 's'),
      trainingParameterSchema: computed(() => null),
      translate: (key, values) => (
        key === 'taskKinds.tasks.detection'
          ? key
          : `${values?.taskType ?? ''} / ${values?.modelType ?? ''}`
      ),
    })
    expect(fallbackParams.trainingModelParameterSectionTitle.value).toBe('detection / yolo11')
  })

  it('uses uppercase ID for conversionRuntimeProfileId across all 4 locales', () => {
    for (const locale of ['zh-CN', 'en-US', 'ja-JP', 'ko-KR'] as const) {
      i18n.global.locale.value = locale
      const value = i18n.global.t('modelOps.fields.conversionRuntimeProfileId')
      expect(value).toContain('ID')
      expect(value).not.toMatch(/\bid\b|id[（(]/u)
    }
  })
})
