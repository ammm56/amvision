import type { BrowserStorageKind } from '@/shared/contracts'

const memoryStorage = new Map<string, string>()

function resolveStorage(storageKind: BrowserStorageKind): Storage | null {
  if (typeof window === 'undefined') {
    return null
  }
  if (storageKind === 'localStorage') {
    return window.localStorage
  }
  if (storageKind === 'sessionStorage') {
    return window.sessionStorage
  }
  return null
}

export function readStorageValue(key: string, storageKind: BrowserStorageKind): string | null {
  const storage = resolveStorage(storageKind)
  if (!storage) {
    return memoryStorage.get(key) ?? null
  }
  return storage.getItem(key)
}

export function writeStorageValue(key: string, value: string, storageKind: BrowserStorageKind): void {
  const storage = resolveStorage(storageKind)
  if (!storage) {
    memoryStorage.set(key, value)
    return
  }
  storage.setItem(key, value)
}

export function removeStorageValue(key: string, storageKind: BrowserStorageKind): void {
  const storage = resolveStorage(storageKind)
  if (!storage) {
    memoryStorage.delete(key)
    return
  }
  storage.removeItem(key)
}