# Spec0058：本地 Embedding 部署与接入（Mac 验证、Linux 验收）

日期：2026-10-26，2026-10-27获用户实施授权。状态：Mac 协议和正式 RAG 合成链路已实测；Linux 32 核／64 GB／无 GPU 开发机由用户按[操作说明](../local-embedding.md)验收，结果待回传。范围仅覆盖现有 RAG 的 Embedding 本地化；首选 Ollama 的 OpenAI 兼容 `/v1/embeddings` 与 `qwen3-embedding:0.6b`。Windows 本地模型验证留到本路线完成之后单独安排。

## 1. 目标与边界

- 目标：正式摄取、增量重建和查询都调用本机 Ollama Embedding；检索、来源和活动版本合同保持。若启用重排，使用已有本地 CrossEncoder；也可显式关闭重排做 Embedding 链路基线。外部模型请求数为零。
- 先复用现有 `openai_compatible` Provider，不先开发 `/api/embed` 原生适配器。OpenAI SDK 所需的非空 `api_key` 暂用明确标注的非密钥占位值；本机 Ollama 忽略它。现有配置和运行时对未选中聊天模型不解析凭据。
- 本片不开发 Agent、MCP、问答生成、远程模型服务、前端、GPU 推理、Windows 模型部署、自动下载权重或多模型动态切换。不改公开 API，不迁移或覆盖已有活动知识库。
- Ollama 仅绑定目标主机回环地址；公司 Linux 的主机用户和网络边界在实际验收前核实。本 Spec 不把“开发机可运行”写成生产服务可靠性或对外访问验收。

## 2. 当前数据流与可复用资产

```text
Markdown → DocumentChunker → ChunkRefiner → prepare_document_encoding_inputs
  → BatchProcessor → DenseEncoder → OpenAICompatibleEmbedding
  → /v1/embeddings → 响应按 index/维度/模型校验 → IndexBundleV2/Chroma

查询 → QueryProcessor → prepare_query_encoding_input → 同一个 Embedding 模型空间
  → HybridSearch → 可选本地 CrossEncoder → 来源证据
```

当前普通正文以 `chunk_size=1000` 字符切分；完整用例、代码和表格可能作为原子块超过该值。实际 Embedding 输入还会加入上下文及 `labeled_case` 视图。`max_input_utf8_bytes=32000` 是字节上限，不是 token 上限。已在合成示例观察到短输入，但公司真实材料分布未知，不能据此断言不存在超窗输入。

`models.json` 已可声明 `provider=openai_compatible`、base URL、模型、维度、`model_revision` 和响应模型别名；当前注册表和 Provider 要求非空 Key，且现有 Provider 支持批量 `encoding_format=float`、超时和响应大小限制。模型空间身份包含 Embedding 配置；本地模型切换必须创建新索引版本，不得把旧外部向量当成本地模型向量复用。运行时的 `max_input_utf8_bytes`、批大小和超时不进入模型空间身份。

## 3. 选型与配置合同

| 项目 | 本轮建议 | 验证点 |
|---|---|---|
| 模型 | `qwen3-embedding:0.6b`，记录 Ollama 版本、模型 tag、实际模型 ID/digest | Mac 与 Linux 使用相同已核验权重；`model_revision` 与记录一致，不能只信可变 tag |
| 协议 | `base_url` 指向目标 Ollama 回环监听地址的 `/v1/` | 现有 SDK 实际发请求；响应 `model`、`data[index]`、1024 维向量与可选 `usage` 通过现有校验 |
| Key | 独立验证配置中使用明确标注的非密钥占位值 | SDK 可构造，Ollama 忽略值；日志与结果不显示它；不得把占位值解释为服务鉴权 |
| 重排 | 首次 Embedding 闭环可设 `none`；完全本地闭环选已有 CrossEncoder | 选中 LLM 重排会重新引入外部模型，验收时禁止 |
| 输入边界 | 保留项目现有字节上限；按真实输入分布和实际 token/窗口结果确定运行值 | 超限明确失败；不以向量返回成功证明原文完整参与编码 |
| CPU 参数 | 批大小、并发、超时在 Mac/Linux 分别实测后配置 | 不把 GPU 或 Mac 延迟推算为 Linux 吞吐量 |

