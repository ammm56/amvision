/** 工作站本地时间。记录列表按分钟显示，运行日志默认保留秒。 */
export function formatSystemDateTime(value: string | null | undefined, precision: 'seconds' | 'minutes' | 'step' = 'seconds'): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '-'
  const year = date.getFullYear()
  const month = pad(date.getMonth() + 1)
  const day = pad(date.getDate())
  const hour = pad(date.getHours())
  const minute = pad(date.getMinutes())
  const second = pad(date.getSeconds())
  const short = `${month}-${day} ${hour}:${minute}`
  if (precision === 'step') return short
  return `${year}-${short}${precision === 'seconds' ? ':' + second : ''}`
}

function pad(value: number): string {
  return String(value).padStart(2, '0')
}
