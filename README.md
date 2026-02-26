# DLP模型调用（Python 模块）

本项目用于为DLP系统提供生成文本类文档的数字指纹功能、数据显隐性分析和上下文分析功能。

## 当前阶段目标（DLP导向）

- 构建企业特有数据集底座（数据集、属性、样本、属性值）。
- 构建企业数据关联知识图谱底座（显性关系边、隐性关系边）。
- 支持后续泄露影响计算（LR/PIC/Risk）的数据准备与结果承载。
- 不在本阶段实现数据比对功能，仅预留扩展能力。

## 数据库初始化策略

- 项目**不会在启动时自动建表**。
- 你可手工执行数据库脚本：`src/database/manual_schema.sql`。
- SQL 常量也同步维护在：`src/database/init_db.py`。

建议执行方式（MySQL）：

```sql
USE graduation_work;
SOURCE src/database/manual_schema.sql;
```

## 扩展方向

- 支持更多指纹算法：SHA256、SimHash、向量指纹（基于 `sentence-transformers`）。
- 引入聚类与相似度分析（`scikit-learn`、`gensim` 等）。
- 提供批量导入目录、状态监控等高级功能。

