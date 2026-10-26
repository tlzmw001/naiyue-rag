# Spec0027：本项目.env凭证加载与模型配置装配

日期：2026-10-14。用户明确要求支持本项目.env、一次配置后复用，模型继续按配置读取；本片实现该范围。Spec0026监督设计暂挂，不将本轮改动当其实现授权/真实服务验收。

## 1. 当前链路和目标

现有load_encoding_settings只读取严格YAML；EncodingSettings已有provider/base_url/model/维度/表示/时限等完整配置。OpenAICompatibleEmbedding(settings,api_key=...)只接显式Key，SDK/Provider可供文档Batch和Query共用。当前没有根.env，当前环境python-dotenv1.2.4已由Chroma依赖安装并在旧锁文件中记录；本轮复用，不安装/升级依赖。

固定参考main/f658c5a4011c8b826707a65a3b11ce9301b0626f的OpenAIEmbedding（src/libs/embedding/openai_embedding.py:69–77）在显式参数、settings.embedding.api_key、OPENAI_API_KEY间回退。本片沿显式装配职责，差异为不把Key存YAML、不猜通用OPENAI_API_KEY、不把.env全量导入进程；本机已核src搜索无load_dotenv/dotenv_values直接调用，不据此断言整个项目没有启动脚本处理。无参考代码复制。

新增路径：

```text
load_embedding_provider(settings_path, project_root=..., key_env=...)
  → load_encoding_settings（provider/model/base_url/维度）
  → resolve_api_key（命名环境变量优先，否则显式项目根.env）
  → OpenAICompatibleEmbedding(settings, api_key=已解析值)
  → 调用方拥有close/context生命周期，继续装配Dense/Sparse/Batch/Query
```

这是应用装配入口，不在core配置加载/包import/Provider内隐式读.env。既有函数签名、load_encoding_settings只读YAML行为不变；不建通用工厂注册层或空厂商适配。

## 2. 接口和优先级

- core/credentials.py：resolve_api_key(project_root,key_env,*,environ=None)->str；environ默认当前os.environ，可显式映射供调用方/测试注入。
- encoding/bootstrap.py：load_embedding_provider(settings_path,*,project_root,key_env)，公开导出该函数；配置失败先于凭证读取、SDK构造/IO。
- project_root必须显式目录，解析到绝对根；只读取该根/.env，不按cwd/配置路径向上搜索、不读其他.env或自动后缀。
- key_env必须显式合法环境变量名，不默认绑定Zhipu/OpenAI。根模板推荐NAIYUE_RAG_ZHIPU_API_KEY；其他云/自部署调用方可配置自己的命名Key。
- 命名环境变量存在时优先，只校验其值，不读取.env；空值/非法值明确credential_invalid，不回退文件掩盖错误。
- 命名变量不存在时读该项目.env；缺文件/缺字段为credential_not_found；空值/裸字段/非ASCII可打印或空白Key为credential_invalid。
- 配置整个文件错误为credential_env_invalid，重复字段拒绝；关键读取/路径错误为credential_file_error，超64KiB为credential_file_too_large；只输出固定码，不含Key/原文/路径/底层异常。

UTF8（可有BOM），复用固定python-dotenv1.2.4的parse_stream解析注释/export/引号/等号；显式检查Binding.error和重复键，避免静默跳过错误。该parser是依赖内部接口，固定版本与解析回归约束它；不自行实现.env语法。无变量插值、shell执行或变量展开，未知字段不导出，os.environ不变；selected value沿Provider的非空ASCII无空白约束，其他值不触发配置/SDK行为。

文件只接受普通文件，拒绝.env symlink/FIFO/目录；读前lstat/打开后fstat核文件身份、使用可用O_NOFOLLOW/O_NONBLOCK保护，读取有界。显式项目根允许规范化路径，不自动寻找其他项目。文件和key_env错误不把供应商文本记录到日志；返回字符串仅在装配局部传给Provider，不进入YAML/模型空间身份/结果/报告。

## 3. 模型与后端边界

模型/base_url/维度仍从EncodingSettings的YAML读取，.env只提供所选凭证。新增config/encoding.example.yaml演示智谱embedding-3/2048/null维度请求、raw/contexts_then_view、空前缀与显式运行预算；示例中没有Key。它是可修改的起点，不作为所有模型最佳参数。

目前真实实现的协议为openai_compatible；OpenAI兼容的自部署端点可配置不同base_url/model/维度及响应别名，按相同合同发起请求。此能力本轮用MockTransport核验不同地址/模型实际到SDK，不声称已部署/验证本地服务。Provider当前要求非空Key；无鉴权本地服务和Ollama原生/api/embed等协议仍是后续适配，不偷偷填占位Key或创建空实现。Claude生成协议也不等同Embedding协议。

