# Spec0052：首版第1片／统一配置、路径与默认初始化

日期：2026-10-26。状态：用户已授权实施Spec0051；本片45项先红后绿，相关158回归通过，完整回归2280 passed。仅第1片配置能力，不提前声称服务、模型装配或nyr已经可用。

## 1. 当前流与目标

旧app.load_app_settings读取主YAML的文件路径，再由各模块load_*读取独立YAML。新增load_application_settings(config_path=None)读取一份主配置，直接构造实际Settings和模型选择参数；复用严格YAML和现有from_dict，保留原公开加载函数和旧应用入口。本片不触发Provider、索引、分词资源或模型加载。

默认配置与模型模板随naiyue_rag/resources提供，通过importlib.resources读取，后续打包片必须包含它们。资源只包含公开示例参数/模型身份和环境变量名，不含真实Key或本机绝对路径。应用层模型标识不进入已有EncodingSettings的模型身份，实际解析由第2片完成。

## 2. 主配置format 1

顶层精确字段：config_version、paths、models_file、service、ingestion、encoding、sparse、storage、chroma、bm25、hybrid、rerank、evidence。未知/缺失字段、错误类型、重复YAML字段/别名及不支持版本明确拒绝。ApplicationSettings为配置源位置和已解析路径/模块Settings的聚合，repr不含完整配置或服务Token。

| 分组 | 合同与模板来源 |
|---|---|
| config_version | 非bool整数1 |
| paths | data_root=./data，knowledge_base_root=knowledge；不创建材料/数据目录 |
| models_file | models.json，相对主配置文件目录 |
| service | host=127.0.0.1；port=8000；startup_timeout_seconds=30、shutdown_timeout_seconds=10、request_timeout_seconds=180；max_request_bytes=1048576；access_token为初始化时生成的URL安全随机值，32–128字符 |
| ingestion | 当前示例size=1000/overlap=300；显式markdown-source-zh-v2，沿IngestionSettings校验 |
| encoding | model为模型表标识embedding；representation/runtime沿当前encoding.example.yaml。此时严格验证表示/运行参数，第2片加入真实模型定义后构造EncodingSettings |
| sparse | 当前示例参数；cache_dir默认cache/sparse，相对data_root |
| storage | 当前示例限额；knowledge_base_id=default；storage_root默认indexes，相对data_root |
| chroma/bm25/hybrid/evidence | 当前示例实际参数，直接交已有Settings.from_dict |
| rerank | backend为none/llm/cross_encoder；model为模型表标识，none时必须null；top_k/max_candidates/max_input_characters沿现有RerankSettings，enabled由backend推导 |

service字段本片只验证/传递，不启动监听；端口不接受0或bool。模板中的access_token为null，只供初始化填充；显式配置留空则报错，不修改用户文件。不会将尚未实现的agent字段作为任意字典接受。

## 3. 路径

config_path指定时读取指定文件，缺失不生成、不搜索其他配置、不写HOME。省略时选择Path.home()/.naiyue-rag/config.yaml并执行第4节默认初始化。models_file和knowledge_base_root相对所选配置目录；data_root也相对配置目录；storage_root/cache_dir相对data_root。绝对路径直接使用，~展开到用户目录；不根据cwd解释模块路径。

解析后交付绝对路径，沿现有禁止控制字符、空路径、..、符号链接和文件冒充目录等边界；已有根目录上的系统路径先按明确来源解析。不存在的材料、索引/缓存目录可在配置阶段表示，不为配置加载自动创建。相对配置文件路径本身由调用时cwd定位，之后其他路径不随cwd变化。Windows路径的实际语义在Windows目标环境另验，不用macOS的PureWindowsPath当主机证明。

## 4. 初始化与失败

只在默认配置缺失时创建默认目录和模板：先models.json，后config.yaml；models.json已存在则逐字保留。config.yaml已存在时不生成或修复其他文件，只读取它。默认models模板format 1记录embedding、chat重排、本地CrossEncoder的公开参数；凭据使用api_key_env，第2片才读取/解析此文件。

