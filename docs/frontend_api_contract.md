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
- 新增 `GET /api/planner/interactive/plans/{plan_id}/viewer`，可按计划 ID 跳转到内置联调 viewer
- 新增 `GET /api/planner/interactive/plans`，可列出 `data/outputs/` 下已保存的 `interactive_plan_*` 结果目录名
- 三类规划结果统一保存到 `data/outputs/<plan_id>/`
- 资产读取和规划创建都已支持 `scene` 场景参数
- 资产接口会返回 `current_scene`、`available_scenes`、`scene_name`
- 规划结果会返回 `scene_name` 和 `persistence` 元数据，前端可据此显示当前场景和保存状态
- 规划结果会返回 `ros_task_payloads`，用于总后台转发给 ROS 端 `uran_autotask`
- 机器人初始化不再固定为 3 台，也不再固定在北门、南门、教12B
- 新增运行时机器人初始化配置接口，支持用户输入机器狗数量并在地图已有节点上放置机器狗
- 机器人初始化配置会以 JSON 保存到本地，并在系统启动后自动读取
- 规划阶段实际使用当前保存的机器人初始化配置；若仍有未放置机器人，规划接口会直接拒绝
- 资产与语义规划已支持风电场/电力场站数据，包括变电站区域、风机节点和光伏类目标

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
- `GET /api/planner/interactive/plans`
- `GET /api/planner/interactive/plans/{plan_id}`
- `POST /api/planner/interactive/plans/{plan_id}/execute`
- `GET /api/planner/interactive/plans/{plan_id}/viewer`

说明：

- `mission_planner` 对总后台提供的是 HTTP 接口。
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

- 前端启动时检查后端是否可用
- 可读取当前允许的跨域来源，辅助定位联调问题

## 5. 读取规划资产

```http
GET /api/planner/interactive/assets
GET /api/planner/interactive/assets?scene=<scene_name>
```

用途：

- 加载建筑、用地、路网底图
- 加载任务点
- 加载机器人起点和 home
- 加载任务模板和语义示例
- 加载当前可切换的场景列表

前端应在应用启动后优先请求这一项。

说明：

- `scene` 取值来自 `data/assets/<scene_name>/` 的目录名，当前仓库内已包含 `NCEPU` 和 `wind_power_station`
- 场景名区分大小写，前端不应自行假设或转换
- `wind_power_station` 场景下会返回电力资产相关字段与语义目标集

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
    "schema_version": "1.0.0",
    "scene_name": "wind_power_station",
    "robot_count": 3,
    "all_robots_placed": true,
    "placed_robot_ids": ["slot_01", "slot_02", "slot_03"],
    "unplaced_robot_ids": [],
    "config_path": "data/configs/robot_initialization/wind_power_station.json",
    "source": "file",
    "updated_at": "2026-04-02T09:00:00+00:00",
    "robots": []
  },
  "available_templates": [],
  "semantic_examples": [],
  "plan_api": {
    "assets": "/api/planner/interactive/assets",
    "robot_config": "/api/planner/interactive/robots/config",
    "list_saved": "/api/planner/interactive/plans",
    "manual": "/api/planner/interactive/plans/manual",
    "polygon": "/api/planner/interactive/plans/polygon",
    "semantic": "/api/planner/interactive/plans/semantic",
    "execute_template": "/api/planner/interactive/plans/{plan_id}/execute"
  }
}
```

字段补充说明：

- `map_areas[]` 至少包含 `area_id`、`layer_type`、`style_key`、`name`、`tags`、`outer`、`holes`
- `map_areas[].style_key=power:substation` 表示变电站区域图层，前端应按电力设施图层渲染
- `nav_points[]` 至少包含 `id`、`name`、`lat`、`lon`、`local_x`、`local_z`、`category`、`semantic_type`
- `nav_points[]` 还会附带建筑关联字段 `building_ref`、`building_name`、`building_category`
- `nav_points[]` 还会附带电力资产关联字段 `power_asset_ref`、`power_asset_name`、`power_asset_category`
- `nav_points[]` 还会附带 `robot_types`、`yaw`、`action`、`note`，可直接用于交互展示或调试提示
- `available_templates` 为当前场景完整任务模板列表，正式前端可直接消费
- `semantic_examples` 为模板里的自然语言示例列表，适合填充语义输入提示或快捷短语
- `plan_api` 为当前调试控制台使用的接口模板，正式前端可参考但不必依赖它生成全部 URL
- `plan_api.list_saved` 可用于获取后端已保存的规划结果目录名列表

前端重点处理：

- 默认不传 `scene` 时，后端会返回默认场景
- 场景切换时重新请求 `GET /api/planner/interactive/assets?scene=<scene_name>`
- 场景栏展示项应直接使用 `available_scenes`
- 地图、图例、任务点、机器人起终点都应随着场景切换整体刷新
- `robots` 为当前已保存的运行时机器人初始化结果，数量和位置都不再固定
- `robot_config` 用于驱动“机器狗初始化”面板，包括配置文件路径、是否还有未放置机器人等
- 当 `nav_points[]` 存在 `power_asset_name/category` 时，前端应将其视为稳定可用的电力资产元数据
- 当 `map_areas[]` 出现 `power:substation` 时，前端应支持变电站区域高亮或图例展示

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
GET /api/planner/interactive/robots/config?scene=<scene_name>
```

