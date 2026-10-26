import {afterEach,expect,it,vi} from 'vitest'
import {PerspectiveCamera,OrthographicCamera,Vector3} from 'three'
import {createCloudRenderer} from '@/workflows/workflow-editor/point-cloud/renderer'
import {rendererUsage,type CloudDisplayData} from '@/workflows/workflow-editor/point-cloud/preview-data'

const captured=vi.hoisted(()=>({camera:null as unknown,resize:null as null|ResizeObserverCallback}))
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
afterEach(()=>{vi.useRealTimers();expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})})
it('uses Z-up, zooms, preserves view on resize and projection switch, then releases',()=>{
  vi.useFakeTimers()
  const host=document.createElement('div')
  vi.spyOn(host,'getBoundingClientRect').mockReturnValue({width:600,height:400} as DOMRect)
  const data={positions:new Float32Array([-1,-1,0,1,1,0]),colors:new Float32Array(6),origin:[0,0,0]} as CloudDisplayData
  const failed=vi.fn(),view=createCloudRenderer(host,data,policy,()=>{},failed)
  const camera=()=>{vi.advanceTimersByTime(20);return captured.camera as PerspectiveCamera|OrthographicCamera}
  try{
    expect(camera().up.toArray()).toEqual([0,0,1])
    const start=camera().position.length();view.zoom(true);expect(camera().position.length()).toBeLessThan(start)
    const position=camera().position.clone(),rotation=camera().quaternion.clone()
    captured.resize!([{contentRect:{width:500,height:400}}] as ResizeObserverEntry[],{} as ResizeObserver)
    expect(camera().position.equals(position)).toBe(true);expect(camera().quaternion.equals(rotation)).toBe(true)
    view.projection(true);expect(camera()).toBeInstanceOf(OrthographicCamera)
    expect(camera().position.distanceTo(position)).toBeLessThan(1e-10)
    view.projection(false);expect(camera().position.distanceTo(position)).toBeLessThan(1e-10)
    for(const axis of ['x','-x','y','-y','z','-z'] as const){view.fit(axis);expect(camera().position.distanceTo(new Vector3())).toBeGreaterThan(0)}
    view.pan(true);view.pan(false);expect(failed).not.toHaveBeenCalled()
  }finally{view.dispose()}
  expect(host.children).toHaveLength(0)
})
