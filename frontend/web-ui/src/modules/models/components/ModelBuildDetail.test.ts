import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { describe, expect, it, vi } from 'vitest'
vi.mock('../services/model.service', () => ({ getProjectModelFileStatus: vi.fn().mockResolvedValue({ file_id: 'file-1', state: 'present', size_bytes: 10 }), downloadProjectModelFile: vi.fn() }))
import ModelBuildDetail from './ModelBuildDetail.vue'
import { downloadProjectModelFile, getProjectModelFileStatus } from '../services/model.service'
import type { PlatformBaseModelBuild, PlatformBaseModelVersionDetail } from '../services/model.service'

const i18n = createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': {} } })
const version: PlatformBaseModelVersionDetail = {
  model_version_id: 'version-1', source_kind: 'training-output', file_ids: [], files: [],
  metadata: { category_names: ['bolt', 'nut'], model_input_spec: { color_space: 'RGB', preprocess: 'letterbox', normalization: 'zero-to-one' } },
}
const build: PlatformBaseModelBuild = {
  model_build_id: 'build-1', source_model_version_id: 'version-1', build_format: 'onnx', runtime_backend: 'onnxruntime', runtime_precision: 'fp32', file_ids: ['file-1'],
  files: [{ file_id: 'file-1', model_id: 'm1', model_build_id: 'build-1', scope_kind: 'project', file_type: 'onnx', logical_name: 'model.onnx', storage_uri: 'models/model.onnx', metadata: {} }],
  metadata: { input_tensor: { dtype: 'float32', layout: 'NCHW', shape: [1, 3, 640, 480] }, input_names: ['images'], output_names: ['scores'] },
}

describe('ModelBuildDetail', () => {
  it('shows the selected artifact and its actual contract without claiming file availability', async () => {
    const wrapper = mount(ModelBuildDetail, { props: { build, version, modelName: 'part detector', modelId: 'm1', projectId: 'p1' }, global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.text()).toContain('ONNX (FP32)')
    expect(wrapper.text()).toContain('model.onnx')
    expect(wrapper.text()).toContain('1 × 3 × 640 × 480')
    expect(wrapper.text()).toContain('scores')
    expect(wrapper.text()).toContain('bolt')
    expect(wrapper.text()).toContain('文件存在')
    expect(wrapper.text()).toContain('部署时按目标环境检查兼容性')
    await wrapper.find('button').trigger('click')
    expect(wrapper.emitted('back')).toHaveLength(1)
  })

  it('distinguishes a failed request from a missing file and permits retry', async () => {
    vi.mocked(getProjectModelFileStatus).mockRejectedValueOnce(new Error('offline')).mockResolvedValueOnce({ file_id: 'file-1', state: 'missing', size_bytes: null })
    const wrapper = mount(ModelBuildDetail, { props: { build, version, modelName: 'part detector', modelId: 'm1', projectId: 'p1' }, global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.text()).toContain('读取失败')
    expect(wrapper.text()).not.toContain('文件缺失')
    await wrapper.findAll('button').find(button => button.text() === '重试')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('文件缺失')
  })

  it('reports a download failure without claiming a missing file', async () => {
    vi.mocked(downloadProjectModelFile).mockRejectedValueOnce(new Error('offline'))
    const wrapper = mount(ModelBuildDetail, { props: { build, version, modelName: 'part detector', modelId: 'm1', projectId: 'p1' }, global: { plugins: [i18n] } })
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text().includes('下载'))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('下载失败')
    expect(downloadProjectModelFile).toHaveBeenCalledWith(expect.objectContaining({ projectId: 'p1', modelId: 'm1', versionId: 'version-1', fileId: 'file-1' }))
  })

  it('checks original version files without inventing a build or precision', async () => {
    const original = { ...version, files: [{ ...build.files[0], model_build_id: null, model_version_id: 'version-1', logical_name: 'best.pt', storage_uri: 'models/best.pt', file_type: 'checkpoint' }] }
    const wrapper = mount(ModelBuildDetail, { props: { version: original, modelName: 'part detector', modelId: 'm1', projectId: 'p1' }, global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.text()).toContain('原始模型文件')
    expect(wrapper.text()).toContain('best.pt')
    expect(wrapper.text()).toContain('文件存在')
    expect(wrapper.text()).not.toContain('ONNX')
    expect(getProjectModelFileStatus).toHaveBeenCalledWith(expect.objectContaining({ projectId: 'p1', modelId: 'm1', versionId: 'version-1', fileId: 'file-1' }))
  })

  it('downloads using the actual filename when a historical logical name differs', async () => {
    vi.mocked(downloadProjectModelFile).mockResolvedValueOnce(new Blob(['class names']))
    const makeUrl = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:test')
    const revokeUrl = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    let downloadName = ''
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) { downloadName = this.download })
    const original = { ...version, files: [{ ...build.files[0], logical_name: 'labels.json', storage_uri: 'models/labels.txt' }] }
    const wrapper = mount(ModelBuildDetail, { props: { version: original, modelName: 'part detector', modelId: 'm1', projectId: 'p1' }, global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.text()).toContain('labels.txt')
    await wrapper.findAll('button').find(button => button.text().includes('下载'))!.trigger('click')
    await flushPromises()
    expect(downloadName).toBe('labels.txt')
    click.mockRestore(); makeUrl.mockRestore(); revokeUrl.mockRestore()
  })

  it('requires both XML and BIN and identifies validation of the selected format', async () => {
    const legacy = { ...build, build_format: 'openvino-ir', files: [{ ...build.files[0], storage_uri: 'models/model.xml' }],
      metadata: { weights_object_uri: 'models/model.bin', validation_summary: { stage: 'validate-onnx', allclose: true } } }
    vi.mocked(getProjectModelFileStatus).mockResolvedValueOnce({ file_id: 'file-1', state: 'present', size_bytes: 10 })
      .mockResolvedValueOnce({ file_id: 'file-1', part: 'weights', state: 'missing', size_bytes: null })
    const wrapper = mount(ModelBuildDetail, { props: { build: legacy, version, modelName: 'detector', modelId: 'm1', projectId: 'p1' }, global: { plugins: [i18n] } })
    await flushPromises()
    expect(wrapper.text()).toContain('model.bin')
    expect(wrapper.text()).toContain('文件缺失')
    expect(wrapper.text()).toContain('未记录')
    expect(wrapper.findAll('button').filter(button => button.text() === '下载')).toHaveLength(1)
  })
})
