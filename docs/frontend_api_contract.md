# Mission Planner 前端对接接口文档

这份文档面向正式的 `Vite + Vue3` 前端，描述当前已经在后端落地的接口契约，以及目前新增但尚未在正式前端完成对接的能力。

当前正式架构：

- 本机只运行 `mission_planner` FastAPI 后端
- 另一台设备运行 `Vite + Vue3` 前端
- 前端直接通过 HTTP 调用本机后端
- 当前仓库里的 `GET /api/planner/interactive/console` 仅用于算法联调和行为参考，不作为正式前端页面

## 1. 本轮后端已落地的关键变更

- 规划流程已经改为“先预览，后执行保存”
- 手动规划、圈选规划、语义规划都不会在创建时自动落盘
- 新增 `POST /api/planner/interactive/plans/{plan_id}/execute`，只有点击执行后才会保存
- 三类规划结果统一保存到 `data/outputs/<plan_id>/`
- 资产读取和规划创建都已支持 `scene` 场景参数
- 资产接口会返回 `current_scene`、`available_scenes`、`scene_name`
- 规划结果会返回 `scene_name` 和 `persistence` 元数据，前端可据此显示当前场景和保存状态
- 机器人初始化不再固定为 3 台，也不再固定在北门、南门、教12B
- 新增运行时机器人初始化配置接口，支持用户输入机器狗数量并在地图已有节点上放置机器狗
- 机器人初始化配置会以 JSON 保存到本地，并在系统启动后自动读取
- 规划阶段实际使用当前保存的机器人初始化配置；若仍有未放置机器人，规划接口会直接拒绝

## 2. 基本信息

- 后端基地址示例：`http://192.168.1.100:8081`
- 开发阶段 Vite 地址示例：`http://192.168.1.101:5173`
- 数据格式：`application/json`
- 坐标系：
  - 局部平面坐标：`local_x`, `local_z`
  - 单位：米
  - `x` 朝东，`z` 朝北
- 地理坐标：`lat`, `lon`，WGS84

建议前端内部统一使用 `local_x / local_z` 做地图渲染。

## 3. 接口总览

- `GET /health`
- `GET /api/planner/interactive/assets`
- `GET /api/planner/interactive/semantic/provider-status`
- `GET /api/planner/interactive/robots/config`
- `PUT /api/planner/interactive/robots/config`
- `POST /api/planner/interactive/plans/manual`
- `POST /api/planner/interactive/plans/polygon`
- `POST /api/planner/interactive/plans/semantic`
- `GET /api/planner/interactive/plans/{plan_id}`
- `POST /api/planner/interactive/plans/{plan_id}/execute`

## 4. 健康检查

```http
GET /health
```

示例响应：

```json
{
  "status": "ok",
  "deployment_mode": "backend_service",
  "frontend_mode": "separate_vite_vue3",
  "cors_allow_origins": ["http://192.168.1.101:5173"]
}
```

用途：

- 前端启动时检查后端是否可用
- 可读取当前允许的跨域来源，辅助定位联调问题

## 5. 读取规划资产

```http
GET /api/planner/interactive/assets
GET /api/planner/interactive/assets?scene=ncepu
```

用途：

- 加载建筑、用地、路网底图
- 加载任务点
- 加载机器人起点和 home
- 加载任务模板和语义示例
- 加载当前可切换的场景列表

前端应在应用启动后优先请求这一项。

核心响应字段示例：

