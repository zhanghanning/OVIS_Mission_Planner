# Cyberdog 场景仿真与任务规划总方案

## 1. 结论

这个想法是可行的，但需要做一个很重要的约束：

- 可以把四足机器人仿真模型放进你基于 OSM2World 生成的场景里，先在仿真环境中做全局路径规划、任务分配、导航点验证和多机调度逻辑验证。
- 但为了保证主线任务不偏移，不建议把“直接把 `scene.glb` 原样塞进当前 Cyberdog Gazebo 仿真器”当成第一步。

当前最稳、最符合你现有环境的路线是：

1. 保留 `scene.glb` 作为高保真可视化资产。
2. 从 `scene.glb / mesh_triangles.json / map_data.json` 生成一个适合 Gazebo 的静态场景模型。
3. 将该静态场景作为 `cyberdog_gazebo` 的 world 或 model 载入。
4. 使用 Nav2 在仿真中完成全局路径规划、导航点执行与局部避障。
5. 后端接入大模型和确定性优化器，完成“语义理解 -> 点位筛选 -> 多机分配 -> 顺序规划”。
6. 等仿真链路稳定后，再迁移到实机。

## 2. 为什么不能把 `scene.glb` 直接当主仿真环境

### 2.1 你本机现有 Cyberdog 仿真栈是 Gazebo Classic 路线

从本机现有工程可确认：

- 本地工作区: `/home/techno/cyberdog_sim`
- 仿真说明: `/home/techno/cyberdog_sim/src/cyberdog_simulator/ReadMe.md`
- 现有 world: `/home/techno/cyberdog_sim/src/cyberdog_simulator/cyberdog_gazebo/world/simple.world`
- 现有 launch: `/home/techno/cyberdog_sim/src/cyberdog_simulator/cyberdog_gazebo/launch/gazebo_nav.launch.py`

当前这套说明文档明确写的是：

- ROS2 Galactic
- Gazebo
- `gazebo_ros`
- Gazebo plugin

这说明你现在线上最稳定的仿真基础是 `ROS2 Galactic + Gazebo Classic`，不是新的 Gazebo Sim，也不是 Isaac Sim。

### 2.2 `glb` 更适合可视化，不一定适合你当前这条 Gazebo 主线

官方 Gazebo Common API 确实已经支持 `GLTF (GLB)` 网格格式。

参考：

- Gazebo Common MeshManager:
  - https://gazebosim.org/api/common/7/MeshManager_8hh.html

但这并不等于“你当前 Cyberdog Gazebo Classic 工作流就应该直接用 `glb` 做主场景资产”。

原因有两个：

1. 你当前本地工程和 launch 全是经典 Gazebo world / model / plugin 组织方式。
2. Gazebo 官方示例里最稳妥、最常见的视觉网格导入路径，仍然是用 `dae / obj / stl` 这样的 mesh 文件组织进 `model.sdf`。

参考：

- Gazebo 添加视觉网格示例:
  - https://gazebosim.org/api/sim/10/adding_visuals.html

所以：

- 如果你现在追求“立刻开始做任务规划仿真”，推荐把 `scene.glb` 转成 Gazebo 更稳的视觉 mesh 格式，再配一个更简单的 collision 模型。
- 如果未来你要升级到新的 Gazebo Sim 或 Isaac Sim，再考虑保留 `glb` 原生导入链路。

## 3. 当前最推荐的总架构

整体架构建议如下：

### 3.1 底图层

使用你已经导出的官方场景包：

- `/home/techno/OSM2World_docs/exports/NCEPU_Repaired_export/scene.glb`
- `/home/techno/OSM2World_docs/exports/NCEPU_Repaired_export/map_data.json`
- `/home/techno/OSM2World_docs/exports/NCEPU_Repaired_export/world_objects.json`
- `/home/techno/OSM2World_docs/exports/NCEPU_Repaired_export/meshes.json`
- `/home/techno/OSM2World_docs/exports/NCEPU_Repaired_export/mesh_triangles.json`

用途：

- `scene.glb`: 前端三维显示、高保真可视化
- `map_data.json`: 路网节点、way、area、经纬度与局部平面坐标
- `world_objects.json`: 建筑、道路、林地等高层语义对象
- `mesh_triangles.json`: 生成仿真视觉 mesh、碰撞包围盒、栅格图

### 3.2 私有任务图层

不要把任务点继续写回公开 OSM。

新增你自己的私有任务层：

- `nav_points.geojson`
- `semantic_catalog.json`
- `route_graph.geojson`
- `robot_registry.json`

### 3.3 仿真执行层

推荐当前先走：

- 四足机器人: Cyberdog Gazebo + Nav2

