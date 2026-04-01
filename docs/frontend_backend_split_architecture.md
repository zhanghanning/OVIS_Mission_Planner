# 前后端分离架构说明

当前项目采用前后端分离架构：

- 本机：仅运行 `mission_planner` 后端服务
- 后端：部署在 Docker 容器中
- 前端：在另一台设备上使用 `Vite + Vue3` 单独开发和运行
- 联调方式：前端直接访问本机 FastAPI 提供的 HTTP 接口
- 仓库内 `GET /api/planner/interactive/console` 仅作为联调参考页面，不是正式前端

## 推荐拓扑

```text
[Frontend Dev Machine]
Vite + Vue3
http://192.168.1.101:5173
        |
        v
[Backend Host]
Docker -> mission_planner(FastAPI)
http://192.168.1.100:8081
```

## 当前前后端职责边界

后端负责：

- 读取 `data/assets/<scene_name>/` 下的场景数据
- 读取和保存 `data/configs/robot_initialization/<scene>.json` 形式的运行时机器人初始化配置
- 组装地图渲染资产、导航点、路径网、机器人起终点
- 根据当前运行时机器人配置动态生成机器人数量、编号、初始节点和颜色
- 执行手选、圈选、语义三类规划
- 提供“预览计划 -> 执行保存”的两阶段规划流程
- 将最终结果统一保存到 `data/outputs/<plan_id>/`

前端负责：

- 拉取资产并渲染地图、图例、任务点、机器人轨迹
- 维护当前场景、已选点、圈选区域、语义输入等交互状态
- 维护机器狗初始化面板中的数量草稿、选中机器人、地图放置交互等临时状态
- 调用机器人初始化配置读写接口
- 发起规划预览请求
- 在用户确认后调用执行接口完成保存
- 根据 `scene_name` 和 `persistence` 渲染当前场景与保存状态

## 近期后端新增能力

- 场景化资产读取：`GET /api/planner/interactive/assets?scene=<scene_name>`
- 场景列表返回：`available_scenes`、`current_scene`
- 机器人初始化配置读取：`GET /api/planner/interactive/robots/config`
- 机器人初始化配置保存：`PUT /api/planner/interactive/robots/config`
- 机器人数量、编号、颜色和初始位置改为运行时配置，不再固定 3 台
- 规划请求支持 `scene`
- 规划结果增加 `scene_name`
- 规划结果增加 `persistence`
- 新增执行接口：`POST /api/planner/interactive/plans/{plan_id}/execute`
- 规划输出目录统一到 `data/outputs/<plan_id>/`

## 正式前端尚需补齐的对接项

- 根据 `available_scenes` 做场景栏，而不是固定单场景
- 场景切换时重新拉取该场景资产
- 增加“机器狗初始化”标签页，用于数量输入、地图放置、配置保存和配置加载
- 正式前端不能再假设只有 `slot_01`、`slot_02`、`slot_03`
- 允许多台机器狗重叠放置，但要用不同颜色同时显示
- 规划前需要读取 `robot_config.all_robots_placed`，未完成放置时禁用规划入口
- 创建手选、圈选、语义规划时传入当前 `scene`
- 增加“执行计划”按钮，不再把预览结果当作已保存结果
- 展示 `persistence.saved`、`persistence.output_dir`、`persistence.saved_at`
- 回显已有计划时，先按 `scene_name` 切换到对应场景再渲染

## 开发阶段建议

1. 后端容器固定监听 `8081`
2. 前端机器通过局域网访问后端机器 IP
3. 后端开启 CORS，只允许前端开发源访问
4. 如果跨公网，再在此基础上额外做端口暴露或反向代理

## 后端需要保证的事项

- `0.0.0.0:8081` 对外可访问
- `BACKEND_CORS_ALLOW_ORIGINS` 已包含前端开发地址
- 规划资产目录和语义模型目录都已挂载进容器

## 前端需要稳定依赖的内容

- 后端基地址
- 接口协议
- 场景切换协议
- 机器人初始化配置协议
- 预览与执行分离的规划流程

其余算法、模型、规划器、数据资产都在后端机器上处理。
