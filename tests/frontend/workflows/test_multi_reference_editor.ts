import {afterEach,expect,it} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import MeasurementSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/MeasurementSettingsEditor.vue'
import {expandedStepMeasurements,measurementIssues,measurementMetrics,measurementNumericItems,measurementRecipeValidator} from '../../../custom_nodes/metrology3d_nodes/frontend/measurement-form'
import {normalizeLimitRule} from '@/workflows/workflow-editor/parameters/limit-rules'
import type {WorkflowGraphNode} from '@/workflows/workflow-editor/types'
const wrappers:ReturnType<typeof mount>[]=[]
afterEach(()=>{wrappers.forEach(w=>w.unmount());wrappers.length=0;document.body.innerHTML=''})
function settings(){return {frame_id:'fixture',length_unit:'mm',mode:{kind:'directional-references',target_feature_id:'top',query:{kind:'configured',query_position:[0,0,0],direction:[0,0,1]},items:['H','Z'].map((item_id,i)=>({item_id,reference_feature_id:'datum',support_radius:2,reference_policy:{kind:'plane-extension',max_extension_distance:i?60:10},quality_policy:{policy_id:item_id,policy_version:1,rules:measurementMetrics(false,'mm').map(m=>normalizeLimitRule({...m,...(m.item_id.endsWith('_count')?{lower:3}:m.item_id.endsWith('_covered')?{lower:1}:m.item_id.endsWith('_cosine')?{lower:.1}:{upper:2})}))}}))}}}
const button=(name:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===name)!
it('enumerates all item IDs and checks every independent policy',()=>{
  const p=settings(),source={nodeId:'multi',nodeTypeId:'custom.metrology3d.measure-step',parameters:{settings:p}}
  expect(measurementIssues(false,p)).toEqual([])
  expect(measurementNumericItems(source)).toEqual([{item_id:'H',unit:'mm'},{item_id:'Z',unit:'mm'}])
  expect(expandedStepMeasurements(p).map(v=>(v.mode as Record<string,unknown>).reference_policy)).toEqual([{kind:'plane-extension',max_extension_distance:10},{kind:'plane-extension',max_extension_distance:60}])
  p.mode.items[1]!.item_id='H';expect(measurementIssues(false,p)).toContain('items / unique IDs')
  p.mode.items[1]!.item_id='Z';p.mode.items[1]!.quality_policy.rules=[];expect(measurementIssues(false,p).length).toBeGreaterThan(0)
  const extra=settings();Object.assign(extra.mode.items[0]!,{query:{kind:'configured'}})
  expect(measurementIssues(false,extra)).toContain('items / fields')
})
it('checks missing second datum and pose source in graph validation',()=>{
  const p=settings();p.mode.items[1]!.reference_feature_id='missing'
  const node={node_id:'multi',node_type_id:'custom.metrology3d.measure-step',parameters:{settings:p},enabled:true,ui_state:{},metadata:{}} as WorkflowGraphNode
  const features=['datum','top'].map(id=>({nodeId:id,nodeTypeId:'custom.metrology3d.fit-plane',parameters:{settings:{feature_id:id}}}))
  expect(measurementRecipeValidator(node,{features},false)).toContain('Plane feature IDs are duplicated or missing')
})
it('edits independent extension caps atomically and removes rows without hidden output IDs',async()=>{
  const p=settings(),w=mount(MeasurementSettingsEditor,{props:{modelValue:p,nodeType:'custom.metrology3d.measure-step'},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}});wrappers.push(w)
  await w.get('button').trigger('click');await flushPromises()
  const inputs=[...document.querySelectorAll<HTMLInputElement>('[aria-label="Maximum datum extension"]')]
  expect(inputs.map(i=>i.value)).toEqual(['10','60'])
  inputs[1]!.value='55';inputs[1]!.dispatchEvent(new Event('input',{bubbles:true}));await flushPromises()
  expect(p.mode.items[1]!.reference_policy.max_extension_distance).toBe(60)
  button('Apply').click();await flushPromises()
  const result=w.emitted('update:modelValue')![0]![0] as ReturnType<typeof settings>
  expect(result.mode.items.map(i=>i.reference_policy.max_extension_distance)).toEqual([10,55])
  await w.get('button').trigger('click');document.querySelector<HTMLButtonElement>('[aria-label="Remove measurement"]')!.click();await flushPromises()
  expect(document.querySelectorAll('[aria-label="Measurement ID"]')).toHaveLength(1)
  button('Cancel').click();await flushPromises();expect(w.emitted('update:modelValue')).toHaveLength(1)
})