```json
{
  "scene_name": "ncepu",
  "current_scene": "ncepu",
  "available_scenes": ["ncepu"],
  "package_id": "mission_planner_assets",
  "counts": {},
  "projection_origin": {},
  "world_boundary": {
    "min_x": 0.0,
    "max_x": 100.0,
    "min_z": 0.0,
    "max_z": 100.0
  },
  "map_areas": [],
  "nav_points": [],
  "route_segments": [],
  "robots": [
    {
      "index": 1,
      "planning_slot_id": "slot_01",
      "hardware_id": "cyberdog2_01",
      "display_name": "机器狗 1",
      "color": "#d94841",
      "placed": true,
      "anchor_nav_point_id": "NP_001",
      "anchor_nav_point_name": "北门",
      "start_nav_point_id": "NP_001",
      "home_nav_point_id": "NP_001",
      "start_pose": {
        "resolved_local_position_m": {
          "x": 404.546,
          "z": 267.565
        }
      },
      "home_pose": {
        "resolved_local_position_m": {
          "x": 404.546,
          "z": 267.565
        }
      }
    }
  ],
  "robot_config": {
    "scene_name": "ncepu",
    "robot_count": 3,
    "all_robots_placed": true,
    "placed_robot_ids": ["slot_01", "slot_02", "slot_03"],
    "unplaced_robot_ids": [],
    "config_path": "data/configs/robot_initialization/ncepu.json",
    "source": "file",
    "updated_at": "2026-04-02T09:00:00+00:00",
    "robots": []
  },
  "available_templates": [],
  "semantic_examples": [],
  "plan_api": {
    "assets": "/api/planner/interactive/assets",
    "robot_config": "/api/planner/interactive/robots/config",
    "manual": "/api/planner/interactive/plans/manual",
    "polygon": "/api/planner/interactive/plans/polygon",
    "semantic": "/api/planner/interactive/plans/semantic",
    "execute_template": "/api/planner/interactive/plans/{plan_id}/execute"
  }
}
```

前端重点处理：

- 默认不传 `scene` 时，后端会返回默认场景
- 场景切换时重新请求 `GET /api/planner/interactive/assets?scene=<scene_name>`
- 场景栏展示项应直接使用 `available_scenes`
- 地图、图例、任务点、机器人起终点都应随着场景切换整体刷新
- `robots` 为当前已保存的运行时机器人初始化结果，数量和位置都不再固定
- `robot_config` 用于驱动“机器狗初始化”面板，包括配置文件路径、是否还有未放置机器人等

异常约定：

- 传入未知 `scene` 时返回 `400`
- 场景目录不存在时返回 `404`

## 6. 语义能力状态

```http
GET /api/planner/interactive/semantic/provider-status
```

用途：

- 判断语义规划能力是否启用
- 判断当前后端使用的语义提供方
- 决定前端是否展示语义规划开关、提示文案或降级提示

核心响应字段：

- `enabled`
- `provider`
- `dependency_status`
- `openai_compatible.configured`
- `local_transformers.configured`
- `local_transformers.cuda_available`

## 7. 机器人初始化配置

### 7.1 读取当前配置

```http
GET /api/planner/interactive/robots/config
GET /api/planner/interactive/robots/config?scene=ncepu
```

用途：

- 页面启动时读取当前场景的机器狗数量、编号和初始节点
- 在用户点击“从配置文件加载”时恢复本地 JSON 中已保存的配置

核心响应字段：

- `scene_name`
- `robot_count`
- `all_robots_placed`
- `placed_robot_ids`
- `unplaced_robot_ids`
- `config_path`
- `updated_at`
- `robots[].index`
- `robots[].planning_slot_id`
- `robots[].hardware_id`
- `robots[].display_name`
- `robots[].color`
- `robots[].anchor_nav_point_id`

### 7.2 保存当前配置

```http
PUT /api/planner/interactive/robots/config
```

请求体：

```json
{
  "scene": "ncepu",
  "robot_count": 4,
  "robots": [
    {"anchor_nav_point_id": "NP_001"},
    {"anchor_nav_point_id": "NP_049"},
    {"anchor_nav_point_id": "NP_058"},
    {"anchor_nav_point_id": "NP_001"}
  ]
}
```

说明：

- `robot_count` 不再固定为 3
- `robots` 按顺序对应 `slot_01`、`slot_02`、`slot_03` ...
- 同一节点允许重复放置多台机器狗
- 若某台机器狗尚未放置，可传 `null` 或不传 `anchor_nav_point_id`
- 保存后会写入 `data/configs/robot_initialization/<scene>.json`
- 系统后续加载资产和执行规划时都会读取这份已保存配置

## 8. 规划工作流

当前正确流程如下：

