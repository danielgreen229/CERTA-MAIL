import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import { vMarquee } from './marquee'
import './style.css'
import './theme'
import { loadSession, session, can } from './session'
import LoginView from './views/LoginView.vue'
import PasswordView from './views/PasswordView.vue'
import LeadsView from './views/LeadsView.vue'
import JobsView from './views/JobsView.vue'
import QualityView from './views/QualityView.vue'
import KnowledgeView from './views/KnowledgeView.vue'
import ConnectorsView from './views/ConnectorsView.vue'
import SettingsView from './views/SettingsView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/leads' },
    { path: '/login', component: LoginView, meta: { public: true } },
    { path: '/password', component: PasswordView },
    { path: '/leads', component: LeadsView },
    { path: '/leads/:key', component: LeadsView },
    { path: '/jobs', component: JobsView },
    { path: '/quality', component: QualityView, meta: { role: 'supervisor' } },
    { path: '/knowledge', component: KnowledgeView },
    { path: '/connectors', component: ConnectorsView },
    { path: '/settings', component: SettingsView },
    { path: '/:pathMatch(.*)*', redirect: '/leads' },
  ],
})

router.beforeEach(async (to) => {
  if (!session.loaded) await loadSession()
  if (to.meta.public) return true
  if (!session.user) return { path: '/login', query: { next: to.fullPath } }
  if (session.user.must_change_password && to.path !== '/password') return '/password'
  const role = to.meta.role as 'supervisor' | 'admin' | undefined
  if (role && !can(role)) return '/leads'
  return true
})

createApp(App).use(router).directive('marquee', vMarquee).mount('#app')
