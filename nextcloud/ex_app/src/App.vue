<template>
  <main class="skjalf">
    <header class="hero">
      <div>
        <p class="eyebrow">PRIVATE BILDSUCHE</p>
        <h1>Skjalf</h1>
        <p class="intro">Finde Bilder in deinen ausgewählten Nextcloud-Ordnern mit einer Beschreibung.</p>
      </div>
      <button class="button secondary" :disabled="busy" @click="refresh">
        {{ busy ? 'Aktualisiere …' : 'Ordner abgleichen' }}
      </button>
    </header>

    <p v-if="error" class="notice error" role="alert">{{ error }}</p>
    <p v-if="notice" class="notice success" role="status">{{ notice }}</p>

    <section class="panel">
      <div class="section-heading">
        <div>
          <h2>Indizierte Ordner</h2>
          <p>Der Abgleich liest Dateinamen und Änderungsstände. Bilder werden erst nach „Indizierung starten“ verarbeitet.</p>
        </div>
        <button class="button primary" :disabled="busy" @click="showBrowser = !showBrowser">
          {{ showBrowser ? 'Ordnerauswahl schließen' : 'Ordner auswählen' }}
        </button>
      </div>

      <div v-if="showBrowser" class="browser">
        <div class="browser-toolbar">
          <button class="button text" :disabled="!folderPath || busy" @click="goUp">← Übergeordneter Ordner</button>
          <span class="current-path">{{ folderPath || 'Dateien' }}</span>
          <button class="button text" :disabled="busy" @click="loadFolders">Aktualisieren</button>
        </div>
        <p v-if="folders.length === 0 && !busy" class="muted">Hier gibt es keine verfügbaren Unterordner.</p>
        <ul v-else class="folder-list">
          <li v-for="folder in folders" :key="folder.file_id">
            <button class="folder-name" @click="openFolder(folder)">
              <span class="folder-icon" aria-hidden="true">▰</span>
              <span>{{ folder.name }}</span>
            </button>
            <button class="button small secondary" :disabled="busy" @click="registerFolder(folder)">Diesen Ordner auswählen</button>
          </li>
        </ul>
      </div>

      <div v-if="roots.length" class="root-list">
        <article v-for="root in roots" :key="root.root_id" class="root-card">
          <div class="root-main">
            <h3>{{ root.path }}</h3>
            <p class="muted">
              {{ root.indexed || 0 }} indiziert · {{ root.failed || 0 }} fehlerhaft
              <span v-if="root.available === false">· Ordner nicht verfügbar</span>
            </p>
            <div v-if="root.status === 'running' || root.status === 'queued'" class="progress-row">
              <progress :value="root.processed || 0" :max="Math.max(root.total || 1, 1)"></progress>
              <span>{{ root.processed || 0 }} / {{ root.total || 0 }}</span>
            </div>
            <p v-if="root.message" class="muted">{{ root.message }}</p>
          </div>
          <div class="root-actions">
            <button v-if="root.status === 'running' || root.status === 'queued'" class="button secondary" @click="pause(root)">Pausieren</button>
            <button v-else class="button primary" :disabled="busy || root.available === false" @click="start(root)">
              {{ root.status === 'paused' || root.status === 'error' ? 'Fortsetzen' : 'Indizierung starten' }}
            </button>
            <button class="button danger" :disabled="busy" @click="removeRoot(root)">Auswahl entfernen</button>
          </div>
        </article>
      </div>
      <p v-else-if="!busy" class="empty">Noch kein Ordner ausgewählt. Deine Originaldateien bleiben in Nextcloud.</p>
    </section>

    <section class="panel search-panel">
      <div class="section-heading">
        <div>
          <h2>Bilder suchen</h2>
          <p>Die Suche zeigt höchstens zehn aktuelle, weiterhin lesbare Treffer aus dem ausgewählten Ordner.</p>
        </div>
      </div>
      <form class="search-form" @submit.prevent="search">
        <label class="field">
          <span>Ordner</span>
          <select v-model="selectedRoot" :disabled="!roots.length">
            <option value="" disabled>Ordner auswählen</option>
            <option v-for="root in roots" :key="root.root_id" :value="root.root_id">{{ root.path }}</option>
          </select>
        </label>
        <label class="field query-field">
          <span>Beschreibung</span>
          <input v-model.trim="query" type="search" maxlength="500" placeholder="z. B. Hund im Schnee" autocomplete="off">
        </label>
        <button class="button primary search-button" type="submit" :disabled="searching || !selectedRoot || !query">
          {{ searching ? 'Suche läuft …' : 'Suchen' }}
        </button>
      </form>

      <div v-if="searched && !results.length" class="empty">Keine aktuellen Treffer gefunden.</div>
      <div v-if="results.length" class="results">
        <a v-for="item in results" :key="item.file_id" class="result-card" :href="fileUrl(item.file_id)" target="_blank" rel="noopener">
          <img :src="previewUrl(item.file_id)" :alt="item.name" loading="lazy" @error="hideBrokenPreview">
          <div class="result-text">
            <strong>{{ item.name }}</strong>
            <span>{{ item.path }}</span>
          </div>
        </a>
      </div>
    </section>

    <footer>Skjalf indiziert nur deine eigenen, lesbaren Dateien in ausgewählten Ordnern.</footer>
  </main>
</template>

<script>
import axios from '@nextcloud/axios'
import { generateUrl } from '@nextcloud/router'

