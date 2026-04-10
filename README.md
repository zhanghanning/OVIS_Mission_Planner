# Mission Planner

`mission_planner` 是当前项目的统一任务规划后端，负责两类核心能力：

1. 批处理规划：接收任务包、异步生成分配结果和全局路径结果包。
2. 交互式规划：面向独立前端或内置联调页，提供场景资产读取、机器狗初始化、手选/圈选/语义规划、预览后执行保存等能力。

当前工程已经从“单校园场景 + 内嵌页面联调”为主，演进为“多场景资产 + 前后端分离 + 电力设施语义规划”的后端服务。仓库内已并行维护校园场景 `NCEPU` 和风电场场景 `wind_power_station`，并支持变电站、风机、光伏等电力资产的语义解析和地图图层返回。

## 当前能力

- 提供 FastAPI 后端，对外暴露批处理规划接口和交互式规划接口。
- 支持多场景资产读取，场景名直接来自 `data/assets/<scene_name>/` 目录名，区分大小写。
- 支持交互式“先预览、后执行保存”的规划工作流。
- 支持运行时机器狗初始化配置，数量不固定，位置由导航点动态绑定。
- 支持手选任务点、圈选范围、语义任务三种交互式建任务方式。
- 支持电力语义目标，包括 `power_infrastructure`、`substation`、`wind_turbine`、`solar_generator`。
- 支持规则解析、OpenAI 兼容接口、本地 Transformers 三种语义解析模式。
- 支持原生 C++ 规划核心的可选加速，构建失败时自动回退到 Python 实现。
- 支持 Docker 部署、Cloudflare Tunnel 暴露和 ROS2 bridge 联动。

## 系统组成

### 批处理规划链路

- `POST /api/planner/jobs`
  接收远程任务包地址，后台下载、校验、解压并执行规划。
- `GET /api/planner/jobs/{job_id}`
  查询任务状态、进度、结果地址。
- `GET /api/planner/jobs/{job_id}/result`
  下载 `planner_result.zip`。

批处理结果包当前会输出：

- `planner_manifest.json`
- `task_assignment.json`
- `global_paths.json`
- `planner_summary.json`
- `formation_plan.json`
- `ros_dispatch.json`

### 交互式规划链路

- `GET /api/planner/interactive/assets`
  返回当前场景地图资产、导航点、路径网、机器人资产、模板和场景列表。
- `GET /api/planner/interactive/robots/config`
- `PUT /api/planner/interactive/robots/config`
  管理机器狗初始化配置。
- `POST /api/planner/interactive/plans/manual`
- `POST /api/planner/interactive/plans/polygon`
- `POST /api/planner/interactive/plans/semantic`
  创建规划预览。
- `GET /api/planner/interactive/plans/{plan_id}`
  读取预览或已保存结果。
- `POST /api/planner/interactive/plans/{plan_id}/execute`
  执行并保存规划结果到 `data/outputs/<plan_id>/`。
- `GET /api/planner/interactive/plans/{plan_id}/viewer`
  跳转到内置联调 viewer 回放指定计划。
- `GET /api/planner/interactive/console`
  内置联调页面，仅作调试参考，不是正式前端。
- `GET /api/planner/interactive/plans`
  返回 `data/outputs/` 下所有已保存的 `interactive_plan_*` 目录名。

## 项目结构

```text
mission_planner/
├── app/
│   ├── api/                    # FastAPI 路由
│   ├── core/                   # 配置、日志、全局设置
│   ├── models/                 # Pydantic 请求/响应模型
│   ├── planners/               # Python 规划器与原生规划器适配
│   │   └── native/             # C++ 原生规划核心
│   ├── services/               # 资产、任务、语义、结果、机器人配置服务
│   └── static/                 # 内置联调页面
├── config/                     # planner.yaml 等静态配置
├── data/
│   ├── assets/                 # 多场景运行时资产
│   │   ├── NCEPU/
│   │   ├── wind_power_station/
│   │   └── <scene_name>/
│   ├── configs/
│   │   └── robot_initialization/  # 每个场景的机器狗初始化配置
│   ├── jobs/                   # 批处理任务状态
│   ├── packages/               # 下载/缓存的任务包
│   ├── results/                # 批处理结果
│   ├── outputs/                # 交互式执行后的规划结果
│   ├── models/                 # 语义模型与微调产物
│   └── training/               # 语义训练数据
├── deploy/
│   └── docker/                 # Docker Compose、Dockerfile、启动脚本
├── docs/                       # 接口与架构文档
├── logs/                       # 运行日志
├── scripts/                    # 开发、同步、训练、构建脚本
├── tests/                      # 当前测试
├── requirements.txt
├── requirements-llm-local.txt
└── README.md
```

## 场景与资产约定

场景资产统一放在：

```text
data/assets/<scene_name>/
```

每个场景通常包含：

```text
<scene_name>/
├── world/              # scene.glb、map_data.json、manifest.json 等世界资产
├── mission/            # nav_points_enriched.geojson、route_graph.json、semantic_catalog.json
├── fleet/              # robot_registry.json
├── planning/
│   ├── assets/         # planner_problem、nav_to_nav_shortest_paths、semantic_target_sets 等
│   ├── examples/       # 示例任务
│   └── runs/           # 场景内规划运行产物，可选
└── source/             # 上游原始素材，可选
```

