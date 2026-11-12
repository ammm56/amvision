/** 读取完整有界诊断，逐条访问避免复制成大对象列表。 */
import {object,count,decodePreviewBytes,reserveCpu,validatePolicy} from './preview-data'
import type {CloudRendererPolicy} from '../services/measurement-resource.service'

export async function decodeEdgeDiagnostic(payload:Record<string,unknown>,policy:CloudRendererPolicy,signal:AbortSignal){
  validatePolicy(policy)
  const body=object(payload.edge_diagnostics),edge=body.edge===null?{}:object(body.edge),sampling=body.sampling===null?{}:object(body.sampling),data=object(body.data)
  if(body.format_id!=='amvision.edge-preview.v1'||body.state!=='ready'||body.observation_id!==payload.observation_id||body.cloud_id!==payload.cloud_id)throw new Error('cloud_preview_invalid')
  const edgeCount=body.edge===null?0:count(edge.record_count),sampleCount=body.sampling===null?0:count(sampling.input_count),n=edgeCount+sampleCount,size=n*68
  if(!Number.isSafeInteger(n)||n>policy.max_points||size!==data.content_length||size>policy.max_data_bytes)throw new Error('cloud_preview_capacity')
  if(body.edge!==null&&(!['height-jump','normal-crease'].includes(String(object(edge.method).kind))||edge.format_id!=='amvision.edge-evidence.v1'||edge.input_count!==payload.point_count||!Array.isArray(edge.reports)))throw new Error('cloud_preview_invalid')
  if(body.sampling!==null&&(sampling.format_id!=='amvision.sampling-evidence.v1'||sampleCount!==payload.point_count||sampling.vertex_kind!==payload.vertex_kind))throw new Error('cloud_preview_invalid')
  const release=reserveCpu(size*6,policy)
  try{
    const raw=await decodePreviewBytes(data,signal),view=new DataView(raw.buffer,raw.byteOffset,raw.byteLength)
    let closed=false
    const integer=(offset:number,signed=false)=>{const value=signed?view.getBigInt64(offset,true):view.getBigUint64(offset,true);if(value>BigInt(Number.MAX_SAFE_INTEGER)||value< -1n)throw new Error('cloud_preview_invalid');return Number(value)}
    function record(index:number){
      if(closed||!Number.isSafeInteger(index)||index<0||index>=n)throw new Error('cloud_preview_invalid')
      const offset=index*68,sample=index>=edgeCount
      const position=[0,8,16].map(k=>view.getFloat64(offset+k,true)),source=integer(offset+24),partner=integer(offset+36,true),status=view.getUint8(offset+32),side=view.getUint8(offset+33),context=view.getUint8(offset+34),candidate=view.getUint8(offset+35),metrics=[44,52,60].map(k=>view.getFloat64(offset+k,true))
      if(!position.every(Number.isFinite)||source>=count(sample&&sampling.vertex_kind==='generated'?payload.point_count:payload.source_point_count)||partner>=edgeCount||partner===index||sample&&(partner!==-1||side!==255||status>31||context>31||candidate>1)||!sample&&(status>13||side>3||context||candidate))throw new Error('cloud_preview_invalid')
      if(metrics.some(v=>!Number.isFinite(v)&&!Number.isNaN(v)))throw new Error('cloud_preview_invalid')
      return {index,position,source,partner,status,side,context,candidate,metrics,sample}
    }
    for(let i=0;i<n;i++)record(i)
    return {count:n,edgeCount,edge,sampling,record,dispose(){if(!closed){closed=true;release()}}}
  }catch(error){release();throw error}
}

export const pairStatusNames=[['已配对','Paired'],['支持无效','Invalid support'],['未归属','Unassigned'],['两面归属歧义','Ambiguous surface'],['缺另一侧','Missing opposite side'],['近邻歧义','Ambiguous nearest'],['超出间隙','Gap exceeded'],['非互为近邻','Not mutual'],['配对歧义','Ambiguous partner'],['非高度跃变','Not height jump'],['法向无效','Invalid normal'],['邻域不完整','Incomplete neighborhood'],['配对冲突','Pairing conflict'],['边序歧义','Ambiguous edge order']]
