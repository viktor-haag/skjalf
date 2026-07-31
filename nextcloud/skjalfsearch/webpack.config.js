const path = require('path')
const webpackConfig = require('@nextcloud/webpack-vue-config')

module.exports = {
  ...webpackConfig,
  entry: {
    app: path.join(__dirname, 'src', 'main.js'),
  },
  output: {
    path: path.join(__dirname, 'js'),
    filename: 'app.js',
  },
}
