import type { RouteRecordRaw } from 'vue-router'

const LoginPage = () => import('./pages/LoginPage.vue')

export const authRoutes: RouteRecordRaw[] = [
  {
    path: '/login',
    component: LoginPage,
    meta: { shell: 'auth', requiresAuth: false },
  },
]
