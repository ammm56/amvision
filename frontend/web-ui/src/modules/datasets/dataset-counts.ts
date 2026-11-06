import { useDatasetText } from './dataset-workspace'

export interface DatasetCountItem {
  key: string
  count: number | null
  label: string
  heading: string
  summary: string
}

/** 所有工作区共用数值含义、顺序及提示；未知值不显示为零。 */
export function useDatasetCounts() {
  const text = useDatasetText()
  const countColumn = (
    key: string,
    count: unknown,
    name = text(key),
    unit = text('imageUnit'),
  ): DatasetCountItem => {
    const value = typeof count === 'number' && Number.isFinite(count) && count >= 0 ? count : null
    const display = value === null ? '—' : `${value.toLocaleString()} ${unit}`.trim()
    const summary = ['train', 'test', 'val'].includes(key)
      ? `${key} ${value?.toLocaleString() ?? '—'}`
      : display
    return { key, count: value, heading: name, label: `${name}：${display}`, summary }
  }
  const countItems = (key: string, count: unknown, name = text(key), unit = text('imageUnit')) => {
    const item = countColumn(key, count, name, unit)
    return item.count === null ? [] : [item]
  }
  // 固定保留样本、类别顺序，缺失统计使用占位，不能冒充零值。
  const sampleColumns = (samples: unknown, classes: unknown) => [
    countColumn('samples', samples),
    countColumn('classes', classes, text('classes'), text('classUnit')),
  ]
  const sampleCounts = (samples: unknown, classes?: unknown) =>
    sampleColumns(samples, classes).filter(item => item.count !== null)
  const objectCounts = (count: unknown) =>
    countItems('object', count, text('object'), text('objectUnit'))
  const splitHeading = (key: string) => {
    const labels: Record<string, string> = {
      train: 'trainingSplit', test: 'testingSplit', val: 'validationSplit',
    }
    const labelKey = labels[key]
    return labelKey ? text(labelKey) : key
  }
  const splitName = (key: string) => ['train', 'test', 'val'].includes(key) ? `${splitHeading(key)} ${key}` : key
  const splitColumns = (
    counts: Record<string, number> | null | undefined,
    unit = text('imageUnit'),
  ) => ['train', 'test', 'val'].map(key =>
    ({ ...countColumn(key, counts ? counts[key] ?? 0 : null, splitName(key), unit), heading: splitHeading(key) }))
  const splitCounts = (
    counts: Record<string, number> | null | undefined,
    unit = text('imageUnit'),
  ) => counts
    ? [...new Set(['train', 'test', 'val', ...Object.keys(counts)])].flatMap(key =>
      countItems(key, counts[key] ?? 0, splitName(key), unit).map(item => ({ ...item, heading: splitHeading(key) })))
    : []
  return { countItems, sampleCounts, sampleColumns, objectCounts, splitCounts, splitColumns, splitName }
}
