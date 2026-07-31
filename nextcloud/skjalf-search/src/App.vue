<template>
  <div id="skjalf-search-app">
    <SearchView />
  </div>
</template>

<script>
import SearchView from './views/SearchView.vue'

export default {
  name: 'SkjalfSearchApp',
  components: {
    SearchView,
  },
}
</script>

<style>
#skjalf-search-app {
  padding: 10px;
}
</style>
