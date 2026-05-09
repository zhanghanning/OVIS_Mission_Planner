# Mission Planner 前端对接接口文档

这份文档面向正式的 `Vite + Vue3` 前端，描述当前 `mission_planner` FastAPI 后端的接口契约。

当前定位：

- FastAPI 后端只负责地图资产分发和路径规划计算。
- FastAPI 后端不保存规划结果，不维护任务历史，不保存机器人初始化配置。
- 前端负责在内存中维护当前机器人数量和初始点位。
- 是否保存规划结果、是否下发给机器人，由 SpringCloud 总后台负责。

## 1. 当前后端职责

- 保留地图资产读取接口，供前端渲染底图、路网、任务点和场景列表。
- 保留语义能力状态接口，供前端判断本地或远程语义模型是否可用。
- 保留手选、圈选、语义三种规划接口，直接返回本次计算结果。
- 规划响应继续返回 `ros_task_payloads`，用于总后台转发给 ROS 端 `uran_autotask`。
- `plan_id` 仍会返回，但只表示本次计算结果的临时标识，不表示 FastAPI 已经保存了该计划。

FastAPI 已删除的职责：

- 不再提供 `GET /api/planner/interactive/robots/config`。
- 不再提供 `PUT /api/planner/interactive/robots/config`。
- 不再提供 `GET /api/planner/interactive/plans`。
- 不再提供 `GET /api/planner/interactive/plans/{plan_id}`。
- 不再提供 `POST /api/planner/interactive/plans/{plan_id}/execute`。
- 不再提供 `GET /api/planner/interactive/plans/{plan_id}/viewer`。
- 不再返回 `persistence` 字段。

## 2. 基本信息

- 后端基地址示例：`http://192.168.1.100:8081`
- 开发阶段 Vite 地址示例：`http://192.168.1.101:5173`
- 数据格式：`application/json`
- 局部平面坐标：`local_x`, `local_z`
- 局部坐标单位：米
- 地理坐标：`lat`, `lon`，WGS84

建议前端内部统一使用 `local_x / local_z` 做地图渲染。

## 3. 接口总览

- `GET /health`
- `GET /api/planner/interactive/assets`
- `GET /api/planner/interactive/semantic/provider-status`
- `POST /api/planner/interactive/plans/manual`
- `POST /api/planner/interactive/plans/polygon`
- `POST /api/planner/interactive/plans/semantic`

说明：

- `mission_planner` 对总后台和前端提供的是 HTTP 接口。
- ROS 端接收总后台任务的入口不在 `mission_planner` 内，而在机器狗侧 `uran_autotask`。
- 当前 ROS 端下行入口为 `/uran/core/downlink/task_ctrl`，消息类型为 `uran_msgs/msg/TaskCtrlCmd`。
- `mission_planner` 不生成 `uran_dispatch` 这类 ROS 内部转发包；ROS 下发细节由总后台、`uran_core` 和 `uran_autotask` 处理。

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

- 前端启动时检查后端是否可用。
- 读取当前允许的跨域来源，辅助定位联调问题。

## 5. 读取规划资产

```http
GET /api/planner/interactive/assets
GET /api/planner/interactive/assets?scene=<scene_name>
```

用途：

- 加载建筑、用地、路网底图。
- 加载任务点。
- 加载机器人模板起点和 home 点。
- 加载任务模板和语义示例。
- 加载当前可切换的场景列表。

说明：

- `scene` 取值来自 `data/assets/<scene_name>/` 的目录名，当前仓库内已包含 `NCEPU` 和 `wind_power_station`。
- 场景名区分大小写，前端不应自行假设或转换。
- 该接口不再返回 `robot_config`，机器人实时布局由前端在内存中维护。

核心响应字段示例：

```json
{
  "scene_name": "wind_power_station",
  "current_scene": "wind_power_station",
  "available_scenes": ["NCEPU", "wind_power_station"],
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
      "planning_slot_id": "slot_01",
      "hardware_id": "cyberdog2_01",
      "start_nav_point_id": "NP_001",
      "home_nav_point_id": "NP_001",
      "start_pose": {},
      "home_pose": {},
      "planner_limits": {}
    }
  ],
  "available_templates": [],
  "semantic_examples": [],
  "plan_api": {
    "assets": "/api/planner/interactive/assets",
    "manual": "/api/planner/interactive/plans/manual",
    "polygon": "/api/planner/interactive/plans/polygon",
    "semantic": "/api/planner/interactive/plans/semantic"
  }
}
```

