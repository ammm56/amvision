/** 已有参数枚举的显示名称；持久值及用户定义 ROI ID 不变。 */
const quantiles:Record<string,[string,string]>={
  inverted_cdf:['经验分布反函数','Inverted empirical CDF'],
  averaged_inverted_cdf:['平均反分布','Averaged inverted CDF'],
  closest_observation:['最近观测','Closest observation'],
  interpolated_inverted_cdf:['插值反分布','Interpolated inverted CDF'],
  hazen:['Hazen 方法','Hazen'],weibull:['Weibull 方法','Weibull'],
  linear:['线性插值','Linear interpolation'],median_unbiased:['中位无偏','Median unbiased'],
  normal_unbiased:['正态无偏','Normal unbiased'],lower:['较低观测值','Lower observation'],
  higher:['较高观测值','Higher observation'],midpoint:['两值中点','Midpoint'],nearest:['最近观测值','Nearest observation'],
}
const roles:Record<string,[string,string]>={outer:['外边界','Outer boundary'],inner:['内边界','Inner boundary'],open:['开放边界','Open boundary'],unknown:['未指定','Unspecified']}
const sides:Record<string,[string,string]>={high:['高侧实测边','Measured high side'],low:['低侧实测边','Measured low side'],a:['A 侧实测边','Measured side A'],b:['B 侧实测边','Measured side B']}
const units:Record<string,[string,string]>={m:['米 (m)','Meter (m)'],mm:['毫米 (mm)','Millimeter (mm)'],um:['微米 (um)','Micrometer (um)']}
export function geometryOptionLabel(path:string,value:string,zh:boolean):string{
  const labels=path.endsWith('length_unit')?units:path==='statistic.method'?quantiles:path==='role'?roles:path.endsWith('.side')?sides:undefined
  return labels?.[value]?.[zh?0:1]??value
}
