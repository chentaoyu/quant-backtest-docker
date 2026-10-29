# 基础镜像可通过 --build-arg 替换；国内网络可改用可访问的镜像源。
ARG NODE_IMAGE=node:22-alpine
ARG PYTHON_IMAGE=python:3.13-slim-bookworm

# 前端构建阶段：Node 只用于把 React/antd 源码编译成静态文件，不进入运行镜像。
FROM ${NODE_IMAGE} AS frontend

# 可选：npm 镜像源（国内可用 https://registry.npmmirror.com）
ARG NPM_REGISTRY=https://registry.npmjs.org
ENV npm_config_registry=${NPM_REGISTRY}

WORKDIR /src/web/frontend
# 显式安装指定版本 pnpm：corepack 不走 npm_config_registry，换源时容易卡住。
RUN npm install -g pnpm@11.28.5 \
    && npm cache clean --force

COPY web/frontend/package.json web/frontend/pnpm-lock.yaml web/frontend/pnpm-workspace.yaml ./
# pnpm 11 在非交互环境遇到未审批的构建脚本会直接失败；
# esbuild 的平台二进制由 optionalDependencies 提供，因此这里安全跳过脚本。
RUN pnpm install --frozen-lockfile --ignore-scripts

COPY web/frontend/ ./
RUN pnpm build


# 运行阶段：Python 3.13 + 已构建静态资源，单容器同时提供 API 和页面。
FROM ${PYTHON_IMAGE} AS runtime

# 可选：pip 镜像源（国内可用 https://pypi.tuna.tsinghua.edu.cn/simple）
ARG PIP_INDEX_URL=https://pypi.org/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Shanghai

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装 Python 依赖，利用 Docker layer cache。
# PIP_INDEX_URL 用环境变量传给 build isolation，uv_build 也会走同一个源。
COPY pyproject.toml uv.lock ./
COPY src ./src
RUN PIP_INDEX_URL="${PIP_INDEX_URL}" pip install --upgrade pip \
    && PIP_INDEX_URL="${PIP_INDEX_URL}" pip install .

# 应用代码。
COPY backtest_engine.py data_loader.py stock_list.py run_backtest.py signals.py holdings.py advisor.py watchlist.py sim.py ./
COPY strategies ./strategies
COPY web/__init__.py web/app.py ./web/
COPY --from=frontend /src/web/static ./web/static

# 非 root 运行；data/reports 会挂载到命名卷。
RUN groupadd --system app \
    && useradd --system --gid app --home-dir /app --shell /usr/sbin/nologin app \
    && mkdir -p /app/data /app/reports \
    && chown -R app:app /app

USER app

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)"

CMD ["python", "-m", "uvicorn", "web.app:app", "--host", "0.0.0.0", "--port", "8000"]
