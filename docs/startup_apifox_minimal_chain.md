# 项目启动与 Apifox 最小可跑通链路

本文给出一条可以直接照做的最小闭环：

1. 本地启动 FastAPI 服务
2. 用 Apifox 调通企业知识图谱相关接口
3. 从手工建表开始，完整跑通隐性风险分析
4. 用 SQL 核验结果是否已落库

---

## 1. 环境准备与项目启动

### 1.1 前置条件

- Python 3.10+（建议 3.11）
- MySQL 8.x（本项目使用 PyMySQL 直连）
- 在项目根目录执行命令：`E:/workProj/GraduationWork_model`

### 1.2 创建虚拟环境并安装依赖（PowerShell）

```powershell
cd E:\workProj\GraduationWork_model
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 1.3 检查数据库配置

编辑 `config/config.yaml` 的 `database` 段，确保与本机 MySQL 一致：

```yaml
database:
  host: "localhost"
  port: 3306
  user: "gw"
  password: "569332"
  db: "graduation_work"
  charset: "utf8mb4"
```

### 1.4 初始化数据库表

项目不会自动建表，请手工执行 `src/database/manual_schema.sql`。

#### 方式 A：在 mysql 命令行执行

```sql
CREATE DATABASE IF NOT EXISTS graduation_work DEFAULT CHARSET utf8mb4;
USE graduation_work;
SOURCE E:/workProj/GraduationWork_model/src/database/manual_schema.sql;
```

#### 方式 B：在图形化客户端执行

直接打开并运行 `src/database/manual_schema.sql` 全量脚本。

### 1.5 启动 FastAPI

```powershell
cd E:\workProj\GraduationWork_model
.\.venv\Scripts\Activate.ps1
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

启动后访问：

- Swagger 文档：`http://127.0.0.1:8000/docs`
- OpenAPI：`http://127.0.0.1:8000/openapi.json`

---

## 2. Apifox 调试配置

### 2.1 新建项目与环境变量

- 新建项目：`GraduationWork_model`
- 新建环境：`local`
- 设置变量：
  - `baseUrl = http://127.0.0.1:8000`

### 2.2 建议接口分组

- `enterprise-data`
  - `POST {{baseUrl}}/api/v1/enterprise-data/datasets`
  - `POST {{baseUrl}}/api/v1/enterprise-data/datasets/{dataset_code}/attributes/batch`
  - `POST {{baseUrl}}/api/v1/enterprise-data/datasets/{dataset_code}/samples/batch`
  - `POST {{baseUrl}}/api/v1/enterprise-data/datasets/{dataset_code}/kg/edges/explicit/batch`
  - `POST {{baseUrl}}/api/v1/enterprise-data/datasets/{dataset_code}/analysis/implicit-risk`

---

## 3. 最小可跑通请求链路（从企业知识图谱初始化开始）

下面使用同一组 `dataset_code`：`ent_demo_001`。

### 3.1 创建数据集

`POST {{baseUrl}}/api/v1/enterprise-data/datasets`

```json
{
  "dataset_code": "ent_demo_001",
  "dataset_name": "企业演示数据集",
  "domain_name": "hr",
  "source_system": "apifox_demo",
  "description": "最小可跑通链路示例",
  "status": "active"
}
```

### 3.2 批量注册属性（含敏感属性 + PIC）

`POST {{baseUrl}}/api/v1/enterprise-data/datasets/ent_demo_001/attributes/batch`

```json
{
  "attributes": [
    {
      "attr_code": "dept",
      "attr_name": "部门",
      "attr_type": "category",
      "is_sensitive": 0,
      "sensitivity_level": 0,
      "is_identifier": 0,
      "nullable_flag": 0,
      "default_pic": 0.35,
      "description": "非敏感维度"
    },
    {
      "attr_code": "title",
      "attr_name": "职级",
      "attr_type": "category",
      "is_sensitive": 0,
      "sensitivity_level": 0,
      "is_identifier": 0,
      "nullable_flag": 0,
      "default_pic": 0.45,
      "description": "非敏感维度"
    },
    {
      "attr_code": "city",
      "attr_name": "城市",
      "attr_type": "category",
      "is_sensitive": 0,
      "sensitivity_level": 0,
      "is_identifier": 0,
      "nullable_flag": 0,
      "default_pic": 0.30,
      "description": "非敏感维度"
    },
    {
      "attr_code": "salary_level",
      "attr_name": "薪资等级",
      "attr_type": "category",
      "is_sensitive": 1,
      "sensitivity_level": 2,
      "is_identifier": 0,
      "nullable_flag": 0,
      "default_pic": 0.90,
      "description": "敏感属性"
    }
  ]
}
```

