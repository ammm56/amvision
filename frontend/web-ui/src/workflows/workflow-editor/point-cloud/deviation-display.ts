/** 有限偏差摘要的显示校验；不以显示采样重新统计或判定完整目标。 */
import {object} from './preview-data'
const point=(v:unknown)=>Array.isArray(v)&&v.length===3&&v.every(n=>typeof n==='number'&&Number.isFinite(n))
const count=(v:unknown)=>Number.isSafeInteger(v)&&Number(v)>=0
export const deviationNames:Record<string,string>={min:'minimum',max:'maximum','peak-to-valley':'peak_to_valley',mean:'mean',rms:'rms'}
export function deviationComponentLabel(key:string,zh:boolean){const labels:Record<string,string>=zh?{min:'最小偏差',max:'最大偏差','peak-to-valley':'偏差峰谷',mean:'平均偏差',rms:'RMS'}:{min:'Minimum deviation',max:'Maximum deviation','peak-to-valley':'Peak-to-valley',mean:'Mean deviation',rms:'RMS'};return labels[key]??key}
export function validateDeviation(item:Record<string,unknown>,geometry:Record<string,unknown>|null,payload:Record<string,unknown>){
  const fail=()=>{throw new Error('cloud_preview_invalid')},s=object(item.summary),p=object(object(item.method).parameters),space=object(payload.spatial),counts=object(s.counts)
  const keys=['covered','extended','invalid_target','invalid_reference','outside_support','support_quality_failed','extension_limit_exceeded']
  if(s.observation_id!==payload.observation_id||p.frame_id!==space.frame_id||p.length_unit!==space.length_unit||s.valid!==item.valid||s.reason!==item.reason||s.diagnostic_only!==!item.valid||!count(s.target_count)||!count(s.source_point_count)||Object.keys(counts).length!==keys.length||keys.some(k=>!count(counts[k]))||keys.reduce((sum,k)=>sum+Number(counts[k]),0)!==s.target_count)fail()
  const stats=object(s.diagnostic),field=deviationNames[String(item.component)]
  if(!field)fail()
  if(item.valid&&(item.value!==stats[field!]||stats.count!==s.target_count||Number(counts.covered)+Number(counts.extended)!==s.target_count))fail()
  if(s.diagnostic!==null){
    if(!count(stats.count)||Number(stats.count)>Number(s.target_count)||Object.values(deviationNames).some(k=>typeof stats[k]!=='number'||!Number.isFinite(stats[k])))fail()
    for(const key of ['minimum_source','maximum_source']){const e=object(stats[key]);if(!count(e.source_index)||Number(e.source_index)>=Number(s.source_point_count)||!count(e.logical_index)||Number(e.logical_index)>=Number(s.target_count)||!count(e.tie_count)||Number(e.tie_count)<1)fail()}
  }
  if(geometry&&(geometry.kind!=='datum-deviation'||!Array.isArray(geometry.endpoints)||geometry.endpoints.length!==2||!geometry.endpoints.every(point)))fail()
}
