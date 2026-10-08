import {formatResultValue} from './result-geometry'
import type {InjectionKey} from 'vue'

export type ResultReasonLabels = Readonly<Record<string,readonly [string,string]>>
export const resultReasonLabelsKey:InjectionKey<ResultReasonLabels>=Symbol('resultReasonLabels')

/** 列显式声明显示语义，普通布尔值不自动变成 OK/NG。 */
export type ResultColumnFormat = 'value' | 'unit' | 'result' | 'validity' | 'reason'
export interface ResultColumn { key:string;label:string;format?:ResultColumnFormat }
export const resultColumnFormats:readonly ResultColumnFormat[]=['value','unit','result','validity','reason']

export function formatResultUnit(value:unknown):string {
  const units:Record<string,string>={millimeter:'mm',micrometer:'µm',pixel:'px',degrees:'°',unitless:'—'}
  return units[String(value)]??formatResultValue(value)
}

export function formatResultCell(value:unknown,format:ResultColumnFormat|undefined,zh:boolean,labels:ResultReasonLabels={}):string {
  if(format==='unit')return formatResultUnit(value)
  if(format==='result'&&typeof value==='boolean')return value?'OK':'NG'
  if(format==='validity'&&typeof value==='boolean')return value?(zh?'有效':'Valid'):(zh?'无效':'Invalid')
  const reasons:Record<string,[string,string]>={missing_value:['缺少数值','Missing value'],feature_missing:['缺少几何特征','Missing geometry'],endpoint_not_observed:['未观测到端点','Endpoint not observed'],section_not_observed:['截面超出观测范围','Section not observed'],above_upper_limit:['超过上限','Above upper limit'],below_lower_limit:['低于下限','Below lower limit'],unit_mismatch:['单位不一致','Unit mismatch'],ambiguous:['定位存在歧义','Ambiguous location'],pose_not_found:['未定位到工件','Pose not found']}
  if(format==='reason'&&typeof value==='string'){const label=labels[value]??reasons[value];if(label)return label[zh?0:1]}
  return value===''?'—':formatResultValue(value)
}
