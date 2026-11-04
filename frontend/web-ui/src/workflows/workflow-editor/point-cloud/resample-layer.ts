import {BufferAttribute,BufferGeometry,LineBasicMaterial,LineSegments,Points,PointsMaterial,type Object3D} from 'three'
import {reserveCpu,reserveGpu,type CloudDisplayData} from './preview-data'
import type {CloudRendererPolicy} from '../services/measurement-resource.service'

/** 对照与选中格独立于 I2/ROI 几何，显隐不重新构建测量证据。 */
export function createResampleLayer(scene:Object3D,origin:number[],policy:CloudRendererPolicy,schedule:()=>void){
  let comparison:Points|null=null,cell:LineSegments|null=null,closed=false
  let releaseComparison=()=>{},releaseCell=()=>{}
  function clearComparison(){comparison?.removeFromParent();comparison?.geometry.dispose();(comparison?.material as PointsMaterial|undefined)?.dispose();comparison=null;releaseComparison();releaseComparison=()=>{}}
  function clearCell(){cell?.removeFromParent();cell?.geometry.dispose();(cell?.material as LineBasicMaterial|undefined)?.dispose();cell=null;releaseCell();releaseCell=()=>{}}
  function buffers(bytes:number){const cpu=reserveCpu(bytes,policy);try{const gpu=reserveGpu(bytes,policy);return ()=>{cpu();gpu()}}catch(e){cpu();throw e}}
  function relative(values:number[],target:Float32Array,offset:number){for(let c=0;c<3;c++){const n=values[c]!-origin[c]!;target[offset+c]=n;if(!Number.isFinite(target[offset+c])||Math.abs(n-target[offset+c]!)>policy.max_position_error)throw new Error('cloud_position_precision')}}
  return {
    comparison(data:CloudDisplayData|null){
      clearComparison();if(closed||!data){schedule();return}
      if(data.count>policy.max_points)throw new Error('cloud_preview_capacity')
      releaseComparison=buffers(data.count*12)
      try{
        const p=new Float32Array(data.count*3)
        for(let i=0;i<data.count;i++)relative(data.point(i).xyz,p,i*3)
        comparison=new Points(new BufferGeometry().setAttribute('position',new BufferAttribute(p,3)),new PointsMaterial({color:0x96a3ad,size:1,sizeAttenuation:false,transparent:true,opacity:.45,depthWrite:false}))
        scene.add(comparison);schedule()
      }catch(e){clearComparison();throw e}
    },
    cell(corners:number[][]|null){
      clearCell();if(closed||!corners){schedule();return}
      if(corners.length!==8||corners.some(v=>v.length!==3))throw new Error('cloud_preview_invalid')
      releaseCell=buffers(24*3*4)
      try{
        const p=new Float32Array(72);let offset=0
        for(let i=0;i<8;i++)for(let axis=0;axis<3;axis++)if(!(i&(1<<axis)))for(const end of [i,i|(1<<axis)]){relative(corners[end]!,p,offset);offset+=3}
        cell=new LineSegments(new BufferGeometry().setAttribute('position',new BufferAttribute(p,3)),new LineBasicMaterial({color:0xffffff,depthTest:false}))
        scene.add(cell);schedule()
      }catch(e){clearCell();throw e}
    },
    dispose(){closed=true;clearCell();clearComparison()},
  }
}