const API = generateUrl('/apps/app_api/proxy/skjalf')

const VALIDATION_MESSAGES = {
  extra_forbidden: 'Dieses Feld wird nicht unterstützt.',
  json_invalid: 'Die Anfrage ist ungültig formatiert.',
  missing: 'Pflichtfeld fehlt.',
  string_too_long: 'Der Text ist zu lang.',
  string_too_short: 'Der Text ist zu kurz.',
  string_type: 'Bitte Text eingeben.',
}

function formatApiErrorDetail(detail) {
  if (typeof detail === 'string' && detail.trim()) return detail

  if (Array.isArray(detail)) {
    const messages = detail.map((issue) => {
      if (typeof issue === 'string') return issue
      if (!issue || typeof issue !== 'object') return ''

      const location = Array.isArray(issue.loc)
        ? issue.loc
          .filter(part => part !== 'body')
          .map((part) => ({ file_id: 'Datei-ID', query: 'Suchbegriff' }[part] || String(part)))
          .join(' → ')
        : ''
      const message = VALIDATION_MESSAGES[issue.type]
        || (typeof issue.msg === 'string' ? issue.msg : '')
      if (!message) return ''
      return location ? `${location}: ${message}` : message
    }).filter(Boolean)

    return messages.length ? messages.join(' · ') : 'Die Anfrage enthält ungültige Angaben.'
  }

  if (detail && typeof detail === 'object' && typeof detail.message === 'string') {
    return detail.message
  }
  return 'Die Anfrage an Skjalf ist fehlgeschlagen.'
}

export default {
  name: 'SkjalfApp',
  data() {
    return {
      roots: [], folders: [], folderPath: '', showBrowser: false,
      selectedRoot: '', query: '', results: [], searched: false,
      busy: false, searching: false, error: '', notice: '',
    }
  },
  mounted() {
    this.refresh()
  },
  methods: {
    async request(method, path, data) {
      try {
        const response = await axios({ method, url: `${API}${path}`, data })
        return response.data || {}
      } catch (error) {
        const detail = error.response && error.response.data && error.response.data.detail
        throw new Error(formatApiErrorDetail(detail))
      }
    },
    async refresh() {
      this.busy = true
      this.error = ''
      this.notice = ''
      try {
        const data = await this.request('get', '/api/roots')
        this.roots = data.roots || []
        if (!this.roots.some(root => root.root_id === this.selectedRoot)) {
          this.selectedRoot = this.roots.length ? this.roots[0].root_id : ''
        }
        if (this.showBrowser) await this.loadFolders()
      } catch (error) {
        this.error = error.message
      } finally {
        this.busy = false
      }
    },
    async loadFolders() {
      try {
        const data = await this.request('get', `/api/folders?path=${encodeURIComponent(this.folderPath)}`)
        this.folders = data.folders || []
      } catch (error) {
        this.error = error.message
      }
    },
    async openFolder(folder) {
      this.folderPath = folder.path
      await this.loadFolders()
    },
    goUp() {
      const parts = this.folderPath.split('/').filter(Boolean)
      parts.pop()
      this.folderPath = parts.join('/')
      this.loadFolders()
    },
    async registerFolder(folder) {
      this.busy = true
      this.error = ''
      this.notice = ''
      try {
        await this.request('post', '/api/roots', { file_id: folder.file_id })
        this.showBrowser = false
        this.notice = 'Ordner ausgewählt. Die Indizierung startet erst auf deinen ausdrücklichen Klick.'
        await this.refresh()
      } catch (error) {
        this.error = error.message
      } finally {
        this.busy = false
      }
    },
    async start(root) {
      await this.rootAction(root, 'index', 'Indizierung wurde gestartet.')
    },
    async pause(root) {
      await this.rootAction(root, 'pause', 'Die Indizierung pausiert nach der aktuellen Datei.')
    },
    async rootAction(root, action, message) {
      this.busy = true
      this.error = ''
      this.notice = ''
      try {
        await this.request('post', `/api/roots/${encodeURIComponent(root.root_id)}/${action}`)
        this.notice = message
        await this.refresh()
      } catch (error) {
        this.error = error.message
      } finally {
        this.busy = false
      }
    },
    async removeRoot(root) {
      if (!window.confirm(`„${root.path}“ aus Skjalf entfernen? Die Originaldateien bleiben erhalten.`)) return
      this.busy = true
      this.error = ''
      try {
        await this.request('delete', `/api/roots/${encodeURIComponent(root.root_id)}`)
        this.notice = 'Ordnerauswahl und zugehöriger Index wurden entfernt.'
        await this.refresh()
      } catch (error) {
        this.error = error.message
      } finally {
        this.busy = false
      }
    },
    async search() {
      this.searching = true
      this.searched = true
      this.results = []
      this.error = ''
      try {
        const data = await this.request('post', `/api/roots/${encodeURIComponent(this.selectedRoot)}/search`, { query: this.query })
        this.results = data.results || []
      } catch (error) {
        this.error = error.message
      } finally {
        this.searching = false
      }
    },
    previewUrl(fileId) {
      return `${generateUrl('/core/preview')}?fileId=${encodeURIComponent(fileId)}&x=480&y=320&a=1`
    },
    fileUrl(fileId) {
      return generateUrl(`/apps/files/files/${encodeURIComponent(fileId)}`)
    },
    hideBrokenPreview(event) {
      event.target.style.visibility = 'hidden'
    },
  },
}
</script>
