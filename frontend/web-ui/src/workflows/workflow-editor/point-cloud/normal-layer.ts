import {BufferAttribute,BufferGeometry,LineBasicMaterial,LineSegments,type Object3D} from 'three'
import {reserveCpu,reserveGpu,type CloudDisplayData} from './preview-data'
import type {CloudRendererPolicy} from '../services/measurement-resource.service'

export interface NormalDisplayOptions {length:number;stride:number}
/** 只绘制概览实有的有效法向；无符号为对称轴，有符号附箭头，不补失败方向。 */
export function createNormalLayer(scene:Object3D,data:CloudDisplayData,policy:CloudRendererPolicy,schedule:()=>void){
  let lines:LineSegments|null=null,release=()=>{},closed=false
  function clear(){lines?.removeFromParent();lines?.geometry.dispose();(lines?.material as LineBasicMaterial|undefined)?.dispose();lines=null;release();release=()=>{}}
  return {
    update(options:NormalDisplayOptions|null){
      clear();schedule();if(closed||!options)return
      if(!Number.isFinite(options.length)||options.length<=0||!Number.isSafeInteger(options.stride)||options.stride<1)throw new Error('cloud_preview_invalid')
      let segments=0
      for(let i=0;i<data.count;i+=options.stride){const n=data.point(i).normal;if(n?.valid)segments+=n.oriented?3:1}
      if(!segments)return
      const bytes=segments*2*3*4*2,cpu=reserveCpu(bytes,policy)
      try{const gpu=reserveGpu(bytes,policy);release=()=>{cpu();gpu()}}catch(e){cpu();throw e}
      try{
        const positions=new Float32Array(segments*6),colors=new Float32Array(positions.length);let at=0
        const vertex=(p:number[],color:number[])=>{for(let c=0;c<3;c++){positions[at]=p[c]!;if(!Number.isFinite(positions[at])||Math.abs(positions[at]!-p[c]!)>policy.max_position_error)throw new Error('cloud_position_precision');colors[at]=color[c]!;at++}}
        for(let i=0;i<data.count;i+=options.stride){
          const n=data.point(i).normal;if(!n?.valid)continue
          const p=Array.from(data.positions.subarray(i*3,i*3+3)),v=n.vector,l=options.length
          const start=p.map((x,c)=>x-(n.oriented?0:.5)*l*v[c]!),end=p.map((x,c)=>x+(n.oriented?1:.5)*l*v[c]!),color=n.oriented?[.12,.85,.5]:[1,.65,.08]
          vertex(start,color);vertex(end,color)
          if(n.oriented){
            const axis=Math.abs(v[0]!)<.8?[1,0,0]:[0,1,0],cross=[v[1]!*axis[2]!-v[2]!*axis[1]!,v[2]!*axis[0]!-v[0]!*axis[2]!,v[0]!*axis[1]!-v[1]!*axis[0]!],norm=Math.hypot(...cross)
            for(const sign of [-1,1]){vertex(end,color);vertex(end.map((x,c)=>x-l*.2*v[c]!+sign*l*.08*cross[c]!/norm),color)}
          }
        }
        lines=new LineSegments(new BufferGeometry().setAttribute('position',new BufferAttribute(positions,3)).setAttribute('color',new BufferAttribute(colors,3)),new LineBasicMaterial({vertexColors:true}))
        scene.add(lines);schedule()
      }catch(e){clear();throw e}
    },
    dispose(){closed=true;clear()},
  }
}
