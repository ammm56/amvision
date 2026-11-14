import {afterEach,expect,it,vi} from 'vitest'
import {PerspectiveCamera,OrthographicCamera,Vector3} from 'three'
import type {OrbitControls} from 'three/addons/controls/OrbitControls.js'
import {createCloudRenderer} from '@/workflows/workflow-editor/point-cloud/renderer'
import {rendererUsage,type CloudDisplayData} from '@/workflows/workflow-editor/point-cloud/preview-data'

const captured=vi.hoisted(()=>({camera:null as unknown,resize:null as null|ResizeObserverCallback,controls:[] as OrbitControls[]}))
vi.mock('three/addons/controls/OrbitControls.js',async importOriginal=>{
  const actual=await importOriginal<typeof import('three/addons/controls/OrbitControls.js')>()
  return {...actual,OrbitControls:class extends actual.OrbitControls {
    constructor(...args:ConstructorParameters<typeof actual.OrbitControls>){super(...args);captured.controls.push(this)}
  }}
})
vi.mock('three',async importOriginal=>{
  const actual=await importOriginal<typeof import('three')>()
  return {...actual,WebGLRenderer:class {
    domElement=document.createElement('canvas')
    setPixelRatio(){} setSize(){} dispose(){} forceContextLoss(){}
    render(_scene:unknown,camera:unknown){captured.camera=camera}
  }}
})
vi.stubGlobal('ResizeObserver',class{constructor(callback:ResizeObserverCallback){captured.resize=callback}observe(){}disconnect(){}})
const policy={max_points:10,max_data_bytes:1000,max_cpu_bytes:10000,max_gpu_bytes:10000000,max_canvas_pixels:1000000,max_position_error:.001}