1. 前端先调用 `GET /api/planner/interactive/assets` 加载当前场景资产
2. 用户在“机器狗初始化”面板读取或编辑机器人配置
3. 前端通过 `PUT /api/planner/interactive/robots/config` 保存当前场景的机器人数量与初始节点
4. 只有当 `robot_config.all_robots_placed=true` 时，才允许用户发起规划
5. 用户通过手选、圈选或语义输入发起规划创建
6. 后端返回“预览计划”，此时 `persistence.saved=false`
7. 前端渲染路线、已选点、圈选区域和保存状态
8. 用户点击“执行计划”按钮
9. 前端调用 `POST /api/planner/interactive/plans/{plan_id}/execute`
10. 后端将结果写入 `data/outputs/<plan_id>/`，并返回 `persistence.saved=true`

重要说明：

- 创建规划接口只负责生成预览，不会保存
- 未执行的预览计划本质上是临时结果，前端不要把它当成已落盘任务
- 若机器人初始化配置中仍有未放置机器人，三类规划接口都会返回 `400`

## 9. 三种建任务方式

### 9.1 手选任务点

```http
POST /api/planner/interactive/plans/manual
```

请求体：

```json
{
  "nav_point_ids": ["NP_049", "NP_050"],
  "mission_label": "manual_pick",
  "notes": "frontend manual selection",
  "scene": "ncepu"
}
```

说明：

- 该接口只生成规划预览
- `scene` 为新增字段，前端当前场景切换后必须带上
- `nav_point_ids` 会在后端做去重和合法性校验

### 9.2 圈选范围

```http
POST /api/planner/interactive/plans/polygon
```

请求体：

```json
{
  "coordinate_mode": "local",
  "mission_label": "polygon_pick",
  "scene": "ncepu",
  "vertices": [
    {"x": 10.0, "z": 20.0},
    {"x": 30.0, "z": 20.0},
    {"x": 30.0, "z": 50.0},
    {"x": 10.0, "z": 50.0}
  ]
}
```

说明：

- 该接口只生成规划预览
- `coordinate_mode` 目前支持 `local` 和 `latlon`
- `scene` 为新增字段，前端当前场景切换后必须带上
- 当圈选范围内没有可规划任务点时，后端返回 `400`

### 9.3 语义任务

```http
POST /api/planner/interactive/plans/semantic
```

请求体：

```json
{
  "query": "巡检二号餐厅",
  "use_llm": true,
  "scene": "ncepu"
}
```

说明：

- 该接口只生成规划预览
- `scene` 为新增字段，前端当前场景切换后必须带上
- `use_llm=false` 时可作为规则解析或降级策略的一部分
- 当语义没有解析到任何任务点时，后端返回 `400`

## 10. 规划结果读取与执行

### 10.1 查询规划结果

```http
GET /api/planner/interactive/plans/{plan_id}
```

用途：

- 读取刚创建出来的预览结果
- 读取已执行保存的结果
- 用于页面刷新后的回显或外部链接回放

说明：

- 若 `plan_id` 对应的是未执行的临时预览，前端应尽快引导用户执行保存
- 若计划不存在，后端返回 `404`

### 10.2 执行并保存规划结果

```http
POST /api/planner/interactive/plans/{plan_id}/execute
```

用途：

- 用户确认当前预览计划
- 将 `request.json` 和 `plan_result.json` 保存到 `data/outputs/<plan_id>/`
- 返回带 `persistence.saved=true` 的最新计划结果

保存路径：

- `data/outputs/<plan_id>/request.json`
- `data/outputs/<plan_id>/plan_result.json`

## 11. 规划结果核心字段

三种规划创建接口和执行接口返回的数据结构基本一致，前端至少需要消费以下字段：

