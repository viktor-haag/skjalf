const path = require('path')
const { VueLoaderPlugin } = require('vue-loader')

module.exports = {
  mode: 'production',
  entry: {
    'skjalf-main': path.resolve(__dirname, 'ex_app/src/main.js'),
  },
  output: {
    path: path.resolve(__dirname, 'ex_app/js'),
    filename: '[name].js',
    chunkFilename: '[name].js',
    // AppAPI serves the script from its proxy route; relative chunks keep the
    // browser on that same proxy prefix if a future view is split into chunks.
    publicPath: './',
    clean: true,
  },
  resolve: {
    extensions: ['.js', '.vue'],
    alias: { vue: 'vue/dist/vue.esm.js' },
  },
  module: {
    rules: [
      { test: /\.vue$/, loader: 'vue-loader' },
      { test: /\.css$/, use: ['style-loader', 'css-loader'] },
    ],
  },
  plugins: [new VueLoaderPlugin()],
}
