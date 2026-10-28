# Spec0053：首版第2片／models.json、凭据与实际运行时

日期：2026-10-26。依赖0052；本片按已授权首版目标实施，不改变现有核心公开签名。

## 1. 数据流和边界

load_application_settings→load_model_registry→选中模型的Settings/凭据→ApplicationRuntime→原IngestionPipeline/DocumentManager/RetrievalPipeline。Registry读取和构造只验证配置，不解析未使用环境变量、不加载权重或发请求；documents不要求Embedding/重排Key。模型权重路径相对data_root，注册表位置相对主配置。旧resolve_api_key和旧app入口保留，新入口不回读.env或生成拆分配置文件。

## 2. Registry合同

新增core/model_registry.py，load_model_registry(ApplicationSettings)读取models_file，根字段精确config_version=1、models字典。模型ID沿0052标识规则；JSON重复字段、NaN、超64KiB、非普通文件和符号链接明确失败，错误和repr不含文件内容/Key。

三类条目：embedding字段为现有EmbeddingSettings全部字段加kind及一种凭据；chat字段为现有LLMRerankSettings全部字段加provider=openai_compatible、kind及一种凭据；cross_encoder字段为CrossEncoderSettings全部字段加kind，无凭据。每项结构/值严格核验，但环境变量只在对应模型实际使用时读取。

api_key和api_key_env二选一，直接Key使用既有非空可打印ASCII约束；环境变量名沿现有ASCII规则。未设置/为空/非法时明确失败，不回退到另一个Key或.env。Registry.encoding_settings()使用实际Embedding参数与统一配置的representation/runtime构造EncodingSettings，模型注册表标识不进入模型空间ID；重排role和model.kind须匹配，不允许把Embedding当聊天模型。

## 3. 运行时

新增runtime.py的ApplicationRuntime，持有经过重新校验的配置副本、Registry和DocumentManager，按需加载一个Embedding Provider及选定重排后端，明确拥有ExitStack和close。公开query、ingest、documents返回原核心结果字典；进入操作时用非阻塞业务锁，竞争返回application_busy，不隐式排队或重试。关闭只在无活动操作时执行，已关闭对象不可复用；清理失败不得掩盖主错误。

documents只走管理快照，零模型请求。ingest按配置材料根调用原增量链和revision；query消费固定版本、Hybrid/Rerank/ResponseBuilder，模型调用/用量沿原合同；none重排不读取重排Key，cross_encoder只读已有且审计通过的权重。准备模型另沿prepare_local_model，不在装配时下载。旧库级配置及实验消费者不由本片整体迁移或删除。

## 4. 影响与验证

core/model_registry.py、runtime.py、根导出及tests/test_model_registry.py、tests/test_application_runtime.py；只扩已有错误码边界，不引新依赖。本片不接HTTP或nyr，不改真实配置。先验证缺模块/缺接线的失败测试，再最小实现。

测试覆盖直接/环境Key与冲突、未知ID/role、坏模型参数、重复JSON/尺寸/文件安全、未选择Key不解析、模型空间ID保持、权重路径、脱敏；实际SDK MockTransport→原生BM25/版本→既有Chroma测试边界→摄取/重复/查询/列表闭环、不同模型Key、选定后端不回退、busy/close/关闭后操作。后续服务/打包切片补真实原生Chroma与发行物新进程验证，不把FakeClient当ANN证明。

```sh
.venv/bin/python -m pytest -q tests/test_model_registry.py tests/test_application_runtime.py --tb=short
.venv/bin/python -m pytest -q tests/test_application_settings.py tests/test_configuration_bootstrap.py tests/test_core_app.py tests/test_credentials.py tests/test_ingestion_pipeline.py tests/test_evidence_response.py --tb=short
.venv/bin/python -m pytest -q tests --tb=short
```

L1文件存在；L2严格身份/来源/凭据和资源生命周期；L3实际运行时串原核心与SDK替身，不声称已具备HTTP服务或真实模型质量。任何新增配置字段先同步0052、模板及对应测试，避免主配置/Registry双重维护同一模型参数。

## 本片实测

先红24 failed/4 errors（模块尚无），实现后28 passed in3.15s。补测编码器部分构造失败先1 failed（已创建Provider未关闭），改为pending ExitStack完成后再交付所有权；扩展174 passed in35.43s，完整`python -m pytest -q tests --tb=short`为2311 passed in450.54s。模型请求为SDK MockTransport，BM25原生、Chroma在本片为既有FakeClient边界；0056另以发行物验证真实Chroma，不能把二者混称。真实Key/材料/厂商请求0。
