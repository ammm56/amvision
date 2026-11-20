import { flushPromises, mount } from '@vue/test-utils'
import { ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('vue-i18n', async (importOriginal) => ({
  ...await importOriginal<typeof import('vue-i18n')>(),
  useI18n: () => ({
    locale: ref('zh-CN'),
    t: (key: string) => ({ 'common.pagination.previous': '上一页', 'common.pagination.next': '下一页' } as Record<string, string>)[key] ?? key,
  }),
}))
vi.mock('../services/model.service', () => ({ listProjectModelCatalog: vi.fn(), getProjectModelCatalogDetail: vi.fn(), getModelTrainingTaskDetail: vi.fn(), listModelVersionReferences: vi.fn() }))
import { getProjectModelCatalogDetail, listModelVersionReferences, listProjectModelCatalog } from '../services/model.service'
import ProjectModelCatalog from './ProjectModelCatalog.vue'
import Select from '@/shared/ui/components/Select.vue'
import { ApiError } from '@/shared/api/error'

const list = vi.mocked(listProjectModelCatalog)
const model = { model_id: 'm1', model_name: 'example', scope_kind: 'project', model_type: 'yolo', task_type: 'detection', model_scale: 's', metadata: {}, version_count: 0, build_count: 0, available_versions: [] }

describe('project model catalog', () => {
  beforeEach(() => { vi.resetAllMocks(); vi.mocked(listModelVersionReferences).mockResolvedValue({ items: [], total: 0 }) })

  it('shows an error rather than an empty state when the request fails and retries', async () => {
    list.mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ items: [model], total: 1 })
    const wrapper = mount(ProjectModelCatalog, { props: { projectId: 'p1' }, global: { stubs: { SideDrawer: true, ProjectSwitcher: true, RouterLink: true } } })
    await flushPromises()
    expect(wrapper.text()).toContain('加载失败')
    expect(wrapper.text()).not.toContain('当前项目还没有模型版本')
    await wrapper.findAll('button').find(button => button.text() === '重试')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('example')
  })

  it('ignores a response for the previously selected project', async () => {
    let resolveFirst!: (value: { items: typeof model[]; total: number }) => void
    list.mockReturnValueOnce(new Promise(resolve => { resolveFirst = resolve }))
      .mockResolvedValueOnce({ items: [], total: 0 })
    const wrapper = mount(ProjectModelCatalog, { props: { projectId: 'p1' }, global: { stubs: { SideDrawer: true, ProjectSwitcher: true, RouterLink: true } } })
    await wrapper.setProps({ projectId: 'p2' })
    await flushPromises()
    resolveFirst({ items: [model], total: 1 })
    await flushPromises()
    expect(wrapper.text()).not.toContain('example')
    expect(wrapper.text()).toContain('当前项目还没有模型版本')
  })

  it('shows each registered runtime format as a labeled icon', async () => {
    list.mockResolvedValueOnce({ items: [{
      ...model,
      available_versions: [{ model_version_id: 'v1', source_kind: 'training-output', file_ids: [], metadata: {}, checkpoint_storage_uri: 'models/best.pt' }],
      build_formats: ['onnx', 'onnx-optimized', 'openvino-ir', 'tensorrt-engine', 'rknn', 'onnx'],
    }], total: 1 })
    const wrapper = mount(ProjectModelCatalog, { props: { projectId: 'p1' }, global: { stubs: { SideDrawer: true, RouterLink: true } } })
    await flushPromises()
    const formats = wrapper.get('.runtime-formats')
    expect(formats.text()).toBe('')
    expect(formats.findAll('[role="img"]').map(icon => icon.attributes('title'))).toEqual([
      'PyTorch', 'ONNX', 'ONNX optimized', 'OpenVINO', 'TensorRT', 'RKNN',
    ])
    expect(wrapper.get('.model-catalog__toolbar').find('button').text()).toBe('基础模型')
    wrapper.unmount()
  })

  it('retains a filtered snapshot through refresh and disconnect, then reloads it on reconnect', async () => {
    vi.useFakeTimers()
    try {
      let fail!: (cause: unknown) => void
      list.mockResolvedValueOnce({ items: [model], total: 1 })
        .mockResolvedValueOnce({ items: [model], total: 1 })
        .mockReturnValueOnce(new Promise((_, reject) => { fail = reject }))
        .mockResolvedValueOnce({ items: [{ ...model, model_name: 'example-reconnected' }], total: 1 })
      const wrapper = mount(ProjectModelCatalog, { props: { projectId: 'p1', canEdit: true, canTrain: true }, global: { stubs: { SideDrawer: true, ResourceMenu: true, RouterLink: true } } })
      await flushPromises()
      await wrapper.get('input').setValue('example')
      await vi.advanceTimersByTimeAsync(250)
      await flushPromises()
      await wrapper.findAll('button').find(button => button.text() === '刷新')!.trigger('click')
      expect(wrapper.get('.model-catalog__table').text()).toContain('example')
      expect(wrapper.text()).toContain('正在刷新模型列表')
      fail(new ApiError(0, { message: 'offline' }))
      await flushPromises()
      expect(wrapper.get('[role="alert"]').text()).toContain('最后更新')
      expect(wrapper.text()).toContain('数据可能已过期')
      expect(wrapper.get('.model-catalog__table').text()).toContain('example')
      window.dispatchEvent(new Event('online'))
      await flushPromises()
      expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ projectId: 'p1', query: 'example', offset: 0 }))
      expect(wrapper.get('.model-catalog__table').text()).toContain('example-reconnected')
      expect(wrapper.find('[role="alert"]').exists()).toBe(false)
      wrapper.unmount()
    } finally { vi.useRealTimers() }
  })

  it('does not display a prior page on pagination failure or retain data after authorization is denied', async () => {
    list.mockResolvedValueOnce({ items: [model], total: 22 })
      .mockRejectedValueOnce(new ApiError(0, { message: 'offline' }))
      .mockResolvedValueOnce({ items: [{ ...model, model_name: 'page-two' }], total: 22 })
      .mockRejectedValueOnce(new ApiError(403, { message: 'denied' }))
    const wrapper = mount(ProjectModelCatalog, { props: { projectId: 'p1' }, global: { stubs: { SideDrawer: true, RouterLink: true } } })
    const button = (label: string) => wrapper.findAll('button').find(item => item.text() === label)!
    await flushPromises()
    await button('下一页').trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('example')
    expect(wrapper.text()).not.toContain('最后更新')
    await button('重试').trigger('click')
    await flushPromises()
    expect(list).toHaveBeenLastCalledWith(expect.objectContaining({ offset: 20 }))
    expect(wrapper.text()).toContain('page-two')
    await button('刷新').trigger('click')
    await flushPromises()
    expect(wrapper.text()).not.toContain('page-two')
    expect(wrapper.text()).toContain('无权读取')
    wrapper.unmount()
  })

  it('shows only artifacts belonging to the chosen version', async () => {
    const versions = [
      { model_version_id: 'v2', version_number: 1, source_kind: 'training-output', file_ids: [], checkpoint_file_id: 'best', checkpoint_storage_uri: 'models/best.pt', metadata: { registered_at: '2026-11-01T12:00:00Z', category_names: ['label'] }, files: [] },
      { model_version_id: 'v1', version_number: 2, source_kind: 'training-output', file_ids: [], metadata: { registered_at: '2026-11-02T12:00:00Z' }, files: [] },
    ]
    list.mockResolvedValue({ items: [{ ...model, version_count: 2, available_versions: versions }], total: 1 })
    vi.mocked(getProjectModelCatalogDetail).mockResolvedValue({
      ...model, version_count: 2,
      versions,
      builds: [
        { model_build_id: 'b1', source_model_version_id: 'v1', build_format: 'onnx', runtime_backend: 'onnxruntime', runtime_precision: 'fp32', file_ids: [], metadata: {}, files: [] },
        { model_build_id: 'b2', source_model_version_id: 'v2', build_format: 'openvino', runtime_backend: 'openvino', runtime_precision: 'fp16', file_ids: [], metadata: {}, files: [] },
      ],
    })
    const wrapper = mount(ProjectModelCatalog, { props: { projectId: 'p1', canConvert: true, canDeploy: true }, global: { stubs: { SideDrawer: { template: '<div><slot /><slot name="footer" /></div>' } } } })
    await flushPromises()
    expect(wrapper.get('.model-catalog__table td:nth-child(3)').text()).toBe('v2')
    await wrapper.findAll('button').find(button => button.text() === '查看')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('ONNX')
    expect(wrapper.text()).not.toContain('openvino')
    const button = (label: string) => wrapper.findAll('button').find(item => item.text() === label)!
    expect(button('创建转换').attributes('disabled')).toBeDefined()
    wrapper.findAllComponents(Select).at(-1)!.vm.$emit('update:modelValue', 'v2')
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain('openvino')
    expect(wrapper.text()).not.toContain('ONNX')
    const selected = { projectId: 'p1', modelId: 'm1', versionId: 'v2', taskType: 'detection' }
    await button('创建转换').trigger('click')
    expect(wrapper.emitted('create-conversion')).toEqual([[selected]])
    await button('创建部署').trigger('click')
    expect(wrapper.emitted('create-deployment')).toEqual([[selected]])
  })

  it('does not flash the first-use empty state while clearing a search', async () => {
    vi.useFakeTimers()
    try {
      list.mockResolvedValueOnce({ items: [model], total: 1 }).mockResolvedValueOnce({ items: [], total: 0 })
      const wrapper = mount(ProjectModelCatalog, { props: { projectId: 'p1' }, global: { stubs: { SideDrawer: true, ProjectSwitcher: true, RouterLink: true } } })
      await flushPromises()
      await wrapper.find('input').setValue('missing')
      await vi.advanceTimersByTimeAsync(250)
      await flushPromises()
      expect(wrapper.text()).toContain('没有符合条件的模型')
      await wrapper.find('input').setValue('')
      expect(wrapper.text()).not.toContain('当前项目还没有模型版本')
      wrapper.unmount()
    } finally { vi.useRealTimers() }
  })

  it('refreshes after returning to an initially empty project', async () => {
    list.mockResolvedValueOnce({ items: [], total: 0 }).mockResolvedValueOnce({ items: [model], total: 1 })
    const wrapper = mount(ProjectModelCatalog, { props: { projectId: 'p1', active: true }, global: { stubs: { SideDrawer: true, ProjectSwitcher: true, RouterLink: true } } })
    await flushPromises()
    expect(wrapper.text()).toContain('当前项目还没有模型版本')
    await wrapper.setProps({ active: false })
    await wrapper.setProps({ active: true })
    await flushPromises()
    expect(wrapper.text()).toContain('example')
    expect(wrapper.text()).not.toContain('当前项目还没有模型版本')
  })

  it('shows direct references with separate runtime states and keeps the total after searching', async () => {
    vi.useFakeTimers()
    try {
      list.mockResolvedValue({ items: [{ ...model, version_count: 1 }], total: 1 })
      vi.mocked(getProjectModelCatalogDetail).mockResolvedValue({
        ...model, version_count: 1,
        versions: [{ model_version_id: 'v1', version_number: 2, source_kind: 'training-output', file_ids: [], metadata: {}, files: [] }], builds: [],
      })
      vi.mocked(listModelVersionReferences).mockResolvedValueOnce({ items: [{ deployment_id: 'dep1', display_name: '产线 A', model_build_id: null, build_format: null, runtime_backend: 'pytorch', runtime_states: { sync: 'running', async: 'stopped' } }], total: 1 }).mockResolvedValue({ items: [], total: 0 })
      const wrapper = mount(ProjectModelCatalog, { props: { projectId: 'p1' }, global: { stubs: { SideDrawer: { template: '<div><slot name="header-leading" /><slot /><slot name="footer" /></div>' }, RouterLink: { props: ['to'], template: '<a><slot /></a>' } } } })
      await flushPromises()
      await wrapper.findAll('button').find(button => button.text() === '查看')!.trigger('click')
      await flushPromises()
      expect(wrapper.text()).toContain('关联引用 （1）')
      await wrapper.find('.model-detail__references').trigger('click')
      expect(wrapper.text()).toContain('同步: 运行中')
      expect(wrapper.text()).toContain('异步: 已停止')
      await wrapper.find('.model-reference__search input').setValue('missing')
      await vi.advanceTimersByTimeAsync(250)
      await flushPromises()
      expect(wrapper.text()).toContain('没有符合条件的引用')
      await wrapper.get('button[aria-label="返回版本"]').trigger('click')
      expect(wrapper.text()).toContain('关联引用 （1）')
      wrapper.unmount()
    } finally { vi.useRealTimers() }
  })
})
