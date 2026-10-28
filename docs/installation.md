# 本机安装与使用（首版候选）

本页对应0.1.0正式发行源码。PyPI上传完成并通过公开安装验证后，使用`pip install naiyue-rag==0.1.0`；上传前可从源码或同版本本地wheel安装。

## 安装

首轮使用64位CPython3.12。目标为Linux x86_64、Windows x86_64、macOS Apple Silicon，不支持Intel Mac；目标平台CI通过前不声称已验收。macOS本机与其他主机证据见Spec0056。全部正式功能依赖默认安装，包括PyTorch、Transformers、Sentence Transformers；允许联网下载依赖，安装体积随平台不同，安装过程不下载模型权重。旧实验的独立虚拟环境不随发行物提供。

```sh
python3.12 -m venv .venv
# Linux/macOS：source .venv/bin/activate
# Windows PowerShell：.venv\Scripts\Activate.ps1
python -m pip install .
# 或使用已经构建的本地候选wheel：
# python -m pip install /绝对路径/naiyue_rag-0.1.0-py3-none-any.whl
nyr --help
```

## 配置与首次运行

```sh
nyr
```

不带子命令时在前台启动本机服务，默认只监听127.0.0.1，端口来自配置（模板8000）。首次实际运行会在用户目录创建`.naiyue-rag/config.yaml`和`models.json`，已存在文件不覆盖。`--help`/`--version`不会创建文件。未填写模型Key仍可启动、查看空知识库；摄取/查询时缺少必要凭据会明确失败。

按Ctrl+C停止后编辑配置；材料、模型和API Key由使用者提供。主配置集中运行参数；模型名、端点、维度、版本与凭据在models.json。默认材料路径是配置目录下的`knowledge`，请创建目录并放入自己的Markdown；不会自动摄取或填示例数据。

可以在models.json某项中将`api_key_env`改为`api_key`并填入Key，或者保留`api_key_env`并在启动进程的环境设置相应变量。二者不能同时出现；不会从旧.env为新入口补读Key。不要把填写后的models.json提交或分享；默认POSIX文件权限为仅当前用户读写，Windows还需遵循用户目录的ACL。

路径以主配置所在目录为基准：

```yaml
paths:
  data_root: ./data
  knowledge_base_root: ./knowledge
models_file: models.json
```

`storage.storage_root`、`sparse.cache_dir`及模型表的本地`model_path`相对data_root；每项都可用绝对路径覆盖。索引内部布局由一个storage_root管理。改变位置不自动搬迁旧数据；路径不允许`..`穿越或符号链接。`--config`完整选择一份统一配置，不与用户目录叠加，显式不存在/坏配置会报错。

```sh
nyr --config /绝对路径/config.yaml
nyr chat --config /绝对路径/config.yaml
```

服务运行期间不热加载配置或模型表；模型环境变量也属于服务进程环境，修改后需停止并重新启动。同端口的配置/协议/认证不匹配会报错，不会自动换端口或停止其他进程。

## 摄取与终端检索

```sh
nyr documents
nyr ingest --expected-revision 0
nyr chat
# 一次查询：
nyr query '开关开启时有哪些边界条件？' --expected-revision 1
```

未有活动版本时revision为0。之后从documents返回的active.revision读取当前值，继续摄取时显式传入。revision变化或结果不确定时先查看状态，不盲目重试写操作；`--force`会按既有合同强制重新计算。

`nyr chat`在无服务时自动启动自己的本机服务并进入终端，有匹配服务时直接连接。一个终端即可使用；`/exit`、EOF或Ctrl+C退出时仅关闭本次启动的服务，已有服务继续运行。父进程异常结束时专用管道EOF通知其子服务退出；关闭超时只终止本次持有的子进程并报告固定错误，不按端口杀进程。

当前chat展示检索证据、原文位置和错误，尚未生成自然语言回答，不维护Agent记忆。一次性命令输出核心JSON，含活动版本、查询指纹与本次用量。没有数据时返回真实空状态。

如需本地重排，先显式准备固定版本的模型，再选择该条目：

```sh
nyr models prepare local-reranker
```

修改config.yaml的rerank.backend为cross_encoder、rerank.model为local-reranker后重启。准备沿原有来源/大小/完整性审计；不会在普通查询中隐式下载权重。也可将backend设为none且model为null，关闭重排。

## 验证与边界

服务Token与模型Key分离，chat自动使用所选配置的服务Token。首版接口只供本机调用；无跨域、局域网/公网、多用户权限、上传、前端或Agent。HTTP接口见Spec0054。Windows保留文件同步/SQLite事务/完整性审计，但目录元数据不保证与POSIX相同的突然断电持久性；不可把正常恢复测试当断电测试。

```sh
python -m pip install -r requirements-dev.txt
python scripts/run_formal_tests.py
python -m build
python scripts/inspect_distribution.py dist/naiyue_rag-0.1.0-py3-none-any.whl dist/naiyue_rag-0.1.0.tar.gz
python scripts/validate_candidate.py --wheel dist/naiyue_rag-0.1.0-py3-none-any.whl --venv /新的临时目录/venv
```

干净安装smoke使用合成本机模型HTTP服务与原生Chroma/BM25/SQLite，离开源码目录执行真实入口，验证重复摄取、源目录离线后查询、服务复用和退出；不调用真实厂商或下载权重。历史实验测试继续保留，其私有旧快照/环境不能作为新克隆的隐式依赖；本机全量与正式独立套件分别记录。

正式PyPI发布前仍须确认包名、版本、许可证、目标账号，并取得上传授权；三平台CI通过才形成对应支持证据。

标签发布、PyPI Trusted Publisher和GitHub环境的配置见[发布文档](publishing.md)。发布验证按源码实际版本选择制品；不会自动修改版本或选择许可证。

本地 Embedding 的 Ollama 接入、Mac 实测结果和 Linux 无 GPU 开发机验收步骤见[本地 Embedding 操作说明](local-embedding.md)。wheel 另提供 `nyr-embedding-audit` 命令；安装 Python 包后，仍须另装 Ollama、下载同版本 GitHub Release 的模型附件并核对 SHA-256。该验证使用独立配置和数据目录，不会自动切换已有知识库的模型或索引。
