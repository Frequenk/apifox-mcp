# Apifox MCP v2 测试结果

测试日期：2026-09-09
测试项目：`remote-service`（只读）、`myself`（读写夹具）

## 改造前基线

| 项目 | 结果 |
| --- | ---: |
| 已注册 MCP 工具 | 29 个 |
| Mock 单测 | 25 个通过，测试本体 0.888s |
| remote JCP 详情冷读 | 约 1,002ms |
| remote JCP 详情缓存读取 | 约 84ms |
| remote JCP 完整快照输出 | 551,455 字符 |
| Schema 详情读取 | 约 704ms，仅返回顶层字段 |

完整快照携带 remote 项目的约 300 个 Schema。原 `update_schema` 只导入目标模型，没有携带嵌套 `$ref` 的依赖，也没有做结构化回读，因此曾出现工具返回成功但引用落为 `{type: object, properties: {}}`。

## v2 结果

| 项目 | 结果 |
| --- | ---: |
| 已注册 MCP 工具 | 7 个 |
| 单元与契约测试 | 21 个通过，1 个真实测试默认跳过，0.04s |
| `myself` 真实读写回归 | 连续 3 次通过，2.42–5.12s（含读取、修改、验证和恢复） |
| remote JCP 详情冷读 | 814–872ms，1 个 HTTP 请求 |
| remote JCP 详情缓存读取 | 16ms，0 个 HTTP 请求 |
| remote JCP 详情输出 | 21,377 字符 |
| remote JCP 列表和详情批量读取 | 26,989 字符，1 个 HTTP 请求 |
| remote JCP 列表和详情审计 | 0 个问题，复用缓存且未发送 HTTP 请求 |
| `myself` 接口与 Schema 分组写入 | 730ms，3 个 HTTP 请求 |
| 分组写入导入体积 | 1,929 bytes，2 个依赖 Schema |

JCP 详情读取输出缩小约 96.1%。分组写入的 3 个请求分别是写前导出、一次 import、写后强制导出；若前面已通过读取工具命中缓存，写入阶段只需 import 和强制回读。

## 覆盖场景

- `$ref` 传递依赖、循环依赖、缺失引用和无关 Schema 排除。
- 对象递归合并、数组替换和 JSON Pointer 删除。
- 批量读取、输出分页、缓存与最小导入文档。
- 接口和 Schema 单次分组写入、无变化跳过、字段描述校验。
- revision 并发保护、示例与 Schema 一致性、事务撤销。
- Apifox 成功计数下的嵌套引用丢失检测及自动恢复。
- `myself` 永久夹具的真实修改、回读和基线恢复。

## 真实测试夹具

- `GET /mcp-tests/document-sync`
- `McpIntegrationItem`
- `McpIntegrationResponse`
- 标签：`MCP集成测试`

真实测试仅在 `APIFOX_MCP_LIVE_TEST=1` 时运行，结束时通过 `finally` 恢复原始接口与 Schema。
