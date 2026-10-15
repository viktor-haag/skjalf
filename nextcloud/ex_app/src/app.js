import Vue from 'vue'
import App from './App.vue'
import './style.css'

Vue.config.productionTip = false

const appApiContent = document.querySelector('#content > #content')
const mountHost = appApiContent || document.getElementById('content-vue') || document.getElementById('content')
if (!mountHost) {
  throw new Error('Skjalf embedded page did not provide #content or #content-vue.')
}

if (appApiContent) {
  mountHost.id = 'skjalf-root'
}
mountHost.classList.add('skjalf-host')
const viewport = document.createElement('div')
viewport.className = 'skjalf-viewport'
const mountTarget = document.createElement('div')
mountTarget.className = 'skjalf-app-mount'
viewport.appendChild(mountTarget)
mountHost.appendChild(viewport)

new Vue({ render: h => h(App) }).$mount(mountTarget)