用途：

- 页面启动时读取当前场景的机器狗数量、编号和初始节点
- 在用户点击“从配置文件加载”时恢复本地 JSON 中已保存的配置

核心响应字段：

- `schema_version`
- `scene_name`
- `robot_count`
- `all_robots_placed`
- `placed_robot_ids`
- `unplaced_robot_ids`
- `config_path`
- `source`
- `updated_at`
- `robots[].index`
- `robots[].planning_slot_id`
- `robots[].hardware_id`
- `robots[].display_name`
- `robots[].color`
- `robots[].placed`
- `robots[].anchor_nav_point_id`
- `robots[].anchor_nav_point_name`
- `robots[].start_nav_point_id`
- `robots[].home_nav_point_id`
- `robots[].start_pose`
- `robots[].home_pose`

说明：

- `source` 可能为 `file` 或 `generated_default`
- `robots[].placed=false` 表示该机器狗槽位尚未绑定到任何导航点
- `start_pose/home_pose` 与 `assets.robots` 中的位姿结构保持一致，正式前端可直接复用

### 7.2 保存当前配置

```http
PUT /api/planner/interactive/robots/config
```

请求体：

```json
{
  "scene": "wind_power_station",
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
  "scene": "NCEPU"
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
  "scene": "NCEPU",
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
  "query": "巡检升压站和附近风机",
  "use_llm": true,
  "scene": "wind_power_station"
}
```

说明：

- 该接口只生成规划预览
- `scene` 为新增字段，前端当前场景切换后必须带上
- `use_llm=false` 时可作为规则解析或降级策略的一部分
- 规则解析除校园建筑外，还支持电力相关语义类别和资产别名匹配
- 已支持的电力相关类别包括 `power_infrastructure`、`substation`、`wind_turbine`、`solar_generator`
- 当语义没有解析到任何任务点时，后端返回 `400`

## 10. 规划结果读取与执行

### 10.1 列出已保存规划结果

```http
GET /api/planner/interactive/plans
```

用途：

- 获取 `data/outputs/` 下所有已保存的 `interactive_plan_*` 文件夹名称
- 供前端先拿到 `plan_id` 列表，再逐个请求 `GET /api/planner/interactive/plans/{plan_id}`

示例响应：

```json
{
  "plan_ids": [
    "interactive_plan_94674fa055",
    "interactive_plan_403aa87232"
  ],
  "count": 2
}
```

说明：

- 仅返回目录名以 `interactive_plan_` 开头、且已存在 `plan_result.json` 的结果目录
- 返回顺序按目录最近修改时间倒序排列

### 10.2 查询规划结果

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

### 10.3 打开内置联调 viewer

```http
GET /api/planner/interactive/plans/{plan_id}/viewer
```

用途：

- 通过固定 URL 打开仓库内置联调页面并自动回放指定计划
- 适合调试、验收或外部系统做“查看该计划”跳转

说明：

- 当前实现会返回 `307` 并重定向到 `/api/planner/interactive/console?plan_id={plan_id}`
- 该接口面向联调 viewer，不替代正式前端页面

### 10.4 执行并保存规划结果

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

### 11.1 当前链路边界

已在 `mission_planner` 侧落地并经过测试的部分：

- 总后台前端调用 `mission_planner` 的手选、圈选、语义规划接口后，可以拿到规划结果。
- 规划结果中会包含 `ros_task_payloads`，每个元素对应一台实际分到路线的机器人。
- 总后台可以把某个 `ros_task_payloads[]` 元素原样序列化为 JSON，再放入 ROS 下行消息的 `task_params_json`。
- `ros_task_payloads[]` 的 JSON 可以被 ROS 端 `uran_autotask` 的新版解析器解析为户外执行点序列。

还不能仅凭当前仓库代码断言已经打通的部分：

