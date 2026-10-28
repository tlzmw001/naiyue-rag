# Spec0051：首版本机服务、统一配置与pip安装计划

日期：2026-10-26。状态：用户已授权实施，0052–0056细化并推进本地候选；各片证据见对应Spec，不是已发布声明。当前源码基线d2d7705，正式核心本机完整回归历史结果2235 passed in437.84s。此次实施不修改真实运行配置、用户知识库或.env，不发布或push；只在本仓库开发环境新增服务依赖，另以干净临时环境验证发行物。

## 1. 首版目标与已确认决定

用户明确先做能实际使用的第一个版本。已确认：

| 项目 | 合同 |
|---|---|
| 安装 | 允许联网；一次pip安装装齐全部已支持功能的运行依赖，包括本地重排依赖；模型权重及配套模型文件不自动下载 |
| 系统 | Linux、Windows、macOS Apple Silicon；不支持Intel Mac；具体首发环境基线与安装组合按第9节验证 |
| 主配置 | 多个运行YAML合并为一个config.yaml；后续Agent配置仍在同一主文件，当前不实现Agent字段/行为 |
| 模型配置 | 单独models.json保存模型连接和参数；可直接配置API Key，也可引用环境变量 |
| 默认位置 | 不指定--config时使用Path.home()/.naiyue-rag/config.yaml，缺失时自动初始化默认目录和模板；已存在文件不覆盖 |
| 指定配置 | --config完整选择一份配置，不叠加用户目录配置；显式文件不存在或格式错误要报错 |
| 数据位置 | 一个可配数据根目录，索引/缓存/模型等路径可相对根目录或用绝对路径覆盖；原始材料独立指定 |
| 服务启动 | nyr在前台启动本机服务；首版只支持本机，不建设局域网、公网或多用户部署 |
| 终端交互 | nyr chat连接同一服务；无服务时自动启动本地服务并进入交互，一个终端完成使用 |
| 退出 | chat只停止自己启动的服务；连接原有服务时退出不影响原服务 |
| 当前能力 | 沿已有摄取、检索、重排、来源及证据能力；chat当前展示检索证据和错误，不预填Agent/生成式回答已经实现 |

首版不加入前端、Agent循环、MCP、远程访问、用户/角色/文档ACL、服务集群、任务队列、热重载或自动数据迁移。现有模块/历史实验资产保留，打包按正式入口的真实依赖与资源选择，不借发布整体删除目录。

## 2. 现状、问题与复用资产

当前app.py要求--config和子命令；load_app_settings读取主YAML后再加载8类模块YAML，execute每次装配并关闭Provider。__main__.py仅调用该入口。尚无HTTP服务、安装包元数据、nyr命令或models.json读取机制。

各模块Settings.from_dict、严格YAML读取、resolve_api_key的安全错误边界、prepare_local_model、IngestionPipeline、DocumentManager、RetrievalPipeline和ResponseBuilder可以复用。新配置加载后直接构造这些类型，不为了兼容多文件格式临时写出一组拆分YAML。现有库级公开函数签名不擅自改变；旧应用配置和示例的迁移范围在对应切片列明，不默认增加双套CLI配置兼容框架。

```text
nyr / nyr chat
  -> 选择config.yaml -> 路径解析、models.json、选定凭据
  -> 本机服务的应用装配 -> 既有RAG核心 -> 资料包 / Chroma / BM25 / 模型
nyr chat -> 已有或本次启动的本机服务 -> 同一个应用装配
```

超过8个文件且新增一个本机服务入口。逻辑上分离CLI、客户端、服务适配和核心库，不拆成多个业务服务；核心库保持不依赖HTTP或UI。

## 3. 统一配置、目录与初始化

