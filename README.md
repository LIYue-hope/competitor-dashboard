## 后续更新安排

- [x] 将上周预览中的综合热度榜固定为上一周数据，不随日期每日更新变动（已实现，2026-09-02）
- [ ] 构建服务器实现页面中点击刷新能够抓取网页中的最新数据而不是拿到仓库中的最性能数据
- [ ] 调整llm输出每日总结的提示词、尽可能避免规则文本的输出

第 1 条已由本周改动落地：`weekly_digest.json` 按自然周成稿即冻结、同周不再重写；
默认板块改为「上周总览」并记忆选择。详见下文「数据文件」「CI 工作流」与看板板块说明。

# 竞品看板

游戏行业竞品资讯监测看板。GitHub Actions 每天定时跑一批采集脚本，把结果写成 `data/*.json`
提交回仓库，再构建 Vue3 静态站部署到 GitHub Pages。整个系统没有后端、没有数据库，
数据文件本身就是"数据库"，页面只读 JSON。

- 仓库：`git@github.com:LIYue-hope/competitor-dashboard.git`
- 线上：GitHub Pages，Vite `base` 为 `/competitor-dashboard/`
  （`https://<user>.github.io/competitor-dashboard/`）

## 看板包含什么

左侧四个互斥板块（侧栏显示条目计数，默认打开「上周总览」；所选板块记在
`localStorage`，刷新后停留在上次打开的板块）：

- **上周总览** — 上一自然周（北京时间周一到周日）的跨源综述 + 综合热度榜 Top 10
- **新游监测** — TapTap / 好游快爆 / 九游 / 游资网 四个二级 Tab，看新游预约与开测排期
- **热门动态** — 按发行商分组（腾讯 / 网易 / 米哈游 / 鹰角、库洛、叠纸 / 其他），
  看各游戏官方近 7 天的版本前瞻、更新公告、新活动、赛事等动态
- **游戏资讯** — 3DMGame / 游侠网 / 游民星空 / GameLook / 游资网 五个来源，
  每个来源内部再分「新闻 / 新闻总结 / 评测（测评）」子 Tab；
  GameLook 与游资网站点没有评测，只有前两个

顶栏有深浅色切换（跟随系统，可手动覆盖，记在 `localStorage`），以及各源里最新的采集时间戳。
吸顶栏和 Tab 栏用半透明磨砂底；不支持 `backdrop-filter` 的浏览器回退为不透明底色。

## 目录结构

```
scripts/                 数据采集层（Python 3.11+，仅 requests + beautifulsoup4）
  crawl_*.py             一个数据源一个脚本，互相独立
  crawl_16p.py           游资网新游开测表（16p.com / gameres gamecenter 接口）
  crawl_gameres.py       游资网资讯
  crawl_taptap_rank.py   TapTap 热门 / 预约 / 新品榜
  summarize_news.py      五个资讯源的每日新闻总结
  summarize_week.py      上周跨源热度榜 + 周报综述
  utils.py               HTTP 封装（重试）、大厂关键词、挂机/搬砖关键词
  game_name.py           从新闻标题提取游戏名（纯函数，资讯爬虫共用）
  heat_utils.py          热度计算纯函数（量级解析、对数归一、上周日期窗口）
  test_*.py              标准库 unittest 单测，不走网络
data/                    采集产物 JSON，展示层直接读取
web/                     展示层（Vue 3.4 + Vite 5）
  src/App.vue            顶栏 + 左侧板块 + 数据加载
  src/components/        各板块面板
  src/composables/       吸顶 Tab 等复用逻辑
.github/workflows/       定时采集 → 提交数据 → 构建部署 Pages
```

## 数据文件

| 文件 | 产出脚本 | 顶层结构 |
| --- | --- | --- |
| `taptap_upcoming.json` | `crawl_taptap.py` | 游戏对象扁平数组 |
| `taptap_rank.json` | `crawl_taptap_rank.py` | `{crawled_at, lists:{hot, reserve, new}}` |
| `haoyoukuaibao_upcoming.json` | `crawl_haoyoukuaibao.py` | `{crawled_at, days:[{date, date_label, games}]}` |
| `9game_upcoming.json` | `crawl_9game.py` | 同上（按日期分组） |
| `16p_upcoming.json` | `crawl_16p.py` | 同上（游资网新游，7 天朝未来） |
| `hot_games_dynamics.json` | `crawl_hot_games.py` | `{crawled_at, window_days, publishers:[{key, label, games}]}` |
| `<源>_news.json` / `<源>_reviews.json` | `crawl_3dmgame/youxia/gamersky/gamelook/gameres.py` | `{crawled_at, window_days, items:[{title, url, game_name, published_at, summary}]}` |
| `<源>_digest.json` | `summarize_news.py` | `{generated_at, source, window_days, top_n, items:[{date, digest, top_games, ...}]}` |
| `weekly_digest.json` | `summarize_week.py` | `{week_start, week_end, digest, heat_formula, hot_ranking:[...]}` |
| `community_history.json` | `summarize_week.py` | TapTap 关注/评价/讨论存量快照，用于算周内增量 |