字段补充说明：

- `map_areas[]` 至少包含 `area_id`、`layer_type`、`style_key`、`name`、`tags`、`outer`、`holes`。
- `map_areas[].style_key=power:substation` 表示变电站区域图层，前端应按电力设施图层渲染。
- `nav_points[]` 至少包含 `id`、`name`、`lat`、`lon`、`local_x`、`local_z`、`category`、`semantic_type`。
- `nav_points[]` 还会附带建筑关联字段和电力资产关联字段。
- `robots[]` 是资产模板里的机器人信息，可用于前端初始化默认展示；正式规划时以后端收到的 `robot_config` 为准。
- `available_templates` 为当前场景完整任务模板列表，正式前端可直接消费。
- `semantic_examples` 为模板里的自然语言示例列表，适合填充语义输入提示或快捷短语。

异常约定：

- 传入未知 `scene` 时返回 `400`。
- 场景目录不存在时返回 `404`。

## 6. 语义能力状态

```http
GET /api/planner/interactive/semantic/provider-status
```

用途：

- 判断语义规划能力是否启用。
- 判断当前后端使用的语义提供方。
- 决定前端是否展示语义规划开关、提示文案或降级提示。

核心响应字段：

- `enabled`
- `provider`
- `dependency_status`
- `openai_compatible.configured`
- `local_transformers.configured`
- `local_transformers.cuda_available`

## 7. 机器人配置传入规则

FastAPI 不再保存机器人初始化配置。前端应在内存中维护当前机器人状态，并在每次规划请求中传入 `robot_config`。

`robot_config` 是三类规划接口的必填字段。

最小结构：

```json
{
  "robot_count": 3,
  "robots": [
    {"anchor_nav_point_id": "NP_001"},
    {"anchor_nav_point_id": "NP_049"},
    {"anchor_nav_point_id": "NP_058"}
  ]
}
```

完整结构可选字段：

```json
{
  "robot_count": 3,
  "robots": [
    {
      "planning_slot_id": "slot_01",
      "hardware_id": "cyberdog2_01",
      "display_name": "机器狗 1",
      "color": "#d94841",
      "anchor_nav_point_id": "NP_001"
    }
  ]
}
```

校验规则：

- `robot_count` 必须为 1 到 32。
- `robots` 至少要有 `robot_count` 个元素。
- 每个机器人都必须有 `anchor_nav_point_id`。
- `anchor_nav_point_id` 必须存在于当前 `scene` 的 `nav_points[]` 中。
- 不传 `planning_slot_id` 时，后端按顺序生成 `slot_01`、`slot_02`。
- 不传 `hardware_id` 时，后端按顺序生成 `cyberdog2_01`、`cyberdog2_02`。
- 不传 `display_name` 和 `color` 时，后端会按顺序生成默认值。
- `planning_slot_id` 和 `hardware_id` 不允许重复。

## 8. 规划工作流

当前正确流程如下：

1. 前端调用 `GET /api/planner/interactive/assets` 加载当前场景资产。
2. 前端在内存中维护机器人数量和每台机器狗绑定的起始导航点。
3. 用户通过手选、圈选或语义输入发起规划。
4. 前端把当前内存中的 `robot_config` 放进规划请求体。
5. FastAPI 直接返回本次计算结果和 `ros_task_payloads`。
6. 前端需要保存业务记录时，把规划结果提交给 SpringCloud 总后台。
7. 需要下发机器人时，由 SpringCloud 总后台按 `ros_task_payloads` 转发给 ROS 端。

重要说明：

- 创建规划接口只负责计算，不负责保存。
- 返回的 `plan_id` 只代表本次计算结果，不保证之后还能通过 FastAPI 查询。
- 前端不要再调用历史查询、执行保存或 viewer 跳转接口。