当前仓库内已存在：

- `NCEPU`
- `wind_power_station`

注意事项：

- `scene` 参数直接使用目录名，区分大小写。
- 交互式资产接口会返回 `available_scenes` 和 `current_scene`，前端应以返回值为准。
- `wind_power_station` 场景中，导航点和语义目录已经包含电力资产信息，前端可以依赖 `power_asset_ref`、`power_asset_name`、`power_asset_category`。
- 地图区域图层已支持 `power:substation`，用于变电站区域渲染。

## 场景与语义能力

当前语义解析能力分为两层：

- 规则解析
  支持模板匹配、建筑名称匹配、编号楼匹配、独立导航点匹配、电力资产名称匹配、类别匹配。
- LLM 解析
  在规则解析未命中时，可使用 OpenAI 兼容接口或本地 Transformers 模型做补充解析。

当前已覆盖的目标类型包括：

- 校园类：教学楼、宿舍、食堂、体育设施、服务建筑、综合建筑
- 电力类：电力设施、变电站、风机、光伏

LLM 候选目录中会包含：

- `target_sets`
- `nav_points[].building_name`
- `nav_points[].building_category`
- `nav_points[].power_asset_name`
- `nav_points[].power_asset_category`

## 快速开始

### 环境要求

- 推荐 Python `3.11`
- 本地开发需要 `venv`
- 若希望启用原生规划加速，需要本机可用的 `g++`
- 若希望启用本地语义模型或微调训练，需要额外安装 `requirements-llm-local.txt` 中的依赖，并具备可用 CUDA 环境

### 本地开发