新文件先写同目录的私有临时文件、flush/fsync后用不覆盖目标的原子发布方式发布；默认目录新建时限制当前用户，文件新建为用户私有，不修改既有目录或文件权限。并发初始化不能看到半个配置、不能覆盖胜者Token；创建/写入/发布/清理失败均以固定码记录，不输出配置原文。临时文件只清理本次创建的实例，不清理用户资产。进程在模型模板发布后中断，下次可保留已完成模板继续；不声称两文件是跨文件事务。

初始化结束仍不代表模型或材料可用；配置加载不检查环境Key、不下载模型、不执行网络或建立知识库。模型文件缺失、Key缺失和材料不存在的业务前置条件由后续消费者检查。本片不操作真实HOME，测试全部通过临时HOME或显式配置路径执行。

## 5. 接口、影响及接线

- core/application_settings.py：ApplicationSettings及service/encoding/rerank选择的严格类型，公开load_application_settings(config_path=None)。
- core/application_paths.py：本入口共用的路径解析。
- core/configuration_bootstrap.py：默认模板初始化与原子不覆盖写入。
- resources/config.yaml、resources/models.json及包资源入口：可复制模板，不是运行配置；不修改根.env或旧示例。
- 根__init__.py导出新入口；tests/test_application_settings.py、tests/test_configuration_bootstrap.py新增确定性回归。

本片L3是新入口真实加载模板并构造各模块配置，不是假装已接入旧CLI；模型装配/HTTP/nyr消费分别由后续切片完成。没有新增运行依赖或依赖升级，没有服务Token网络暴露。单源码文件不超过500行，不把一次性调用强行抽为通用配置框架。

## 6. 验收

预期红灯先运行新增配置与初始化测试，证明入口/统一schema/路径/默认初始化缺失。覆盖默认和显式读取、精确字段/版本/数值、配置不完整、YAML重复/别名、UTF-8及64KiB限额、根目录/绝对覆盖/~/cwd不敏感、未知后端/模型引用形状；首次/重复/并发初始化、用户编辑保留、已有模型文件保留、不可写/非目录/符号链接/文件写失败、旧配置不自动修复，且无网络/材料/索引副作用。

命令：

```sh
.venv/bin/python -m pytest -q tests/test_application_settings.py tests/test_configuration_bootstrap.py --tb=short
.venv/bin/python -m pytest -q tests/test_settings.py tests/test_core_app.py tests/test_credentials.py tests/test_encoding_settings.py tests/test_sparse_encoding_settings.py tests/test_cross_encoder_reranker.py --tb=short
.venv/bin/python -m pytest -q tests --tb=short
.venv/bin/python -m compileall -q naiyue_rag tests
.venv/bin/python -m pip check
git diff --check
```

相关测试实际文件名先按仓库核对再执行，不能将不存在的目标当成功。本片未设安装构建，构建仍不适用；不能用compileall代替功能测试。回退仅涉及新增入口/模板/导出，不动已有用户配置、原材料、索引或依赖。通过后继续第2片模型表/凭据/应用接线，不要求用户再次批准已确认字段方向。

## 2026-10-26实施记录

新增45项测试先45 failed in0.41s，缺统一入口/初始化模块；实现后45 passed in0.34s。既有配置、CLI、凭据、编码和本地重排相关158 passed in10.30s。compileall退出0，pip check为No broken requirements found.，git diff --check退出0。模板写入使用同目录临时文件+fsync+不覆盖hard link发布，测试证明四线程得到同一完整配置/Token，已有配置和models文件原字节保留。L1新模块/资源存在；L2严格schema/路径/原子初始化；L3公开load_application_settings真实构造已有模块Settings，后续服务/CLI尚未接线。

本片完整命令`.venv/bin/python -m pytest -q tests --tb=short`得到2280 passed in443.48s（0:07:23）；本次收集的是第1片源码与45项新测试。通过后进入第2片实现；第2片新增测试另有24 failed/4 errors的预期红灯，不计入本片完整结果。

收尾补充：临时流构造失败的描述符泄漏先1项红灯，再显式转交fd所有权并在失败时关闭；旧文件仍不覆盖，临时文件清理/关闭失败均固定码可观察。后续与服务/CLI/发行合同相关84 passed in7.05s。最终全量见0056，未触碰真实HOME配置。