后续扩展：

- 无人机: 独立仿真器或独立机载局部规划器

### 3.4 调度层

职责拆开：

- 大模型负责语义理解和候选点筛选
- OR-Tools 或别的确定性求解器负责任务分配和访问顺序
- Nav2 / 机载规划器负责局部执行

## 4. 对“把 Cyberdog 放进场景里先做规划”的判断

### 4.1 可行

是可行的。

而且这是非常值得做的第一步，因为它能优先验证：

- 你的导航点设计是否合理
- 你的图坐标与仿真坐标是否一致
- 你的全局路径是否穿模、穿墙或不可达
- 你的任务分配和顺序规划是否可执行

### 4.2 但要用“分层资产”

不要让一个文件同时承担所有任务。

建议分成 3 份资产：

1. 可视化资产
   - 来自 `scene.glb`
   - 追求显示效果

2. 碰撞资产
   - 来自 `mesh_triangles.json` 的简化结果
   - 追求稳定碰撞检测

3. 规划资产
   - 来自 `map_data.json` 和 `route_graph.geojson`
   - 追求路径合理性和算法速度

这样做的好处是：

- 场景显示可以复杂
- 碰撞体可以简单
- 规划图可以干净

## 5. 推荐路线：先走 Gazebo 稳定版，不迁移主线

### 5.1 先不要迁移仿真器

为了不让主线偏掉，当前不建议你立刻迁移到：

- Gazebo Sim Harmonic
- Isaac Sim
- Unity

虽然这些环境对 `glb / gltf` 更友好，但迁移成本太高，会分散你当前最关键的工作。

### 5.2 直接利用你现有的 `cyberdog_sim`

你本机现成可用的入口已经在：

- `/home/techno/cyberdog_sim/src/cyberdog_simulator/cyberdog_gazebo/launch/gazebo_nav.launch.py`

这个 launch 已经支持：

- 选择 world 名称 `wname`
- 启动 `gzserver / gzclient`
- 用 `spawn_entity.py` 按 URDF 把机器人生成进去

这意味着你只需要新增一个 world 和一个场景 model，就能直接上手。

## 6. 一步一步的实施方案

## 第 0 步：冻结当前主线基准

以这套修复后导出结果为当前基准：

- `/home/techno/OSM2World_docs/exports/NCEPU_Repaired_export`

不要再频繁改 OSM 数据，除非发现明显错误。

后续算法、导航点、仿真 world 都先基于这套版本展开。

## 第 1 步：建立任务点层，不再往 OSM 里加点

新增文件：

- `/home/techno/mission_stack/data/nav_points.geojson`

每个点至少存：

- `id`
- `name`
- `lat`
- `lon`
- `local_x`
- `local_z`
- `yaw`
- `category`
- `building_ref`
- `robot_types`
- `action`

这样能同时满足：

- 和真实世界的经纬度对齐
- 和 OSM2World 本地坐标对齐
- 被前端、后端、ROS 同时读取

## 第 2 步：建立语义目录供大模型读取

新增文件：

- `/home/techno/mission_stack/data/semantic_catalog.json`

内容建议：

- 建筑 ID
- 建筑名称
- 建筑类别
- 楼号或别名
- 对应导航点列表
- 对应巡检类型

输入给大模型的不是原始 `mesh_triangles.json`，而是这份更干净的语义目录。

## 第 3 步：建立规划用路网图

新增文件：

- `/home/techno/mission_stack/data/route_graph.geojson`

图结构：

- node: 导航点、路口、转弯点、关键停靠点
- edge: 可通行边
- 属性:
  - `length`
  - `cost`
  - `allowed_robot_types`
  - `one_way`
  - `priority`

如果你后面准备用 Nav2 Route Server，这个图非常关键。

参考：

- Nav2 Route Tool:
  - https://docs.nav2.org/tutorials/docs/route_server_tools/navigation2_route_tool.html

## 第 4 步：把 OSM2World 场景转换成 Gazebo 可加载场景

这是当前最重要的一步。

### 4.1 生成视觉 mesh

把：

- `scene.glb`

转换为：

- `scene_vis.dae` 或 `scene_vis.obj`

推荐用途：

- 只做 `visual`
- 不直接做复杂 `collision`

原因：

- 视觉 mesh 可以很复杂
- Gazebo 对复杂 collision 会明显拖慢

### 4.2 生成简化 collision

从：

- `mesh_triangles.json`

派生出：

- 简化碰撞 mesh
- 或多个 box / convex hull
- 或直接做 2D occupancy map

推荐原则：

- 建筑、围墙、林地外边界保留
- 细碎装饰面删掉
- collision 模型宁可粗，也不要过密

