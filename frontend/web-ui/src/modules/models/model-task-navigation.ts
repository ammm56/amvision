import { inject, ref, watch } from 'vue'
import { routeLocationKey, routerKey, type LocationQuery } from 'vue-router'

type TaskTab = 'training' | 'conversion'

export function modelTaskListLocation(tab: TaskTab, taskType?: string, query?: LocationQuery) {
  return {
    path: '/models',
    query: { tab, task: taskType, q: query?.q, state: query?.state, page: query?.page, size: query?.size },
  }
}

export function useModelTaskListNavigation(tab: TaskTab) {
  const route = inject(routeLocationKey, null)
  const router = inject(routerKey, null)
  const search = ref('')
  const status = ref('all')
  const page = ref(1)
  const pageSize = ref(20)

  function query() {
    return {
      q: search.value || undefined,
      state: status.value === 'all' ? undefined : status.value,
      page: page.value > 1 ? String(page.value) : undefined,
      size: pageSize.value !== 20 ? String(pageSize.value) : undefined,
    }
  }

  watch(() => route?.query, (next) => {
    search.value = typeof next?.q === 'string' ? next.q : ''
    const state = next?.state
    status.value = typeof state === 'string' && ['queued', 'running', 'paused', 'succeeded', 'failed', 'timed_out', 'cancelled'].includes(state) ? state : 'all'
    const requestedPage = typeof next?.page === 'string' ? Number(next.page) : 1
    page.value = Number.isSafeInteger(requestedPage) && requestedPage > 1 ? requestedPage : 1
    const size = Number(next?.size)
    pageSize.value = [10, 20, 50].includes(size) ? size : 20
  }, { immediate: true })

  function sync() {
    if (router && route?.path === '/models') {
      void router.replace({ query: { ...route.query, ...query() } })
    }
  }

  function setSearch(value: string) {
    search.value = value
    page.value = 1
    sync()
  }

  function setStatus(value: string) {
    status.value = value
    page.value = 1
    sync()
  }

  function setPage(value: number) {
    page.value = value
    sync()
  }
  function setPageSize(value: number) {
    pageSize.value = value
    page.value = 1
    sync()
  }

  function detailLocation(taskType: string, taskId: string) {
    return { path: `/models/${taskType}/${tab}-tasks/${encodeURIComponent(taskId)}`, query: query() }
  }

  return { search, status, page, pageSize, detailLocation, setSearch, setStatus, setPage, setPageSize }
}
