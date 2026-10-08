export interface LimitRule {item_id:string;unit:string;lower:number|null;upper:number|null;required:boolean;enabled:boolean;include_lower:boolean;include_upper:boolean}
export function normalizeLimitRule(value:unknown):LimitRule {
  const source=value&&typeof value==='object'&&!Array.isArray(value)?value as Partial<LimitRule>:{}
  return {lower:null,upper:null,enabled:true,required:true,include_lower:true,include_upper:true,...source,
    item_id:typeof source.item_id==='string'?source.item_id:'',unit:typeof source.unit==='string'?source.unit:''} as LimitRule
}
/** 与公开 LimitRule 的有限数值、闭区间和必检约束一致，字段不依赖行业包。 */
export function limitRuleError(rule:LimitRule):string|null {
  const id=/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/
  if(typeof rule.item_id!=='string'||typeof rule.unit!=='string'||!id.test(rule.item_id)||!id.test(rule.unit))return 'identity'
  if(![rule.enabled,rule.required,rule.include_lower,rule.include_upper].every(v=>typeof v==='boolean'))return 'boolean'
  if(![rule.lower,rule.upper].every(v=>v===null||typeof v==='number'&&Number.isFinite(v)))return 'number'
  if(rule.lower===null&&rule.upper===null)return 'bound'
  if(rule.lower!==null&&rule.upper!==null&&(rule.lower>rule.upper||rule.lower===rule.upper&&(!rule.include_lower||!rule.include_upper)))return 'interval'
  return null
}