it('centers diagnostic points without changing the current scale or orientation',()=>{
  vi.useFakeTimers()
  const host=document.createElement('div')
  vi.spyOn(host,'getBoundingClientRect').mockReturnValue({width:600,height:400} as DOMRect)
  const data={positions:new Float32Array([-1,-1,0,1,1,0]),colors:new Float32Array(6),origin:[0,0,0]} as CloudDisplayData
  const failed=vi.fn(),view=createCloudRenderer(host,data,policy,()=>{},failed,()=>{})
  try{
    for(const orthographic of [true,false]){
      view.projection(orthographic);view.zoom(true);vi.advanceTimersByTime(20)
      const control=captured.controls.at(-1)!,camera=control.object as OrthographicCamera|PerspectiveCamera
      const zoom=camera.zoom,offset=camera.position.clone().sub(control.target),rotation=camera.quaternion.clone(),matrix=camera.projectionMatrix.clone()
      for(const points of [[[7,8,9]],[[7,8,9],[9,8,9]]]){
        view.geometry({payload:{spatial:{frame_id:'fixture',length_unit:'mm'}},edgePoints:points})
        view.focus('edge');vi.advanceTimersByTime(20)
        expect(control.target.distanceTo(new Vector3(points.length===1?7:8,8,9))).toBeLessThan(1e-12)
        expect(camera.position.clone().sub(control.target).distanceTo(offset)).toBeLessThan(1e-12)
        expect(camera.quaternion.angleTo(rotation)).toBeLessThan(1e-7)
        expect(camera.zoom).toBe(zoom);expect(camera.projectionMatrix.equals(matrix)).toBe(true)
      }
    }
    expect(failed).not.toHaveBeenCalled()
  }finally{view.dispose()}
})
afterEach(()=>{vi.useRealTimers();captured.controls=[];expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})})
it('does not restart detail loading on unchanged ResizeObserver notifications',()=>{
  vi.useFakeTimers()
  const host=document.createElement('div')
  vi.spyOn(host,'getBoundingClientRect').mockReturnValue({width:600,height:400} as DOMRect)
  const data={positions:new Float32Array([-1,-1,0,1,1,0]),colors:new Float32Array(6),origin:[0,0,0]} as CloudDisplayData
  const view=createCloudRenderer(host,data,policy,()=>{},()=>{},()=>{}),changed=vi.fn()
  try{
    view.detailEvents(changed,null)
    for(let i=0;i<10;i++)captured.resize!([{contentRect:{width:600,height:400}}] as ResizeObserverEntry[],{} as ResizeObserver)
    expect(changed).not.toHaveBeenCalled()
    captured.resize!([{contentRect:{width:600,height:380}}] as ResizeObserverEntry[],{} as ResizeObserver)
    expect(changed).toHaveBeenCalledOnce()
    for(let i=0;i<10;i++)captured.resize!([{contentRect:{width:600,height:380}}] as ResizeObserverEntry[],{} as ResizeObserver)
    expect(changed).toHaveBeenCalledOnce()
  }finally{view.dispose()}
})
it('suspends a hidden or zero-size viewport without reallocating or losing camera state',()=>{
  vi.useFakeTimers()
  const host=document.createElement('div'),rect={width:600,height:400}
  vi.spyOn(host,'getBoundingClientRect').mockImplementation(()=>rect as DOMRect)
  const data={positions:new Float32Array([-1,-1,0,1,1,0]),colors:new Float32Array(6),origin:[0,0,0]} as CloudDisplayData
  const failed=vi.fn(),view=createCloudRenderer(host,data,policy,()=>{},failed,()=>{})
  try{
    vi.advanceTimersByTime(20)
    const camera=captured.camera as OrthographicCamera,position=camera.position.clone(),rotation=camera.quaternion.clone(),usage=rendererUsage(),control=captured.controls.at(-1)!
    for(let i=0;i<20;i++){
      view.activity(false);expect(control.enabled).toBe(false);expect(vi.getTimerCount()).toBe(0)
      captured.resize!([{contentRect:{width:0,height:0}}] as ResizeObserverEntry[],{} as ResizeObserver)
      expect(rendererUsage()).toEqual(usage);expect((camera.right-camera.left)/(camera.top-camera.bottom)).toBeCloseTo(1.5,14)
      view.activity(true);vi.advanceTimersByTime(20);expect(control.enabled).toBe(true)
    }
    expect(captured.controls).toHaveLength(1);expect(host.children).toHaveLength(1)
    expect(camera.position.equals(position)).toBe(true);expect(camera.quaternion.equals(rotation)).toBe(true)
    rect.width=0;rect.height=0;view.activity(true);expect(control.enabled).toBe(false);expect(vi.getTimerCount()).toBe(0)
    expect(failed).not.toHaveBeenCalled()
  }finally{view.dispose()}
})
it('starts in orthographic top view, zooms, preserves orientation on resize and projection switch, then releases',()=>{
  vi.useFakeTimers()
  const host=document.createElement('div')
  vi.spyOn(host,'getBoundingClientRect').mockReturnValue({width:600,height:400} as DOMRect)
  const data={positions:new Float32Array([-1,-1,0,1,1,0]),colors:new Float32Array(6),origin:[0,0,0]} as CloudDisplayData
  const failed=vi.fn(),changed=vi.fn(),view=createCloudRenderer(host,data,policy,()=>{},failed,changed)
  const camera=()=>{vi.advanceTimersByTime(20);return captured.camera as PerspectiveCamera|OrthographicCamera}
  try{
    expect(camera()).toBeInstanceOf(OrthographicCamera)
    expect(camera().up.toArray()).toEqual([0,1,0])
    expect(changed).toHaveBeenLastCalledWith('z')
    const start=camera().zoom;view.zoom(true);expect(camera().zoom).toBeGreaterThan(start)
    const position=camera().position.clone(),rotation=camera().quaternion.clone()
    captured.resize!([{contentRect:{width:500,height:400}}] as ResizeObserverEntry[],{} as ResizeObserver)
    expect(camera().position.equals(position)).toBe(true);expect(camera().quaternion.equals(rotation)).toBe(true)
    view.projection(false);expect(camera()).toBeInstanceOf(PerspectiveCamera)
    expect(camera().quaternion.equals(rotation)).toBe(true)
    const perspectivePosition=camera().position.clone()
    view.projection(true);expect(camera()).toBeInstanceOf(OrthographicCamera)
    view.projection(false);expect(camera().position.distanceTo(perspectivePosition)).toBeLessThan(1e-10)
    for(const axis of ['x','-x','y','-y','z','-z'] as const){view.fit(axis);expect(camera().position.distanceTo(new Vector3())).toBeGreaterThan(0);expect(changed).toHaveBeenLastCalledWith(axis)}
    view.pan(true);view.pan(false);expect(failed).not.toHaveBeenCalled()
    view.geometry({payload:{spatial:{frame_id:'fixture',length_unit:'mm'}},rois:[{roi_id:'r',frame_id:'fixture',length_unit:'mm',kind:'box',geometry:{center:[7,8,9],size:[1,2,3],rotation:[[1,0,0],[0,1,0],[0,0,1]]}}],selectedId:'r'})
    view.focus('roi');camera();expect(captured.controls.at(-1)!.target.distanceTo(new Vector3(7,8,9))).toBeLessThan(1e-12)
    view.fit();camera();expect(captured.controls.at(-1)!.target.toArray()).toEqual([0,0,0])
  }finally{view.dispose()}
  expect(host.children).toHaveLength(0)
})

