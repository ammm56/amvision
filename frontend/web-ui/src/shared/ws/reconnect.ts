export function getReconnectDelayMs(attempt: number): number {
  return Math.min(Math.max(attempt, 1) * 1000, 10000)
}