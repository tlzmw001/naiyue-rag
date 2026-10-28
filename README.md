# Naiyue RAG · 耐阅知识库

把 Markdown 需求、方案和测试用例变成可追溯的知识证据。

Naiyue RAG 是一个本地运行的知识检索服务。导入文档后，可以用自然语言查找相关内容，获得带文件位置、原文行号和知识库版本的证据，供知识问答、需求分析、问题排查和用例设计使用。

比如，检查一个功能变更时，可以查询“开关关闭后，哪些历史边界用例仍然适用？”，再沿返回的需求、方案和完整用例核对依据。当前终端展示检索证据，生成式回答与知识库 Agent 是后续方向。

## 能做什么

- **理解 Markdown 结构**：保留标题层级、代码、表格、来源位置和显式文档关系，测试用例按完整证据单位准备。
- **混合检索**：结合 Chroma 向量召回、BM25 关键词召回和 RRF 排名融合，支持文档范围过滤。
- **配置重排**：可用 OpenAI 兼容接口的聊天模型重排，也可显式准备本地 CrossEncoder，或关闭重排。
- **增量更新**：复用未变化文档的编码，新增或变化的文档重新编码；模型、表示或切分策略改变时重新计算。
- **追溯证据**：检索结果绑定同一活动版本，保留来源指纹、实际位置和本次调用用量；已入库内容可在原始目录离线后继续查询。
- **独立使用**：提供 Python 核心库、本机 HTTP 服务和 `nyr` 命令，核心检索链路独立于 Agent 和界面。

## 安装

使用 **64 位 Python 3.12**。目标平台为 Linux x86_64、Windows x86_64 和 macOS Apple Silicon，不支持 Intel Mac；各平台支持以实际 CI 验收结果为准。

从仓库根目录安装源码：

```sh
python -m pip install .
nyr --help
```

0.1.0 发布到 PyPI 后，安装方式为：

```sh
pip install naiyue-rag
```

一次安装会装齐全部正式功能的运行依赖，包括 PyTorch、Transformers 和 Sentence Transformers。依赖包允许联网下载，模型权重需要另行显式准备。

虚拟环境、平台说明和本地 wheel 安装方式见[安装文档](https://github.com/tlzmw001/naiyue-rag/blob/main/docs/installation.md)。

## 从自己的文档开始

### 1. 初始化配置

```sh
nyr documents
```

首次实际运行时，程序会在用户目录创建缺失的默认配置。`documents` 会自动启动临时服务、查看文档列表，然后退出；没有导入材料时返回空列表。

```text
~/.naiyue-rag/
├── config.yaml      # 运行参数、路径和选用的模型
├── models.json      # 模型端点、参数和凭据来源
├── knowledge/       # 自行创建，放入 Markdown 材料
└── data/            # 使用时生成的索引、缓存及本地模型等
```

已有配置不会被覆盖，`--help` 和 `--version` 不创建这些文件。

### 2. 配置模型并放入材料

编辑 `models.json` 中的 Embedding 和重排模型。每个云端模型选择一种凭据来源：

| 字段 | 用法 |
|---|---|
| `api_key_env` | 填写环境变量名，服务从该变量读取 Key |
| `api_key` | 直接填写 Key；需删除同一条目中的 `api_key_env` |

默认模板引用 `NAIYUE_RAG_ZHIPU_API_KEY`。替换模型时，需要同步核对端点、模型名、Embedding 维度及允许的响应模型。完整字段见[模型模板](https://github.com/tlzmw001/naiyue-rag/blob/main/naiyue_rag/resources/models.json)。不要提交或分享填写了真实 Key 的配置文件。

在 `~/.naiyue-rag/knowledge/` 放入自己的 Markdown 文档，也可以在 `config.yaml` 的 `paths.knowledge_base_root` 指向其他目录。

### 3. 导入并检索

```sh
# 首次导入，当前无活动版本时 revision 为 0
nyr ingest --expected-revision 0

# 连续终端检索
nyr chat
```

**只用 `nyr chat` 就能在一个终端中使用。** 没有服务时自动启动，有匹配的服务时直接连接；输入 `/exit`、EOF 或按 Ctrl+C 退出，只会关闭它本次启动的服务。

之后更新文档时，先运行 `nyr documents` 查看 `active.revision`，再将该值传给 `ingest --expected-revision`。版本冲突或结果不确定时，先核对状态再操作。

## 常用命令

| 命令 | 作用 |
|---|---|
| `nyr` | 在前台启动本机服务 |
| `nyr chat` | 自动启动或连接服务，连续检索证据 |
| `nyr documents` | 查看文档和当前活动版本 |
| `nyr ingest --expected-revision N` | 按指定版本摄取新增或变化的材料 |
| `nyr query '问题内容'` | 一次查询，输出结构化 JSON 证据 |
| `nyr models prepare local-reranker` | 显式下载并审计配置中的本地重排模型 |

所有实际运行命令均可用 `--config` 指定统一配置，比如：

```sh
nyr chat --config /path/to/config.yaml
```

主配置位置决定 `models_file` 和原始材料等相对路径；`paths.data_root` 管理运行数据根目录，索引、缓存和本地模型路径可相对它设置，也可单独使用绝对路径。改变配置不会自动搬迁旧数据。运行中的服务不会热加载配置、模型表或新的模型环境变量，修改后需要重启。

## 检索流程

```text
Markdown → 结构准备与切分 → Dense / Sparse 编码 → Chroma + BM25 → 版本激活

问题 → 固定活动版本与范围 → 两路召回 → RRF → 可选重排 → 带来源的证据
```

最终结果包含证据正文、文件位置、原文行号、活动版本及调用观测。检索排名用于选择相关材料，不能代替对业务结论的核对。

## 当前边界

- 输入材料以 Markdown 为主；PDF、图片和网页解析尚未提供。
- `chat` 当前提供终端检索，不生成回答，也不维护 Agent 会话记忆。
- 服务只监听本机回环地址，并校验独立服务 Token；当前不提供远程访问、前端或 MCP。
- Windows 保留文件同步、SQLite 事务和完整性审计；目录元数据的突然断电持久性与 POSIX 平台不同。
- 本地合成验证与真实资料质量、模型效果及大库性能验收分别记录。

## 开发与文档

```sh
python -m pip install -r requirements-dev.txt
python scripts/run_formal_tests.py
```

正式测试集使用公开或合成材料。仓库也保留早期实验与课程资产，历史全量测试中部分用例依赖未提交的旧快照或独立环境，详情见开发记录。

- [安装与配置](https://github.com/tlzmw001/naiyue-rag/blob/main/docs/installation.md)
- [标签发布与 PyPI 配置](https://github.com/tlzmw001/naiyue-rag/blob/main/docs/publishing.md)
- [设计与实现 Spec](https://github.com/tlzmw001/naiyue-rag/blob/main/docs/specs/README.md)
- [开发状态与验收记录](https://github.com/tlzmw001/naiyue-rag/blob/main/docs/handoff.md)
- [代码学习路线](https://github.com/tlzmw001/naiyue-rag/blob/main/docs/1.0/learning-roadmap.md)

项目代码采用 [MIT 许可证](LICENSE)；本地 Embedding 模型附件的许可证见其独立清单。
