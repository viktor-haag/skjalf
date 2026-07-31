<template>
  <div class="skjalf-search-container">
    <div class="search-header">
      <h2>Skjalf Search</h2>
      <p>Search your Nextcloud images using AI embeddings</p>
    </div>

    <div class="search-box">
      <input
        v-model="query"
        type="text"
        placeholder="Search images..."
        @keyup.enter="handleSearch"
      />
      <button @click="handleSearch" :disabled="loading">
        {{ loading ? 'Searching...' : 'Search' }}
      </button>
    </div>

    <div v-if="error" class="error-message">{{ error }}</div>

    <div v-if="loading" class="loading-indicator">
      <div class="spinner"></div>
    </div>

    <div v-if="results.length > 0" class="results-container">
      <h3>Results ({{ results.length }})</h3>
      <div class="results-grid">
        <div
          v-for="result in results"
          :key="result.file_id"
          class="result-card"
        >
          <img
            :src="thumbnailUrl(result.file_id)"
            :alt="result.file_path"
            class="result-thumbnail"
          />
          <div class="result-info">
            <p class="result-path">{{ result.file_path }}</p>
            <p class="result-similarity">
              Similarity: {{ (result.similarity * 100).toFixed(1) }}%
            </p>
          </div>
        </div>
      </div>
    </div>

    <div v-if="folders.length > 0" class="folders-section">
      <h3>Registered Folders</h3>
      <ul>
        <li v-for="folder in folders" :key="folder" class="folder-item">
          {{ folder }}
        </li>
      </ul>
    </div>
  </div>
</template>

<script>
import { useSkjalfStore } from '../store'

export default {
  name: 'SearchView',
  data() {
    return {
      query: '',
    }
  },
  computed: {
    store() {
      return useSkjalfStore()
    },
    results() {
      return this.store.results
    },
    loading() {
      return this.store.loading
    },
    error() {
      return this.store.error
    },
    folders() {
      return this.store.folders
    },
  },
  mounted() {
    this.store.getFolders()
  },
  methods: {
    async handleSearch() {
      if (!this.query.trim()) return
      await this.store.search(this.query)
    },
    thumbnailUrl(fileId) {
      return OC.generateUrl('/apps/files/thumbnail') + `?fileId=${fileId}&x=200&y=200`
    },
  },
}
</script>

<style scoped>
.skjalf-search-container {
  max-width: 1200px;
  margin: 0 auto;
}

.search-header {
  margin-bottom: 20px;
}

.search-header h2 {
  color: #0082c9;
  margin-bottom: 5px;
}

.search-box {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
}

.search-box input {
  flex: 1;
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
}

.search-box button {
  padding: 10px 20px;
  background-color: #0082c9;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.search-box button:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error-message {
  color: #d00;
  margin-bottom: 10px;
}

.loading-indicator {
  text-align: center;
  padding: 20px;
}

.spinner {
  border: 3px solid #f3f3f3;
  border-top: 3px solid #0082c9;
  border-radius: 50%;
  width: 30px;
  height: 30px;
  animation: spin 1s linear infinite;
  margin: 0 auto;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.results-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 15px;
  margin-top: 15px;
}

.result-card {
  border: 1px solid #ddd;
  border-radius: 8px;
  overflow: hidden;
  transition: transform 0.2s;
}

.result-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
}

.result-thumbnail {
  width: 100%;
  height: 150px;
  object-fit: cover;
}

.result-info {
  padding: 10px;
}

.result-path {
  font-size: 12px;
  color: #666;
  margin: 0 0 5px 0;
  word-break: break-all;
}

.result-similarity {
  font-size: 13px;
  color: #0082c9;
  font-weight: bold;
  margin: 0;
}

.folders-section {
  margin-top: 30px;
  padding-top: 20px;
  border-top: 1px solid #eee;
}

.folder-item {
  padding: 5px 0;
  color: #333;
}
</style>