主文件建议包含config_version、paths、models_file、service、ingestion、encoding、sparse、storage、chroma、bm25、hybrid、rerank、evidence分组。现有算法/预算字段沿已验证配置，不借合并改检索参数或模型身份规则；模板参数来源为examples/core-demo的当前实际值，不带本机绝对路径。新增服务参数在实施Spec显式列出默认值与校验，不使用运行时散落常量。

| 路径 | 相对路径基准 | 说明 |
|---|---|---|
| paths.data_root | 所选config.yaml所在目录 | 建议模板为./data |
| models_file | 所选config.yaml所在目录 | 模板为models.json，不属于数据目录 |
| knowledge_base_root | 所选config.yaml所在目录 | 指向用户材料，绝对路径可用；不自动搬动或生成示例材料 |
| storage.storage_root | data_root | 模板为indexes |
| sparse.cache_dir | data_root | 模板为cache/sparse |
| 本地模型model_path | data_root | 按选定模型的独立目录保存；绝对路径可覆盖 |
| 服务日志等实际新增运行产物 | data_root | 只为首版确实消费的资源增加字段，不提前建未使用模块 |

绝对路径直接使用；处理用户主目录展开后统一为绝对路径，再进入已有路径与来源校验。索引内部artifacts/vectors/bm25及catalog.sqlite3继续由同一storage_root和知识库ID推导，不分别开放任意位置。改变配置不自动搬迁、覆盖或重建已有数据；迁移是另一项显式操作。

首次实际运行时初始化，不在pip构建/安装阶段写用户主目录；--help/--version不写文件。默认文件缺失时以不覆盖已有文件的方式创建config.yaml、models.json模板；失败须安全报告，不截断旧文件。已有配置损坏时保留现场并报错，不重置。模板不含真实凭据，不隐式摄取或下载模型；必要模型/凭据/材料未配置时，说明需要编辑的文件和字段并停止相应操作，不能声称可用。

## 4. models.json与凭据

models.json按模型标识管理服务协议、模型名称、地址、能力类型与模型专属参数。主配置通过模型标识选择Embedding和重排；后续Agent可以引用同一模型表，当前不实现Agent消费者。Embedding维度/允许响应模型/版本必须进入已有EncodingSettings身份；本地模型沿现有固定revision、来源文件清单与审计。

每个需要凭据的模型支持直接api_key或api_key_env二选一；同时配置两种来源拒绝，避免隐含优先级。环境变量不存在、为空或无效时明确失败，不回退到其他Key。新入口不强制额外密钥文件，也不自动从旧project_root/.env补读模型Key。选定模型之外的凭据不提前解析；本地无凭据模型不被要求填写API Key。

客户端不取得或输出模型Key；日志、异常、配置展示、服务状态和追踪不包含Key、原始HTTP响应或模型注册表原文。模型服务账号由使用者提供；不请求用户在聊天里发送凭据。现有Provider对SDK日志和环境副作用的保护保留；Chroma自己的环境配置消费需在接线中核对，不把统一模型凭据误解释为可以删除原安全边界。

## 5. 本机服务建议合同

技术建议采用FastAPI的请求/错误适配与lifespan，加Uvicorn管理本机监听，复用已存在的httpx客户端。原因是直接使用官方路由、请求约束与生命周期，避免自行维护HTTP解析器。FastAPI当前未安装，Uvicorn当前0.54.0；依赖只在实现授权后通过候选环境解析/验证，不修改当前环境或绕过固定SDK检查。官方来源见第10节。

本轮另只读核对本地Modular参考的src/mcp_server/server.py，其入口使用MCP SDK与stdio传输；不等同本方案的HTTP服务，不声称参考已提供此实现。HTTP适配是本项目为本机客户端和后续前端增加的应用边界；没有运行参考代码或setup。

首版单服务进程、单worker、无reload，监听固定本机回环地址；端口放入service配置。仅开放首版实际消费的健康/身份检查、摄取、查询、文档查看操作；上传、任意文件路径、远程停服、动态模型写入等不随之扩展。选定材料根目录来自配置，不由HTTP请求临时扩大。核心结果和错误的状态/来源/本次用量与激活结果不改写成假成功。

