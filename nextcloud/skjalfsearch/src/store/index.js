import axios from '@nextcloud/axios'
import { generateUrl } from '@nextcloud/router'
import { defineStore } from 'pinia'

export const useSkjalfStore = defineStore('skjalfsearch', {
  state: () => ({
    query: '',
    results: [],
    loading: false,
    error: null,
    folders: [],
    embeddingStatus: {},
  }),

  actions: {
    async search(query, limit = 20, threshold = 0.5) {
      this.loading = true
      this.error = null
      try {
        const response = await axios.post(
          generateUrl('/apps/skjalfsearch/api/v1/search'),
          { query, limit, threshold }
        )
        this.results = response.data.results || []
      } catch (e) {
        this.error = e.response?.data?.error || 'Search failed'
      } finally {
        this.loading = false
      }
    },

    async getFolders() {
      try {
        const response = await axios.get(
          generateUrl('/apps/skjalfsearch/api/v1/folders')
        )
        this.folders = response.data.folders || []
      } catch (e) {
        this.error = e.response?.data?.error || 'Failed to load folders'
      }
    },

    async registerFolder(folderPath) {
      try {
        const response = await axios.post(
          generateUrl('/apps/skjalfsearch/api/v1/folders'),
          { path: folderPath }
        )
        return response.data.status === 'registered'
      } catch (e) {
        this.error = e.response?.data?.error || 'Failed to register folder'
        return false
      }
    },

    async embedFile(fileId) {
      try {
        const response = await axios.post(
          generateUrl('/apps/skjalfsearch/api/v1/embed/file/{fileId}'),
          { fileId }
        )
        return response.data
      } catch (e) {
        this.error = e.response?.data?.error || 'Failed to embed file'
        return null
      }
    },

    async getEmbeddingStatus(fileId) {
      try {
        const response = await axios.get(
          generateUrl('/apps/skjalfsearch/api/v1/status/{fileId}'),
          { params: { fileId } }
        )
        this.embeddingStatus[fileId] = response.data
        return response.data
      } catch (e) {
        return { status: 'unknown' }
      }
    },
  },
})
