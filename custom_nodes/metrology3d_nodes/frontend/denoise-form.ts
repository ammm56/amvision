/** 去噪方法互斥，数值由配方填写，不用 UI 缺省值代替工程选择。 */
export type DenoiseDraft = {kind: string; neighbors?: number | ''; std_ratio?: number | ''; radius?: number | ''; min_neighbors?: number | ''}
export function newDenoise(kind: string): DenoiseDraft {
  return kind === 'radius' ? {kind, radius: '', min_neighbors: ''} : {kind: 'statistical', neighbors: '', std_ratio: ''}
}
export function denoiseValid(value: DenoiseDraft): boolean {
  const positive = (n: unknown) => typeof n === 'number' && Number.isFinite(n) && n > 0
  const integer = (n: unknown) => positive(n) && Number.isSafeInteger(n)
  return value.kind === 'statistical'
    ? integer(value.neighbors) && positive(value.std_ratio)
    : value.kind === 'radius' && positive(value.radius) && integer(value.min_neighbors)
}
