import {afterEach,expect,it,vi} from 'vitest'
import {Scene} from 'three'
import {createResampleLayer} from '@/workflows/workflow-editor/point-cloud/resample-layer'
import {createComparisonController} from '@/workflows/workflow-editor/point-cloud/comparison-controller'
import {rendererUsage,type CloudDisplayData} from '@/workflows/workflow-editor/point-cloud/preview-data'
import {voxelGrid,voxelCorners,comparableClouds} from '@/workflows/workflow-editor/point-cloud/voxel-display'
const policy={max_points:20,max_data_bytes:10000,max_cpu_bytes:10000,max_gpu_bytes:10000,max_canvas_pixels:10000,max_position_error:1e-5}
const display=(xyz:number[]):CloudDisplayData=>({positions:new Float32Array(xyz),colors:new Float32Array(3),origin:[0,0,0],count:1,point:()=>({xyz,sourceIndex:'0',scalar:null}),dispose:vi.fn()})
afterEach(()=>expect(rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0}))
it('maps a rotated scaled original cell and owns only bounded overlay geometry',()=>{
  const grid=voxelGrid({origin:[10,20,30],axes:[[0,2,0],[-2,0,0],[0,0,2]]})
  const corners=voxelCorners(grid,['1','-1','0'])
  expect(corners[0]).toEqual([12,22,30]);expect(corners[7]).toEqual([10,24,32])
  const scene=new Scene(),layer=createResampleLayer(scene,[10,20,30],policy,vi.fn())
  try{
    layer.cell(corners);expect(scene.children).toHaveLength(1);expect(rendererUsage()).toEqual({cpuBytes:288,gpuBytes:288})
    layer.cell(corners);expect(scene.children).toHaveLength(1)
    layer.comparison(display([10,20,30]))
    expect(scene.children).toHaveLength(2)
    layer.cell(null);expect(scene.children).toHaveLength(1)
    layer.comparison(null);expect(scene.children).toHaveLength(0)
  }finally{layer.dispose();layer.dispose()}
})
it('releases allocation after GPU rejection or coordinate precision failure',()=>{
  for(const p of [{...policy,max_gpu_bytes:1},policy]){
    const scene=new Scene(),layer=createResampleLayer(scene,[0,0,0],p,vi.fn())
    expect(()=>layer.comparison(display([1e10+.1,0,0]))).toThrow()
    layer.dispose();expect(scene.children).toHaveLength(0)
  }
  expect(()=>voxelGrid({origin:[0,0,0],axes:[[1,0,0],[0,-1,0],[0,0,1]]})).toThrow()
  expect(voxelGrid({origin:[0,0,0],axes:[[2,0,0],[8e-9,2,0],[0,0,2]]}).axes[1]).toEqual([8e-9,2,0])
  expect(()=>voxelCorners({origin:[0,0,0],axes:[[1,0,0],[0,1,0],[0,0,1]]},['9223372036854775807','0','0'])).toThrow()
})
it('drops late comparison reads on selection changes and unmount',async()=>{
  const install=vi.fn(),report=vi.fn(),controller=createComparisonController(install,report)
  let resolve!:(data:CloudDisplayData)=>void
  const old={dispose:vi.fn()} as unknown as CloudDisplayData,newer={dispose:vi.fn()} as unknown as CloudDisplayData
  const pending=controller.load(()=>new Promise(r=>{resolve=r}))
  await controller.load(async()=>newer);resolve(old);await pending
  expect(install).toHaveBeenLastCalledWith(newer);expect(old.dispose).toHaveBeenCalledOnce()
  controller.dispose();expect(newer.dispose).toHaveBeenCalledOnce()
  const c=createComparisonController(install,report),late=c.load(()=>new Promise(r=>{resolve=r}));c.dispose();resolve(old);await late
  expect(old.dispose).toHaveBeenCalledTimes(2);expect(install).toHaveBeenLastCalledWith(null)
})
it('accepts only explicit same observation and spatial coordinates',()=>{
  const a={state:'ready',observation_id:'o',spatial:{frame_id:'sensor',length_unit:'mm'}}
  expect(comparableClouds(a,a)).toBe(true)
  expect(comparableClouds(a,{...a,observation_id:'other'})).toBe(false)
  expect(comparableClouds(a,{...a,spatial:{frame_id:'sensor',length_unit:'m'}})).toBe(false)
})
