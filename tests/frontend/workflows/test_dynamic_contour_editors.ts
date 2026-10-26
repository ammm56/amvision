import {afterEach,expect,it,vi} from 'vitest'
import {flushPromises,mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import BoundarySettingsEditor from '../../../custom_nodes/_metrology3d_nodes/frontend/BoundarySettingsEditor.vue'
import EvaluationEditor from '../../../custom_nodes/_metrology3d_nodes/frontend/EvaluationEditor.vue'
import {boundaryIssues,boundaryRecipeValidator,newBoundaryMethod,newBoundarySettings,newContourHeight} from '../../../custom_nodes/_metrology3d_nodes/frontend/boundary-form'
import {evaluationIssues,newEvaluation,axisDirection,planePosition} from '../../../custom_nodes/_metrology3d_nodes/frontend/evaluation-form'
import type {RecipeValidator} from '@/workflows/workflow-editor/parameters/recipe-validation'
vi.mock('@/workflows/workflow-editor/point-cloud/CloudViewer.vue',()=>({default:{template:'<div />'}}))
afterEach(()=>{document.body.innerHTML=''})
const plugins=[createI18n({legacy:false,locale:'en-US'})]
const space={frame_id:'fixture',length_unit:'mm'}

it('does not guess ratio, height, order, pose or quality thresholds',()=>{
  expect(newContourHeight('fixed')).toEqual({kind:'fixed',value:null})
  expect(newContourHeight('measurement-ratio')).toMatchObject({ratio:null,order:null,item_id:''})
  expect(newBoundaryMethod('pose-contour')).toMatchObject({numeric_tolerance:null,height:{value:null}})
  expect(evaluationIssues({...space,kind:'pose',pose_id:'',target_frame_id:''},['pose'])).toContain('evaluation / pose')
})
it('rejects mixed source fields, stale origin and invalid signed-source contracts',()=>{
  expect(evaluationIssues({...space,kind:'feature'},['feature'])).toEqual([])
  expect(evaluationIssues({...space,kind:'feature',origin:[0,0,0]},['feature'])).not.toEqual([])
  const p={...newBoundarySettings('extract-boundary'),evaluation:{...space,kind:'pose',pose_id:'datum',target_frame_id:'part'},method:{kind:'pose-contour',reference_feature_id:'base',numeric_tolerance:1e-8,height:{kind:'measurement-ratio',item_id:'step',reference_feature_id:'base',target_feature_id:'top',ratio:.5,order:'target-below'}}}
  expect(boundaryIssues('extract-boundary',p)).not.toContain('contour / height source')
  for(const bad of [0,1,-1,NaN])expect(boundaryIssues('extract-boundary',{...p,method:{...p.method,height:{...p.method.height,ratio:bad}}})).toContain('contour / height source')
  expect(axisDirection({kind:'axis',axis:'-u'})).toBe(true)
  expect(axisDirection({kind:'axis',axis:'n'})).toBe(false)
  expect(planePosition({kind:'plane-uv',uv:[0,2]})).toBe(true)
})
it('checks connected pose, measurement item and live plane sources',()=>{
  const settings={...newBoundarySettings('extract-boundary'),evaluation:{...space,kind:'pose',pose_id:'datum',target_frame_id:'part'},method:{kind:'pose-contour',reference_feature_id:'base',height:{kind:'measurement-ratio',item_id:'step',reference_feature_id:'base',target_feature_id:'top',ratio:.5,order:'target-above'},numeric_tolerance:1e-8}}
  const node:Parameters<RecipeValidator>[0]={node_id:'extract',enabled:true,ui_state:{},metadata:{},node_type_id:'custom.metrology3d.extract-boundary',parameters:{settings}}
  const source=(kind:string,settings:Record<string,unknown>,outputPort:string)=>({nodeId:kind,nodeTypeId:'custom.metrology3d.'+kind,parameters:{settings},outputPort})
  const sources={features:[source('fit-plane',{feature_id:'base'},'features'),source('fit-plane',{feature_id:'top'},'features')],pose:[source('build-frame',{pose_id:'datum',target_frame_id:'part'},'pose')],evidence:[source('measure-step',{item_id:'step'},'evidence')]}
  const good=boundaryRecipeValidator(node,sources,false)
  expect(good.some(v=>v.includes('connection')||v.includes('sources')||v.includes('evidence'))).toBe(false)
  expect(boundaryRecipeValidator(node,{...sources,pose:[]},false)).toContain('Evaluation source and pose connection differ')
  expect(boundaryRecipeValidator(node,{...sources,features:sources.features.slice(0,1)},false)).toContain('Plane sources are missing or duplicated')
})
it('switching the evaluation source removes editable stale geometry and switching back leaves the origin blank',async()=>{
  const w=mount(EvaluationEditor,{props:{modelValue:{...space,origin:[1,2,3],rotation:[[1,0,0],[0,1,0],[0,0,1]]},allowFeature:true},global:{plugins}})
  try{
    await w.get('select').setValue('feature')
    const next=w.emitted('update:modelValue')![0]![0]
    expect(next).toEqual({...space,kind:'feature'})
    await w.setProps({modelValue:next})
    expect(w.text()).not.toContain('Evaluation origin XYZ')
    expect(newEvaluation('configured',next).origin).toEqual([null,null,null])
  }finally{w.unmount()}
})
it('switches dynamic/fixed modes without leaving hidden source fields and closes on source changes',async()=>{
  const w=mount(BoundarySettingsEditor,{props:{modelValue:newBoundarySettings('extract-boundary'),nodeType:'custom.metrology3d.extract-boundary'},attachTo:document.body,global:{plugins}})
  async function select(text:string,value:string){const s=[...document.querySelectorAll('select')].find(s=>s.textContent?.includes(text))!;s.value=value;s.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises()}
  try{
    await w.get('button').trigger('click');await flushPromises()
    await select('Current pose contour','pose-contour')
    expect(document.body.textContent).toContain('Current pose ID')
    expect(document.body.textContent).not.toContain('Evaluation origin XYZ')
    await select('Current measurement ratio','measurement-ratio')
    expect(document.body.textContent).toContain('Target below reference')
    await select('Current measurement ratio','fixed')
    expect(document.body.textContent).not.toContain('Target below reference')
    await select('Current pose contour','projection')
    expect(document.body.textContent).not.toContain('Current pose ID')
    await w.setProps({inputSources:{features:[]}})
    expect(document.querySelector('[role=dialog]')).toBeNull()
    expect(w.emitted('update:modelValue')).toBeUndefined()
  }finally{w.unmount()}
})