```json
{
  "plan_id": "interactive_plan_xxxxx",
  "created_at": "2026-04-02T08:00:00+00:00",
  "scene_name": "ncepu",
  "target_nav_point_ids": ["NP_049", "NP_050"],
  "unassigned_nav_point_ids": [],
  "selection": {
    "resolution_mode": "manual_selection",
    "resolved_nav_point_ids": ["NP_049", "NP_050"],
    "matched_nav_point_ids": ["NP_049", "NP_050"]
  },
  "selected_nav_points": [],
  "unassigned_nav_points": [],
  "robots": [
    {
      "planning_slot_id": "slot_01",
      "color": "#d94841",
      "route_nav_point_ids": ["NP_049"],
      "route_nav_points": [],
      "display_route_local_m": [
        {"x": 10.0, "z": 20.0}
      ],
      "legs": [
        {
          "type": "start_to_nav",
          "polyline_local_m": [
            {"x": 10.0, "z": 20.0}
          ]
        }
      ]
    }
  ],
  "visualization": {
    "bounds_local_m": {
      "min_x": 0.0,
      "max_x": 100.0,
      "min_z": 0.0,
      "max_z": 100.0
    },
    "selected_polygon": [],
    "nav_points": [],
    "robots": []
  },
  "persistence": {
    "output_dir": "data/outputs/interactive_plan_xxxxx",
    "request_path": "data/outputs/interactive_plan_xxxxx/request.json",
    "result_path": "data/outputs/interactive_plan_xxxxx/plan_result.json",
    "saved": false,
    "saved_at": null
  }
}
```

字段说明：

- `scene_name`：该计划所属场景，回显计划前应先切到对应场景
- `selection`：记录规划来源，手选/圈选/语义会不同
- `selected_nav_points`：前端可直接用于高亮已命中的任务点
- `robots[].display_route_local_m`：机器人整条显示路径
- `robots[].legs[].polyline_local_m`：分段路径，适合做更细粒度展示
- `visualization.selected_polygon`：圈选模式下的原始多边形
- `persistence.saved`：当前是否已真正保存
- `persistence.output_dir`：最终输出目录，可用于 UI 提示

## 12. 新增但正式前端尚未对接的重点

以下内容已在后端落地，但需要正式 `Vite + Vue3` 前端补齐：

- 场景栏对接：前端需要基于 `available_scenes` 渲染场景切换栏，而不是写死 `ncepu`
- 场景切换请求：切换场景时需要重新请求 `GET /api/planner/interactive/assets?scene=<scene_name>`
- 场景透传：手选、圈选、语义三类创建请求都必须带当前 `scene`
- 预览与保存解耦：创建规划后不能再默认认为“已经保存”，必须新增“执行计划”按钮调用执行接口
- 保存状态展示：UI 需要消费 `persistence.saved`、`persistence.output_dir`、`persistence.saved_at`
- 计划回显时切场景：如果 `GET /plans/{plan_id}` 返回的 `scene_name` 与当前页面场景不一致，前端应先切换场景再渲染
- 临时预览提示：未执行的计划只是预览，页面上应有明确提示，避免用户误以为结果已落盘
- 机器狗初始化页：正式前端需要新增与路径规划并列的“机器狗初始化”面板
- 机器狗数量输入：正式前端不能再假设机器人固定为 3 台
- 机器狗放置交互：正式前端需要支持用户选中某台机器狗后，再点击地图节点完成放置
- 配置文件读写：正式前端需要接入 `GET/PUT /api/planner/interactive/robots/config`
- 规划前校验：当 `robot_config.all_robots_placed=false` 时，应禁用三类规划入口并给出提示

## 13. 前端工程建议

前端 `.env` 推荐：

```env
VITE_API_BASE_URL=http://192.168.1.100:8081
```

代码里统一：

```ts
const apiBase = import.meta.env.VITE_API_BASE_URL
```

推荐的最小封装：

- `loadAssets(scene?: string)`
- `loadRobotConfig(scene?: string)`
- `saveRobotConfig(payload)`
- `createManualPlan(payload)`
- `createPolygonPlan(payload)`
- `createSemanticPlan(payload)`
- `getPlan(planId)`
- `executePlan(planId)`

参考实现：

- 仓库内调试页已经支持场景切换、预览后执行保存、执行按钮、保存状态提示和机器狗初始化面板
- 如需参考交互逻辑，可查看 `app/static/planning_console.html`
