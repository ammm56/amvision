import {afterEach,expect,it,vi} from 'vitest'
import {flushPromises,mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import {ref} from 'vue'
import MeasurementSettingsEditor from '../../../custom_nodes/_metrology3d_nodes/frontend/MeasurementSettingsEditor.vue'
import {measurementIssues,measurementMetrics,newMeasurement,newMeasurementMode,measurementRecipeValidator} from '../../../custom_nodes/_metrology3d_nodes/frontend/measurement-form'
import {parameterCloudPreviewsKey,parameterPreviewStateKey} from '@/workflows/workflow-editor/parameters/editor-context'
import {normalizeLimitRule} from '@/workflows/workflow-editor/parameters/limit-rules'
import {trustedNumericItemProviders} from '@/workflows/workflow-editor/parameters/trusted-recipe-providers'
import type {WorkflowGraphNode} from '@/workflows/workflow-editor/types'
vi.mock('@/workflows/workflow-editor/point-cloud/CloudViewer.vue',()=>({default:{name:'TestCloudViewer',props:['payload','allowPick'],emits:['candidate'],template:'<div data-test="cloud"></div>'}}))
const plugin=()=>createI18n({legacy:false,locale:'en-US'})
function settings(){return {item_id:'step',frame_id:'fixture',length_unit:'mm',mode:{...newMeasurementMode(),reference_feature_id:'a',target_feature_id:'b',query_position:[0,0,0],direction:[0,0,1],support_radius:2,quality_policy:{policy_id:'test',policy_version:1,rules:measurementMetrics(false,'mm').map(m=>normalizeLimitRule({...m,...(m.item_id.endsWith('_count')?{lower:3}:m.item_id.endsWith('_covered')?{lower:1}:m.item_id.endsWith('_cosine')?{lower:.1}:{upper:2})}))}}}}
afterEach(()=>{document.body.innerHTML='';vi.clearAllMocks()})
function button(text:string){return [...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===text)!}
function select(value:string){const element=[...document.querySelectorAll('select')].find(s=>[...s.options].some(o=>o.value===value))!;element.value=value;element.dispatchEvent(new Event('change',{bubbles:true}))}
it('keeps production thresholds empty and requires complete mutually exclusive settings',()=>{
  expect(measurementIssues(true,newMeasurement(true))).not.toEqual([])
  expect(measurementIssues(false,newMeasurement(false))).not.toEqual([])
  expect(measurementIssues(false,settings())).toEqual([])
  const node={node_id:'step',node_type_id:'custom.metrology3d.measure-step',parameters:{settings:settings()},enabled:true,ui_state:{},metadata:{}} as WorkflowGraphNode
  expect(measurementRecipeValidator(node,{},false)).toContain('Measurement mode and input connections do not match')
  expect(trustedNumericItemProviders[node.node_type_id]!({nodeId:'step',nodeTypeId:node.node_type_id,parameters:node.parameters})).toEqual([{item_id:'step',unit:'mm'}])
})
it('applies only an atomic draft and discards hidden fields when changing measurement mode',async()=>{
  const w=mount(MeasurementSettingsEditor,{props:{modelValue:settings(),nodeType:'custom.metrology3d.measure-step'},attachTo:document.body,global:{plugins:[plugin()]}})
  await w.get('button').trigger('click');await flushPromises()
  expect(button('Apply').disabled).toBe(false)
  const input=document.querySelector<HTMLInputElement>('[aria-label="Query position XYZ 1"]')!;input.value='9';input.dispatchEvent(new Event('input',{bubbles:true}));await flushPromises()
  expect(w.emitted('update:modelValue')).toBeUndefined();button('Cancel').click();await flushPromises()
  await w.get('button').trigger('click');await flushPromises();expect(document.querySelector<HTMLInputElement>('[aria-label="Query position XYZ 1"]')!.value).toBe('0')
  select('roi-statistic');await flushPromises();expect(document.querySelector('[aria-label="Reference plane ID"]')).toBeNull();expect(button('Apply').disabled).toBe(true)
  select('quantile');await flushPromises();expect(document.querySelector<HTMLInputElement>('[aria-label="Quantile probability"]')!.value).toBe('')
  await w.setProps({modelValue:settings()});expect(document.querySelector('[role=dialog]')).toBeNull();w.unmount()
})
it('requires matching current preview, ignores late picks and invalidates on run changes',async()=>{
  const state=ref({runId:'one',succeeded:true}),payload={observation_id:'obs',state:'ready',spatial:{frame_id:'fixture',length_unit:'mm'}}
  const views=ref([{id:'v',label:'Cloud',projectId:'p',payload}])
  const w=mount(MeasurementSettingsEditor,{props:{modelValue:settings(),nodeType:'custom.metrology3d.measure-step'},attachTo:document.body,global:{plugins:[plugin()],provide:{[parameterCloudPreviewsKey as symbol]:()=>views.value,[parameterPreviewStateKey as symbol]:()=>state.value}}})
  await w.get('button').trigger('click');select('v');await flushPromises()
  const cloud=w.findComponent({name:'TestCloudViewer'});expect(cloud.props('allowPick')).toBe(true)
  cloud.vm.$emit('candidate',{payload:cloud.props('payload'),xyz:[3,4,5]});await flushPromises()
  expect(document.querySelector<HTMLInputElement>('[aria-label="Query position XYZ 1"]')!.value).toBe('3')
  state.value={runId:'two',succeeded:false};await flushPromises();expect(document.querySelector('[data-test=cloud]')).toBeNull()
  cloud.vm.$emit('candidate',{payload:payload,xyz:[8,8,8]});await flushPromises()
  expect(document.querySelector<HTMLInputElement>('[aria-label="Query position XYZ 1"]')!.value).toBe('3')
  button('Apply').click();await flushPromises();expect(w.emitted('update:modelValue')).toHaveLength(1)
  await w.get('button').trigger('click');await w.setProps({disabled:true});expect(document.querySelector('[role=dialog]')).toBeNull();w.unmount()
})
it('requires an explicit extension bound and discards it when returning to measured support',async()=>{
  const w=mount(MeasurementSettingsEditor,{props:{modelValue:settings(),nodeType:'custom.metrology3d.measure-step'},attachTo:document.body,global:{plugins:[plugin()]}})
  await w.get('button').trigger('click');select('plane-extension');await flushPromises()
  const input=document.querySelector<HTMLInputElement>('[aria-label="Maximum datum extension (mm)"]')!
  expect(input.value).toBe('');expect(button('Apply').disabled).toBe(true)
  input.value='10';input.dispatchEvent(new Event('input',{bubbles:true}));await flushPromises()
  expect(button('Apply').disabled).toBe(false)
  button('Apply').click();await flushPromises()
  const result=w.emitted('update:modelValue')![0]![0] as ReturnType<typeof settings>
  expect((result.mode as Record<string,unknown>).reference_policy).toEqual({kind:'plane-extension',max_extension_distance:10})
  await w.setProps({modelValue:result});await w.get('button').trigger('click');select('measured-support');await flushPromises()
  expect(document.querySelector('[aria-label="Maximum datum extension (mm)"]')).toBeNull()
  button('Apply').click();await flushPromises()
  expect(((w.emitted('update:modelValue')![1]![0] as ReturnType<typeof settings>).mode as Record<string,unknown>).reference_policy).toEqual({kind:'measured-support'})
  await w.get('button').trigger('click');select('roi-statistic');await flushPromises()
  expect([...document.querySelectorAll('option')].some(o=>o.value==='plane-extension')).toBe(false)
  w.unmount()
})