it('tracks actual orbit orientation, keeps pan and zoom labels, and detaches rebuilt controls',()=>{
  vi.useFakeTimers()
  const host=document.createElement('div')
  vi.spyOn(host,'getBoundingClientRect').mockReturnValue({width:600,height:400} as DOMRect)
  const data={positions:new Float32Array([-1,-1,0,1,1,0]),colors:new Float32Array(6),origin:[0,0,0]} as CloudDisplayData
  const changed=vi.fn(),failed=vi.fn(),view=createCloudRenderer(host,data,policy,()=>{},failed,changed)
  const controls=()=>captured.controls.at(-1)!
  try{
    view.fit('z')
    const top=controls(),shift=new Vector3(3,4,0)
    top.object.position.add(shift);top.target.add(shift);top.update()
    expect(changed).toHaveBeenLastCalledWith('z')
    const count=changed.mock.calls.length
    view.zoom(true);view.zoom(false);view.projection(true);view.projection(false)
    expect(changed).toHaveBeenCalledTimes(count)
    const orbit=controls()
    orbit.object.position.sub(orbit.target).applyAxisAngle(new Vector3(0,1,0),.3).add(orbit.target)
    orbit.update()
    expect(changed).toHaveBeenLastCalledWith('free')
    view.zoom(true);view.projection(true)
    expect(changed).toHaveBeenLastCalledWith('free')
    view.fit('z')
    expect(changed).toHaveBeenLastCalledWith('z')
    const calls=changed.mock.calls.length
    vi.advanceTimersByTime(20)
    const timers=vi.getTimerCount()
    top.dispatchEvent({type:'change'});orbit.dispatchEvent({type:'change'})
    expect(changed).toHaveBeenCalledTimes(calls)
    expect(vi.getTimerCount()).toBe(timers)
    view.fit('z')
    const current=controls()
    current.object.up.negate();current.object.lookAt(current.target);current.dispatchEvent({type:'change'})
    expect(changed).toHaveBeenLastCalledWith('free')
    view.fit('z')
    const last=controls(),beforeDispose=changed.mock.calls.length
    view.dispose();last.dispatchEvent({type:'change'});view.fit('x')
    expect(changed).toHaveBeenCalledTimes(beforeDispose)
    expect(failed).not.toHaveBeenCalled()
    expect(vi.getTimerCount()).toBe(0)
  }finally{view.dispose()}
})

it('tolerates only numeric polar offsets and stops view events after context loss',()=>{
  vi.useFakeTimers()
  const host=document.createElement('div')
  vi.spyOn(host,'getBoundingClientRect').mockReturnValue({width:600,height:400} as DOMRect)
  const data={positions:new Float32Array([-1,-1,0,1,1,0]),colors:new Float32Array(6),origin:[0,0,0]} as CloudDisplayData
  const changed=vi.fn(),failed=vi.fn(),view=createCloudRenderer(host,data,policy,()=>{},failed,changed)
  try{
    view.fit('z')
    const controls=captured.controls.at(-1)!
    controls.object.position.applyAxisAngle(new Vector3(0,1,0),1e-7);controls.update()
    expect(changed).toHaveBeenLastCalledWith('z')
    controls.object.position.applyAxisAngle(new Vector3(0,1,0),1e-4);controls.update()
    // 控制器自身会省略极小变化的事件，显式触发以独立检查标签容差。
    controls.dispatchEvent({type:'change'})
    expect(changed).toHaveBeenLastCalledWith('free')
    const calls=changed.mock.calls.length
    host.querySelector('canvas')!.dispatchEvent(new Event('webglcontextlost',{cancelable:true}))
    controls.dispatchEvent({type:'change'})
    expect(changed).toHaveBeenCalledTimes(calls)
    expect(failed).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({message:'cloud_context_lost'}))
    expect(host.children).toHaveLength(0)
    expect(vi.getTimerCount()).toBe(0)
  }finally{view.dispose()}
})
