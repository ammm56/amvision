import { selectControl, chooseSelect } from './select-control'
import {afterEach,expect,it} from 'vitest'
import Select from '@/shared/ui/components/Select.vue'
import {flushPromises,mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import RoiEditor from '../../../custom_nodes/metrology3d_nodes/frontend/RoiEditor.vue'
import GeometryFields from '../../../custom_nodes/metrology3d_nodes/frontend/GeometryFields.vue'
import WorkflowLimitRulesEditor from '@/workflows/workflow-editor/components/WorkflowLimitRulesEditor.vue'
import {measurementQualityItems,geometryQualityItems,boundaryQualityItems,dimensionQualityItems,registrationQualityItems,relationQualityItems,deviationQualityItems} from '../../../custom_nodes/metrology3d_nodes/frontend/quality-items'
import {normalizeLimitRule} from '@/workflows/workflow-editor/parameters/limit-rules'
const plugin=()=>createI18n({legacy:false,locale:'zh-CN'})
const source=()=>({kind:'parameters',roi:{format_id:'amvision.roi3d.v1',roi_id:'area',frame_id:'fixture',length_unit:'mm',kind:'box',geometry:{center:[1,2,3],size:[2,3,4],rotation:[[1,0,0],[0,1,0],[0,0,1]]}},bounds:[]})
const wrappers:ReturnType<typeof mount>[]=[]
it('offers complete method metrics with explicit units, no numeric thresholds and no cross-method candidates',()=>{
  const p={evaluation:{length_unit:'um'},method:{kind:'visible-envelope'}}
  const envelope=boundaryQualityItems('extract-boundary',p,true)
  expect(envelope.map(i=>i.item_id)).toEqual(expect.arrayContaining(['surface_point_count','face_count','missing_neighbor_fraction','profile_max_jump','added_cell_count']))
  expect(envelope.find(i=>i.item_id==='profile_max_gap')?.unit).toBe('um')
  const line=boundaryQualityItems('fit-line',p,true),circle=boundaryQualityItems('fit-circle',p,true)
  expect(line.find(i=>i.item_id==='max_gap')?.unit).toBe('um')
  expect(circle.find(i=>i.item_id==='max_gap')?.unit).toBe('rad')
  expect(circle.map(i=>i.item_id)).toContain('occupied_sector_count')
  expect(boundaryQualityItems('extract-boundary',{...p,method:{kind:'normal-crease'}},true).map(i=>i.item_id)).toEqual(['support_count','length','max_pair_distance'])
  expect(boundaryQualityItems('extract-boundary',p,true,true).map(i=>i.item_id)).toEqual(['support_count','length'])
  expect(registrationQualityItems({length_unit:'mm',initialization:'datum'},true).map(i=>i.item_id)).toContain('datum_valid')
  expect(registrationQualityItems({length_unit:'mm',initialization:'datum'},true).map(i=>i.item_id)).not.toContain('candidate_consistency')
  expect(relationQualityItems({relation:{kind:'plane-angle'}},true).map(i=>i.item_id)).not.toContain('contacts_unique')
  expect(deviationQualityItems({length_unit:'m'},true).every(i=>i.item_id.startsWith('reference_'))).toBe(true)
  expect(dimensionQualityItems('measure-edge-pair',p,true).find(i=>i.item_id==='reference_count')?.label).toBe('基准 · 支持点数')
  expect(dimensionQualityItems('measure-arc',p,true).find(i=>i.item_id==='coverage_angle')?.unit).toBe('rad')
  for(const item of [...envelope,...line,...circle]){expect(item.label).not.toBe(item.item_id);expect(item).not.toHaveProperty('lower');expect(item).not.toHaveProperty('upper')}
})
afterEach(()=>{wrappers.splice(0).forEach(w=>w.unmount());document.body.innerHTML=''})
it('opens the public ROI source selector and cancels input mode without changing the recipe',async()=>{
  const value=source(),w=mount(RoiEditor,{props:{modelValue:value},attachTo:document.body,global:{plugins:[plugin()]}});wrappers.push(w)
  await w.get('button').trigger('click');await flushPromises()
  const select=selectControl(w,'parameters')
  await chooseSelect(select,'input')
  expect(w.emitted('update:modelValue')).toBeUndefined();expect(value).toEqual(source())
  await chooseSelect(select,'parameters')
  expect(document.querySelector<HTMLInputElement>('input[aria-label="中心 XYZ 1"]')?.value).toBe('1')
  await chooseSelect(select,'input')
  ;[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()==='取消')!.click();await flushPromises()
  expect(document.querySelector('[role=dialog]')).toBeNull()
  await w.get('button').trigger('click');await flushPromises()
  expect(selectControl(w,'parameters').props('modelValue')).toBe('parameters')
})
it('keeps explicit embedded ROI restrictions and discards drafts when the cloud connection changes',async()=>{
  const w=mount(RoiEditor,{props:{modelValue:source(),allowInput:false,inputSources:{cloud:[{nodeId:'a',nodeTypeId:'custom.metrology3d.read-cloud',parameters:{},outputPort:'cloud'}]}},attachTo:document.body,global:{plugins:[plugin()]}});wrappers.push(w)
  await w.get('button').trigger('click');await flushPromises()
  expect(w.findAllComponents(Select).some(s=>s.props('options').some(o=>o.value==='input'))).toBe(false)
  await w.setProps({inputSources:{cloud:[{nodeId:'b',nodeTypeId:'custom.metrology3d.read-cloud',parameters:{},outputPort:'cloud'}]}})
  expect(document.querySelector('[role=dialog]')).toBeNull();expect(w.emitted('update:modelValue')).toBeUndefined()
})
it('applies port mode without carrying the inactive parameter ROI',async()=>{
  const value=source(),w=mount(RoiEditor,{props:{modelValue:value},attachTo:document.body,global:{plugins:[plugin()]}});wrappers.push(w)
  await w.get('button').trigger('click');await flushPromises()
  await chooseSelect(selectControl(w,'parameters'),'input')
  ;[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()==='应用')!.click();await flushPromises()
  expect(w.emitted('update:modelValue')?.[0]?.[0]).toEqual({kind:'input',bounds:[]});expect(value).toEqual(source())
})
it('keeps an ROI draft during Preview refresh but closes it when upstream parameters change',async()=>{
  const cloud={nodeId:'source',nodeTypeId:'custom.metrology3d.read-cloud',parameters:{source:'file'},outputPort:'cloud'}
  const w=mount(RoiEditor,{props:{modelValue:source(),inputSources:{cloud:[cloud]}},attachTo:document.body,global:{plugins:[plugin()]}});wrappers.push(w)
  await w.get('button').trigger('click');await flushPromises()
  await w.setProps({inputSources:{cloud:[{...cloud,previewOutput:{cloud_id:'new-observation'}}]}});await flushPromises()
  expect(document.querySelector('[role=dialog]')).not.toBeNull()
  await w.setProps({inputSources:{cloud:[{...cloud,parameters:{source:'asset'}}]}});await flushPromises()
  expect(document.querySelector('[role=dialog]')).toBeNull();expect(w.emitted('update:modelValue')).toBeUndefined()
})
it('shows translated enum labels and explicit unknown values without replacing saved values',async()=>{
  const w=mount(GeometryFields,{props:{modelValue:{method:{side:'invalid'}},fields:[{path:'method.side',label:'输出实测侧',type:'select',options:['high','low']}]},global:{plugins:[plugin()]}});wrappers.push(w)
  const select=selectControl(w)
  expect(select.props('options').map(o=>o.label)).toContain('高侧实测边');expect(w.text()).toContain('无效选项: invalid');expect(w.get('button').attributes('aria-invalid')).toBe('true')
  expect(w.emitted('update:modelValue')).toBeUndefined();await chooseSelect(select,'low')
  expect(w.emitted('update:modelValue')?.[0]?.[0]).toEqual({method:{side:'low'}})
  await w.setProps({modelValue:{roi:'high'},fields:[{path:'roi',label:'边界',type:'select',options:['high']}]})
  expect(w.text()).not.toContain('高侧实测边');expect(w.text()).toContain('high')
})
it('uses method quality candidates without inventing limits and preserves the rule on apply',async()=>{
  const rule=normalizeLimitRule({item_id:'reference_count',unit:'1',lower:10,required:true,enabled:true})
  const items=measurementQualityItems(false,'mm',true)
  expect(items).toHaveLength(12);expect(items.find(i=>i.item_id==='target_max_residual')?.unit).toBe('mm')
  const w=mount(WorkflowLimitRulesEditor,{props:{modelValue:[rule],quality:true,availableItems:items},attachTo:document.body,global:{plugins:[plugin()]}});wrappers.push(w)
  await w.get('button').trigger('click');await flushPromises()
  expect(document.body.textContent).toContain('基准 · 支持点数');expect(document.body.textContent).not.toContain('上游条目不可静态解析')
  const apply=[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()==='应用')!
  expect(apply.disabled).toBe(false);apply.click();await flushPromises()
  expect(w.emitted('update:modelValue')?.[0]?.[0]).toEqual([rule])
})
it('keeps an unknown quality item visible but rejects applying it',async()=>{
  const rule=normalizeLimitRule({item_id:'old_metric',unit:'1',lower:1,required:true,enabled:true})
  const w=mount(WorkflowLimitRulesEditor,{props:{modelValue:[rule],quality:true,availableItems:measurementQualityItems(false,'mm',true)},attachTo:document.body,global:{plugins:[plugin()]}});wrappers.push(w)
  await w.get('button').trigger('click');await flushPromises()
  expect(document.body.textContent).toContain('old_metric');expect(document.body.textContent).toContain('当前方法或上游配方缺少该项')
  expect([...document.querySelectorAll('button')].find(b=>b.textContent?.trim()==='应用')!.disabled).toBe(true)
  expect(w.emitted('update:modelValue')).toBeUndefined()
})
it('does not guess the plane residual unit and closes quality drafts on parameter replacement',async()=>{
  const items=geometryQualityItems(true,false,true)
  expect(items.find(i=>i.item_id==='rms')?.unit).toBeUndefined()
  const rule=normalizeLimitRule({item_id:'rms',unit:'um',upper:10,required:true,enabled:true})
  const w=mount(WorkflowLimitRulesEditor,{props:{modelValue:[rule],quality:true,availableItems:items},attachTo:document.body,global:{plugins:[plugin()]}});wrappers.push(w)
  await w.get('button').trigger('click');await flushPromises()
  expect(selectControl(w,'um').props('modelValue')).toBe('um')
  await w.setProps({modelValue:[{...rule,upper:20}]});await flushPromises()
  expect(document.querySelector('[role=dialog]')).toBeNull();expect(w.emitted('update:modelValue')).toBeUndefined()
})
it('rejects a dimensionless plane residual until an explicit length unit is selected',async()=>{
  const rule=normalizeLimitRule({item_id:'rms',unit:'1',upper:10,required:true,enabled:true})
  const w=mount(WorkflowLimitRulesEditor,{props:{modelValue:[rule],quality:true,availableItems:geometryQualityItems(true,false,true)},attachTo:document.body,global:{plugins:[plugin()]}});wrappers.push(w)
  await w.get('button').trigger('click');await flushPromises()
  const apply=()=>[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()==='应用')!
  expect(apply().disabled).toBe(true);expect(document.body.textContent).toContain('单位与检查项不一致')
  const unit=selectControl(w,'1')
  await chooseSelect(unit,'mm')
  expect(apply().disabled).toBe(false);apply().click();await flushPromises()
  expect(w.emitted('update:modelValue')?.[0]?.[0]).toEqual([{...rule,unit:'mm'}])
})
