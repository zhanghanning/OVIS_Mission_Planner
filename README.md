# Mission Planner

`mission_planner` 是当前唯一保留的任务规划后端根目录。它负责批处理任务规划、交互式规划、语义任务解析，以及与三机协同规划结果相关的资产读取、结果落盘和对外 API 暴露。

原先分散在 `OSM2World_docs/deploy` 的 Docker 部署文件，以及 `mission_stack/.env` 的运行时环境变量，现已统一并入本项目。后续部署、启动、联调都只以 `mission_planner` 为入口。

## 项目能力

- 接收规划任务并生成结果包
- 提供交互式规划接口和调试控制台
- 支持手选任务点、框选区域、语义任务三种规划入口
- 支持多场景资产读取，包括校园与风电场场景
- 读取任务点、路网、机器人注册信息，以及建筑/电力资产语义数据
- 支持变电站、风机、光伏等电力设施的语义解析与规划
- 预留本地模型直载与 OpenAI 兼容接口两类语义解析后端
- 支持 Docker 化部署、Cloudflare Tunnel 暴露和 ROS2 bridge 联动

## 目录总览

```text
mission_planner/
├── app/
│   ├── api/                # FastAPI 路由
│   ├── core/               # 配置与日志
│   ├── models/             # 请求/响应 schema
│   ├── planners/           # 多机规划与分配算法
│   ├── services/           # 任务、结果、资产、语义服务
│   └── static/             # 内置调试页面
├── config/                 # planner.yaml 等配置
├── data/
│   ├── assets/
│   │   ├── NCEPU/          # 校园场景资产
│   │   ├── wind_power_station/ # 风电场场景资产
│   │   └── <scene_name>/   # 其他并行场景资产目录
│   ├── jobs/               # 批处理任务输入
│   ├── packages/           # 上传的任务包
│   ├── results/            # 规划结果包
│   ├── outputs/            # 交互式计划执行后保存的结果
│   ├── local_plans/        # 旧版交互式结果目录，现仅兼容历史数据
│   ├── models/             # 语义模型与适配器
│   └── training/           # 训练数据
├── deploy/
│   └── docker/             # 统一部署入口
│       ├── .env
│       ├── .env.example
│       ├── docker-compose.yml
│       ├── Dockerfile.planner-lite
│       ├── Dockerfile.planner-geo
│       ├── Dockerfile.ros-bridge-galactic
│       ├── requirements-geo.txt
│       └── ros_entrypoint.sh
├── docs/                   # 对接与架构文档
├── logs/
├── scripts/                # 本地开发与资产同步脚本
├── tests/
├── requirements.txt
├── requirements-llm-local.txt
└── README.md
```

新增目录的规划原则是：

- 现有业务代码目录保持不动
- 所有部署相关文件统一收口到 `deploy/docker/`
- 运行环境变量只保留一份，放在 `deploy/docker/.env`
- 后续不再依赖 `OSM2World_docs` 或 `mission_stack`

## 关键接口

- `GET /health`
- `GET /api/planner/interactive/console`
- `GET /api/planner/interactive/assets`
- `GET /api/planner/interactive/semantic/provider-status`
- `GET /api/planner/interactive/robots/config`
- `PUT /api/planner/interactive/robots/config`
- `POST /api/planner/interactive/plans/manual`
- `POST /api/planner/interactive/plans/polygon`
- `POST /api/planner/interactive/plans/semantic`
- `GET /api/planner/interactive/plans/{plan_id}`
- `POST /api/planner/interactive/plans/{plan_id}/execute`
- `GET /api/planner/interactive/plans/{plan_id}/viewer`

说明：

- `GET /api/planner/interactive/console` 仅用于算法联调，不是正式前端页面
- 三类交互式规划接口现在只生成预览，不会自动落盘
- 只有调用执行接口后，结果才会写入 `data/outputs/<plan_id>/`
- 场景资产按 `data/assets/<scene_name>/` 组织，`scene` 取值直接来自目录名，区分大小写
- 当前仓库已包含 `NCEPU` 和 `wind_power_station` 两套并行场景资产

## 本地开发

```bash
cd /home/techno/mission_planner
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8081 --reload
```

也可以直接使用现成脚本：

```bash
cd /home/techno/mission_planner
./scripts/run_dev.sh
```

健康检查：

```bash
curl http://127.0.0.1:8081/health
```

## Docker 部署

当前推荐的统一入口：

```bash
cd /home/techno/mission_planner/deploy/docker
docker-compose --env-file .env up -d planner-api-lite
```

重建并启动：

```bash
cd /home/techno/mission_planner/deploy/docker
docker-compose --env-file .env up --build -d planner-api-lite
```

查看日志：

```bash
docker logs -f planner-api-lite
```

如果你的环境安装的是 Docker Compose v2 插件，也可以把上面的 `docker-compose` 替换成 `docker compose`。

如果你习惯使用快捷脚本，也可以直接运行：

```bash
~/run_backend.sh
```

它现在会直接指向 `mission_planner/deploy/docker` 和新的 `.env`。

可选服务：

- `planner-api-geo`: 带地理依赖的后端镜像，监听 `8082`
- `ros-bridge`: 挂载 `ROS2_WS_PATH`，用于和 ROS2 Galactic 工作区联动
- `public-tunnel-quick`: Cloudflare Quick Tunnel
- `public-tunnel-managed`: Cloudflare Managed Tunnel

## 环境变量

统一编辑：

```text
/home/techno/mission_planner/deploy/docker/.env
```

最关键的变量有：

- `MISSION_PLANNER_PATH`: 本机项目绝对路径
- `PUBLIC_BASE_URL`: 前端实际访问的后端地址
- `BACKEND_CORS_ALLOW_ORIGINS`: 允许的前端源
- `LOCAL_MODEL_ROOT`: 本地模型根目录，会挂载到容器的 `/workspace/models`
- `SEMANTIC_LLM_*`: 语义模型启用方式、本地模型路径或 OpenAI 兼容接口配置
- `ROS2_WS_PATH`: ROS2 工作区路径

如果只想本地规则解析或关闭模型能力，可将：

- `SEMANTIC_LLM_ENABLED=false`
- `SEMANTIC_LLM_PROVIDER=disabled`

如果要启用 OpenAI 兼容接口，可将：

- `SEMANTIC_LLM_ENABLED=true`
- `SEMANTIC_LLM_PROVIDER=openai_compatible`
- `SEMANTIC_LLM_BASE_URL=...`
- `SEMANTIC_LLM_API_KEY=...`
- `SEMANTIC_LLM_MODEL=...`

## 数据与产物

默认数据落点：

- 资产目录：`data/assets/<scene_name>/`
- 批处理任务：`data/jobs`
- 任务包缓存：`data/packages`
- 批处理结果：`data/results`
- 交互式执行结果：`data/outputs`

交互式计划在点击执行后会保存：

- `data/outputs/<plan_id>/request.json`
- `data/outputs/<plan_id>/plan_result.json`

## 相关文档

- `docs/frontend_api_contract.md`
- `docs/frontend_backend_split_architecture.md`
- `docs/public_access_for_frontend.md`
- `docs/Cyberdog_GLB_Sim_Integration_Plan.md`
