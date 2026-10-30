import {afterEach,expect,it,vi} from 'vitest'
import {mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import {PerspectiveCamera,Scene,Vector3,type Object3D} from 'three'
import type {TransformControls} from 'three/addons/controls/TransformControls.js'
import {arcGesture,arcWorld,arcUV,fullTurn,validArc,type ArcEdit} from '@/workflows/workflow-editor/point-cloud/arc-edit'
import {createGeometryOverlay} from '@/workflows/workflow-editor/point-cloud/geometry-overlay'
import {rendererUsage} from '@/workflows/workflow-editor/point-cloud/preview-data'
import {boundaryArcEdit} from '../../../custom_nodes/metrology3d_nodes/frontend/arc-form'
import ArcSettingsForm from '../../../custom_nodes/metrology3d_nodes/frontend/ArcSettingsForm.vue'
import {newBoundarySettings} from '../../../custom_nodes/metrology3d_nodes/frontend/boundary-form'
import type {ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'

const plane={frame_id:'fixture',length_unit:'mm',origin:[1000000,2,3],rotation:[[1,0,0],[0,0,-1],[0,1,0]]}
const arc={center:[2,4],radius_range:[1,3],start_angle:350*Math.PI/180,sweep:30*Math.PI/180,max_overlap_angle:.01}
const edit:ArcEdit={key:'current',values:arc,evaluation:plane,displayRadius:3,minSweep:.01,handle:'end'}
const policy={max_points:10000,max_data_bytes:1000000,max_cpu_bytes:10000000,max_gpu_bytes:10000000,max_canvas_pixels:1000000,max_position_error:.001}
const payload={state:'ready',observation_id:'obs',spatial:{frame_id:'fixture',length_unit:'mm'},bounds:{min:[999990,-10,-10],max:[1000010,10,10]}}
const source={nodeId:'input',nodeTypeId:'custom.metrology3d.crop-roi',parameters:{},outputPort:'cloud',previewOutput:{state:'ready',run_id:'run',observation_id:'obs',spatial:payload.spatial}}
afterEach(()=>{document.body.innerHTML='';expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})})
const polar=(angle:number)=>[2+3*Math.cos(angle),4+3*Math.sin(angle)]
it('uses independent tilted-plane coordinates and preserves signed UV',()=>{
  expect(arcWorld(edit,[5,-7])).toEqual([1000005,2,-4])
  expect(arcUV(edit,[1000005,2,-4])).toEqual([5,-7])
  expect(arcGesture({...edit,handle:'center'})([-2,8])?.center).toEqual([-2,8])
  expect(arcGesture({...edit,handle:'start'})(polar(10*Math.PI/180))).toMatchObject({start_angle:expect.closeTo(10*Math.PI/180,12),sweep:arc.sweep})
})
it('unwraps end gestures across zero without exchanging ends or inventing a full turn',()=>{
  const move=arcGesture(edit)
  expect(move(polar(5*Math.PI/180))?.sweep).toBeCloseTo(15*Math.PI/180)
  expect(move(polar(355*Math.PI/180))?.sweep).toBeCloseTo(5*Math.PI/180)
  expect(move(polar(349*Math.PI/180))).toBeNull()
  expect(move(polar(2*Math.PI/180))?.sweep).toBeCloseTo(12*Math.PI/180)
  const full={...edit,values:{...arc,start_angle:0,sweep:fullTurn}}
  expect(arcGesture(full)(polar(0))?.sweep).toBe(fullTurn)
  expect(arcGesture(full)(polar(.1))).toBeNull()
  expect(arcGesture({...edit,handle:'inner'})([2.5,4])?.radius_range).toEqual([.5,3])
  expect(arcGesture({...edit,handle:'outer'})([2.5,4])).toBeNull()
  expect(arcGesture(edit)(arc.center)).toBeNull()
  expect(validArc({...arc,sweep:0})).toBe(false)
  expect(validArc({...arc,radius_range:[3,1]})).toBe(false)
})
it('requires current input identity and does not infer an evaluation plane from background geometry',()=>{
  const draft={...newBoundarySettings('extract-boundary'),feature_id:'b',evaluation:plane,method:{kind:'projection'}}
  const target={group_id:'g',arc},sources:ParameterEditorSources={cloud:[source]}
  expect(boundaryArcEdit('extract-boundary',draft,target,payload,sources,'run','end')).toMatchObject({evaluation:{origin:plane.origin,rotation:plane.rotation},minSweep:.01})
  const invalidSources:ParameterEditorSources[]=[{},{cloud:[{...source,previewOutput:{...source.previewOutput,run_id:'old'}}]},{cloud:[source,source]},{cloud:[{...source,previewOutput:{...source.previewOutput,state:'unavailable'}}]}]
  for(const s of invalidSources)expect(boundaryArcEdit('extract-boundary',draft,target,payload,s,'run','end')).toBeNull()
  expect(boundaryArcEdit('extract-boundary',{...draft,method:{kind:'pose-contour'}},target,payload,sources,'run','end')).toBeNull()
  expect(boundaryArcEdit('extract-boundary',draft,target,{...payload,observation_id:'other'},sources,'run','end')).toBeNull()
  for(const max_overlap_angle of [null,undefined,'0',-1,Math.PI])expect(boundaryArcEdit('extract-boundary',draft,{...target,arc:{...arc,max_overlap_angle}},payload,sources,'run','end')).toBeNull()
})
it('formats degrees without changing untouched radians or unrelated quality fields',async()=>{
  const value={...arc,start_angle:1.12345678912345}
  const w=mount(ArcSettingsForm,{props:{modelValue:value,band:true,unit:'mm',handle:'none',available:false},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
    expect(w.emitted('update:modelValue')).toBeUndefined()
    const sweep=w.findAll('label').find(l=>l.text().startsWith('Sweep'))!.get('input')
    await sweep.setValue('360')
    expect(w.emitted('update:modelValue')!.at(-1)![0]).toEqual({...value,sweep:fullTurn})
    await w.setProps({modelValue:value});expect(w.emitted('update:modelValue')).toHaveLength(1)
  }finally{w.unmount()}
})
it('inherits the upstream boundary plane for weight sectors without editing fit radius or measured support',()=>{
  const evaluation={kind:'feature',frame_id:'fixture',length_unit:'mm'}
  const draft={...newBoundarySettings('fit-circle'),feature_id:'circle',evaluation,selection:{feature_id:'boundary',group_ids:['g']},radius_range:[9,11],robust:{kind:'angular-soft-l1',...arc,sector_count:32,loss_scale:.02,inlier_residual:.06}}
  const topology={point_count:2,segments:[{segment_id:'fragment',group_id:'g',start:0,count:2,closed:false,role:'open',orientation:'open'}]}
  const method={method_id:'extract-boundary',method_version:1,parameters:{evaluation:plane,method:{kind:'projection'}},resolution:{evaluation:plane}}
  const boundary={kind:'boundary',feature_id:'boundary',valid:true,reason:null,geometry:topology,topology,support_point_count:2,points:[[1000005,2,7],[1000002,2,10]],quality:{usable:true,metrics:{observation_id:'obs'}},method}
  const display={...payload,geometry:{format_id:'amvision.geometry-preview.v1',curves:[boundary]}}
  const input={run_id:'run',observation_id:'obs',...payload.spatial,items:[boundary]}
  const sources:ParameterEditorSources={features:[{...source,outputPort:'features',previewOutput:input}]}
  const resolved=boundaryArcEdit('fit-circle',draft,undefined,display,sources,'run','end')!
  expect(resolved.evaluation).toEqual({origin:plane.origin,rotation:plane.rotation})
  expect(resolved.displayRadius).toBe(3)
  expect(resolved.values).not.toHaveProperty('radius_range')
  expect(draft.radius_range).toEqual([9,11]);expect(boundary.points).toEqual([[1000005,2,7],[1000002,2,10]])
  expect(boundaryArcEdit('fit-circle',draft,undefined,display,sources,'run','outer')).toBeNull()
  expect(boundaryArcEdit('fit-circle',draft,undefined,display,{features:[{...sources.features![0]!,previewOutput:{...input,items:[{...boundary,valid:false}]}}]},'run','end')).toBeNull()
  expect(boundaryArcEdit('fit-circle',draft,undefined,payload,sources,'run','end')).toBeNull()
})
function control(scene:Scene){let found:TransformControls|undefined;scene.traverse(o=>{const c=(o as Object3D&{controls?:TransformControls}).controls;if(c)found=c});return found!}
it('cancels a gesture and ignores stale controls after source replacement and disposal',async()=>{
  const scene=new Scene(),changed=vi.fn(),failed=vi.fn(),canvas=document.createElement('canvas')
  const overlay=createGeometryOverlay(scene,new PerspectiveCamera(),canvas,[1000000,0,0],policy,()=>{},()=>{},failed)
  try{
    overlay.update({payload,arc:{...edit,handle:'center'},arcChanged:changed})
    const c=control(scene);c.dispatchEvent({type:'mouseDown',mode:'translate'});c.dragging=true
    c.object!.position.copy(new Vector3(8,2,11));c.dispatchEvent({type:'objectChange'})
    expect(changed.mock.lastCall![1].center).toEqual([8,8])
    document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));await Promise.resolve()
    expect(changed.mock.lastCall![1].center).toEqual(arc.center)
    expect(overlay.focus('arc')).not.toBeNull()
    const current=control(scene);current.dragging=true
    overlay.update({payload:{...payload,observation_id:'other'},arc:{...edit,key:'new',handle:'center'},arcChanged:changed})
    const calls=changed.mock.calls.length;current.dispatchEvent({type:'objectChange'});expect(changed).toHaveBeenCalledTimes(calls)
    const last=control(scene);overlay.dispose();last.dispatchEvent({type:'objectChange'});await Promise.resolve();expect(changed).toHaveBeenCalledTimes(calls);expect(failed).not.toHaveBeenCalled()
  }finally{overlay.dispose()}
})
it('releases arc buffers on budget refusal and repeated gesture rendering',()=>{
  for(const max_gpu_bytes of [1,policy.max_gpu_bytes]){
    const scene=new Scene(),overlay=createGeometryOverlay(scene,new PerspectiveCamera(),document.createElement('canvas'),[1000000,0,0],{...policy,max_gpu_bytes},()=>{},()=>{},e=>{throw e})
    try{
      if(max_gpu_bytes===1){expect(()=>overlay.update({payload,arc:edit,arcChanged:()=>{}})).toThrow();continue}
      overlay.update({payload,arc:{...edit,handle:'center'},arcChanged:()=>{}})
      const initial=rendererUsage(),c=control(scene)
      for(let i=0;i<40;i++){c.object!.position.set(i,2,11);c.dispatchEvent({type:'objectChange'});expect(rendererUsage()).toEqual(initial)}
    }finally{overlay.dispose()}
  }
})
