import {afterEach,expect,it,vi} from 'vitest'
import {flushPromises,mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import BoundarySettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/BoundarySettingsEditor.vue'
import DimensionSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/DimensionSettingsEditor.vue'
import published from '../../../docs/development/assets/r5-f4/workpiece-published-workflow.json'
import type {WorkflowGraphTemplate,WorkflowGraphNode} from '@/workflows/workflow-editor/types'
import {recipeIssues,recipeSources} from '@/workflows/workflow-editor/parameters/recipe-validation'
import {trustedNumericItemProviders,trustedRecipeValidators} from '@/workflows/workflow-editor/parameters/trusted-recipe-providers'

vi.mock('@/workflows/workflow-editor/point-cloud/CloudViewer.vue',()=>({default:{template:'<div />'}}))
afterEach(()=>{document.body.innerHTML='';vi.clearAllMocks()})
const graph=()=>structuredClone(published.template) as unknown as WorkflowGraphTemplate
const issues=(g:WorkflowGraphTemplate)=>recipeIssues(g.nodes,g.edges,trustedNumericItemProviders,trustedRecipeValidators,false)
function applyButton(){return [...document.querySelectorAll('button')].find(b=>b.textContent?.trim()==='Apply')!}

it.each(['S2.circle','S2.diameter','A_top_L.boundary','A_top_L.extents'])('allows a locally valid %s draft while another node is incomplete',async id=>{
  const g=graph(),node=g.nodes.find(n=>n.node_id===id)!
  const editor=node.node_type_id.includes('.measure-')?DimensionSettingsEditor:BoundarySettingsEditor
  const before=JSON.stringify(node.parameters.settings)
  const w=mount(editor,{props:{modelValue:node.parameters.settings,nodeType:node.node_type_id,inputSources:recipeSources(g.nodes,g.edges,id),draftIssues:()=>['another-node / Missing input']},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
    await w.get('button').trigger('click');await flushPromises()
    expect(document.body.textContent).toContain('another-node / Missing input')
    expect(applyButton().disabled).toBe(false)
    applyButton().click();await flushPromises()
    expect(w.emitted('update:modelValue')?.[0]?.[0]).toEqual(node.parameters.settings)
    expect(JSON.stringify(node.parameters.settings)).toBe(before)
  }finally{w.unmount()}
})

it.each(['S2.circle','S2.diameter'])('still rejects invalid local %s settings',async id=>{
  const node=graph().nodes.find(n=>n.node_id===id)!
  const editor=id==='S2.circle'?BoundarySettingsEditor:DimensionSettingsEditor
  const value={...node.parameters.settings as Record<string,unknown>,feature_id:''}
  const w=mount(editor,{props:{modelValue:value,nodeType:node.node_type_id,draftIssues:()=>[]},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{await w.get('button').trigger('click');await flushPromises();expect(applyButton().disabled).toBe(true);applyButton().click();await flushPromises();expect(w.emitted('update:modelValue')).toBeUndefined()}finally{w.unmount()}
})

it('keeps graph preflight blocked between a feature rename and the downstream reference update',()=>{
  const g=graph()
  expect(issues(g)).toEqual([])
  const settings=(id:string)=>(g.nodes.find(n=>n.node_id===id) as WorkflowGraphNode).parameters.settings as Record<string,unknown>
  settings('S2.circle').feature_id='S2-renamed'
  expect(issues(g)).toEqual(expect.arrayContaining([expect.objectContaining({nodeId:'S2.diameter',message:'Selected feature is not in current inputs'})]))
  settings('S2.diameter').feature_id='S2-renamed'
  expect(issues(g)).toEqual([])
})

it('changes only the explicit circle weighting method and preserves all quality limits',async()=>{
  const g=graph(),node=g.nodes.find(n=>n.node_id==='S2.circle')!
  const before=structuredClone(node.parameters.settings) as Record<string,unknown>
  const w=mount(BoundarySettingsEditor,{props:{modelValue:before,nodeType:node.node_type_id,inputSources:recipeSources(g.nodes,g.edges,node.node_id)},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
    await w.get('button').trigger('click');await flushPromises()
    const select=[...document.querySelectorAll('select')].find(s=>[...s.options].some(o=>o.value==='arc-length-soft-l1'))!
    select.value='arc-length-soft-l1';select.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises()
    expect(applyButton().disabled).toBe(false)
    expect(w.emitted('update:modelValue')).toBeUndefined()
    applyButton().click();await flushPromises()
    const after=w.emitted('update:modelValue')![0]![0] as Record<string,unknown>
    expect(after).toEqual({...before,robust:{...before.robust as Record<string,unknown>,kind:'arc-length-soft-l1'}})
    expect((before.robust as Record<string,unknown>).kind).toBe('angular-soft-l1')
    node.parameters.settings=after
    expect(issues(g)).toEqual([])
  }finally{w.unmount()}
})