`weekly_digest.json` 按自然周「每周生成一期并冻结」：只在每周结束后的第一次运行
按当时的爬取数据成稿，之后该周文件不随每日更新重写（榜单与条数保持成稿时的样子，
等下一自然周第一次运行再进入新一轮）；`community_history.json` 的社区快照不冻结，
每天照常追加一张，供跨周算周内新增。

资讯源 key：`3dmgame` / `youxia` / `gamersky` / `gamelook` / `gameres`。
GameLook 与游资网没有评测文件。

## 数据源与采集约定

各采集脚本互相独立，一个源一个脚本，但共用同一套写文件约定：

- **优先走站点接口，没有接口才解析 HTML。** 已确认可用的接口：
  TapTap 榜单 `webapiv2/app-top/v2/hits`、
  游民星空 `db2.gamersky.com/LabelJsonpAjax.aspx`（JSONP）、
  GameLook WordPress REST API `wp-json/wp/v2/posts`、
  游资网资讯 `gameres.com/api/v1/portal/articles`（cursor 翻页，`page_size` 上限 50）、
  游资网新游 `gameres.com/api/public/v1/gamecenter/test_game`（与 16p.com 同一后端）、
  腾讯内容中心 `apps.game.qq.com/cmc/cross`、
  米哈游官网 CMS `content_v2_user/getContentList`。
  TapTap 新游列表、好游快爆、九游、3DMGame、游侠网走服务端渲染 HTML + BeautifulSoup，
  全项目不引入 playwright。
- **滚动窗口而非全量覆盖。** 资讯类：新闻 10 天、评测 15 天（评测出稿频率低，窗口更长）；
  热门游戏动态与好游快爆/九游排期：7 天；游资网新游是 `[today, today+6]` 朝未来 7 天。
  每次运行先读旧文件，翻页抓新数据，某一页所有条目都早于窗口起点就停止翻页，
  然后按 `url` 去重合并（同 url 以最新抓到的为准），过滤掉出窗的条目，按发布时间降序写回。
- **0 条拒绝写。** 网络失败或解析出 0 条时不用空结果覆盖旧文件，保留上一次的数据，
  宁可数据不更新也不丢数据。
- **编码要显式指定。** 好游快爆、游侠网、3DMGame 等站点响应头不带 charset，
  requests 会误判 ISO-8859-1；梦幻西游官网是 gb18030；GameLook 接口带 UTF-8 BOM，
  必须 `json.loads(resp.content.decode("utf-8-sig"))`。这些都是实测坑，改动时别删。
- **游戏名统一从标题的书名号提取**（`scripts/game_name.py`），来源自带的标签只做兜底：
  实测 3DMGame 的标签有相当比例是频道名/平台名（「游戏新闻」「Steam」），直接当游戏名会污染统计。
  游资网 tags 是频道分类而不是游戏名，不做兜底。

单源的具体坑都写在各脚本头部 docstring 里，改脚本前先读。几条容易踩的：

- 游侠网游戏频道滞后约 1 天，当天内容由全站资讯补齐，可能夹带少量非游戏资讯。
- 游民星空手游频道自 2026-07-31 起停更，10 天窗口内为 0 条，不是抓取错误。
- 游资网资讯只收「推荐 / 原创 / 产品 / 厂商 / 市场」五类（按 `tid` 白名单，
  「市场」父类 tid=13 不会出现在条目 tags 里，必须展开成子标签）。
- 游资网新游必须传 `type_range=2`（国内游戏），且 `testtype` 精确等于「上线」
  （`startswith` 会把「上线试玩」带进来）；不要再用 `game.area == "CN"` 二次筛。
- TapTap 详情页需逐个请求补预约量级。

## LLM 总结与热度榜

`summarize_news.py` 给五个资讯源各生成「每日一段综述 + Top 15 游戏各自一段动态」，
`summarize_week.py` 生成上周综述与跨源热度榜。两者共用同一套模型调用约定：