### 3.3 批量导入样本

`POST {{baseUrl}}/api/v1/enterprise-data/datasets/ent_demo_001/samples/batch`

```json
{
  "samples": [
    {
      "sample_key": "emp_001",
      "source_trace": "demo_batch_1",
      "values": {
        "dept": "R&D",
        "title": "P6",
        "city": "Beijing",
        "salary_level": "L3"
      }
    },
    {
      "sample_key": "emp_002",
      "source_trace": "demo_batch_1",
      "values": {
        "dept": "R&D",
        "title": "P7",
        "city": "Beijing",
        "salary_level": "L4"
      }
    },
    {
      "sample_key": "emp_003",
      "source_trace": "demo_batch_1",
      "values": {
        "dept": "Sales",
        "title": "P5",
        "city": "Shanghai",
        "salary_level": "L2"
      }
    },
    {
      "sample_key": "emp_004",
      "source_trace": "demo_batch_1",
      "values": {
        "dept": "Sales",
        "title": "P6",
        "city": "Shanghai",
        "salary_level": "L3"
      }
    },
    {
      "sample_key": "emp_005",
      "source_trace": "demo_batch_1",
      "values": {
        "dept": "Finance",
        "title": "P6",
        "city": "Shenzhen",
        "salary_level": "L3"
      }
    },
    {
      "sample_key": "emp_006",
      "source_trace": "demo_batch_1",
      "values": {
        "dept": "Finance",
        "title": "P7",
        "city": "Shenzhen",
        "salary_level": "L4"
      }
    }
  ]
}
```

### 3.4 批量写入显性关系边（知识图谱初始化建议步骤）

`POST {{baseUrl}}/api/v1/enterprise-data/datasets/ent_demo_001/kg/edges/explicit/batch`

```json
{
  "edges": [
    {
      "from_node_type": "attribute",
      "from_node_key": "dept",
      "from_display_name": "部门",
      "to_node_type": "attribute",
      "to_node_key": "salary_level",
      "to_display_name": "薪资等级",
      "relation_type": "business_rule",
      "relation_desc": "部门与薪资等级存在业务关联",
      "source_type": "manual",
      "confidence": 0.85,
      "evidence": {
        "owner": "security_team",
        "note": "示例显性边"
      }
    },
    {
      "from_node_type": "attribute",
      "from_node_key": "title",
      "from_display_name": "职级",
      "to_node_type": "attribute",
      "to_node_key": "salary_level",
      "to_display_name": "薪资等级",
      "relation_type": "business_rule",
      "relation_desc": "职级与薪资等级强相关",
      "source_type": "manual",
      "confidence": 0.90,
      "evidence": {
        "owner": "hr_team",
        "note": "示例显性边"
      }
    }
  ]
}
```

### 3.5 触发隐性关系与泄露风险分析

`POST {{baseUrl}}/api/v1/enterprise-data/datasets/ent_demo_001/analysis/implicit-risk`

```json
{
  "sensitive_attr_code": "salary_level",
  "candidate_attr_codes": [
    "dept",
    "title",
    "city"
  ],
  "pic_defaults": {
    "dept": 0.35,
    "title": 0.45,
    "city": 0.30
  },
  "default_pic": 0.5,
  "max_combination_size": 2,
  "sampling_times": 200,
  "theta": 0.2
}
```

预期响应中至少包含：

- `calc_batch_id`
- `risk_final`
- `is_high_risk`
- `top_results`（按风险倒序）

---

## 4. SQL 核验（确认链路落库）

> 先执行：`USE graduation_work;`

### 4.1 数据集是否创建成功

```sql
SELECT id, dataset_code, dataset_name, status, create_time
FROM enterprise_dataset
WHERE dataset_code = 'ent_demo_001' AND is_deleted = 0;
```

### 4.2 属性是否注册成功

```sql
SELECT id, attr_code, attr_name, is_sensitive, default_pic
FROM enterprise_attribute
WHERE dataset_id = (
  SELECT id FROM enterprise_dataset WHERE dataset_code = 'ent_demo_001' AND is_deleted = 0
)
AND is_deleted = 0
ORDER BY id;
```