## 9. 三种建任务方式

### 9.1 手选任务点

```http
POST /api/planner/interactive/plans/manual
```

请求体：

```json
{
  "scene": "NCEPU",
  "nav_point_ids": ["NP_049", "NP_050"],
  "mission_label": "manual_pick",
  "notes": "frontend manual selection",
  "robot_config": {
    "robot_count": 2,
    "robots": [
      {"anchor_nav_point_id": "NP_001"},
      {"anchor_nav_point_id": "NP_058"}
    ]
  }
}
```

说明：

- `scene` 为当前场景，前端切换场景后必须带上。
- `nav_point_ids` 会在后端做去重和合法性校验。
- `robot_config` 必填，由前端传入当前机器人状态。

### 9.2 圈选范围

```http
POST /api/planner/interactive/plans/polygon
```

请求体：

```json
{
  "scene": "NCEPU",
  "coordinate_mode": "local",
  "mission_label": "polygon_pick",
  "robot_config": {
    "robot_count": 2,
    "robots": [
      {"anchor_nav_point_id": "NP_001"},
      {"anchor_nav_point_id": "NP_058"}
    ]
  },
  "vertices": [
    {"x": 10.0, "z": 20.0},
    {"x": 30.0, "z": 20.0},
    {"x": 30.0, "z": 50.0},
    {"x": 10.0, "z": 50.0}
  ]
}
```

说明：

- `coordinate_mode` 目前支持 `local` 和 `latlon`。
- `robot_config` 必填，由前端传入当前机器人状态。
- 当圈选范围内没有可规划任务点时，后端返回 `400`。

### 9.3 语义任务

```http
POST /api/planner/interactive/plans/semantic
```

请求体：

```json
{
  "scene": "wind_power_station",
  "query": "巡检升压站和附近风机",
  "use_llm": true,
  "robot_config": {
    "robot_count": 3,
    "robots": [
      {"anchor_nav_point_id": "NP_035"},
      {"anchor_nav_point_id": "NP_036"},
      {"anchor_nav_point_id": "NP_037"}
    ]
  }
}
```

说明：

- `robot_config` 必填，由前端传入当前机器人状态。
- `use_llm=false` 时可作为规则解析或降级策略的一部分。
- 规则解析除校园建筑外，还支持电力相关语义类别和资产别名匹配。
- 当语义没有解析到任何任务点时，后端返回 `400`。

## 10. 规划结果核心字段

三种规划创建接口返回的数据结构基本一致，前端至少需要消费以下字段。

### 10.1 当前链路边界

已在 `mission_planner` 侧落地并经过测试的部分：

- 总后台前端调用 `mission_planner` 的手选、圈选、语义规划接口后，可以拿到规划结果。
- 规划结果中会包含 `ros_task_payloads`，每个元素对应一台实际分到路线的机器人。
- 总后台可以把某个 `ros_task_payloads[]` 元素原样序列化为 JSON，再放入 ROS 下行消息的 `task_params_json`。
- `ros_task_payloads[]` 的 JSON 可以被 ROS 端 `uran_autotask` 的新版解析器解析为户外执行点序列。

还不能仅凭当前仓库代码断言已经打通的部分：

- 总后台是否已经把 `ros_task_payloads[]` 正确转发到机器狗 ROS 端。
- 机器狗 ROS 端收到任务后是否已经完成真实导航动作触发、状态回传和异常闭环。
- GPS、视觉里程计和 Nav2 在真机户外场景下的整体闭环效果。

### 10.2 核心响应示例