- 主用 + 备用两组环境变量，每组三个齐了才算可用；一组都没配就完整走规则生成，不报错：

  ```
  DIGEST_LLM_BASE_URL / DIGEST_LLM_API_KEY / DIGEST_LLM_MODEL
  DIGEST_LLM_FALLBACK_BASE_URL / DIGEST_LLM_FALLBACK_API_KEY / DIGEST_LLM_FALLBACK_MODEL
  ```

  `BASE_URL` 形如 `https://xxx/v1`，不含 `/chat/completions`。CI 里主用智谱
  GLM-4.7-Flash（永久免费，并发 1），备用讯飞星火 Lite（官方标注「支持免费使用」，
  OpenAI 兼容接口 `https://spark-api-open.xf-yun.com/v1`，模型名 `lite`）。
  千帆 3.5 / Speed / Lite / Tiny 已退役，`ernie-4.5-turbo-128k` 只是新用户试用；
  混元-lite 已从现行价目下架。key 走仓库 secrets（`DIGEST_LLM_API_KEY` /
  `DIGEST_LLM_FALLBACK_API_KEY`，必须是控制台 **Lite 版本页** 的 APIPassword，
  不是 APPID / APIKey，也不能拿 Pro/Ultra 的密码打 `lite`，否则会 11200
  AppIdNoAuthError）。secret 里如果整段贴了 `Bearer xxx`，脚本会剥掉前缀，避免变成
  `Bearer Bearer xxx`。
- 智谱免费档并发 1、共享算力高峰会连着 429。同一条请求停在原地等窗口，比立刻换备用
  更划算：429 固定等 15 秒再打同一条，最多 4 次（含首次）；响应头或 body 带
  `Retry-After` 时优先听服务端的，但下限仍是 15 秒。成功回包后也隔 15 秒才发下一条。
  仍失败才换备用；两家都不行就走规则文本。星火 Lite 不支持 system 角色，指令并进 user。
- 模型输出要过 `verify_digest` 数字校验：任一数字/日期在输入里找不到就换下一家，
  全失败退回规则文本——编造具体数字是这类摘要任务最主要的翻车方式。
  日期允许只差前导零（素材里的 `08` 与模型写的 `8` 视为同一个数）。
  综述经常被模型拆成两三行，解析时从「综述：」起笔一直拼到第一条「游戏名｜动态」为止，
  避免只收第一行被字数下限误杀。`content` 为空时才回退 `reasoning_content`，
  有正文时绝不拿推理草稿凑数。
- 按日期维度用 `input_hash` 复用旧结果，只对新增/变化的日期调模型。
  综述短于 90 字的旧条目不进缓存，改了字数口径后会被冲掉。
  命令行可传来源 key 只跑一部分，例如 `python scripts/summarize_news.py youxia`，
  不传则五个都跑。
- 热度公式（写在 `weekly_digest.json` 的 `heat_formula` 字段里，随数据一起展示）：
  资讯量 30% + 跨源覆盖 15% + 预约量 18% + 社区（周内新增关注/评价/讨论）15% +
  TapTap 榜单名次 12% + 官方动态 7% + 评测讨论 3%；各项先对数归一（资讯满格 200 条），
  缺测维度计 0、不倒扣，满分 100。窗口是北京时间「上一个自然周的周一到周日」。
  社区维度必须有窗口开始前的快照才能做差，刚上线只有一周数据时该维记 0，
  不会把历史存量当成本周增量。

## 展示层

Vue 3.4 + Vite 5，无状态管理库、无 UI 框架，组件直接 `fetch` 对应 JSON。

- 数据路径统一为 `${import.meta.env.BASE_URL}data/xxx.json`。`web/vite.config.js` 里的
  自定义 `repo-data` 插件负责让这条路径在两种环境都成立：dev 时拦截 `/data/*.json`
  从仓库根目录 `data/` 读盘，build 时在 `closeBundle` 把 `data/` 整个拷进 `dist/data/`。
  所以采集脚本只管往仓库根 `data/` 写，不用关心 `web/` 结构。
- 各数据源 `Promise.allSettled` 独立加载，一个文件挂掉只影响它自己那个 Tab。
- 「更新」按钮（`RefreshButton.vue`）**不触发采集**，只从 GitHub raw 拉 main 分支上已有的
  `data/*.json`（最多重试 3 次，空数组/空对象视为异常不覆盖页面）。成功后 2 小时冷却、
  失败 30 分钟冷却，状态存在 localStorage 的 `refresh:<storageKey>` 下。
  真正重新抓取要去 Actions 手动跑一次 workflow，再点按钮取结果。
- 组件分工：`NewGamesPanel`（四个新游来源 + 按日期分组）、`GameCard`（单张新游卡片）、
  `HotGamesPanel`（发行商 Tab + 动态类型子 Tab）、`GameNewsPanel`（资讯源通用面板，
  日期区间筛选 + 当日热点 + 评分徽章 + 每日总结）、`WeeklyDigestPanel`（综述 + 热度榜）、
  `useStickyTabs`（吸顶 Tab 高度实测与锚点）。