### 4.3 样本与属性值是否导入成功

```sql
SELECT COUNT(*) AS sample_cnt
FROM enterprise_sample
WHERE dataset_id = (
  SELECT id FROM enterprise_dataset WHERE dataset_code = 'ent_demo_001' AND is_deleted = 0
)
AND is_deleted = 0;
```

```sql
SELECT COUNT(*) AS value_cnt
FROM enterprise_sample_value v
JOIN enterprise_sample s ON s.id = v.sample_id
WHERE s.dataset_id = (
  SELECT id FROM enterprise_dataset WHERE dataset_code = 'ent_demo_001' AND is_deleted = 0
)
AND s.is_deleted = 0
AND v.is_deleted = 0;
```

### 4.4 显性边是否写入成功

```sql
SELECT e.id, fn.node_key AS from_key, tn.node_key AS to_key, e.relation_type, e.confidence, e.create_time
FROM enterprise_kg_edge_explicit e
JOIN enterprise_kg_node fn ON fn.id = e.from_node_id
JOIN enterprise_kg_node tn ON tn.id = e.to_node_id
WHERE e.dataset_id = (
  SELECT id FROM enterprise_dataset WHERE dataset_code = 'ent_demo_001' AND is_deleted = 0
)
ORDER BY e.id DESC;
```

### 4.5 隐性分析结果是否落库

```sql
SELECT
  e.id,
  fn.node_key AS combo_attrs,
  tn.node_key AS sensitive_attr,
  e.metric_type,
  e.metric_value,
  e.pic_value,
  e.risk_value,
  e.calc_batch_id,
  e.create_time
FROM enterprise_kg_edge_implicit e
JOIN enterprise_kg_node fn ON fn.id = e.from_node_id
JOIN enterprise_kg_node tn ON tn.id = e.to_node_id
WHERE e.dataset_id = (
  SELECT id FROM enterprise_dataset WHERE dataset_code = 'ent_demo_001' AND is_deleted = 0
)
ORDER BY e.risk_value DESC, e.id DESC;
```

---

## 5. 常见报错与定位

### 5.1 `数据集不存在`

- 先调用创建数据集接口，再调后续接口。
- 确认路径参数 `dataset_code` 与创建时一致。

### 5.2 `无可用候选属性，请先注册非敏感属性`

- 至少要有一个 `is_sensitive=0` 的属性参与分析。
- `sensitive_attr_code` 不能同时出现在候选属性里。

### 5.3 `样本为空或样本属性值缺失，无法执行分析`

- 检查样本是否成功导入。
- 检查样本里是否包含敏感属性和候选属性值。

### 5.4 `敏感属性熵为0，无法计算LR`

- 说明敏感属性取值几乎全一样（常量化）。
- 增加样本多样性后再计算。

---

## 6. 一次性执行顺序（Checklist）

1. 安装依赖并启动服务
2. 手工执行 `manual_schema.sql`
3. 在 Apifox 按顺序调用 5 个接口
4. 执行核验 SQL，确认显性边和隐性边都已落库
5. 根据 `risk_final` 和 `top_results` 判定高风险组合

---

## 7. CoBAn 最小闭环（训练 -> 检测 -> 结果核验）

本节使用仓库内 mock 目录 `examples/coban_mock/`，演示 CoBAn 独立链路。

### 7.1 准备 mock 语料

- 训练机密语料：`examples/coban_mock/train/confidential/`
- 训练非机密语料：`examples/coban_mock/train/non_confidential/`
- 检测样例文本：`examples/coban_mock/detect/`

### 7.2 训练模型

`POST {{baseUrl}}/api/v1/coban/train`

```json
{
  "run_name": "coban_mock_quickstart",
  "dataset_name": "coban_mock_dataset",
  "source_type": "real",
  "real_confidential_dirs": [
    "E:/workProj/GraduationWork_model/examples/coban_mock/train/confidential"
  ],
  "real_non_confidential_dirs": [
    "E:/workProj/GraduationWork_model/examples/coban_mock/train/non_confidential"
  ],
  "use_mock": false,
  "ngram_range": [1, 3],
  "n_clusters": 3,
  "context_span": 20,
  "cluster_similarity_threshold": 0.05,
  "detection_threshold": 0.8
}
```

预期响应字段（需记录后续核验）：

