# 语义微调方案

## 结论

可以做，而且适合做。

但当前这类问题不只是模型能力问题，还包含 3 类结构性问题：

1. 同义词覆盖不够
2. 缺少“锚点 + 附近范围”这种选择器
3. 目标集定义不完整，例如“运动场地”目前由体育中心和独立球场点共同组成

所以推荐路线不是“直接拿现在的错误样本去训”，而是：

1. 先补规则和语义结构
2. 再自动生成大批量标注数据
3. 最后做 LoRA / QLoRA 微调

## 当前已补上的能力

后端已经补了这些规则：

- `寝室 / 学生公寓 / 公寓 / 住宿区 / 住寝区` 会落到宿舍目标集
- `二号餐厅 / 二号食堂 / 第2食堂 / 2餐` 这类表达会只命中二餐
- `三号餐厅 / 第3食堂` 会只命中三餐
- `南门附近 / 北门附近 / 网球场北门附近` 这类表达会按锚点半径展开任务点
- `所有运动场地` 会同时覆盖 `体育中心 + 篮球场 + 足球场 + 操场`

## 自动造数脚本

脚本位置：

- `scripts/generate_semantic_sft_dataset.py`

运行方式：

```bash
cd mission_planner
python3 scripts/generate_semantic_sft_dataset.py
```

默认会读取：

- `data/assets/ncepu/mission/semantic_catalog.json`
- `data/assets/ncepu/mission/nav_points_enriched.geojson`
- `data/assets/ncepu/planning/assets/semantic_target_sets.json`

默认输出到：

- `data/training/semantic_sft/semantic_sft_train.jsonl`
- `data/training/semantic_sft/semantic_sft_eval.jsonl`
- `data/training/semantic_sft/semantic_sft_summary.json`

## 数据格式

每一条样本都是 chat 格式，包含：

- `system`: 当前在线语义解析器使用的系统提示词
- `user`: 任务描述 + 当前可用目标集和导航点目录
- `assistant`: 目标输出 JSON

输出 JSON 结构固定为：

```json
{
  "selected_target_set_ids": ["category::dormitory"],
  "selected_nav_point_ids": ["NP_002", "NP_005"],
  "reason": "Category selection for dormitory"
}
```

## 推荐训练方式

### 方案 A：QLoRA 微调当前本地模型

适合你现在已有的 `Qwen3-VL-4B-Instruct`。

建议：

- 4-bit 量化加载
- LoRA rank 16 或 32
- 只训练文本相关层
- 先用纯文本样本，不引入图像

### 方案 B：单独换成文本推理模型做语义解析

如果后面发现这个模块长期只做文字理解，不做图像输入，那么更推荐单独换成文本 Instruct 模型作为语义解析器。

优点：

- 显存压力更小
- 推理更快
- 微调更便宜

## 训练前必须做的两件事

1. 先构造评测集

评测集建议固定覆盖：

- 宿舍同义词：`寝室 / 学生公寓 / 宿舍区`
- 餐厅同义词：`二号餐厅 / 第二食堂 / 饭堂`
- 运动场地：`球场 / 体育场地 / 操场 / 运动区域`
- 附近表达：`南门附近 / 北门一圈 / 南门周边`
- 范围表达：`教11到教12 / 学11到学12`

2. 先把规则兜底逻辑保留

微调后的模型也不应该裸奔。

推荐仍然保留：

- 编号建筑规则
- 附近锚点规则
- 结果校验
- 非法 nav_point_id 过滤

## 训练后的接入建议

训练完成后，优先保持当前接口不变：

- `POST /api/planner/interactive/plans/semantic`

只替换语义解析内部实现：

- 旧：规则 + 原始本地模型
- 新：规则 + 微调后的本地模型

这样前后端、规划器和可视化都不用改。

## 判断微调是否有效

至少用下面 3 类指标评估：

1. 目标点召回率
2. 错误点误选率
3. 语义歧义稳定性

最关键的观察项是：

- `二号餐厅` 不能再带出 `三餐`
- `所有运动场地` 不能漏掉北侧球场
- `南门附近` 不能完全空结果
- `寝室` 必须稳定落到宿舍目标集
