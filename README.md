# quant-backtest-docker

A 股日线策略回测平台的 **Docker 一键部署版**：FastAPI + React/antd + backtesting.py，支持参数优化、样本外切分，持仓的策略体检和每日买卖建议，以及**页面一键在线更新**（CI 构建镜像 → GHCR → 服务器拉取替换，支持回滚）。

这是从 `quant-backtest` 复制出来的独立项目，原项目不会被覆盖。

## 一键启动

前置：安装 Docker Desktop（或 Docker Engine + Compose 插件）。

```bash
cp .env.example .env
# 可选：编辑 .env，填入 TUSHARE_TOKEN
./scripts/docker-up.sh
```

打开：

```text
http://127.0.0.1:8000
```

也可以直接：

```bash
docker compose up -d --build
```

第一次构建会下载 Node/Python 依赖，通常需要几分钟；之后重建会复用缓存。

## 新 ECS / 新机器一键部署

把代码传到服务器后，执行一条命令即可（会检查/安装 Docker、生成 `.env`、构建、启动并等待健康检查）：

```bash
./scripts/deploy-ecs.sh
```

全自动、指定端口和 Tushare token：

```bash
./scripts/deploy-ecs.sh -y --port 8000 --token 你的token
```

国内网络建议加上镜像源参数（构建时的 npm / pip 走国内镜像）：

```bash
./scripts/deploy-ecs.sh -y --cn-mirror
```

其他参数见 `./scripts/deploy-ecs.sh --help`。脚本可重复执行：已存在的 `.env` 不会被覆盖，只更新显式传入的项。

部署完成后记得在云厂商安全组放行端口，并且**不要直接把 8000 暴露到公网**（服务没有登录鉴权），建议只放行自己的 IP。

## 数据在新机器上怎么办

镜像不含数据：行情缓存（`/app/data`）和回测报告（`/app/reports`）都在命名卷里。新机器上是空的，**首次回测会按需拉取并缓存**，不影响使用，只是第一次慢一些。

如果想把现有数据一起搬过去：

```bash
# 旧机器导出（文件属主是当前用户，不需要 sudo）
docker run --rm -v quant-backtest_quant_data:/data ghcr.io/chentaoyu/quant-backtest-docker:latest \
  tar czf - -C /data . > quant_data.tgz
scp quant_data.tgz user@ecs:/opt/quant-backtest/

# 新机器导入：先执行一次 deploy 让卷创建出来，再解包
docker run --rm -i -v quant-backtest_quant_data:/data ghcr.io/chentaoyu/quant-backtest-docker:latest \
  tar xzf - -C /data < quant_data.tgz
docker compose restart web
```

报告卷同理，把卷名换成 `quant-backtest_quant_reports`。

## 我的持仓：每日买卖建议

页面顶部「我的持仓」：

1. **导入**：从券商 App / Excel 复制持仓表格直接粘贴（识别“证券代码 / 股票余额 / 参考成本价”等表头），或上传 CSV；无表头时按 `代码,股数,成本价[,买入日期]`。同一只股票多行会按加权成本合并。
2. **策略体检**（导入后自动跑，每只约 5–10 秒，30 天有效）：近 5 年滚动验证（训练 3 年 / 测试 1 年），6 个策略里样本外夏普最高且为正的作为这只股票的主策略；都不行就标记“无有效策略”。
3. **今日建议**（每天收盘后刷新）：止损/止盈 > 主策略今日信号 > 持有 / 已离场；并给出**明日收盘触发价**（如“收盘 ≤ 45.24 触发买入”）和 6 策略多空共识。点行打开 K 线详情。

持仓与体检结果保存在 `data/holdings.json`、`data/checkups.json`（Docker 下在 `quant_data` 卷里）。

行情缓存每只股票一份（`{source}_{代码}_qfq.csv`），过了收盘时间自动增量补拉；检测到除权会全量重拉。旧版按区间命名的缓存首次读取时自动迁移。

## 自选股与模拟仓

