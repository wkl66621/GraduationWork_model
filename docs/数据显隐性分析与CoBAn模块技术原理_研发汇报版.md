# 数据显隐性分析与 CoBAn 模块技术原理（研发汇报版）

## 1. 汇报目标与范围

本次汇报面向研发团队，聚焦项目中两条核心能力链路：

- 结构化数据链路：数据显隐性分析（LR/PIC/Risk）
- 非结构化文本链路：CoBAn 机密文本识别（训练 + 检测）

汇报目标是明确这两个模块的工程实现、算法逻辑、落库结构和当前边界，便于后续优化、联调和上线评审。

---

## 2. 总体技术架构

当前系统采用“API 路由 -> 服务编排 -> 算法处理器 -> 数据库存储”的分层结构：

- API 层
  - 企业数据与隐性风险分析：`src/api/routers/enterprise_data.py`
  - CoBAn 训练与检测：`src/api/routers/coban.py`
- 服务层
  - 显隐性风险编排：`src/services/risk_analysis_service.py`
  - CoBAn 训练编排：`src/services/coban_training_service.py`
  - CoBAn 检测编排：`src/services/coban_detection_service.py`
- 算法层
  - 显隐性计算核心：`src/processors/explicit_implicit_analysis.py`
  - CoBAn 文本预处理/聚类/术语打分/图构建：`src/processors/coban_*.py`
- 存储层
  - 表结构定义：`src/database/manual_schema.sql`

---

## 3. 数据显隐性分析模块（结构化数据）

## 3.1 研发视角下的核心问题

对于结构化企业数据，仅依赖“字段是否标记敏感”并不足够。实际风险来自：

- 非敏感字段组合对敏感字段存在高解释力
- 解释力与可识别能力叠加后形成可利用泄露路径

因此模块目标是对“候选属性组合 -> 敏感属性”的映射进行量化评估，并将结果落库到隐性关系边。

## 3.2 计算流程

1. 加载数据集、属性元数据、样本属性值（服务层透视为行级字典）。
2. 指定敏感属性 `S`，构造候选组合 `C`（1 到 N 阶）。
3. 对每个组合计算：
   - 互信息 `I(C;S)`
   - 敏感属性熵 `H(S)`
   - `LR = I(C;S) / H(S)`
4. 结合属性 PIC（单属性默认值 + 联合 PIC 估计）得到：
   - `Risk(C->S) = LR * PIC(C)`
5. 取最大风险值作为 `risk_final`，并与阈值 `theta` 比较得到高风险标记。
6. 将组合结果写入 `enterprise_kg_edge_implicit`，形成可追溯隐性关系边。

## 3.3 关键实现要点

- 数值稳定与边界处理
  - 熵为 0 时阻断计算（敏感属性常量化）
  - 互信息最小截断为 0
- 样本有效性筛选
  - 仅使用“组合属性 + 敏感属性都非空”的样本
- 联合 PIC 估计
  - 以单属性 PIC 的上下界区间采样平均近似联合 PIC
- 组合搜索控制
  - 通过 `max_combination_size` 限制组合爆炸

## 3.4 工程输出

- 返回结果
  - `risk_final`
  - `is_high_risk`
  - `top_results`
  - `calc_batch_id`
- 落库结果
  - `enterprise_kg_node`：属性组节点（`attribute_group`）
  - `enterprise_kg_edge_implicit`：每个组合的 `lr/pic/risk/evidence_json`

---

## 4. CoBAn 模块（文本机密识别）

## 4.1 模块定位

CoBAn 解决非结构化文本的机密识别问题，核心思想是：

- 先按语义聚类形成“主题簇”
- 再在簇内学习“机密术语 + 语境词”
- 对新文本做“簇相似度 + 术语证据 + 上下文证据”的综合评分

## 4.2 训练链路（Train）

训练主流程由 `train_coban_model` 编排：

1. 语料加载
   - 支持真实目录语料与内置 mock 语料混合
2. 文本预处理
   - 中英文分词、停用词过滤、`1~3gram` 术语构建
3. 聚类建模
   - `TF-IDF + KMeans` 生成 `cluster` 与 `centroid`
