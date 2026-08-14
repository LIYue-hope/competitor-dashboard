import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import fs from 'node:fs'
import path from 'node:path'

// 静态资源路径处理方案：
// 项目的采集数据存放在仓库根目录的 data/ 下（供采集脚本写入），而不是
// web/public/ 下。展示层通过 fetch('/data/taptap_upcoming.json') 读取数据，
// 为了让开发调试（vite dev）和生产构建（vite build）都能在这个路径下访问到
// 同一份数据，这里没有让开发者手动复制文件，而是：
//   1. 开发环境：通过下方自定义 middleware 插件，将 /data/*.json 请求
//      代理到仓库根目录的 data/ 目录直接读盘返回。
//   2. 生产构建：通过 vite-plugin-static-copy 风格的简单自定义插件，
//      在 closeBundle 阶段把仓库根目录 data/ 整个拷贝进 dist/data/，
//      使其与其它构建产物一起发布到 GitHub Pages。
// 这样 data/ 目录本身仍然只有一份，采集脚本无需关心 web/ 目录结构。

const repoRoot = fileURLToPath(new URL('..', import.meta.url))
const dataSourceDir = path.join(repoRoot, 'data')

function copyDataDir(destDir) {
  if (!fs.existsSync(dataSourceDir)) return
  fs.mkdirSync(destDir, { recursive: true })
  for (const file of fs.readdirSync(dataSourceDir)) {
    if (!file.endsWith('.json')) continue
    fs.copyFileSync(path.join(dataSourceDir, file), path.join(destDir, file))
  }
}

function repoDataPlugin() {
  return {
    name: 'repo-data-plugin',
    configureServer(server) {
      // 开发环境下拦截 /data/*.json 请求，直接从仓库根目录 data/ 读取
      server.middlewares.use((req, res, next) => {
        if (req.url && req.url.startsWith('/data/') && req.url.endsWith('.json')) {
          const filePath = path.join(dataSourceDir, req.url.replace('/data/', ''))
          if (fs.existsSync(filePath)) {
            res.setHeader('Content-Type', 'application/json; charset=utf-8')
            res.end(fs.readFileSync(filePath, 'utf-8'))
            return
          }
        }
        next()
      })
    },
    closeBundle() {
      // 生产构建结束后，把 data/ 目录拷贝进构建产物 dist/data/
      copyDataDir(path.join(repoRoot, 'web', 'dist', 'data'))
    },
  }
}

export default defineConfig({
  plugins: [vue(), repoDataPlugin()],
  base: './',
})