## 4. 修改范围与验收

新增core/credentials.py、encoding/bootstrap.py、tests/test_credentials.py、tests/test_embedding_bootstrap.py、根.env.example、config/encoding.example.yaml；修改包__init__.py公共导出、.gitignore仅放行根.env.example、requirements-encoding两文件显式声明已经安装/锁定的python-dotenv1.2.4及复用现有wheel hash。共10源码/测试/模板/依赖文件；无新安装/版本变化，不修改真实.env或复制旧聊天Key，不改现有编码器/实验API。

新功能TDD：先缺入口红灯；环境优先/空值不回退、根目录限定/no upward discovery、无os.environ副作用、注释/引号/带等号Key/不插值、重复/畸形/坏UTF8/超限、缺失/目录/symlink/FIFO/读权限错误、哨兵不入日志；实际YAML→凭证→真实SDK MockTransport→Dense/Query，模型/URL/Key正确且客户端关闭。不同兼容端点/模型用独立配置，不默认继承旧model alias。坏配置先失败、无凭证/坏.env时0网络、旧只读YAML加载测试保持。

全量pytest tests、compileall/pip check/diff，依赖版本和已有资产hash核对。无真实模型请求/索引/质量成绩；应用构建尚未设立。失败日志固定码，外层没有返回Provider则不创建客户端；成功由调用方close，无全局状态需要回滚。实际运行配置和.env由用户按模板填写，助手本片只提供空模板。

## 5. Spec0026后续接线

本片结束后更新Spec0026凭证规则：监督父进程在固定项目根解析.env/命名环境变量，再只将选中Key注入worker专用环境；worker仍显式构造Provider，不向子进程传整份.env。父进程模型仍读原EncodingSettings，不与凭证混写。新监督入口/硬截止/真实POST继续待实施与验收，不在本片顺带开发。

## 6. 实施与实际验证

已完成上述10文件范围。新源码credentials76行/bootstrap11行；108份原源码/测试/依赖及ignore快照只变root导出、.gitignore和两个encoding依赖声明4文件。原测试、编码器和已安装包版本保持；复用既有python-dotenv1.2.4锁定hash，无安装/升级。

预期红灯为缺credentials模块/装配入口，最小实现后43项绿灯；另补文件描述符创建流失败的回归，确认未关闭fd红灯后修源码，最终44项通过。没有放宽断言或改测试基础设施。

```sh
.venv/bin/python -m pytest -q tests/test_credentials.py tests/test_embedding_bootstrap.py --tb=short
# 44 passed in 1.26s
.venv/bin/python -m pytest -q tests --tb=short
# 1211 passed in 82.63s (0:01:22)
.venv/bin/python data/research/spec0027-evidence/wiring_probe.py
# temporary synthetic project .env -> YAML -> actual SDK/MockTransport -> real Sparse/Query
# model_from_yaml=true, url_from_yaml=true, selected_key_reached_sdk=true
# process_environment_unchanged=true, query_result_roundtrip=true, provider_closed=true
# mock_http_requests=1, network_attempts=0, real_model_requests=0, real_project_env_modified=false
.venv/bin/python -m compileall -q naiyue_rag experiments tests
# exit 0，语法检查；应用构建未设立/不适用
.venv/bin/python -m pip check
# No broken requirements found.
git diff --check
# exit 0
```

L1：两个模块、根公共入口、空.env.example及无凭证YAML存在，git只放行根模板，真实.env仍忽略。L2：有界真实dotenv解析/固定错误/优先级/无环境副作用及模型装配真实实现。L3：独立YAML和临时合成.env由正式load_embedding_provider读取，实际SDK MockTransport收到正确认证、地址、model，再接QueryEncoder/真实jieba及JSON/关闭；另一个兼容本地地址/模型的配置也经MockTransport验证传递，无真实本地部署证据。

本轮没有读取或新建根真实.env、保存用户Key或模型POST；实际根.env仍不存在。凭证加载成功不能当Key服务权限/余额有效。用户复制空模板填写一次后可用新入口读取；原只读YAML/旧实验CLI不自动获得.env功能。单独验收入口Spec0026凭证设计已同步，但其worker/硬截止仍为未实施提案。

用户本轮明确工程需求，未做新完整课堂；理解/独立调试证据保持未评估。唯一下一步：回到Spec0026确认受监督验收切片范围，再实现离线监督；真实服务边界与Key就绪另按同一Spec执行。