```bash
cd /home/techno/mission_planner
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

启动开发服务：

```bash
cd /home/techno/mission_planner
./scripts/run_dev.sh
```

或直接运行：

```bash
cd /home/techno/mission_planner
source .venv/bin/activate
uvicorn app.main:app --host 0.0.0.0 --port 8081 --reload
```

健康检查：

```bash
curl http://127.0.0.1:8081/health
```

打开内置联调页面：

```text
http://127.0.0.1:8081/api/planner/interactive/console
```

### 原生规划核心

构建原生 C++ 规划核心：

```bash
cd /home/techno/mission_planner
./scripts/build_planner_native.sh
```

说明：

- 成功时会输出 `.so` 文件路径
- Docker 启动时也会自动尝试构建
- 构建失败不会阻断服务启动，系统会回退到 Python 规划实现

## Docker 部署

### 1. 准备环境变量

```bash
cd /home/techno/mission_planner/deploy/docker
cp .env.example .env
```

至少需要根据本机修改：

- `MISSION_PLANNER_PATH`
- `PUBLIC_BASE_URL`
- `BACKEND_CORS_ALLOW_ORIGINS`
- `LOCAL_MODEL_ROOT`
- `ROS2_WS_PATH`

### 2. 检查默认场景

当前代码会根据 `MISSION_ASSET_ROOT_DIR` 决定默认场景。容器环境下，这个变量在 `deploy/docker/docker-compose.yml` 中写死到服务环境变量里，而不是从 `.env.example` 读取。

如果你要使用当前仓库中的真实场景目录，请确认 `planner-api-lite` 和 `planner-api-geo` 的：

```yaml
MISSION_ASSET_ROOT_DIR: /workspace/mission_planner/data/assets/NCEPU
```

或改成：

```yaml
MISSION_ASSET_ROOT_DIR: /workspace/mission_planner/data/assets/wind_power_station
```

否则默认场景可能会指向不存在或历史遗留的目录名。

### 3. 启动服务

启动主后端：

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

可选服务：

- `planner-api-geo`
  带地理依赖的后端镜像，宿主机端口 `8082`
- `public-tunnel-quick`
  Cloudflare Quick Tunnel
- `public-tunnel-managed`
  Cloudflare Managed Tunnel
- `ros-bridge`
  挂载 ROS2 工作区并运行 `path_dispatcher_node`

### 4. 容器启动行为

`deploy/docker/start_planner_backend.sh` 会在容器启动时：

1. 尝试构建原生规划核心
2. 构建失败时打印日志并回退到 Python 规划器
3. 启动 `uvicorn app.main:app --host 0.0.0.0 --port 8081`

## 配置项

应用主要通过环境变量控制，核心配置在：

```text
deploy/docker/.env
```

常用变量：

- `PUBLIC_BASE_URL`
  用于批处理结果回调和结果下载地址拼接
- `BACKEND_CORS_ALLOW_ORIGINS`
  正式前端的允许来源
- `SEMANTIC_LLM_ENABLED`
  是否启用语义模型
- `SEMANTIC_LLM_PROVIDER`
  `disabled`、`openai_compatible`、`local_transformers`
- `SEMANTIC_LLM_BASE_URL`
- `SEMANTIC_LLM_API_KEY`
- `SEMANTIC_LLM_MODEL`
- `SEMANTIC_LLM_LOCAL_MODEL_PATH`
- `SEMANTIC_LLM_LOCAL_ADAPTER_PATH`
- `SEMANTIC_LLM_LOCAL_DEVICE`
- `SEMANTIC_LLM_LOCAL_LOAD_IN_4BIT`
- `ROS2_WS_PATH`

语义提供方说明：

- `disabled`
  仅使用规则解析
- `openai_compatible`
  使用 OpenAI 兼容接口做语义补充解析
- `local_transformers`
  使用本地模型和可选 LoRA Adapter 做语义补充解析

## 接口速览

### 基础接口

- `GET /health`

### 批处理接口

- `POST /api/planner/jobs`
- `GET /api/planner/jobs/{job_id}`
- `GET /api/planner/jobs/{job_id}/result`

`POST /api/planner/jobs` 请求体示例：

```json
{
  "mission_id": "mission_demo_001",
  "package_url": "https://example.com/mission_package.zip",
  "callback_url": "https://example.com/callback",
  "planner_type": "multi_robot_global",
  "package_sha256": "optional",
  "auth_token": "optional"
}
```

### 交互式接口

- `GET /api/planner/interactive/assets`
- `GET /api/planner/interactive/semantic/provider-status`
- `GET /api/planner/interactive/robots/config`
- `PUT /api/planner/interactive/robots/config`
- `GET /api/planner/interactive/console`
- `POST /api/planner/interactive/plans/manual`
- `POST /api/planner/interactive/plans/polygon`
- `POST /api/planner/interactive/plans/semantic`
- `GET /api/planner/interactive/plans`
- `GET /api/planner/interactive/plans/{plan_id}`
- `POST /api/planner/interactive/plans/{plan_id}/execute`
- `GET /api/planner/interactive/plans/{plan_id}/viewer`

交互式规划标准流程：

1. 读取 `assets`
2. 读取或保存 `robots/config`
3. 创建手选、圈选或语义规划预览
4. 如需展示历史记录，可先请求 `GET /api/planner/interactive/plans` 获取已保存 `plan_id` 列表
5. 查看 `plan_id` 对应预览结果或已保存结果
6. 调用 `execute` 保存到 `data/outputs/<plan_id>/`
7. 如需联调回放，可调用 `viewer`

## 常用脚本

### 开发与运行

- `scripts/run_dev.sh`
  本地虚拟环境启动脚本
- `scripts/build_planner_native.sh`
  编译原生规划核心

### 资产同步

- `scripts/sync_runtime_assets.sh`
  将外部资产目录同步到 `mission_planner/data/assets/<scene_name>/`
- `scripts/normalize_asset_paths.py`
  规范化同步后资产里的相对路径
- `scripts/sync_sim_staging_assets.py`
  生成/更新面向仿真的规划资产和 staging 信息

建议显式传入源目录和目标目录，不要依赖脚本里的历史默认值。例如：

```bash
cd /home/techno/mission_planner
./scripts/sync_runtime_assets.sh /home/techno/NCEPU_OSM_Info /home/techno/mission_planner/data/assets/NCEPU
./scripts/sync_runtime_assets.sh /home/techno/WindPowerStation_OSM_Info /home/techno/mission_planner/data/assets/wind_power_station
```

### 语义数据与训练

- `scripts/generate_semantic_sft_dataset.py`
  生成语义 SFT 训练/评估数据
- `scripts/train_semantic_sft.py`
  基于 QLoRA 执行语义解析微调

如果要运行本地模型或训练脚本，先安装：

```bash
pip install -r requirements-llm-local.txt
```

## 数据与产物

默认本地目录：

- `data/assets/<scene_name>/`
  场景运行资产
- `data/configs/robot_initialization/<scene>.json`
  场景级机器狗初始化配置
- `data/jobs/`
  批处理任务状态
- `data/packages/`
  下载/缓存的任务包
- `data/results/<job_id>/`
  批处理结果目录
- `data/outputs/<plan_id>/`
  交互式执行后的规划结果
- `data/models/semantic_sft/`
  语义微调输出
- `data/training/semantic_sft/`
  语义训练数据

交互式规划执行后，至少会保存：

- `data/outputs/<plan_id>/request.json`
- `data/outputs/<plan_id>/plan_result.json`

## 测试与验证

当前仓库已包含原生规划器一致性测试：

```bash
cd /home/techno/mission_planner
source .venv/bin/activate
python -m unittest tests.test_formal_multi_robot_native
```

该测试会：

1. 先调用 `scripts/build_planner_native.sh`
2. 检查原生规划器是否可用
3. 对比公共规划接口与 Python 回退实现的一致性

## 相关文档

- `docs/frontend_api_contract.md`
  正式前端对接接口契约
- `docs/frontend_backend_split_architecture.md`
  前后端分离架构与职责边界
- `docs/public_access_for_frontend.md`
  前端访问后端的公网/局域网暴露说明
- `docs/Cyberdog_GLB_Sim_Integration_Plan.md`
  仿真与 GLB 集成说明
- `docs/semantic_finetune_plan.md`
  语义微调方案说明