AGENTS.md要求API入口显式认证授权。具体适配建议为初始化时生成一个本机服务Token，chat自动读取使用，与模型API Key分离；所有业务/身份接口显式校验。它只解决本机入口访问，不建设用户体系；不实现远程绑定与远程访问配置。Token存储、对外健康字段及监听参数的具体schema在服务切片审核，不把本方案写成用户已选定认证实现。

启动/停止拥有资源的边界明确；关闭失败不掩盖主要错误。现有Provider有busy约束，不能把一套客户端无条件并发复用：首版采用显式有界业务执行与busy反馈，不增加持久队列或靠多worker复制模型解决。HTTP适配保持错误脱敏、输入预算、来源和revision门禁。

## 6. nyr chat生命周期

先核对目标服务的协议、认证与配置身份；端口连通不等于本项目服务存在。无服务才创建子进程，通过当前Python解释器和模块入口启动，不用shell字符串、fork限定实现或根据端口杀进程。就绪等待有明确截止、子进程退出检测和失败诊断；不以固定短sleep判断成功。

已有服务时只连接；自己启动的服务保存本次进程/实例所有权。用户退出、EOF或Ctrl+C后，仅清理本次拥有的服务。启动失败、端口被占用或身份不符时不继续进入假可用界面。客户端异常退出、服务异常退出与跨平台信号/句柄行为分别测试。

交互首版只做连续输入、当前查询证据展示、安全错误与退出；不引入会话记忆、回答生成、Agent任务或TUI框架。其他已有一次性命令及显式模型准备入口在CLI切片列清映射，复用原实现；没有业务需求就不增加命令别名和控制面。

## 7. 五个实施切片

| 顺序 | 交付 | 主要影响 | 本片验收 |
|---|---|---|---|
| 1 | 统一主配置、路径规则与首次初始化 | 新配置/路径模块、严格读取与模板、对应单元测试 | 显式/默认选择、已有文件不覆盖、错误保留、根目录与单项覆盖、中文/空格/Windows路径 |
| 2 | 模型配置表与实际应用装配 | 模型表/凭据适配、应用factory、原Provider和Settings消费者测试 | 两种Key来源、缺失/冲突失败、角色/参数/来源绑定、Key不泄露、相同配置产生相同核心行为 |
| 3 | 本机HTTP服务 | 服务模块、lifespan、入口访问和错误适配、原生接线测试 | 本机启动/停止、认证与预算、摄取/查询/查看实接线、busy/失败/活动版本边界 |
| 4 | nyr及chat自动启动/退出 | CLI、服务客户端、受控子进程与终端输入、CLI子进程测试 | 一个命令完成使用、连接已有服务、只清理自己启动的服务、启动失败/端口冲突/EOF/Ctrl+C |
| 5 | 安装包与三平台可重复验收 | pyproject、资源打包、正式依赖声明、跨平台IO适配、CI、安装文档 | 干净环境安装wheel，离开源码目录执行真实入口和合成闭环；三平台通过后才声明支持 |

每片实施前进一步确定其接口/文件清单和正常异常合同；先失败测试、最小实现、相关回归，再完整回归。字段变化同步消费者/序列化/持久化；单源码文件不超过500行。配置初始化不修改本仓库真实.env或已有用户配置；测试使用临时HOME/目录和合成凭据。

## 8. 安装包、跨平台与发布门槛

建议首发验收CPython3.12，Linux x86_64的glibc2.28+、Windows x86_64、macOS14+的arm64。具体Windows系统支持声明必须与实际验收环境对应，不以Windows CI存在覆盖所有Windows版本。GPU、本地Embedding部署、Linux/Windows ARM不列入首版保证。

