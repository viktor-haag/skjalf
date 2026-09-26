import Vue from 'vue'
import App from './App.vue'
import './style.css'

Vue.config.productionTip = false

const mountHost = document.getElementById('content') || document.getElementById('content-vue')
if (!mountHost) {
  throw new Error('Skjalf embedded page did not provide #content or #content-vue.')
}

mountHost.classList.add('skjalf-host')
const viewport = document.createElement('div')
viewport.className = 'skjalf-viewport'
const mountTarget = document.createElement('div')
mountTarget.className = 'skjalf-app-mount'
viewport.appendChild(mountTarget)
mountHost.appendChild(viewport)

new Vue({ render: h => h(App) }).$mount(mountTarget)
