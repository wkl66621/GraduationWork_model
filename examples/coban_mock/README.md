# CoBAn Mock 数据说明

本目录提供可直接用于 CoBAn 训练与检测演示的最小语料，覆盖：

- 训练语料（机密/非机密）
- 检测输入（机密样例/非机密样例）
- 结果核验（配合 `docs/startup_apifox_minimal_chain.md` 中 SQL）

## 目录结构

```text
examples/coban_mock/
├─ train/
│  ├─ confidential/
│  └─ non_confidential/
└─ detect/
   ├─ case_confidential.txt
   └─ case_non_confidential.txt
```

## 使用方式

1. 启动服务并完成建表（见 `docs/startup_apifox_minimal_chain.md`）。
2. 在 `POST /api/v1/coban/train` 中使用本目录作为真实语料输入目录。
3. 使用 `detect` 目录下文本调用 `POST /api/v1/coban/detect`。
4. 根据响应中的 `run_id`、`doc_uid` 执行 SQL 核验。

## 注意事项

- 文件编码统一为 UTF-8。
- 如仅验证接口连通性，也可在训练时设置 `use_mock=true` 使用内置 mock 语料。