## 本地开发

采集脚本（Python 3.11+，CI 用 3.11）：

```bash
pip install -r scripts/requirements.txt
python scripts/crawl_taptap.py            # 单独跑某个源
python scripts/crawl_16p.py               # 游资网新游
python scripts/summarize_news.py youxia   # 只给一个来源生成总结，不传参则五个都跑
python scripts/summarize_week.py          # 上周热度榜与综述
```

单测用标准库 unittest，不需要 pytest，也不走网络：

```bash
python -m unittest discover -s scripts -p "test_*.py" -v
```

测试文件里的中文一律写成 `\uXXXX` 转义，是为了避免 Windows 控制台代码页把源码搞坏，
新增用例请沿用这个写法。

展示层：

```bash
cd web
npm install
npm run dev      # 开发（数据从仓库根 data/ 实时读盘）
npm run build    # 产物在 web/dist，含拷贝进去的 data/
```

## CI 工作流

`.github/workflows/crawl.yml`，每天 UTC 00:00 定时触发，也可手动 `workflow_dispatch`。
两个 job：`crawl`（采集 + 提交）→ `deploy`（构建 + 部署 Pages）。几个关键设计：

- 每个采集步骤都是 `continue-on-error: true` 并带 `id`，避免"一个源改版导致当天全都不更新"。
  判定失败必须用 `steps.<id>.outcome`（`continue-on-error` 会把 `conclusion` 改写成 success）。
- 失败信息先由一个"哨兵"步骤逐个打成 `::error::` 注解，然后先提交推送已成功的数据，
  最后才 `exit 1` 让整个 run 变红——顺序颠倒会导致数据推不上去。
- `deploy` 用 `if: always() && ...` 解除失败拦截（部分成功也要更新页面），
  并额外加 `concurrency: pages-deploy` 串行化，避免手动重跑 deploy 时产生两份同名
  `github-pages` artifact 让 `deploy-pages@v4` 报歧义错误。
- `deploy` 的 checkout 必须显式 `ref: ${{ github.ref_name }}`，否则拿到的是采集推送前的
  commit，页面永远落后一次采集。
- `.gitattributes` 声明 `data/*.json merge=keep-crawled`，workflow 里显式注册
  `merge.keep-crawled.driver 'cp %B %A'`，让数据文件冲突时以本次采集结果为准；
  rebase 兜底用 `git checkout --theirs`（rebase 语义下 `--theirs` 才是正在重放的本次采集）。
- 仓库需要配置两个 secrets：`DIGEST_LLM_API_KEY`（智谱）和
  `DIGEST_LLM_FALLBACK_API_KEY`（讯飞星火 Lite 的 APIPassword）。没配也能跑，
  摘要会完整走规则生成。

采集顺序：各源爬虫（含游资网资讯 / 新游）→ 每日 digest → TapTap 榜单 → 上周总结 → 提交 `data/*.json`。
「上周总结」每天都会随流程跑，但同一自然周只在每周结束后的第一次运行成稿并冻结：
之后新闻窗口继续回填也不再重写该周，等下一自然周才生成新一期。

## 已知限制

- HTML 解析类爬虫（TapTap 新游、好游快爆、九游、3DMGame、游侠网）的选择器绑定当前页面
  DOM 结构，站点前端改版会导致解析失败；此时脚本会拒绝写空数据，页面停留在旧数据，
  需要用浏览器开发者工具核对真实 DOM 后调整选择器。
- TapTap 新游的预约量级只在详情页出现，脚本会对每个游戏 ID 额外发一次请求，
  请求量随新游数量线性增长，注意抓取频率。
- TapTap 榜单接口只认 `type_name=hot/reserve/sell/new`（`played`/`download` 返回 400），
  且硬限 `limit=10`，名次靠 `from` 翻页拼出来。接口返回里没有 app_id 的节点（榜单标题等）
  必须丢掉，否则会把真实名次整体后移。
- 米哈游官网 CMS 的 `appSn` / `iChanId` 是官网前端 JS 里的硬编码值，官网改版即失效，
  失效时降级回米哈游公告接口。
- 页面的「更新」按钮只能拉到 GitHub 上已有的数据，无法在浏览器里触发采集；
  想立刻刷新数据要去 Actions 手动跑一次 workflow。
- 智谱免费档 RPM / 并发都很紧，CI 里靠 15 秒间隔硬扛；高峰时仍可能整批 429 后降级到
  星火或规则文本，页面永远有内容，只是文案会从模型综述变成规则拼接。