- **自选股**：粘贴代码批量添加（可分组），自动体检。每只可设策略：自动（体检主策略）/ 指定策略 + 体检参数 / 指定策略 + 手动参数。表格显示今日信号、持有状态、明日触发价、最近一次信号，可筛选“只看今日有信号”。
- **模拟仓**：只从创建当天往后跑。
  - 策略跟单：在自选股点“加入模拟”，给这只股票分配资金，策略参数在加入时冻结；信号次日开盘成交。停止跟单后次日开盘清仓，资金回到可用现金。
  - 手动下单：下一交易日开盘价成交，可撤单。
  - A 股规则：100 股整数倍、T+1、佣金万 2.5（最低 5 元）+ 卖出印花税 0.05%、开盘涨停买不进 / 跌停卖不出则顺延。
  - 净值曲线对比沪深 300；“策略成绩单”按策略统计已平仓跟单的胜率、盈亏比，并对照体检时的样本外夏普。
  - 成交不落盘，每次按“账户配置 + 行情”重放计算；行情用前复权价，除权后历史成交价会随复权调整。

数据文件：`data/watchlist.json`、`data/sim_accounts.json`。

## 环境变量

`.env` 由 Compose 自动读取：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `TUSHARE_TOKEN` | 空 | Tushare Pro token；不填则自动回退 akshare |
| `QUANT_DATA_SOURCE` | `auto` | `auto` / `tushare` / `akshare` |
| `PORT` | `8000` | 宿主机端口；被占用时改成 `8001` |
| `NODE_IMAGE` | `node:22-alpine` | 前端构建基础镜像，可换镜像源 |
| `PYTHON_IMAGE` | `python:3.13-slim-bookworm` | 运行基础镜像，可换镜像源 |
| `NPM_REGISTRY` | `https://registry.npmjs.org` | 构建前端时的 npm 源，国内可换 npmmirror |
| `PIP_INDEX_URL` | `https://pypi.org/simple` | 构建镜像时的 pip 源，国内可换清华源 |
| `UPDATE_TOKEN` | 自动生成 | 在线更新令牌；**留空 = 免鉴权**（仅本地用）。ECS 由 deploy-ecs.sh 生成 |
| `UPDATE_MODE` | `none` | `host-updater` = 启用宿主机在线更新服务；本地开发保持 `none` |
| `IMAGE_TAG` | `latest` | 使用的 GHCR 镜像 tag（在线更新器会自动改写） |
| `GITHUB_TOKEN` | 空 | 可选：GitHub API 令牌，提高版本检测限额（匿名 60 次/小时，一般够用） |

不填 token 也能启动，但首次拉取股票列表和行情会更慢，且 akshare 接口偶尔不稳定。

## 架构

```text
浏览器
  │ :8000
  ▼
┌─────────────────────────────────────────┐
│ 单容器 quant-backtest                     │
│                                         │
│  FastAPI (web.app:app)                   │
│    ├─ /api/*       回测/持仓/历史 API     │
│    ├─ /reports/*   Bokeh HTML 报告        │
│    └─ /             React 静态产物         │
│                                         │
│  /app/data      ← quant_data 命名卷       │
│  /app/reports   ← quant_reports 命名卷    │
│  /app/update-channel ← bind mount        │
└──────────────────┬──────────────────────┘
                   │ 写更新请求 / 读状态、日志
                   ▼
┌─────────────────────────────────────────┐
│ 宿主机 systemd updater（quant-updater）  │
│  git 同步 → 改 IMAGE_TAG → compose pull  │
│  → up -d 替换容器（不健康自动回滚）        │
└─────────────────────────────────────────┘

镜像来源（本地与 CI 共用同一份多阶段 Dockerfile：
Node 22 + pnpm 构建前端 → Python 3.13 运行）：
· 打 v* tag 触发 GitHub Actions → ghcr.io/chentaoyu/quant-backtest-docker:{版本,latest}
· push main → 同上 :main、:sha-<短hash>
· 本地 docker compose build → 打同名 tag
```

设计取舍：

- **单容器**：前端是纯静态文件，由 FastAPI 直接托管，不需要 Nginx、不需要处理 CORS；一键启动最简单。
- **多阶段构建**：Node 和 pnpm 只存在于构建阶段，运行镜像不含 node_modules。
- **非 root 运行**：容器内使用 `app` 用户；数据和报告写入命名卷。
- **数据和报告持久化**：`docker compose down` 不会删数据；`down -v` 才会删除卷。
- **单 worker**：回测执行有进程内锁，默认一个 uvicorn worker，避免同一批次并发写报告。
- **在线更新零侵入容器**：容器保持非 root、不挂 docker.sock、不含 git；更新由宿主机 systemd 服务执行，通过 bind mount 的 `update-channel` 目录交换请求与状态。

## 常用命令