### 4.3 在 `cyberdog_gazebo` 中创建静态场景 model

建议新增目录：

- `/home/techno/cyberdog_sim/src/cyberdog_simulator/cyberdog_gazebo/model/ncepu_scene`

内部结构：

- `model.config`
- `model.sdf`
- `meshes/scene_vis.dae`
- `meshes/scene_collision.dae`

`model.sdf` 里建议：

- `<static>true</static>`
- `visual` 使用 `scene_vis.dae`
- `collision` 使用更简化的 `scene_collision.dae`

### 4.4 新建 world

新增文件：

- `/home/techno/cyberdog_sim/src/cyberdog_simulator/cyberdog_gazebo/world/ncepu_scene.world`

这个 world 可以基于现有：

- `/home/techno/cyberdog_sim/src/cyberdog_simulator/cyberdog_gazebo/world/simple.world`

扩展一条：

- `<include><uri>model://ncepu_scene</uri></include>`

这样你就能直接通过：

- `wname:=ncepu_scene`

来启动。

## 第 5 步：在 Gazebo 中启动 Cyberdog

当前你现有入口已经具备：

- world 加载
- 机器人生成

所以仿真启动路线就是：

1. 启动 Gazebo world
2. 通过 `spawn_entity.py` 生成 robot
3. 启动 Cyberdog 控制程序
4. 启动 RViz / 可视化

你现有参考命令已经在：

- `/home/techno/cyberdog_sim/src/cyberdog_simulator/ReadMe.md`

未来实际命令会演化成类似：

```bash
source /opt/ros/galactic/setup.bash
source /home/techno/cyberdog_sim/install/setup.bash
ros2 launch cyberdog_gazebo gazebo_nav.launch.py wname:=ncepu_scene
```

## 第 6 步：用 Nav2 接管路径规划执行

当前最推荐的四足路线是：

- 全局规划: Nav2 Smac Planner
- 路点执行: Waypoint Follower
- 局部控制: Nav2 controller + costmap

参考：

- Waypoint Follower:
  - https://docs.nav2.org/configuration/packages/configuring-waypoint-follower.html
- Smac Planner:
  - https://docs.nav2.org/configuration/packages/configuring-smac-planner.html
- Smac State Lattice:
  - https://docs.nav2.org/configuration/packages/smac/configuring-smac-lattice.html
- Commander API:
  - https://docs.nav2.org/commander_api/index.html

为什么推荐这个组合：

- 你现在不是做四足低层步态算法仿真
- 你现在更关心“导航点是否可达、全局任务链路是否跑通”
- Nav2 更适合先把整条任务执行链打通

## 第 7 步：位置坐标统一

你后面必须统一 3 套坐标：

1. OSM / WGS84 经纬度
2. OSM2World 本地坐标 `local_xz_meters`
3. Gazebo world 坐标

建议：

- 直接把 Gazebo 世界坐标定义成 OSM2World 的 `local_xz_meters`
- 即：
  - Gazebo `x = local_x`
  - Gazebo `y = local_z`
  - Gazebo `z = local_y / 高度`

这一步非常重要，因为它能让：

- `nav_points.geojson`
- `scene.glb`
- `route_graph.geojson`
- Gazebo 中机器人 pose

全部共享同一套平面坐标定义。

## 第 8 步：现实世界映射

进入实机后，需要打通：

- GPS / RTK
- IMU
- 里程计
- `mission_map`

推荐使用：

- `robot_localization`
- `navsat_transform_node`

参考：

- Nav2 + robot_localization:
  - https://docs.nav2.org/setup_guides/odom/setup_robot_localization.html

这样你就能把真实世界 GPS 位置映射回任务地图坐标。

## 第 9 步：大模型与任务分配

推荐职责边界如下：

### 大模型负责

- 理解任务语义
- 从 `semantic_catalog.json` 中筛选目标建筑和目标点
- 输出候选巡检点集合

### 优化器负责

- 多机任务分配
- 点位访问顺序
- 路径代价最小化
- 设备能力约束

推荐工具：

- OR-Tools

参考：

- Assignment:
  - https://developers.google.com/optimization/assignment
- Routing:
  - https://developers.google.com/optimization/routing

## 第 10 步：从仿真迁移到实机

仿真与实机应共享这些资产：

- `nav_points.geojson`
- `semantic_catalog.json`
- `route_graph.geojson`
- 任务协议
- 调度器输出格式

而不共享这些资产：

- Gazebo 的 collision mesh
- Gazebo world 文件
- 仅仿真使用的控制参数

## 7. 现在就能开始做的最小可运行目标

当前建议的最小目标不是“一次把所有事情做完”，而是先打通下面这条链：

