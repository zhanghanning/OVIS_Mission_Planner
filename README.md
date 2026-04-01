# Mission Planner

这是算法后端的最小可运行骨架。

当前目标：

- 接收总后台下发的规划任务
- 下载并解压 `mission_package.zip`
- 读取 `route_graph.json / goals.json / robots.json`
- 生成 `planner_result.zip`
- 提供本地交互式规划接口
- 支持手选任务点、框选范围、语义任务三类规划入口
- 可视化展示三只 Cyberdog2 的规划结果

推荐优先使用 Docker 运行，相关模板在：

- `../OSM2World_docs/deploy/docker`

如果本地直接跑：

```bash
# 在 mission_planner 项目根目录执行
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8081 --reload
```

交互式规划入口：

- 控制台页面：`GET /api/planner/interactive/console`
- 规划资产：`GET /api/planner/interactive/assets`
- 语义模型状态：`GET /api/planner/interactive/semantic/provider-status`
- 手选任务点：`POST /api/planner/interactive/plans/manual`
- 框选范围：`POST /api/planner/interactive/plans/polygon`
- 语义任务：`POST /api/planner/interactive/plans/semantic`
- 查询结果：`GET /api/planner/interactive/plans/{plan_id}`

交互式规划结果会写入：

- `data/local_plans/<plan_id>/request.json`
- `data/local_plans/<plan_id>/plan_result.json`

当前默认读取的校园资产目录是：

- `data/assets/ncepu`

如果你临时还想读取外部资产目录，再手动覆盖：

```bash
export MISSION_ASSET_ROOT_DIR=/your/asset/root
```

语义任务默认先走本地规则解析。后端已经同时预留了两类大模型接入方式：

- `local_transformers`
  - 后端进程直接从本地模型目录加载
  - 适合本机或挂载模型目录的专用容器
- `openai_compatible`
  - 调用兼容 OpenAI Chat Completions 的本地服务或远程服务
  - 适合后续切换到本地推理服务、vLLM、代理网关或云 API

启用本地模型直载：

```bash
source .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/cu128 torch==2.8.0+cu128
pip install bitsandbytes>=0.45,<1.0
pip install -r requirements-llm-local.txt
export SEMANTIC_LLM_ENABLED=true
export SEMANTIC_LLM_PROVIDER=local_transformers
export SEMANTIC_LLM_LOCAL_MODEL_PATH=../models/Qwen3-VL-4B-Instruct
export SEMANTIC_LLM_LOCAL_DEVICE=cuda
export SEMANTIC_LLM_LOCAL_DTYPE=auto
export SEMANTIC_LLM_LOCAL_LOAD_IN_4BIT=true
export SEMANTIC_LLM_LOCAL_BNB_COMPUTE_DTYPE=float16
uvicorn app.main:app --host 0.0.0.0 --port 8081 --reload
```

启用 OpenAI 兼容接口：

- `SEMANTIC_LLM_ENABLED=true`
- `SEMANTIC_LLM_PROVIDER=openai_compatible`
- `SEMANTIC_LLM_BASE_URL=...`
- `SEMANTIC_LLM_API_KEY=...`
- `SEMANTIC_LLM_MODEL=...`

补充说明：

- 当前本地模型目录 `../models/Qwen3-VL-4B-Instruct` 实际是一个软链接，如果你在 Docker 里启用本地模型，优先挂载真实模型根目录，而不是只挂载这个软链接入口。
- 当前语义解析只使用文本输入，不依赖图像推理链路。

前端对接请看：

- `docs/frontend_api_contract.md`
# OVIS_Mission_Planner
