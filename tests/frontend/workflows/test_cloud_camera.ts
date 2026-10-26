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
afterEach(()=>{vi.useRealTimers();captured.controls=[];expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})})
it('uses Z-up, zooms, preserves view on resize and projection switch, then releases',()=>{
  vi.useFakeTimers()
  const host=document.createElement('div')
  vi.spyOn(host,'getBoundingClientRect').mockReturnValue({width:600,height:400} as DOMRect)
  const data={positions:new Float32Array([-1,-1,0,1,1,0]),colors:new Float32Array(6),origin:[0,0,0]} as CloudDisplayData
  const failed=vi.fn(),changed=vi.fn(),view=createCloudRenderer(host,data,policy,()=>{},failed,changed)
  const camera=()=>{vi.advanceTimersByTime(20);return captured.camera as PerspectiveCamera|OrthographicCamera}
  try{
    expect(camera().up.toArray()).toEqual([0,0,1])
    expect(changed).toHaveBeenLastCalledWith('iso')
    const start=camera().position.length();view.zoom(true);expect(camera().position.length()).toBeLessThan(start)
    const position=camera().position.clone(),rotation=camera().quaternion.clone()
    captured.resize!([{contentRect:{width:500,height:400}}] as ResizeObserverEntry[],{} as ResizeObserver)
    expect(camera().position.equals(position)).toBe(true);expect(camera().quaternion.equals(rotation)).toBe(true)
    view.projection(true);expect(camera()).toBeInstanceOf(OrthographicCamera)
    expect(camera().position.distanceTo(position)).toBeLessThan(1e-10)
    view.projection(false);expect(camera().position.distanceTo(position)).toBeLessThan(1e-10)
    for(const axis of ['x','-x','y','-y','z','-z'] as const){view.fit(axis);expect(camera().position.distanceTo(new Vector3())).toBeGreaterThan(0);expect(changed).toHaveBeenLastCalledWith(axis)}
    view.pan(true);view.pan(false);expect(failed).not.toHaveBeenCalled()
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
