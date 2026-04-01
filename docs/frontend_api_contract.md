# Mission Planner 前端对接接口文档

这份文档面向软件前端同学。

当前正式架构是：

- 本机只运行 `mission_planner` FastAPI 后端
- 另一台设备运行 `Vite + Vue3` 前端
- 前端直接通过 HTTP 调用本机后端
- 当前仓库里的 `GET /api/planner/interactive/console` 仅用于算法联调，不作为正式前端页面

## 1. 基本信息

- 后端基地址示例：`http://192.168.1.100:8081`
- 开发阶段 Vite 地址示例：`http://192.168.1.101:5173`
- 数据格式：`application/json`
- 坐标系：
  - 局部平面坐标：`local_x`, `local_z`
  - 单位：米
  - `x` 朝东，`z` 朝北
- 地理坐标：`lat`, `lon`，WGS84

建议前端内部统一使用 `local_x / local_z` 做地图渲染。

## 2. 接口总览

- `GET /health`
- `GET /api/planner/interactive/assets`
- `GET /api/planner/interactive/semantic/provider-status`
- `POST /api/planner/interactive/plans/manual`
- `POST /api/planner/interactive/plans/polygon`
- `POST /api/planner/interactive/plans/semantic`
- `GET /api/planner/interactive/plans/{plan_id}`

## 3. 健康检查

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

## 4. 读取规划资产

```http
GET /api/planner/interactive/assets
```

用途：

- 加载建筑/用地/路网底图
- 加载任务点
- 加载机器人起点和 home
- 加载规划模板

前端应在应用启动后优先请求这一项。

## 5. 三种建任务方式

### 5.1 手选任务点

```http
POST /api/planner/interactive/plans/manual
```

```json
{
  "nav_point_ids": ["NP_049", "NP_050"],
  "mission_label": "manual_pick",
  "notes": "frontend manual selection"
}
```

### 5.2 圈选范围

```http
POST /api/planner/interactive/plans/polygon
```

```json
{
  "coordinate_mode": "local",
  "mission_label": "polygon_pick",
  "vertices": [
    {"x": 10.0, "z": 20.0},
    {"x": 30.0, "z": 20.0},
    {"x": 30.0, "z": 50.0},
    {"x": 10.0, "z": 50.0}
  ]
}
```

### 5.3 语义任务

```http
POST /api/planner/interactive/plans/semantic
```

```json
{
  "query": "巡检二号餐厅",
  "use_llm": true
}
```

## 6. 查询规划结果

```http
GET /api/planner/interactive/plans/{plan_id}
```

前端可以在创建规划成功后直接请求该接口，或用它做历史回显。

## 7. 前端工程建议

前端 `.env` 推荐：

```env
VITE_API_BASE_URL=http://192.168.1.100:8081
```

代码里统一：

```ts
const apiBase = import.meta.env.VITE_API_BASE_URL
```

## 8. 说明

- 正式前端不应依赖仓库内调试页面样式
- 只需按上述 HTTP 接口自行实现 Vue 页面
- 当前后端已支持跨设备访问，只要 `BACKEND_CORS_ALLOW_ORIGINS` 正确配置即可
