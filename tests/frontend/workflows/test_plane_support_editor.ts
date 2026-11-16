import {afterEach,expect,it,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import PlaneSupportEditor from '../../../custom_nodes/metrology3d_nodes/frontend/PlaneSupportEditor.vue'
import RoiForm from '../../../custom_nodes/metrology3d_nodes/frontend/RoiForm.vue'
import {parameterBatchUpdateKey,parameterNodePreviewKey,parameterNodeContextKey} from '@/workflows/workflow-editor/parameters/editor-context'
import {normalizeLimitRule} from '@/workflows/workflow-editor/parameters/limit-rules'
import {trustedParameterEditor} from '@/workflows/workflow-editor/parameters/trusted-editors'
import {planeSupportIssues} from '../../../custom_nodes/metrology3d_nodes/frontend/form'
import {geometryRecipeValidator} from '../../../custom_nodes/metrology3d_nodes/frontend/recipe-validation'
import type {WorkflowGraphNode,WorkflowJsonObject} from '@/workflows/workflow-editor/types'
const roi={kind:'parameters',roi:{roi_id:'fit-area',frame_id:'fixture',length_unit:'mm',kind:'box',geometry:{center:[0,0,3],size:[2,2,1],rotation:[[1,0,0],[0,1,0],[0,0,1]]}},bounds:[]}
const wrappers:ReturnType<typeof mount>[]=[]
afterEach(()=>{wrappers.forEach(w=>w.unmount());wrappers.length=0;document.body.innerHTML=''})
const settings={feature_id:'plane',positive_normal:[0,0,1],min_orientation_cosine:0.5,algorithm:{kind:'svd'},quality_policy:{policy_id:'q',policy_version:1,rules:['inlier_count','tangent_ratio','normal_gap','rms','max_residual'].map(id=>normalizeLimitRule({item_id:id,required:true,enabled:true,unit:['rms','max_residual'].includes(id)?'mm':'1',...(['rms','max_residual'].includes(id)?{upper:1}:{lower:id==='inlier_count'?3:0.01})}))}}
const batch=vi.fn((_node:string,_expected:WorkflowJsonObject,_updates:WorkflowJsonObject)=>true)
const preview=vi.fn(async(_node:string)=>{})
function editor(value:unknown={kind:'cloud'}){batch.mockClear();preview.mockReset();const w=mount(PlaneSupportEditor,{props:{modelValue:value,parameters:{settings,support:value} as never},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})],provide:{[parameterNodePreviewKey as symbol]:preview,[parameterBatchUpdateKey as symbol]:batch,[parameterNodeContextKey as symbol]:()=>({nodeId:'plane',cloudPorts:[],sources:{}})}}});wrappers.push(w);return w}
const button=(name:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===name)!
async function mode(value:string){const select=document.querySelector('select')!;select.value=value;select.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises()}
it('registers the existing ROI editor without enabling an unconnected ROI input',async()=>{
  expect(trustedParameterEditor('custom.metrology3d.fit-plane','support')).toBe(PlaneSupportEditor)
  const w=editor();await w.get('button').trigger('click');await mode('parameters')
  expect(button('Apply').disabled).toBe(true)
  expect(w.getComponent(RoiForm).props('allowInput')).toBe(false)
  w.getComponent(RoiForm).vm.$emit('update:modelValue',roi);await flushPromises()
  expect(w.emitted('update:modelValue')).toBeUndefined()
  button('Apply').click();await flushPromises()
  expect(batch).toHaveBeenCalledWith('plane',{settings,support:{kind:'cloud'}},{settings,support:roi})
})
it('keeps explicit support on cancel and removes all ROI configuration when whole input is applied',async()=>{
  const w=editor(roi);await w.get('button').trigger('click');await mode('cloud');button('Cancel').click();await flushPromises()
  expect(w.emitted('update:modelValue')).toBeUndefined()
  await w.get('button').trigger('click');expect(w.getComponent(RoiForm).props('modelValue')).toEqual(roi)
  await mode('cloud');button('Apply').click();await flushPromises()
  expect(batch).toHaveBeenCalledWith('plane',{settings,support:roi},{settings,support:{kind:'cloud'}})
})
it('closes nested drafts on source changes, disable and unmount without submitting',async()=>{
  const w=editor(roi);await w.get('button').trigger('click')
  await w.setProps({inputSources:{cloud:[]}});expect(document.querySelector('[role=dialog]')).toBeNull()
  await w.get('button').trigger('click');await w.setProps({disabled:true});expect(document.querySelector('[role=dialog]')).toBeNull()
  await w.setProps({disabled:false});await w.get('button').trigger('click');w.unmount()
  expect(document.querySelector('[role=dialog]')).toBeNull();expect(w.emitted('update:modelValue')).toBeUndefined()
})
it('validates support in both field and full graph checks',()=>{
  expect(planeSupportIssues(undefined)).toEqual([])
  expect(planeSupportIssues(roi)).toEqual([])
  expect(planeSupportIssues({kind:'cloud'})).toEqual([])
  for(const support of [null,{kind:'input'},{kind:'cloud',roi:roi.roi},{...roi,bounds:{}},{...roi,roi:{...roi.roi,geometry:{...roi.roi.geometry,size:[0,2,1]}}}]){
    expect(planeSupportIssues(support).length).toBeGreaterThan(0)
    const node={node_id:'plane',node_type_id:'custom.metrology3d.fit-plane',parameters:{settings:{},support},enabled:true,ui_state:{},metadata:{}} as WorkflowGraphNode
    expect(geometryRecipeValidator(node,{},false)).toEqual(expect.arrayContaining(planeSupportIssues(support)))
  }
})
it('does not silently replace a malformed null support with whole input',async()=>{
  const w=editor(null);await w.get('button').trigger('click');await flushPromises()
  expect(button('Apply').disabled).toBe(true)
  expect(w.emitted('update:modelValue')).toBeUndefined()
})
it('keeps the dialog open when an atomic update rejects a changed graph',async()=>{
  const w=editor(roi);batch.mockReturnValueOnce(false)
  await w.get('button').trigger('click');await mode('cloud')
  button('Apply').click();await flushPromises()
  expect(document.querySelector('[role=dialog]')).not.toBeNull()
  expect(document.querySelector('[role=alert]')?.textContent).toContain('Node changed')
  expect(w.emitted('update:modelValue')).toBeUndefined()
})
it('applies the exact draft then previews without closing or saving the App',async()=>{
  const w=editor(roi);await w.get('button').trigger('click');await mode('cloud')
  batch.mockImplementationOnce((_node,expected,updates)=>{void w.setProps({parameters:{...expected,...updates}});return true})
  button('Apply and preview fit').click();await flushPromises()
  expect(preview).toHaveBeenCalledWith('plane')
  expect(document.querySelector('[role=dialog]')).not.toBeNull()
  expect(batch.mock.calls[0]?.[2]).toEqual({support:{kind:'cloud'},settings})
  expect(w.emitted('update:modelValue')).toBeUndefined()
  button('Cancel').click();await flushPromises()
  expect(batch).toHaveBeenCalledTimes(1)
})
it('does not preview on stale update or after synchronous cancellation',async()=>{
  const w=editor(roi);await w.get('button').trigger('click');batch.mockReturnValueOnce(false)
  button('Apply and preview fit').click();await flushPromises();expect(preview).not.toHaveBeenCalled()
  button('Apply and preview fit').click();button('Cancel').click();await flushPromises()
  expect(preview).not.toHaveBeenCalled()
  expect(document.querySelector('[role=dialog]')).toBeNull()
})
it('ignores a late failure after unmount',async()=>{
  let reject!:(e:Error)=>void
  const w=editor(roi);preview.mockImplementationOnce(()=>new Promise((_,fail)=>{reject=fail}))
  await w.get('button').trigger('click');button('Apply and preview fit').click();await flushPromises()
  w.unmount();reject(new Error('late'));await flushPromises()
  expect(document.body.textContent).not.toContain('late')
})