- `run_id`
- `model_run_pk`
- `model_artifact_path`
- `train_doc_count`

> 备注：若只想快速验证链路，也可将 `use_mock` 设为 `true`，仅使用内置语料训练。

### 7.3 执行检测

`POST {{baseUrl}}/api/v1/coban/detect`

```json
{
  "run_id": "替换为上一步返回的 run_id",
  "doc_name": "case_confidential.txt",
  "doc_path": "E:/workProj/GraduationWork_model/examples/coban_mock/detect/case_confidential.txt",
  "input_text": "本次融资谈判方案包含授信额度上限、抵押条款和银行利率底线。并购估值区间与关键对手报价仅限核心管理层阅读，严禁对外传播。",
  "top_k_clusters": 3,
  "irregular_ratio_threshold": 20.0
}
```

预期响应字段（需记录后续核验）：

- `doc_uid`
- `confidentiality_score`
- `is_confidential`
- `matched_clusters`
- `evidence_terms`

### 7.4 查询训练与检测详情

1) 查询训练批次：

`GET {{baseUrl}}/api/v1/coban/models/{run_id}`

2) 查询检测详情：

`GET {{baseUrl}}/api/v1/coban/detections/{doc_uid}`

### 7.5 SQL 核验（CoBAn）

> 先执行：`USE graduation_work;`

#### 7.5.1 训练批次是否成功

```sql
SELECT id, run_id, source_type, train_doc_count, conf_doc_count, non_conf_doc_count, status, model_artifact_path
FROM coban_model_run
WHERE run_id = '替换为 run_id' AND is_deleted = 0;
```

#### 7.5.2 聚类和文档是否落库

```sql
SELECT COUNT(*) AS cluster_cnt
FROM coban_cluster
WHERE run_id = (
  SELECT id FROM coban_model_run WHERE run_id = '替换为 run_id' AND is_deleted = 0
);
```

```sql
SELECT COUNT(*) AS doc_cnt,
       SUM(CASE WHEN is_confidential = 1 THEN 1 ELSE 0 END) AS conf_cnt,
       SUM(CASE WHEN is_confidential = 0 THEN 1 ELSE 0 END) AS non_conf_cnt
FROM coban_corpus_document
WHERE run_id = (
  SELECT id FROM coban_model_run WHERE run_id = '替换为 run_id' AND is_deleted = 0
);
```

#### 7.5.3 术语图是否生成

```sql
SELECT COUNT(*) AS conf_term_cnt
FROM coban_term_confidential
WHERE run_id = (
  SELECT id FROM coban_model_run WHERE run_id = '替换为 run_id' AND is_deleted = 0
);
```

```sql
SELECT COUNT(*) AS context_term_cnt
FROM coban_term_context
WHERE run_id = (
  SELECT id FROM coban_model_run WHERE run_id = '替换为 run_id' AND is_deleted = 0
);
```

```sql
SELECT COUNT(*) AS graph_edge_cnt
FROM coban_graph_edge
WHERE run_id = (
  SELECT id FROM coban_model_run WHERE run_id = '替换为 run_id' AND is_deleted = 0
);
```

#### 7.5.4 检测结果是否落库

```sql
SELECT d.id, m.run_id, d.doc_uid, d.doc_name, d.confidentiality_score, d.threshold_value, d.is_confidential, d.create_time
FROM coban_detection_result d
JOIN coban_model_run m ON m.id = d.run_id
WHERE m.run_id = '替换为 run_id'
ORDER BY d.id DESC;
```

#### 7.5.5 证据项抽查

```sql
SELECT d.doc_uid, d.matched_clusters_json, d.evidence_json, d.decision_reason
FROM coban_detection_result d
JOIN coban_model_run m ON m.id = d.run_id
WHERE m.run_id = '替换为 run_id'
ORDER BY d.id DESC
LIMIT 1;
```

### 7.6 CoBAn 一次性执行顺序（Checklist）

1. 准备并确认 `examples/coban_mock/` 目录下语料存在
2. 调用 `POST /api/v1/coban/train`，记录 `run_id`
3. 调用 `POST /api/v1/coban/detect`，记录 `doc_uid`
4. 调用 `GET /api/v1/coban/models/{run_id}` 与 `GET /api/v1/coban/detections/{doc_uid}`
5. 执行 CoBAn 核验 SQL，确认训练产物与检测结果均已落库