1. 用现有 `scene.glb` 生成 Gazebo 静态场景 model
2. 在 `ncepu_scene.world` 中加载这个静态场景
3. 用现有 `cyberdog_gazebo` 把机器人放进去
4. 在场景里手工给 5 个导航点
5. 用 Nav2 跑一条从 A -> B -> C 的 waypoint 任务
6. 在 RViz / 前端里同时显示机器人和任务点

只要这 6 步完成，就说明主链路成立了。

## 8. 当前最推荐的具体技术路线

### 推荐路线 A

这是现在最推荐、最稳的路线：

- 仿真器:
  - 继续使用当前 `cyberdog_sim` 的 Gazebo Classic
- 场景视觉:
  - `scene.glb -> scene_vis.dae/obj`
- 碰撞:
  - `mesh_triangles.json -> 简化 collision`
- 全局规划:
  - Nav2 Smac / Route Server
- 路点执行:
  - Waypoint Follower
- 任务分配:
  - LLM + OR-Tools

优点：

- 不迁移主仿真器
- 和你当前环境最一致
- 可以最快开始上手

### 备选路线 B

未来如果你追求更高保真和更自然的 `glb` 导入体验，可以考虑：

- Gazebo Sim 新版本
- Isaac Sim

但这条路线当前不建议作为主线。

## 9. 风险与控制策略

### 风险 1：`scene.glb` 太重

当前导出结果：

- `scene.glb` 约 85 MB
- `mesh_triangles.json` 约 365 MB

这对 Gazebo 来说不轻。

控制策略：

- 可视化和碰撞分离
- collision 做强简化
- 规划尽量依赖 `route_graph` 和栅格图，不直接扫 mesh

### 风险 2：仿真和实机坐标不一致

控制策略：

- 统一以 OSM2World `projection_origin + local_xz` 为主坐标系
- 所有导航点同时存经纬度和局部平面坐标

### 风险 3：机器人模型并非严格 Cyberdog2

本机现有的是：

- `cyberdog_sim`

不是我已经核实过的 “Cyberdog2 官方专用仿真包”。

所以当前建议是：

- 先把它当“四足平台仿真底座”用
- 验证任务规划主链路
- 后续如果你拿到 Cyberdog2 专用 description / 控制器，再做替换

## 10. 这件事是否值得立刻开始

值得，而且可以直接开始。

但第一步不应该是“继续改大模型”，而是：

1. 先把 `scene.glb` 变成 Gazebo 场景 model
2. 让 Cyberdog 在里面跑起来
3. 先验证导航点和全局规划

只要这一条跑通，你后面接大模型、任务分配、多机协同才有稳定基础。

## 11. 参考资料

### 本机现成工程

- Cyberdog 仿真说明:
  - `/home/techno/cyberdog_sim/src/cyberdog_simulator/ReadMe.md`
- Cyberdog Gazebo launch:
  - `/home/techno/cyberdog_sim/src/cyberdog_simulator/cyberdog_gazebo/launch/gazebo_nav.launch.py`
- 现有 simple world:
  - `/home/techno/cyberdog_sim/src/cyberdog_simulator/cyberdog_gazebo/world/simple.world`

### 官方资料

- Gazebo Common MeshManager:
  - https://gazebosim.org/api/common/7/MeshManager_8hh.html
- Gazebo 添加视觉网格:
  - https://gazebosim.org/api/sim/10/adding_visuals.html
- Gazebo SDF 世界:
  - https://gazebosim.org/docs/latest/sdf_worlds/
- Nav2 配置总览:
  - https://docs.nav2.org/configuration/index.html
- Nav2 Waypoint Follower:
  - https://docs.nav2.org/configuration/packages/configuring-waypoint-follower.html
- Nav2 Smac Planner:
  - https://docs.nav2.org/configuration/packages/configuring-smac-planner.html
- Nav2 Smac State Lattice:
  - https://docs.nav2.org/configuration/packages/smac/configuring-smac-lattice.html
- Nav2 Route Tool:
  - https://docs.nav2.org/tutorials/docs/route_server_tools/navigation2_route_tool.html
- Nav2 Commander API:
  - https://docs.nav2.org/commander_api/index.html
- Nav2 + robot_localization:
  - https://docs.nav2.org/setup_guides/odom/setup_robot_localization.html
- OR-Tools Assignment:
  - https://developers.google.com/optimization/assignment
- OR-Tools Routing:
  - https://developers.google.com/optimization/routing
- OSM Good Practice:
  - https://wiki.openstreetmap.org/wiki/Good_practice
- OSM Limitations:
  - https://wiki.openstreetmap.org/wiki/Limitations