```bash
# 查看状态
docker compose ps

# 看日志
docker compose logs -f web

# 停止（保留数据）
docker compose down

# 重新构建并启动（本地改动后）
docker compose up -d --build

# 更新到最新发布版（页面右上角徽章也可一键更新）
git pull && docker compose pull web && docker compose up -d

# 删除容器 + 数据卷（会清空行情缓存和报告）
docker compose down -v

# 健康检查
curl http://127.0.0.1:8000/api/health
```

## 在线版本更新

页面右上角的版本徽章：查看当前版本 / 最新版本，一键更新到最新 Release，支持回滚。

### 前提（一次性设置）

1. **发版打 tag**：`git tag v0.3.0 && git push origin v0.3.0` → GitHub Actions 自动构建多架构镜像（amd64/arm64）推到 GHCR（`ghcr.io/chentaoyu/quant-backtest-docker:v0.3.0` 与 `:latest`），并创建 GitHub Release。之后每次发版同样打 tag。
2. **GHCR 包设为 public**：首次 CI 推送后，打开[包设置页](https://github.com/users/chentaoyu/packages/container/quant-backtest-docker/settings) → Danger Zone → Change visibility → Public（ECS 匿名拉取才不需要凭证；保持 private 则需在服务器上用 PAT 执行 `docker login ghcr.io`）。
3. **ECS 装好 updater**：`./scripts/deploy-ecs.sh` 自动完成（生成 UPDATE_TOKEN、安装 systemd path unit）。

### 更新流程

```text
浏览器点击「更新到 vX.Y.Z」
   │  POST /api/update（X-Update-Token 令牌校验）
   ▼
FastAPI 写 update-channel/update_request.json
   │
   ▼  systemd path unit 监听到文件出现，触发 host-update.sh
宿主机：git 同步到目标 tag → 改写 .env 的 IMAGE_TAG
   → docker compose pull web（失败即止，容器不动）
   → docker compose up -d --wait（替换容器并等健康检查）
   │
   ▼  新版本起不来时自动回滚：IMAGE_TAG=last_good → pull → up
前端轮询 /api/health，恢复后自动刷新页面
```

### 本地 Mac 也用在线更新（可选）

Mac 没有 systemd，默认走「本地开发模式」（页面只显示手动命令）。想在本机体验和线上完全一样的点击更新，跑一次安装脚本（幂等）：

```bash
./scripts/local-update-setup.sh
```

它会把模式写进 `.env`、固化当前镜像 tag，并安装 launchd WatchPaths 代理（macOS 版的 systemd path unit）监听 `update-channel/`。之后：GitHub 打新 tag → 页面红点 → 点击更新，和 ECS 行为一致。本地默认免令牌（`UPDATE_TOKEN` 留空），点击即更新。

注意：更新器会 `git reset --hard` 到目标 tag，本地有未提交改动时会**自动中止**而不是吞掉它们——先 commit 或 stash 再点更新；更新后仓库处于 detached HEAD（对齐镜像版本），继续开发前 `git checkout main`。

### 说明

- **数据安全**：`quant_data` / `quant_reports` 命名卷不受更新影响。
- **更新令牌**：`.env` 的 `UPDATE_TOKEN`——它保护的不是公开的仓库/镜像，而是"重启你的服务"这个动作（全应用唯一有破坏性的接口）。**留空 = 免鉴权**，适合端口只有自己能访问的本地部署；ECS 等对外可达的部署请保留（deploy-ecs.sh 自动生成），前端首次使用输入一次即记住。
- **回滚**：页面一键回滚到最近一次成功版本（本地旧镜像还在，秒级）；新版本启动失败也会自动回滚。
- **对齐保证**：镜像与 compose/脚本来自同一个 git tag，host-update.sh 更新时会 `git reset` 到目标 tag。
- **任务中断**：更新会重启容器，正在运行的回测/体检任务会被中断，触发前页面有提示。
- **查看日志**：`journalctl -u quant-updater.service -f`；完整执行日志在 `update-channel/update.log`（页面也会展示尾部）。
- **本地开发**（`UPDATE_MODE=none`）：页面只读版本信息，更新入口显示手动命令；想开启点击更新见上面的「本地 Mac 也用在线更新」。
- **首次部署**：CI 镜像不存在时 deploy-ecs.sh 自动回退本地构建；打完第一个 tag 后，线上即可页面更新。

## 数据与报告

- 行情缓存：命名卷 `quant_data` → 容器内 `/app/data`
- 回测报告：命名卷 `quant_reports` → 容器内 `/app/reports`
- 页面里的「报告」「最近批次」直接读取容器内文件，不需要额外挂载。

如果需要把报告导出到宿主机：

```bash
mkdir -p export/reports
docker compose cp web:/app/reports/. ./export/reports/
```

## 开发模式

只构建 Docker 镜像（与 CI 同名，构建完可直接 `docker compose up -d`）：

```bash
docker compose build web
```

本地不用 Docker 时：

```bash
uv sync

# 新项目没有提交 web/static，先构建一次前端
cd web/frontend
pnpm install
pnpm build
cd ../..

./scripts/start_web.sh
```

## 目录

```text
Dockerfile             多阶段构建（Node 前端 + Python 运行时）
docker-compose.yml     端口、环境变量、命名卷、健康检查
.dockerignore          排除 .env/data/reports/update-channel 等
scripts/docker-up.sh   本地一键启动脚本
scripts/deploy-ecs.sh  新机器/ECS 一键部署（Docker 检查 + 构建 + 健康检查）
scripts/host-update.sh 宿主机在线更新执行器（git 同步 + compose pull + up）
scripts/quant-updater.path/.service  systemd 触发器（监听更新请求文件）
backtest_engine.py     回测执行 / 网格优化 / 滚动验证窗口
data_loader.py         行情获取、缓存、校验
stock_list.py          A 股股票列表
signals.py             最新信号 / 明日触发价
holdings.py            持仓存储与导入
advisor.py             策略体检 / 持仓与自选建议 / K 线数据
watchlist.py           自选股与策略设置
sim.py                 模拟仓（跟单 + 手动单重放）
tests/                 pytest（uv run pytest）
strategies/            六个只做多策略
web/app.py             FastAPI 入口
web/update_api.py      在线更新 API（版本检测 / 触发 / 状态 / 回滚）
web/frontend/          React + antd + ECharts 源码
.github/workflows/release.yml  CI：构建镜像推 GHCR + 创建 Release
```

## 常见问题

### 端口被占用

```bash
PORT=8001 docker compose up -d --build
# 打开 http://127.0.0.1:8001
```

### 页面显示 Tushare 未配置

`.env` 的 `TUSHARE_TOKEN` 为空，或 token 无效。检查：

```bash
docker compose exec web printenv TUSHARE_TOKEN | wc -c
```

不要把这行命令的输出贴到公开地方。

### Docker Hub 拉取基础镜像超时

可以改用 ECR Public 镜像：

```bash
NODE_IMAGE=public.ecr.aws/docker/library/node:22-alpine \
PYTHON_IMAGE=public.ecr.aws/docker/library/python:3.13-slim-bookworm \
docker compose up -d --build
```

或者在 `.env` 里取消这两行的注释，再重新构建。

### 构建时 pnpm 下载失败

是网络问题，重试：

```bash
docker compose build --no-cache web
```

### 在线更新失败 / 页面提示更新卡住

看宿主机更新器的执行日志：

```bash
journalctl -u quant-updater.service -f     # systemd 触发与服务日志
tail -100 update-channel/update.log        # git/pull/up 的完整输出
```

常见原因：GHCR 包还是 private（拉取 401/404，见「在线版本更新」的前提 2）、服务器到 ghcr.io 不通。**更新失败不影响正在运行的服务**（拉取失败即止，容器不动）；新版本起不来会自动回滚到上一版本。手动回滚：改 `.env` 的 `IMAGE_TAG` 为上一版本后执行 `docker compose pull web && docker compose up -d`。

### 页面版本显示 dev 或 main-xxxxx

正常现象：`dev` 是本地 `docker compose build` 的镜像（未传版本 build args）；`main-xxxxx` 是 main 分支的 CI 构建。只有 `vX.Y.Z`（tag 构建）会参与「是否最新」的判断，第一次在线更新到正式版后就统一了。

### 报告在宿主机看不到

报告在命名卷里，不在项目目录；这是为了避免容器内 UID 和宿主机文件权限冲突。用页面查看，或按上面的 `docker compose cp` 导出。

## 安全说明

- 默认把端口映射到宿主机，**没有登录鉴权**，适合本机/内网使用；不要直接暴露到公网。
- `.env` 已在 `.gitignore` 和 `.dockerignore` 中，token 不会打进镜像。
- 容器以非 root 用户运行；数据卷只包含缓存、报告和股票列表。
- 回测结果只用于研究，不构成投资建议。
