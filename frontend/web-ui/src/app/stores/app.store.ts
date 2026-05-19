import { defineStore } from 'pinia'

export type BackendConnectionState = 'checking' | 'online' | 'offline' | 'degraded'

export const useAppStore = defineStore('app', {
  state: () => ({
    backendConnectionState: 'checking' as BackendConnectionState,
    lastGlobalError: null as string | null,
  }),
  actions: {
    setBackendConnectionState(state: BackendConnectionState): void {
      this.backendConnectionState = state
    },
    setLastGlobalError(message: string | null): void {
      this.lastGlobalError = message
    },
  },
})