- 总后台是否已经把 `ros_task_payloads[]` 正确转发到机器狗 ROS 端。
- 机器狗 ROS 端收到任务后是否已经完成真实导航动作触发、状态回传和异常闭环。
- GPS、视觉里程计和 Nav2 在真机户外场景下的整体闭环效果。

因此目前准确结论是：`mission_planner -> ROS 任务包 -> uran_autotask 解析` 这一段已经打通；总后台转发和真机执行还需要端到端联调证明。

### 11.2 核心响应示例

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
- `selection.matched_asset_ids`、`selection.matched_asset_names`：电力资产语义匹配时会返回
- `selected_nav_points`：前端可直接用于高亮已命中的任务点
- `robots[].display_route_local_m`：机器人整条显示路径
- `robots[].legs[].polyline_local_m`：分段路径，适合做更细粒度展示
- `ros_task_payloads`：只包含实际分到路径的机器人；没有任务的机器人不会生成空任务包
- `ros_task_payloads[].route.points[]`：给机器人执行的细粒度路径点，包含 `geo` 地理坐标、`local` 局部坐标和 `map` 坐标
- `ros_task_payloads[].route.points[].geo`：WGS84 地理坐标，字段为 `lat/lon/alt`；地面机器可以只读 `lat/lon`，空中机器可以同时读取 `alt`
- `ros_task_payloads[].route.points[].local`：任务规划局部坐标，字段为 `x/y/z`，其中 `x` 朝东，`z` 朝北，`y` 朝上，单位都是米
- `ros_task_payloads[].route.points[].map`：ROS 坐标，当前约定 `map.x = local.x`，`map.y = local.z`，`map.z = local.y`
- `visualization.selected_polygon`：圈选模式下的原始多边形
- `visualization.nav_points`：当前场景完整导航点列表，字段结构与 `GET /assets` 保持一致
- `persistence.saved`：当前是否已真正保存
- `persistence.output_dir`：最终输出目录，可用于 UI 提示

### 11.3 总后台转发约定

`mission_planner` 不直接连接 ROS，也不负责把任务发给机器狗。总后台拿到规划结果后，应按下面规则转发：

- 遍历 `ros_task_payloads`。
- 用 `ros_task_payloads[].robot.hardware_id` 或 `ros_task_payloads[].robot.planning_slot_id` 选择目标机器狗。
- 将单个 `ros_task_payloads[]` 元素原样序列化为 JSON 字符串，作为 `TaskCtrlCmd.task_params_json`。
- 向机器狗 ROS 端发布 `uran_msgs/msg/TaskCtrlCmd`。
- ROS 话题为 `/uran/core/downlink/task_ctrl`。
- ROS 消息类型为 `uran_msgs/msg/TaskCtrlCmd`。

`TaskCtrlCmd` 字段对应关系：

- `msg_version`：由总后台或 `uran_core` 填写，建议当前用 `"1.0"`
- `task_id`：取 `ros_task_payloads[].task_id`
- `action`：规划下发时填 `"start"`
- `task_type`：取 `ros_task_payloads[].task_type`，当前为 `"mission_planner_route"`
- `task_params_json`：单个 `ros_task_payloads[]` 元素的 JSON 字符串
- `timestamp_ns`：由总后台或 ROS 端下发适配层填真实纳秒时间

ROS 端当前接收入口：

- 节点：`uran_autotask`
- 订阅话题：`/uran/core/downlink/task_ctrl`
- 消息类型：`uran_msgs/msg/TaskCtrlCmd`
- 处理逻辑：`action=start` 时解析 `task_params_json`，识别 `task_type=mission_planner_route`，生成户外执行点序列并触发导航调度

ROS 端设备应根据自身能力读取有效字段：

- 地面机器狗：主要读取 `map.x/map.y` 或 `geo.lat/geo.lon`，高度字段可忽略或只作为记录。
- 空中设备：可同时读取 `geo.alt`、`local.y` 或 `map.z`，并结合自身飞控坐标系转换。
- 如果某类设备有自己的高度基准，例如相对起飞点高度、海拔高度或场景高度，总后台或设备端需要在自己的适配层明确转换；`mission_planner` 当前只保证字段存在，不保证不同设备的高度基准已经完成实地标定。

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
- `loadRobotConfig(scene?: string)`
- `saveRobotConfig(payload)`
- `createManualPlan(payload)`
- `createPolygonPlan(payload)`
- `createSemanticPlan(payload)`
- `listSavedPlans()`
- `getPlan(planId)`
- `executePlan(planId)`
- `getPlanViewerUrl(planId)`

参考实现：

- 仓库内调试页已经支持场景切换、预览后执行保存、执行按钮、保存状态提示和机器狗初始化面板
- 如需参考交互逻辑，可查看 `app/static/planning_console.html`
