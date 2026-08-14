# 竞品看板

游戏行业竞品资讯监测看板。当前实现范围：**TapTap 新游监测**。

三角洲行动版本公告监测、行业资讯监测暂未实现，属于后续规划。

## 架构

- `scripts/` — 数据采集层（Python），定时抓取数据源，输出结构化 JSON 到 `data/`
- `data/` — 采集结果 JSON，供展示层读取
- `web/` — 展示层（Vue3 + Vite），构建产物用于 GitHub Pages
- `.github/workflows/` — GitHub Actions 定时任务：跑采集脚本 → 提交数据 → 部署 Pages

## 本地运行采集脚本

```bash
cd scripts
pip install -r requirements.txt
python crawl_taptap.py
```

采集结果会写入 `data/taptap_upcoming.json`。

## 本地运行展示层

```bash
cd web
npm install
npm run dev
```

## 数据源说明与已知限制

TapTap 新游监测数据来源于 `https://www.taptap.cn/upcoming` 列表页 + 各游戏详情页（`https://www.taptap.cn/app/{id}`）。

- 列表页未发现可直接调用的公开 JSON API（未找到稳定的 `/webapiv2/...` 类接口返回新游列表数据），因此采用 `requests + BeautifulSoup` 直接解析服务端渲染的列表页 HTML。
- 列表页本身不包含"预约量级"字段，该字段需要访问每个游戏的详情页单独抓取，因此脚本会对列表页解析出的每个游戏 ID 发起一次详情页请求，请求量随新游数量线性增长，请留意抓取频率与网站的访问压力。
- 页面 HTML 的 CSS class 命名可能随 TapTap 前端版本更新而变化，脚本中的选择器是基于当前观察到的页面结构编写的**推断值**，如后续解析持续失败，需要用浏览器开发者工具重新核对真实 DOM 结构后调整 `scripts/crawl_taptap.py` 中的选择器。
- 本地开发环境未安装 Python，本次未能实际运行脚本进行端到端验证，仅通过页面抓取结果人工核对了字段来源，实际抓取效果需要在有 Python 环境的机器/CI 上验证。
