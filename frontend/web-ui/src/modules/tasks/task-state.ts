export type CanonicalTaskState = 'queued' | 'running' | 'paused' | 'succeeded' | 'failed' | 'timed_out' | 'cancelled' | 'unknown'

export function normalizeTaskState(value: string | null | undefined): CanonicalTaskState {
  const state = String(value ?? '').trim().toLowerCase()
  if (!state) return 'unknown'
  if (state === 'paused' || state.includes('pause')) return 'paused'
  if (state === 'timed_out' || state.includes('time_out') || state.includes('timeout')) return 'timed_out'
  if (state.includes('cancel') || state.includes('revoke')) return 'cancelled'
  if (state.includes('fail') || state.includes('error') || state.includes('terminate')) return 'failed'
  if (state.includes('success') || state.includes('succeed') || state.includes('complete') || state.includes('finish')) return 'succeeded'
  if (state.includes('run') || state.includes('process') || state.includes('validat') || state.includes('convert') || state.includes('train')) return 'running'
  if (state.includes('queue') || state.includes('pending') || state.includes('received') || state.includes('created')) return 'queued'
  return 'unknown'
}