2026-10-26只读查询PyPI JSON得到：chromadb1.5.9有manylinux x86_64/win_amd64/macOS arm64 wheel；torch2.14.1对应manylinux2.28 x86_64/win_amd64/macOS14 arm64；sentence-transformers6.1.0和bm25s0.3.13有通用wheel。此证据只说明发行文件存在，不证明完整依赖解析、Python ABI、模型计算或本项目跨平台运行成功。

固定版本约束从当前SDK身份检查、直接import和现有锁文件提取；不直接合并整个开发虚拟环境，也不把实验/测试专用依赖变成运行必需项。全部正式功能依赖默认安装，不使用可选extra拆本地重排。PyTorch在不同系统的发行包及其依赖可能很大，不承诺只下载CPU专用发行包或三平台安装体积相同。权重始终由用户明确准备。

必须检查目录fsync、文件权限、SQLite URI、进程终止与UTF-8终端等实际平台差异，尤其BundleStore._sync_directory对资料包/双索引/catalog的共同影响。先复现后修复，不空catch吞失败，不把无法执行的持久化动作说成已完成；Windows语义差异若影响已有数据保证，需报告具体证据后调整Spec。

构建wheel/sdist时明确包发现和模板资源清单，不带真实.env、models.json凭据、模型、知识库数据、测试运行产物或第三方克隆。安装验证从发行物进入，不靠仓库cwd、sys.path补丁或当前虚拟环境证明可安装。构建/元数据检查、pip check、正式确定性测试与合成原生闭环分别给实际输出。

包名拟为naiyue-rag，CLI为nyr；只读PyPI查询返回404不等于已保留名称或保证可创建。首发版本、项目许可证、目标发布账号/仓库和发布授权由用户在正式发布前确认；这不阻止先完成本地构建与验收。不得借此前git提交/push授权直接上传PyPI、创建release或新标签。

## 9. 验证、失败与回退

设计阶段只做文档结构、链接、来源和diff检查；不以历史2235全量结果证明新服务/安装包已经通过，不因文档变更运行模型或全量套件。

实施验收包括：首次/重复初始化、并发初始化不覆盖、错误配置/重复JSON键、凭据冲突/脱敏、根目录与绝对覆盖、原材料不动；新进程本机认证/服务身份、超预算和busy；chat启动/复用/停止/超时/异常清理；既有版本/来源/真实native双索引回读；三平台发行物干净安装与CLI生命周期。纯静态检查和PyPI文件清单都不替代L3实接线或目标主机测试。

失败不静默改端口、不回退其他Key/模型、不自动全量重建或搬迁目录。停止仅作用于本次拥有的子进程，退出不停止既有服务。回退代码不修改旧索引/原材料；已有用户配置不自动降版或覆盖。首次配置不完整应提供可操作提示并退出，使用者填写后重试。

## 10. 已核源码与官方来源

- [现有应用装配](../../naiyue_rag/app.py)、[凭据解析](../../naiyue_rag/core/credentials.py)、[严格YAML](../../naiyue_rag/core/yaml_config.py)。
- [资料包路径/同步](../../naiyue_rag/storage/bundle_store.py)、[活动版本](../../naiyue_rag/storage/index_catalog.py)、[模型准备](../../naiyue_rag/validation/prepare_local_model.py)。
- [PyPA依赖、安装命令入口](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)。
- [平台wheel标签](https://packaging.python.org/en/latest/specifications/platform-compatibility-tags/)。
- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/)、[Uvicorn监听与进程设置](https://uvicorn.dev/settings/)。
- PyPI只读元数据：[Chroma1.5.9](https://pypi.org/pypi/chromadb/1.5.9/json)、[PyTorch2.14.1](https://pypi.org/pypi/torch/2.14.1/json)、[Sentence Transformers6.1.0](https://pypi.org/pypi/sentence-transformers/6.1.0/json)、[BM25s0.3.13](https://pypi.org/pypi/bm25s/0.3.13/json)。