端口、路径、批大小、超时、上下文窗口均通过已有配置或 Ollama 服务配置给出，不在源码新增常量；测试配置与真实用户配置分离。[Qwen 模型卡](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)标注该模型最大 1024 维、32K 上下文，但服务有效窗口须在目标运行环境核验；不能直接按模型标称上限放行输入。

Ollama 文档说明 `/api/embed` 的 `truncate` 默认 true，false 时超窗报错；其 OpenAI 兼容 `/v1/embeddings` 没有 `truncate` 字段。当前上游转换代码转发 model、input 和 dimensions，不转发 `truncate`。因此兼容接口的“返回向量”不是无截断证据。实际发行版本须做超窗探针，并核对真实输入是否远低于有效窗口。[原生接口](https://docs.ollama.com/api/embed)、[兼容接口](https://docs.ollama.com/api/openai-compatibility)、[兼容转换源码](https://github.com/ollama/ollama/blob/main/middleware/openai.go)。

## 4. 分片与退出条件

| 片 | 交付 | 主要改动范围 | 退出条件 |
|---|---|---|---|
| 1：兼容协议探针 | Mac 上固定 Ollama/模型版本和权重身份，直接请求兼容接口，再通过现有 Provider 请求短文本、批量文本与明确超窗文本 | 临时验证配置、探针记录；原则上不改产品源码 | 响应模型名、索引、维度、usage/未知用量、错误行为可解释；记录版本与 digest；超窗行为明确。兼容失败则停止该路径，更新本 Spec 再评估原生适配 |
| 2：Mac RAG 闭环 | 在隔离数据根目录先统计实际组装的 Embedding 输入、核验接近窗口的输入，再用真实本地 Embedding 完成首次摄取、重复摄取、查询和可选本地重排 | 已有 `models.json`/`config.yaml` 的独立验证副本、验证记录；只有实测合同不匹配才触及源代码及对应测试 | 输入边界结论先于建库；本地 Ollama 请求可观察、外部请求 0；新模型空间/索引与旧外部索引隔离；来源、revision、成对数据与原链一致；关停 Ollama 时明确失败、不产生新活动版本 |
| 3：Linux CPU 验收 | 在指定开发机上安装相同候选、核验权重身份；先用获准的真实资料统计最终 Embedding 输入并处理超窗项，再跑完整摄取/查询 | 目标机独立配置与数据目录、验收报告；本仓库配置模板仅在确认通用值后另行修改 | 无 GPU 的 32 核/64 GB 环境完成规定资料集；记录最大/分位输入长度、超窗数、总片段数、请求数、耗时与峰值内存、查询结果/来源；外部请求 0，错误和活动版本可追踪；不把开发机结果写成生产 SLA |

第 1 片不需要预先修改 `ModelRegistry`、`ApplicationRuntime` 或 `OpenAICompatibleEmbedding`。若仅需非密钥占位值即可贯通，不增加“无 Key Provider”分支。若真实探针暴露兼容响应差异，先写失败测试，再在现有模块做最小修复；若问题是无法接受的静默截断，另写原生接口补充 Spec，不在本轮预建第二套传输层。

## 5. 正常、异常与数据一致性

- 首次摄取使用新的模型身份和隔离索引；同一材料重复摄取在身份匹配时复用。模型、维度、版本或表示身份变化时，按现有失效机制重建，不能复用旧向量。
- 查询必须与所选活动版本的模型空间和维度一致。新模型检索质量需与固定问题和旧外部模型基线逐题比较；工程闭环通过不等于质量不下降。
- Ollama 未启动、模型未拉取、响应模型/维度错误、请求超时、输入过大及内存不足均明确失败并保留旧活动版本；日志不包含原文、凭据或完整响应体。
- 超长输入风险由真实最终输入统计和目标服务 token/窗口探针评估。接近窗口的输入可用原生 `/api/embed` 加 `truncate=false` 做**验收探针**，这不要求产品接入原生接口；若真实资料出现此类输入，先决定是否调整切分/上下文或改原生 fail-fast，未解决前不激活该批索引。受保护原子块的完整性优先于为了适配模型而悄悄丢字段。
- 模型 tag 可变，`model_revision` 是配置身份而非运行时自动权重证明；Mac 和 Linux 均需以 Ollama 实际模型 ID/digest 对照记录。发现不一致不得复用已建索引。

## 6. 验证证据与回退

- 片 1：保存不含原文和非公开路径的版本、模型 ID/digest、短/批量/超窗请求结果；不能用官方文档或模拟响应替代真实 Ollama 测试。
- 片 2：记录 `nyr ingest`、`nyr documents`、`nyr query` 的实际退出码和脱敏结果；相关定向测试、完整测试和构建若发生源码修改必须全绿。L1 文件/模型存在，L2 服务真实返回并通过校验，L3 从正式入口完成摄取与查询。
- 片 3：用户按操作说明在目标机选定获准的资料并执行；回传脱敏汇总后记录同一候选版本、权重核验、输入分布、CPU/内存/延迟及失败现场。源数据和索引不传回本机，不在文档记录原文。Mac 结果只算预验证，Linux 主机结果才算该目标验收。
- 回退仅切回原模型配置及其原活动索引/备份，不覆盖或删除历史索引。活动版本切换仍通过既有审计和 revision 门禁；如需对现有真实知识库重建或修改真实配置，实施前再次明确目标目录、范围和保留项。

## 7. Mac 本机实施证据（2026-10-27）

- Ollama 0.40.11 已安装，`qwen3-embedding:0.6b` 完整 digest 为 `ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d`。本机首次拉取遇到系统代理假 IP，给 Ollama 服务进程设置本机 HTTP(S) 代理后完成下载；运行期在回环地址、`OLLAMA_NO_CLOUD=true` 下复测。Mac 为 Apple M5 Pro／24 GB，不推算 Linux CPU 性能。
- `/v1/embeddings` 真实批量返回模型名、`index=[0,1]`、两条 1024 维向量和已知用量；现有 `OpenAICompatibleEmbedding` 的真实请求通过。6000 字合成超窗输入：原生 `truncate=false` 返回 400，兼容接口返回 200、`prompt_tokens=4095`，证实当前版本会静默截断。
- 5 份合成 Markdown 经正式准备后为 12 片段／12 个最终输入，最大 356 UTF-8 字节；12 条原生 `truncate=false` 探针全部通过。隔离验证配置将 `max_input_utf8_bytes` 从模板 32000 收紧至 3000，不改仓库真实配置。
- `nyr ingest` 首次激活 revision 1：5 份文档、12 条编码、2 次本地模型请求、用量 556 token；重复摄取 `unchanged`，12 条复用、0 次编码。`nyr query` 查询合成折扣问题返回 5 条证据，包含 `TC-01`，服务模型为本地 Qwen。关闭 Ollama 后变化文档摄取退出码 2，错误 `embedding_connection_failed`，活动 revision 和 bundle 不变；服务恢复后 1 份变化文档重编码 2 条、复用 10 条、激活 revision 2，查询再次返回 5 条证据。
- 新增 `scripts/audit_local_embedding.py`：核对配置模型 digest、只允许回环 Ollama、统计真实组装的输入长度与请求预算，并可对每条输入执行原生无截断探针；不输出原文或路径。定向测试 6 项和 Mac 实际脚本运行分别验证；测试已接入 `scripts/run_formal_tests.py` 的 CI 清单。Linux 的真实资料、输入分布、吞吐和内存仍未验收。

另一会话的 Spec0057 本地候选已完成但当前工作树仍未提交；本轮只新增本地 Embedding 验收脚本、测试和文档，未改其进行中的源码、真实配置或索引。删除、发布和 push 不在本任务范围。

本轮最终验证：`.venv/bin/python -m pytest -q tests --tb=short` 为 `2381 passed in 448.56s`；`.venv/bin/python scripts/run_formal_tests.py` 为 `1710 passed in 397.71s`；`.venv/bin/python -m build` 成功生成 wheel 和 sdist，`scripts/inspect_distribution.py` 均通过；`pip check` 为 `No broken requirements found.`；`git diff --check` 退出 0。以上均为 Mac 本地验证，不替代 Linux 目标机验收。

## 8. 发布形态补充分片（2026-10-27）

用户确认 Linux 可访问 PyPI 和 GitHub Release。交付分为 Python wheel/sdist 与模型 Release 附件：wheel 的 `Requires-Dist` 负责让 `pip install` 下载 Python 依赖，不把跨平台第三方 wheel 或 Ollama 可执行文件塞入本项目 wheel；模型权重不进入 Git 仓库、wheel 或 sdist。当前 25 项直接依赖已在发行元数据中，先用干净安装验证，不无故升级依赖。项目正式版本、项目许可证和真实上传仍按 Spec0057 的发布门禁处理。

| 分片 | 文件与接口 | 验收 |
|---|---|---|
| 安装后审计入口 | 将现有 `scripts/audit_local_embedding.py` 的实质代码移入 `naiyue_rag.validation.local_embedding_audit`；原脚本保留薄入口；在 `pyproject.toml` 加 `nyr-embedding-audit` 命令，参数仍为 `--config`、`--probe` | wheel 包含模块与命令；离开源码目录的干净安装能执行；原有审计测试沿包内模块运行，脱敏与无截断合同不变 |
| 模型附件候选 | 从本机已验证的 Ollama 权重提取 Qwen 官方 Q8_0 GGUF（639150592 字节，SHA-256 `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`），本地生成可供 GitHub Release 上传的同字节附件、来源与 Apache-2.0 许可说明、摘要清单；只放在忽略的 `dist/` | 附件摘要精确匹配；用 Ollama 官方 `Modelfile FROM <gguf>`/`ollama create` 在隔离模型目录导入，验证 Embedding 维度与无截断探针；以独立名称避免覆盖既有模型，验收配置记录目标机实际 manifest digest，不沿用旧 digest |
| Linux 安装路径 | 更新 `docs/local-embedding.md` 和 `docs/installation.md`：`pip install` 安装 Python 包依赖，另装 Ollama、从对应 Release 下载并校验模型附件、导入后审计再摄取 | 不再要求把源码验收压缩包转移到 Linux；真实资料/索引保持在隔离目录；未获得 Linux 回传前不声称目标机完成验收 |

此分片不创建标签、GitHub Release、PyPI 项目或上传公开资产。上传前须核对目标仓库、版本/tag、附件名/摘要、项目与模型各自的许可证和不可触碰项；第一次发布仍需远端 CI 与公开安装验收。

### 分片 8 本机验证记录

- wheel/sdist 在新的临时输出目录构建并通过发行内容检查；wheel 提供 `nyr-embedding-audit` 可执行入口。联网干净安装后，在源码目录外调用该命令与正式 `nyr` 入口，完成本地模型探针、隔离资料首次摄取和查询。安装 smoke 返回 `status=passed`、`native_documents=2`、`active_revision=1`、`query_evidence=2`，`pip check` 报 `No broken requirements found.`。
- 忽略目录 `dist/model-assets/` 内的 GGUF 为 639150592 字节，SHA-256 为 `06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439`；同目录备妥模型许可证与来源清单。Mac 隔离 Ollama 模型仓用该 GGUF `ollama create` 成功，导入模型的两个 1024 维 Embedding 向量与原模型逐值一致（最大绝对差 0），无截断超窗请求均报 400。导入后的 manifest digest 与原 `ollama pull` digest 不同，验收配置必须记录目标机实际 digest。
- Linux 主机 CPU 安装、真实材料的输入分布、运行耗时和内存仍待远端验收；项目正式版本、项目许可证、PyPI/GitHub 环境配置及公开上传也未完成。本机候选不等于可执行 `pip install naiyue-rag` 的公开版本。
