import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import DatasetSampleDetails from '../../../frontend/web-ui/src/modules/datasets/components/DatasetSampleDetails.vue'
import { annotationBounds } from '../../../frontend/web-ui/src/modules/datasets/annotations'
const annotation = (overrides = {}) => ({ annotation_id: 'a', annotation_type: 'detection', category_id: 0, bbox_xywh: [10,20,30,40], polygon_xy: null, segmentation: null, keypoints: null, is_anomalous: null, metadata: {}, ...overrides })
function view(task: string, item = annotation()) {
  return mount(DatasetSampleDetails, { props: { task, selected: 'a', categories: [{ category_id: 0, name: '零件' }], source: 'COCO', sample: { sample_id: 's', image_id: 1, dataset_version_id: 'v1', file_name: 'part.jpg', width: 100, height: 80, split: 'train', metadata: {}, annotations: [item] } }, global: { plugins: [createI18n({ legacy: false, locale: 'zh-CN', messages: {} })] } })
}
it('分类样本显示图像标签，不伪造边界框或置信度', () => {
  const w = view('classification', annotation({ annotation_type: 'classification', bbox_xywh: null }))
  expect(w.text()).toContain('图像标签'); expect(w.text()).not.toContain('边界框'); expect(w.text()).not.toContain('置信度')
  expect(w.find('.sample-details__coordinates').exists()).toBe(false); w.unmount()
})
it('旋转框显示原始四顶点，点击行发出真实对象 ID', async () => {
  const w = view('obb', annotation({ annotation_type: 'obb', polygon_xy: [1,2,3,4,5,6,7,8] }))
  expect(w.text()).toContain('P4'); expect(w.find('.sample-details__coordinates').exists()).toBe(false)
  await w.get('.sample-details__object').trigger('click'); expect(w.emitted('select')).toEqual([['a']]); w.unmount()
})
it('关键点未标注坐标不作为有效测量展示', () => {
  const w = view('pose', annotation({ annotation_type: 'pose', keypoints: [0,0,0,10,20,1,30,40,2] }))
  expect(w.text()).toContain('未标注'); expect(w.text()).toContain('遮挡'); expect(w.text()).toContain('可见'); w.unmount()
})
it('裁切范围支持旋转框和可见关键点，超大轮廓不会展开函数参数导致栈溢出', () => {
  expect(annotationBounds(annotation({ bbox_xywh: null, polygon_xy: [1,2,5,2,5,8,1,8] }))).toEqual([1,2,4,6])
  expect(annotationBounds(annotation({ bbox_xywh: null, keypoints: [0,0,0,10,20,1,30,40,2] }))).toEqual([10,20,20,20])
  expect(annotationBounds(annotation({ bbox_xywh: null, polygon_xy: Array.from({ length: 300000 }, (_, i) => i % 100) }))).toEqual([0,1,98,98])
  expect(annotationBounds(annotation({ bbox_xywh: [0,0,-1,2] }))).toBeNull()
})