4. 机密术语打分（Eq.1 风格）
   - 按簇统计机密/背景概率比，保留正分术语
5. 上下文术语打分（Eq.2 风格）
   - 基于术语命中窗口统计上下文词区分度
6. 术语图构建
   - 边权重 `edge_weight = conf_score * context_score`
7. 产物与结果持久化
   - `model.pkl` + `metadata.json`
   - 多表落库（run/cluster/doc/term/context/graph）

## 4.3 检测链路（Detect）

检测主流程由 `detect_coban_confidentiality` 编排：

1. 加载指定 `run_id`（不传则回退最近成功批次）
2. 对输入文本执行同构预处理
3. 文本向量与各簇中心做余弦相似度，取 `top_k` 候选簇
4. 候选簇内证据计算
   - 直接命中机密术语
   - irregular 扩展术语（机密支持/非机密支持比值）
   - 上下文术语匹配（机密术语 + context 共同命中）
5. 单簇分数计算
   - 相似度与术语/上下文综合得分后做指数归一化
6. 文档总分计算
   - 按簇相似度加权平均得到 `confidentiality_score`
7. 阈值判定
   - `score >= threshold` 判为机密
8. 结果落库
   - `coban_detection_result`（含 `matched_clusters_json`、`evidence_json`、`decision_reason`）

## 4.4 CoBAn 关键表

- `coban_model_run`：训练批次主表
- `coban_cluster`：簇统计与中心向量
- `coban_corpus_document`：训练语料与簇分配
- `coban_term_confidential`：机密术语与得分
- `coban_term_context`：上下文术语与得分
- `coban_graph_edge`：术语图边
- `coban_detection_result`：检测结果与证据

---

## 5. 最小可演示闭环（建议汇报演示顺序）

可直接基于 `docs/startup_apifox_minimal_chain.md` 演示两条链路。

### 5.1 结构化链路演示

1. 创建数据集
2. 注册属性（含敏感属性与默认 PIC）
3. 导入样本值
4. 写入显性关系边
5. 触发 `/analysis/implicit-risk` 并展示 `risk_final/top_results`
6. SQL 验证 `enterprise_kg_edge_implicit` 落库内容

### 5.2 CoBAn 链路演示

1. 使用 `examples/coban_mock/` 训练语料调用 `/api/v1/coban/train`
2. 记录 `run_id`
3. 调用 `/api/v1/coban/detect` 检测样例文本
4. 记录 `doc_uid`
5. 查询模型与检测详情接口
6. SQL 验证 `coban_*` 相关表产物完整性

---

## 6. 当前实现优势

- 分层清晰：路由、服务、算法、存储职责明确，便于迭代
- 可解释性较好：结构化链路可追溯到组合风险，文本链路可追溯证据词
- 可运营性较好：训练批次、检测结果均可按 `run_id/doc_uid` 审计
- 具备最小闭环：已支持从训练到检测到落库验证的一体化流程

---

## 7. 当前边界与风险

- 显隐性分析对样本质量敏感
  - 样本稀疏、敏感属性分布单一会导致指标不稳定
- CoBAn 对语料覆盖敏感
  - 行业术语覆盖不足时，召回与泛化能力受限
- 阈值仍需业务校准
  - `theta`、`detection_threshold` 目前偏工程默认值
- 评估体系待补强
  - 尚需构建标准验证集与线上回流闭环

---

## 8. 后续研发建议（下一阶段）

- 结构化链路
  - 引入更系统的组合剪枝策略与稳定性检验
  - 增加分层风险解释模板（面向安全与业务双视角）
- CoBAn 链路
  - 引入增量训练与术语漂移监控
  - 补充更细粒度证据权重学习策略
- 工程能力
  - 补充离线评测脚本与基准数据集
  - 打通告警与治理动作（脱敏、拦截、审批）联动

---

## 9. 汇报结论

本项目已形成“结构化 + 非结构化”双链路的 DLP 核心能力原型：

- 结构化侧能量化隐性推断风险并写入知识图谱
- 文本侧能给出机密判定与可解释证据

从研发视角看，当前版本已具备“可演示、可落库、可扩展”的基础条件，下一步重点应转向评测体系、参数标定与业务联动能力建设。

