import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import DatasetCloudView from '../../../frontend/web-ui/src/modules/datasets/components/DatasetCloudView.vue'

const mocks = vi.hoisted(() => ({ read: vi.fn(), create: vi.fn(), reserve: vi.fn(() => () => {}) }))
vi.mock('@/modules/datasets/sample-media', () => ({ readSampleAsset: mocks.read }))
vi.mock('@/workflows/workflow-editor/point-cloud/renderer', () => ({ createCloudRenderer: mocks.create }))
vi.mock('@/workflows/workflow-editor/point-cloud/preview-data', () => ({ reserveCpu: mocks.reserve }))
afterEach(() => vi.clearAllMocks())

it('点云高度色标使用原始范围，视角变化更新坐标轴，切换原色隐藏色标', async () => {
  mocks.read.mockResolvedValue({ size: 24, arrayBuffer: async () => new ArrayBuffer(24) })
  mocks.create.mockImplementation((_host, _data, _policy, _pick, _fail, _view, _active, presentation) => {
    const orient = (top: boolean) => presentation.orientationChanged([
      { label: 'X', x: top ? 1 : 0.5, y: 0, depth: 0 },
      { label: 'Y', x: 0, y: -1, depth: 0 },
      { label: 'Z', x: 0, y: 0, depth: 1 },
    ])
    return { fit: (axis: string) => orient(axis === 'z'), projection: vi.fn(), pointSize: vi.fn(), colors: vi.fn(), dispose: vi.fn() }
  })
  const wrapper = mount(DatasetCloudView, { props: {
    dataset: 'd', sample: { sample_id: 's', image_id: 1, dataset_version_id: 'v', file_name: 'part.ply', width: 480, height: 360, split: 'train', metadata: {}, annotations: [] },
    media: { kind: 'point-cloud', id: 'c', assets: ['cloud', 'points'], preview_count: 1, point_count: 1, valid_count: 1, invalid_count: 0, unit: 'mm', z_range: [-12, 36], origin: [0, 0, 12], scale: 24 },
  }, global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })] } })
  await flushPromises()
  expect(wrapper.get('[aria-label="高度色标"]').text()).toContain('36')
  expect(wrapper.get('[aria-label="高度色标"]').text()).toContain('-12')
  const xLine = () => wrapper.findAll('[aria-label="坐标轴方向"] g').find(item => item.text() === 'X')!.get('line')
  expect(xLine().attributes('x2')).toBe('57.5')
  const zAxis = wrapper.findAll('[aria-label="坐标轴方向"] g').find(item => item.text() === 'Z')!
  expect(zAxis.find('line').exists()).toBe(false)
  expect(zAxis.find('circle').exists()).toBe(true)
  await wrapper.findAll('button').find(button => button.text() === '俯视')!.trigger('click')
  expect(xLine().attributes('x2')).toBe('71')
  await wrapper.get('select').setValue('original')
  expect(wrapper.find('[aria-label="高度色标"]').exists()).toBe(false)
  wrapper.unmount()
})
