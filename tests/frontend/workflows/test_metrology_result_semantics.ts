import {expect,it} from 'vitest'
import {mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import MeasurementSummary from '@/workflows/workflow-editor/point-cloud/MeasurementSummary.vue'
import type {MeasurementDisplay} from '@/workflows/workflow-editor/point-cloud/measurement-display'
import {measurementMethod} from '@/workflows/workflow-editor/point-cloud/measurement-labels'
import {reactive} from 'vue'
import CloudPreviewSelector from '../../../custom_nodes/metrology3d_nodes/frontend/CloudPreviewSelector.vue'
import {parameterPreviewStateKey} from '@/workflows/workflow-editor/parameters/editor-context'
import {curveColor,curveColorScale} from '@/workflows/workflow-editor/point-cloud/curve-colors'
import type {CurveDisplay} from '@/workflows/workflow-editor/point-cloud/boundary-display'
const item:MeasurementDisplay={kind:'measure-hole',component:'diameter',item_id:'S2.D',valid:true,value:20.184324165,reason:null,geometry:null,support:[{point_count:63}],quality:{metrics:{items:[]}},method:{parameters:{target_kind:'open-arc'}},query:null}
it('labels partial-arc estimates without claiming accuracy or product pass; formatting does not mutate evidence',async()=>{
  const input=structuredClone(item),before=JSON.stringify(input)
  const wrapper=mount(MeasurementSummary,{props:{items:[input],unit:'mm',selected:input.item_id},global:{plugins:[createI18n({legacy:false,locale:'zh-CN'})]}})
  expect(wrapper.text()).toContain('几何有效');expect(wrapper.text()).toContain('未作产品公差判定');expect(wrapper.text()).toContain('部分实测圆弧估计')
  expect(wrapper.text()).toContain('20.184324165')
  await wrapper.find('select').setValue('3')
  expect(wrapper.text()).toContain('20.184');expect(wrapper.find('[title="20.184324165"]').exists()).toBe(true)
  expect(JSON.stringify(input)).toBe(before)
  await wrapper.setProps({items:[{...input,valid:false,value:null,reason:'outside_support'}]})
  expect(wrapper.text()).toContain('几何无效');expect(wrapper.text()).toContain('outside_support');expect(wrapper.text()).not.toContain('20.184')
  wrapper.unmount()
})
it('preserves explicit closed-hole and envelope method distinctions in both languages',()=>{
  expect(measurementMethod(item,false)).toContain('partial-arc')
  expect(measurementMethod({...item,method:{parameters:{target_kind:'closed-hole'}}},false)).toContain('closed-hole')
  expect(measurementMethod({...item,kind:'measure-extents',method:{parameters:{mode:{kind:'robust-profile-spans'}}}},true)).toContain('稳健剖面')
})
it('keeps selection explicit across source/run changes and explains stale, failed and running states',async()=>{
  const state=reactive({runId:'one',succeeded:false,phase:'running' as 'running'|'failed'|'stale'|'ready'})
  const wrapper=mount(CloudPreviewSelector,{props:{modelValue:'',previews:[]},global:{plugins:[createI18n({legacy:false,locale:'zh-CN'})],provide:{[parameterPreviewStateKey as symbol]:()=>state}}})
  expect(wrapper.text()).toContain('正在运行')
  state.phase='failed';await wrapper.vm.$nextTick();expect(wrapper.text()).toContain('未成功')
  state.phase='stale';await wrapper.vm.$nextTick();expect(wrapper.text()).toContain('已过期')
  state.phase='ready';state.succeeded=true
  const previews=[{id:'a:cloud',projectId:'p',label:'同名预览',payload:{spatial:{frame_id:'camera',length_unit:'mm'}}},{id:'b:cloud',projectId:'p',label:'同名预览',payload:{spatial:{frame_id:'fixture',length_unit:'mm'}}}]
  await wrapper.setProps({previews});expect(wrapper.get('select').element.value).toBe('');expect(wrapper.text()).toContain('尚未选择')
  await wrapper.get('select').setValue('b:cloud');expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['b:cloud'])
  await wrapper.setProps({modelValue:'b:cloud',changed:true});expect(wrapper.text()).toContain('fixture / mm');expect(wrapper.text()).toContain('结果未更新')
  state.runId='two';state.phase='running';await wrapper.setProps({previews:[]});expect(wrapper.text()).not.toContain('b:cloud');expect(wrapper.text()).toContain('正在运行')
  wrapper.unmount()
})
it('colors only recorded evidence and handles equal weights and signed residuals',()=>{
  const curve={fit_weights:[.5,1,1.5],radial_residuals:[-.02,.01,0]} as CurveDisplay
  expect(curveColorScale(curve,'weight')).toEqual({min:.5,max:1.5})
  expect(curveColorScale(curve,'residual')).toEqual({min:-.02,max:.02})
  expect(curveColorScale(curve,'support')).toBeNull()
  expect(curveColor(1,1,1)).toEqual([1,1,1]);expect(curveColor(-.02,-.02,.02)).toEqual([0,0,1]);expect(curveColor(.02,-.02,.02)).toEqual([1,0,0])
})
