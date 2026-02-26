# GraduationWork_model 阅读路线图（新手版）

这份文档给你一条“从能跑起来到看懂模块职责”的最短路径。建议按阶段顺序阅读，每阶段约 30 分钟。

## 阶段 1：先建立全局认知（约 30 分钟）

- 先看 `README.md`，了解项目目标和当前支持的接口能力。
- 再看 `main.py`，确认应用入口和 CLI 入口分别是什么。
- 看 `src/api/routers/__init__.py`，理解路由是如何聚合注册的。

你在这一阶段要回答两个问题：
- 这个项目主要解决什么问题？
- 请求进入后，第一站会到哪个模块？

## 阶段 2：从接口层看业务入口（约 30 分钟）

按这个顺序读：
- `src/api/routers/fingerprint.py`
- `src/api/routers/enterprise_data.py`
- `src/api/dependencies.py`

阅读重点：
- 每个路由函数的 `Args` / `Returns` / `Raises`。
- `BaseModel` 请求体与响应体字段语义（配合 `Field(description=...)` 看）。
- 异常是如何转换成 HTTP 状态码的（400/500）。

## 阶段 3：进入服务层看真实业务（约 30-45 分钟）

按这个顺序读：
- `src/services/fingerprint_service.py`
- `src/services/enterprise_dataset_service.py`
- `src/services/risk_analysis_service.py`

阅读重点：
- service 是如何编排 processor + database 的。
- 哪些函数是“流程主干”（公开函数），哪些是“内部步骤”（私有函数）。
- 入参如何在函数间流转，最后返回给 API 的结构是什么。

## 阶段 4：看算法与工具函数（约 30 分钟）

按这个顺序读：
- `src/processors/file_processor.py`
- `src/processors/text_segmenter.py`
- `src/processors/fingerprint.py`
- `src/processors/explicit_implicit_analysis.py`

阅读重点：
- `file_processor`：文件如何被标准化读取。
- `text_segmenter`：文本如何切分，长句如何二次切分。
- `fingerprint`：MD5 如何对文本和文件分别计算。
- `explicit_implicit_analysis`：LR/PIC/Risk 计算链路和输入约束。

## 阶段 5：看配置与数据库基础设施（约 30 分钟）

按这个顺序读：
- `src/config/settings.py`
- `src/config/database.py`
- `src/database/connection.py`
- `src/database/init_db.py`
- `src/database/manual_schema.sql`

阅读重点：
- 配置加载优先级（默认值 -> YAML -> 环境变量）。
- 数据库连接参数如何从配置转换出来。
- SQL 表结构和服务层写入逻辑如何对应。

## 推荐的“边读边验证”方式

每读完一个阶段，做一次小验证：

1. 调用一个你刚读过的 API（如指纹导入接口）。
2. 打印或查看该调用返回值结构。
3. 追踪这个返回值来自哪个 service 函数。
4. 再追踪 service 里调用了哪些 processor/database 函数。

这样能把“静态阅读”变成“动态理解”。

## 常见术语速查

- `dataset`：企业数据集定义（业务对象集合）。
- `attribute`：数据集内字段/属性定义。
- `sample`：一条业务样本记录（如员工、订单等）。
- `explicit edge`：人工或规则给出的显性关系。
- `implicit edge`：算法计算出的隐性关系。
- `risk`：泄露风险指标，通常由 `LR * PIC` 得到。

## 下一步建议

当你完成这 5 个阶段后，可以继续做两件事：
- 给每个核心模块画一张调用关系图（API -> service -> processor/db）。
- 选一条完整链路（如 `analyze_implicit_risk`）做“从请求到落库”的逐行走读。

