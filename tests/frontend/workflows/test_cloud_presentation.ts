import {expect,it} from 'vitest'
import {Color,SRGBColorSpace} from 'three'
import {coordinateRange,coordinateColor,fillCoordinateColors,linearizeDisplayColors,scaleBar} from '@/workflows/workflow-editor/point-cloud/view-presentation'

it('matches CSS/sRGB legend and input RGB after the renderer output conversion',()=>{
  const values=new Float32Array([.25,.5,.75]),expected=values.slice()
  linearizeDisplayColors(values);expect(values[1]).toBeCloseTo(.214041,5)
  const output=new Color().setRGB(values[0]!,values[1]!,values[2]!).getRGB({r:0,g:0,b:0},SRGBColorSpace)
  expect([output.r,output.g,output.b].map(v=>Math.round(v*255))).toEqual([...expected].map(v=>Math.round(v*255)))
})

it('colors physical Z without changing source coordinates or dropping saturated points',()=>{
  const positions=new Float32Array([0,0,-2,1,2,0,3,4,2]),before=positions.slice(),colors=new Float32Array(9)
  fillCoordinateColors(colors,positions,1000,{min:999,max:1001})
  expect([...colors]).toEqual([0,0,1,0,1,0,1,0,0]);expect(positions).toEqual(before)
  expect(coordinateColor(7,{min:7,max:7})).toEqual([0,1,0])
  expect(()=>fillCoordinateColors(colors,positions,0,{min:2,max:1})).toThrow('cloud_preview_invalid')
  expect(()=>fillCoordinateColors(colors,positions,Infinity,{min:1,max:2})).toThrow('cloud_preview_invalid')
})
it('requires finite ordered display bounds and permits a planar cloud',()=>{
  expect(coordinateRange({bounds:{min:[0,0,2],max:[1,1,2]}})).toEqual({min:2,max:2})
  for(const payload of [{},{bounds:{min:[0,0,2],max:[0,0,1]}},{bounds:{min:[0,0,NaN],max:[0,0,1]}}])expect(coordinateRange(payload)).toBeNull()
})
it('uses physical 1/2/5 scale steps within the viewport and handles zoom',()=>{
  expect(scaleBar(100,600)).toEqual({value:20,pixels:120})
  expect(scaleBar(50,600)).toEqual({value:10,pixels:120})
  expect(scaleBar(100,300)).toEqual({value:20,pixels:60})
  for(const [world,pixels] of [[0,600],[Infinity,600],[1,40]])expect(scaleBar(world!,pixels!)).toBeNull()
})
