/** 点云字段与显示配置的表单校验；不执行过滤或着色。 */
import {object} from './form'
export const fieldId=(value:unknown):value is string=>typeof value==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(value)
const decimal=/^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/
/** 比较十进制文本，不将 uint64 边界转成有损的 Number。 */
export function compareDecimal(a:string,b:string):number {
  function parts(value:string){
    const [mantissa,exponent='0']=value.toLowerCase().split('e'),negative=mantissa!.startsWith('-')
    const [whole,fraction='']=mantissa!.replace('-','').split('.')
    const digits=(whole!+fraction).replace(/^0+/,'')||'0'
    return {sign:digits==='0'?0:negative?-1:1,digits,order:BigInt(exponent)-BigInt(fraction.length)+BigInt(digits.length)}
  }
  const x=parts(a),y=parts(b)
  if(x.sign!==y.sign)return x.sign-y.sign
  if(!x.sign)return 0
  const width=Math.max(x.digits.length,y.digits.length),left=x.digits.padEnd(width,'0'),right=y.digits.padEnd(width,'0')
  return x.sign*(x.order<y.order?-1:x.order>y.order?1:left<right?-1:left>right?1:0)
}
export function sentinelValue(text:string):number|string|null {
  if(!text||text.length>128||!decimal.test(text))return null
  if(/^(0|-?[1-9][0-9]*)$/.test(text))return text
  const number=Number(text)
  return Number.isFinite(number)?number:null
}
export function cloudDataIssues(parameter:string,value:unknown):string[] {
  if(parameter==='finite_fields')return Array.isArray(value)&&value.every(fieldId)&&value.includes('positions')&&new Set(value).size===value.length?[]:['fields']
  if(parameter==='sentinels')return Array.isArray(value)&&value.every(raw=>{
    const row=object(raw)
    return Object.keys(row).every(k=>['field','match','values'].includes(k))&&fieldId(row.field)&&['all','any'].includes(String(row.match))&&Array.isArray(row.values)&&row.values.length>=1&&row.values.length<=3&&row.values.every(v=>typeof v==='number'?Number.isFinite(v):typeof v==='string'&&/^(0|-?[1-9][0-9]*)$/.test(v))
  })?[]:['sentinels']
  const color=object(value)
  if(['solid','rgb'].includes(String(color.mode)))return Object.keys(color).length===1?[]:['color']
  if(color.mode!=='scalar'||Object.keys(color).some(k=>!['mode','field','component','range'].includes(k))||!fieldId(color.field)||!Number.isSafeInteger(color.component)||Number(color.component)<0)return ['color']
  const range=object(color.range)
  if(range.mode==='finite-range')return Object.keys(range).length===1?[]:['range']
  if(range.mode!=='fixed'||Object.keys(range).some(k=>!['mode','min','max'].includes(k))||![range.min,range.max].every(v=>typeof v==='string'&&v.length<=128&&decimal.test(v)))return ['range']
  return compareDecimal(String(range.min),String(range.max))<0?[]:['range']
}