```json
{
  "plan_id": "interactive_plan_xxxxx",
  "created_at": "2026-04-02T08:00:00+00:00",
  "scene_name": "NCEPU",
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
      "hardware_id": "cyberdog2_01",
      "display_name": "机器狗 1",
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
      ],
      "start_pose": {},
      "home_pose": {}
    }
  ],
  "ros_task_payloads": [
    {
      "schema_version": "1.2.0",
      "task_type": "mission_planner_route",
      "task_id": "mp_interactive_plan_xxxxx_cyberdog2_01",
      "planner_result_id": "interactive_plan_xxxxx",
      "scene_name": "NCEPU",
      "robot": {
        "planning_slot_id": "slot_01",
        "hardware_id": "cyberdog2_01",
        "display_name": "机器狗 1"
      },
      "route": {
        "route_nav_point_ids": ["NP_049"],
        "points": [
          {
            "seq": 0,
            "point_id": "start_slot_01",
            "kind": "start",
            "local": {"x": 10.0, "y": 0.0, "z": 20.0},
            "map": {"frame_id": "map", "x": 10.0, "y": 20.0, "z": 0.0},
            "geo": {"lat": 38.0, "lon": 115.0, "alt": 0.0, "source": "nav_point"},
            "required": false,
            "allow_skip": true
          }
        ]
      }
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
  }
}
```

字段说明：

- `plan_id`：本次计算结果的临时标识，可用于前端本地状态和提交 SpringCloud 时做关联。
- `scene_name`：该计划所属场景，回显计划前应先切到对应场景。
- `selection`：记录规划来源，手选、圈选、语义会不同。
- `selection.matched_asset_ids`、`selection.matched_asset_names`：电力资产语义匹配时会返回。
- `selected_nav_points`：前端可直接用于高亮已命中的任务点。
- `robots[].display_route_local_m`：机器人整条显示路径。
- `robots[].legs[].polyline_local_m`：分段路径，适合做更细粒度展示。
- `ros_task_payloads`：只包含实际分到路径的机器人；没有任务的机器人不会生成空任务包。
- `ros_task_payloads[].route.points[]`：给机器人执行的细粒度路径点，包含 `geo` 地理坐标、`local` 局部坐标和 `map` 坐标。
- `visualization.selected_polygon`：圈选模式下的原始多边形。
- `visualization.nav_points`：当前场景完整导航点列表，字段结构与 `GET /assets` 保持一致。

## 11. 总后台转发约定

`mission_planner` 不直接连接 ROS，也不负责把任务发给机器狗。总后台拿到规划结果后，应按下面规则转发：

- 遍历 `ros_task_payloads`。
- 用 `ros_task_payloads[].robot.hardware_id` 或 `ros_task_payloads[].robot.planning_slot_id` 选择目标机器狗。
- 将单个 `ros_task_payloads[]` 元素原样序列化为 JSON 字符串，作为 `TaskCtrlCmd.task_params_json`。
- 向机器狗 ROS 端发布 `uran_msgs/msg/TaskCtrlCmd`。
- ROS 话题为 `/uran/core/downlink/task_ctrl`。
- ROS 消息类型为 `uran_msgs/msg/TaskCtrlCmd`。

`TaskCtrlCmd` 字段对应关系：

- `msg_version`：由总后台或 `uran_core` 填写，建议当前用 `"1.0"`。
- `task_id`：取 `ros_task_payloads[].task_id`。
- `action`：规划下发时填 `"start"`。
- `task_type`：取 `ros_task_payloads[].task_type`，当前为 `"mission_planner_route"`。
- `task_params_json`：单个 `ros_task_payloads[]` 元素的 JSON 字符串。
- `timestamp_ns`：由总后台或 ROS 端下发适配层填真实纳秒时间。

ROS 端当前接收入口：

- 节点：`uran_autotask`
- 订阅话题：`/uran/core/downlink/task_ctrl`
- 消息类型：`uran_msgs/msg/TaskCtrlCmd`
- 处理逻辑：`action=start` 时解析 `task_params_json`，识别 `task_type=mission_planner_route`，生成户外执行点序列并触发导航调度。

## 12. 前端工程建议

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
- `getSemanticProviderStatus()`
- `createManualPlan(payload)`
- `createPolygonPlan(payload)`
- `createSemanticPlan(payload)`
- `savePlanToSpringCloud(planResult)`
- `dispatchPlanViaSpringCloud(rosTaskPayloads)`

前端不再需要封装：

- `loadRobotConfig(scene?: string)`
- `saveRobotConfig(payload)`
- `listSavedPlans()`
- `getPlan(planId)`
- `executePlan(planId)`
- `getPlanViewerUrl(planId)`
