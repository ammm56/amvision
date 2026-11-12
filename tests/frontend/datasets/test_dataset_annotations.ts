import {describe,it,expect,vi} from 'vitest'
import {decodeMaskRuns,paintAnnotations} from '../../../frontend/web-ui/src/modules/datasets/annotations'
import type {DatasetAnnotation,DatasetSample} from '../../../frontend/web-ui/src/modules/datasets/services/dataset-workspace.service'

const annotation=(value:Partial<DatasetAnnotation>):DatasetAnnotation=>({annotation_id:'a',annotation_type:'detection',category_id:0,bbox_xywh:null,segmentation:null,keypoints:null,polygon_xy:null,is_anomalous:null,metadata:{},...value})
function canvas(){return {save:vi.fn(),restore:vi.fn(),strokeRect:vi.fn(),fillRect:vi.fn(),measureText:()=>({width:10}),fillText:vi.fn(),beginPath:vi.fn(),closePath:vi.fn(),lineTo:vi.fn(),moveTo:vi.fn(),arc:vi.fn(),stroke:vi.fn(),fill:vi.fn()} as unknown as CanvasRenderingContext2D}
const sample=(annotations:DatasetAnnotation[]):DatasetSample=>({sample_id:'s',image_id:1,dataset_version_id:'v',file_name:'sample.png',width:3,height:2,split:'train',annotations,metadata:{}})
describe('Dataset ground truth rendering',()=>{
 it('decodes compressed and uncompressed COCO without allocating source-size pixel arrays',()=>{
  expect(decodeMaskRuns({size:[2,3],counts:'0220'})).toEqual({width:3,height:2,runs:[0,2,2,2]})
  expect(decodeMaskRuns({size:[2,3],counts:[0,2,2,2]})).toEqual(decodeMaskRuns({size:[2,3],counts:'0220'}))
  expect(decodeMaskRuns({size:[2,3],counts:'_'})).toBeNull()
  expect(decodeMaskRuns({size:[2,3],counts:[1,4]})).toBeNull()
  expect(decodeMaskRuns({size:[2,3],counts:[1,-1,6]})).toBeNull()
 })
 it('renders RLE in column order and reports mismatched dimensions',()=>{
  const ctx=canvas(),item=annotation({annotation_type:'segmentation',segmentation:{size:[2,3],counts:'0220'}})
  expect(paintAnnotations(ctx,sample([item]),new Map([[0,'part']]),30,20)).toBe(0)
  expect(ctx.fillRect).toHaveBeenCalledWith(0,0,10,20)
  expect(ctx.fillRect).toHaveBeenCalledWith(20,0,10,20)
  expect(paintAnnotations(ctx,sample([annotation({...item,segmentation:{size:[3,2],counts:[6]}})]),new Map(),30,20)).toBe(1)
 })
 it('keeps classification box-free and OBB as four corners, never the fallback axis-aligned box',()=>{
  const ctx=canvas()
  paintAnnotations(ctx,sample([annotation({annotation_type:'classification'}),annotation({annotation_type:'obb',polygon_xy:[0,1,1,0,3,1,2,2],bbox_xywh:[0,0,3,2]})]),new Map(),30,20)
  expect(ctx.strokeRect).not.toHaveBeenCalled()
  expect(ctx.lineTo).toHaveBeenCalledWith(30,10)
 })
 it('does not plot unlabelled keypoints, differentiates occluded and visible points',()=>{
  const ctx=canvas()
  paintAnnotations(ctx,sample([annotation({annotation_type:'pose',keypoints:[0,0,0,1,1,1,2,1,2]})]),new Map(),30,20)
  expect(ctx.arc).toHaveBeenCalledTimes(2)
  expect(ctx.stroke).toHaveBeenCalledTimes(1)
  expect(ctx.fill).toHaveBeenCalledTimes(1)
 })
})
