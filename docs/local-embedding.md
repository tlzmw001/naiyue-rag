# 本地 Embedding：Mac 验证与 Linux 开发机验收

状态（2026-10-27）：Mac 上已用 Ollama 0.40.11、`qwen3-embedding:0.6b` 和正式 `nyr` 入口跑通隔离合成知识库；从准备作为 Release 附件的同字节 GGUF 重新导入后也通过协议探针。Linux 32 核／64 GB／无 GPU 由使用者在目标机执行下述验收；尚无该机器的结果。以下 `pip install` 和 Release 下载步骤须等 0.1.0 正式版本与模型附件均公开后执行。此文不修改默认模型配置，也不迁移现有知识库。

## 已验证的接入方式

当前 `OpenAICompatibleEmbedding` 可直接使用 Ollama `/v1/embeddings`。选中模型在 `models.json` 中保持 `provider: openai_compatible`；`base_url` 指向本机 Ollama 的 `/v1/`，`model` 与 `allowed_response_models` 均为本次导入的模型名，`expected_dimensions` 为 1024，`model_revision` 记录目标机实际导入后的完整 digest。OpenAI SDK 必须收到非空 `api_key`，本机 Ollama 忽略该值，因此隔离配置用非密钥占位值。重排设为 `none`，避免外部聊天模型请求；已有本地 CrossEncoder 可另行选用。[Ollama 兼容接口](https://docs.ollama.com/api/openai-compatibility)、[Qwen 模型卡](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B)

**输入边界必须先查。** 本机 Ollama 默认上下文为 4096 token；Mac 实测 6000 字的合成输入在原生 `/api/embed` 加 `truncate=false` 时返回 400，在兼容 `/v1/embeddings` 却返回 200，报告只处理 4095 token。`max_input_utf8_bytes` 是字节限额，不能直接当 token 数。以下验收先统计最终 Embedding 输入，再用原生无截断请求逐条核验，产品调用仍走兼容接口。[Ollama 上下文说明](https://docs.ollama.com/faq)、[原生 Embedding 接口](https://docs.ollama.com/api/embed)

## Linux 目标机操作

以下命令从正式发布的 Python wheel 安装，不依赖源码目录；项目依赖由 `pip install naiyue-rag` 根据 wheel 元数据安装，Ollama 程序和模型文件单独准备。首轮使用 Linux x86_64、64 位 Python 3.12。公司机器上的材料目录由你指定；新索引写在单独的验收目录，不碰当前活动知识库。

先核对目标机基础条件；当前 PyPI 上 `torch==2.14.1` 的 Linux x86_64 wheel 标为 `manylinux_2_28`，因此 glibc 低于 2.28 的主机不能直接沿用这套 wheel。普通安装还会下载 PyTorch 的 Linux 依赖和约 639 MB 的模型附件，请确认可用磁盘空间。若条件不符，先停止并回传脱敏版本与剩余空间，不要尝试覆盖系统 Python。[PyTorch 文件列表](https://pypi.org/project/torch/2.14.1/#files)

```sh
uname -m
ldd --version | head -1
python3.12 --version
df -h "$HOME"
```

1. 安装 Ollama（已安装则跳过），检查本机服务。安装命令和 CPU 用法见[官方 Linux 文档](https://docs.ollama.com/linux)。如果公司要求由管理员安装，请沿用其安装方式。

   ```sh
   curl -fsSL https://ollama.com/install.sh | OLLAMA_VERSION=0.40.11 sh
   curl -fsS http://127.0.0.1:11434/api/version
   ss -ltn | grep ':11434'
   ```

   安装器若已启动服务，不要再启动第二份；若尚无服务，才在单独终端运行 `OLLAMA_NO_CLOUD=true OLLAMA_HOST=127.0.0.1:11434 ollama serve`。确认监听只在目标机回环地址后检查版本：

   ```sh
   ollama --version
   ollama list
   ```

   `ss` 的监听地址应为 `127.0.0.1:11434`（或等价的本机回环地址）；若显示 `0.0.0.0:11434` 或外网地址，先调整服务配置再载入模型和资料。系统服务按公司的服务管理方式设置 `OLLAMA_NO_CLOUD=true` 和回环监听；当前 shell 的环境变量不会改变已启动的服务。模型从本项目 Release 下载后本机导入，不执行 `ollama pull`。

2. 在**新的验收目录**安装 Python 包并下载同版本 Release 模型附件。包版本对应 `v<版本>` Release；若尚无这个 Release 或附件，停在这里。模型 SHA-256 必须匹配[来源清单](model-assets/qwen3-embedding-0.6b-q8_0.json)。

   ```sh
   export NYR_ACCEPTANCE_ROOT="$(mktemp -d "$HOME/nyr-local-embedding-XXXXXX")"
   python3.12 -m venv "$NYR_ACCEPTANCE_ROOT/venv"
   "$NYR_ACCEPTANCE_ROOT/venv/bin/python" -m pip install naiyue-rag
   export NYR_PYTHON="$NYR_ACCEPTANCE_ROOT/venv/bin/python"
   export NO_PROXY="${NO_PROXY:+$NO_PROXY,}127.0.0.1,localhost"
   export NYR_VERSION="$("$NYR_PYTHON" -c 'from importlib.metadata import version; print(version("naiyue-rag"))')"
   export NYR_OLLAMA_MODEL="naiyue-qwen3-embedding:$NYR_VERSION"
   export NYR_MODEL_FILE="$NYR_ACCEPTANCE_ROOT/Qwen3-Embedding-0.6B-Q8_0.gguf"
   export NYR_RELEASE_BASE="https://github.com/tlzmw001/naiyue-rag/releases/download/v$NYR_VERSION"
   curl -fL --retry 3 -o "$NYR_MODEL_FILE" "$NYR_RELEASE_BASE/Qwen3-Embedding-0.6B-Q8_0.gguf"
   curl -fL --retry 3 -o "$NYR_ACCEPTANCE_ROOT/Qwen3-Embedding-0.6B-Q8_0.LICENSE.txt" "$NYR_RELEASE_BASE/Qwen3-Embedding-0.6B-Q8_0.LICENSE.txt"
   curl -fL --retry 3 -o "$NYR_ACCEPTANCE_ROOT/qwen3-embedding-0.6b-q8_0.json" "$NYR_RELEASE_BASE/qwen3-embedding-0.6b-q8_0.json"
   printf '%s  %s\n' '06507c7b42688469c4e7298b0a1e16deff06caf291cf0a5b278c308249c3e439' "$NYR_MODEL_FILE" | sha256sum -c -
   printf 'FROM %s\n' "$NYR_MODEL_FILE" > "$NYR_ACCEPTANCE_ROOT/Modelfile"
   if ollama list | awk 'NR > 1 { print $1 }' | grep -Fxq "$NYR_OLLAMA_MODEL"; then
       printf '模型别名已存在，停止以免覆盖: %s\n' "$NYR_OLLAMA_MODEL" >&2
       exit 1
   fi
   ollama create "$NYR_OLLAMA_MODEL" -f "$NYR_ACCEPTANCE_ROOT/Modelfile"
   ollama list
   ```

   命令会在 `NYR_OLLAMA_MODEL` 同名模型已存在时停止，避免覆盖。`ollama create` 得到的 manifest digest 可以与上游 `ollama pull` 的 digest 不同；以下载文件 SHA-256 和下方无截断探针作为权重与输入验证。上面的模型别名包含 Python 包版本，便于与其他版本区分。[Ollama GGUF 导入说明](https://docs.ollama.com/import)

3. 在相同验收目录创建独立配置。先设置已获准的资料目录；不要把真实路径、`config.yaml` 或完整查询结果回传到聊天。配置模板从已安装的 Python 包读取，生成随机本机服务 Token。

   ```sh
   printf '已获准的 Markdown 资料目录绝对路径: '
   read -r NYR_KNOWLEDGE_ROOT
   export NYR_KNOWLEDGE_ROOT
   ```

   ```sh
   "$NYR_PYTHON" - <<'PY'
   import json, os, secrets, socket, urllib.request, yaml
   from importlib.resources import files
   from pathlib import Path

   root = Path(os.environ['NYR_ACCEPTANCE_ROOT']).resolve()
   knowledge = Path(os.environ['NYR_KNOWLEDGE_ROOT']).expanduser().resolve(strict=True)
   if not knowledge.is_dir() or (root / 'config.yaml').exists():
       raise SystemExit('knowledge directory invalid or acceptance config already exists')
   model = os.environ['NYR_OLLAMA_MODEL']
   opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
   with opener.open('http://127.0.0.1:11434/api/tags', timeout=10) as response:
       installed = json.load(response)['models']
   digest = next((item['digest'] for item in installed if item['name'] == model), None)
   if not digest:
       raise SystemExit('imported model missing; stop and report')

   config = yaml.safe_load(files('naiyue_rag.resources').joinpath('config.yaml').read_text())
   config['paths']['knowledge_base_root'] = str(knowledge)
   config['service']['access_token'] = secrets.token_urlsafe(32)
   with socket.socket() as listener:
       listener.bind(('127.0.0.1', 0))
       config['service']['port'] = listener.getsockname()[1]
   config['service']['request_timeout_seconds'] = 3900
   config['encoding']['runtime'].update(batch_size=8, max_requests=125,
       max_input_utf8_bytes=3000, timeout_seconds=300, deadline_seconds=3600)
   config['rerank'].update(backend='none', model=None)
   with (root / 'config.yaml').open('x') as output:
       yaml.safe_dump(config, output, allow_unicode=True, sort_keys=False)
   embedding = dict(kind='embedding', provider='openai_compatible',
       base_url='http://127.0.0.1:11434/v1/', model=model,
       expected_dimensions=1024, request_dimensions=None,
       model_revision=digest, allowed_response_models=[model],
       api_key='ollama-local-placeholder')
   with (root / 'models.json').open('x') as output:
       json.dump({'config_version': 1, 'models': {'embedding': embedding}}, output)
   print('acceptance config ready; imported model digest recorded:', digest)
   PY
   ```

   这组超时和请求数仅供开发机验收；`deadline_seconds` 是**整次编码作业**的截止，不是单请求超时。服务端口和 Ollama 地址均在隔离配置中，按实际主机调整。模型、表示或版本变化会形成不同模型空间；不要把旧外部向量直接复用到本次索引。

4. **先审计，再建库。** 第一条命令只读资料和 Ollama 模型元数据，输出文档／片段／最终输入计数及 UTF-8 字节分布。若 `over_configured_byte_limit` 非零，或 `documents`、`chunks`、`inputs` 超过输出中的对应配置上限，先停在这里，不运行摄取。否则第二条命令用原生 `truncate=false` 对每条实际输入做完整窗口检查；在无 GPU 机器上，它也会实际计算向量，耗时需要单独记录。

   ```sh
   "$NYR_ACCEPTANCE_ROOT/venv/bin/nyr-embedding-audit" --config "$NYR_ACCEPTANCE_ROOT/config.yaml" > "$NYR_ACCEPTANCE_ROOT/audit.json"
   cat "$NYR_ACCEPTANCE_ROOT/audit.json"
   "$NYR_ACCEPTANCE_ROOT/venv/bin/nyr-embedding-audit" --config "$NYR_ACCEPTANCE_ROOT/config.yaml" --probe > "$NYR_ACCEPTANCE_ROOT/probe.json"
   cat "$NYR_ACCEPTANCE_ROOT/probe.json"
   ```

   只有 `no_truncation_probe` 为 `passed` 才继续。若出现 `input_limit_exceeded`、`runtime_budget_exceeded` 或 `ollama_http_400`，不要调高上限后直接重试摄取；把汇总指标与失败输入序号发给我，再决定是否调整上下文、批次预算、切分或接入方式。

5. 在相同隔离目录运行正式入口。先用 `documents` 确认 revision 为 0；首次摄取成功后应为 1，重复摄取应为 `unchanged` 且编码请求数为零。查询请换成资料里你已知答案的问题，并人工核对来源和原文位置；完整 JSON 可能包含资料原文，只留在公司机器。

   ```sh
   "$NYR_ACCEPTANCE_ROOT/venv/bin/nyr" --config "$NYR_ACCEPTANCE_ROOT/config.yaml" documents
   /usr/bin/time -f 'client_elapsed_seconds=%e client_peak_rss_kb=%M' \
       "$NYR_ACCEPTANCE_ROOT/venv/bin/nyr" --config "$NYR_ACCEPTANCE_ROOT/config.yaml" ingest --expected-revision 0 \
       > "$NYR_ACCEPTANCE_ROOT/ingest1.json"
   "$NYR_ACCEPTANCE_ROOT/venv/bin/nyr" --config "$NYR_ACCEPTANCE_ROOT/config.yaml" ingest --expected-revision 1 \
       > "$NYR_ACCEPTANCE_ROOT/ingest2.json"
   "$NYR_ACCEPTANCE_ROOT/venv/bin/nyr" --config "$NYR_ACCEPTANCE_ROOT/config.yaml" query '你选定的已知答案问题' --expected-revision 1 \
       > "$NYR_ACCEPTANCE_ROOT/query.json"
   ollama ps
   ```

   `/usr/bin/time` 中的峰值 RSS 只代表被测 CLI 进程，不代表独立 Ollama 服务和模型的总内存。执行摄取和查询时另用 `ollama ps`、`free -h` 观察 CPU／内存；若要给出可靠峰值，需要在目标机另做进程采样。若完整资料的编码预计超过 3600 秒，先用少量资料测吞吐并确定验收预算，再调整这份**隔离配置**。

6. 只回传脱敏汇总。可发送 `audit.json`、`probe.json` 的输出，以及下列脚本的结果；不要发送 `config.yaml`、`models.json`、`query.json`、索引、原始 Markdown 或 Ollama 日志。

   ```sh
   "$NYR_PYTHON" - <<'PY'
   import json, os
   from pathlib import Path
   root = Path(os.environ['NYR_ACCEPTANCE_ROOT'])
   first = json.loads((root / 'ingest1.json').read_text())
   second = json.loads((root / 'ingest2.json').read_text())
   query = json.loads((root / 'query.json').read_text())
   print(json.dumps({
       'first_status': first['status'], 'revision': first['active']['revision'],
       'encoded_chunks': first['encoding_summary']['encoded_chunk_count'],
       'reused_chunks': first['encoding_summary']['reused_chunk_count'],
       'embedding_requests': first['encoding_report']['requests']['attempted_requests'],
       'repeat_status': second['status'],
       'repeat_encoded_chunks': second['encoding_summary']['encoded_chunk_count'],
       'query_status': query['status'], 'query_evidence_count': len(query['evidence']),
       'query_revision': query['active']['revision'],
       'returned_model': query['observations']['embedding']['batches'][0]['returned_model'],
   }, ensure_ascii=False))
   PY
   ```

## Mac 本机证据

Ollama 0.40.11、模型 digest `ac6da0dfba84a81fdbfbaf330198c33cd77c4cdfc53e8bc50eb581914a15621d`，在回环地址服务。5 份合成 Markdown → 12 个片段／最终输入，最大 356 UTF-8 字节；12 条原生 `truncate=false` 探针全部通过。首次 `nyr ingest` 激活 revision 1，12 条编码、2 次 Embedding 请求、556 token；重复摄取 `unchanged`，12 条复用、0 次编码。查询返回 5 条证据，包含合成 `TC-01`。停止 Ollama 后，变化文档摄取报 `embedding_connection_failed`，revision 仍为 1；恢复服务后只重编码 2 条、复用 10 条并激活 revision 2，查询继续返回 5 条证据。以上是 Mac 合成材料工程证据，不代表 Linux CPU 性能或公司真实资料质量。
