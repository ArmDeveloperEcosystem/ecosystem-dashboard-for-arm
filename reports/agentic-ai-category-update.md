# Agentic AI category update report

Branch: `feat/agentic-ai-category`

Scope: Linux package listings only. Of 70 requested projects in the revised list, 43 have matching Linux listings (including the approved ONNX replacements, OpenAI Whisper match, and WRK and vLLM benchmark matches) and 27 do not. Including the subsequently requested ONNX, Ampere Optimized ONNX Runtime, and OpenAI Whisper additions, updated 48 Linux listings from the supplied list and follow-ups. A subsequent review moves 19 additional AI/ML listings, bringing the total to 67 updated Linux listings. Of the 67 categorized source listings, 66 are displayed: nm-vllm has the pre-existing `works_on_arm: false` flag and is excluded by the dashboard’s Arm-support filter. Windows packages, taxonomy, and dashboard filters are unchanged. No new package listings were created.

Each package has one `category` field containing its subcategory. All 12 requested subcategories now map to the top-level **Agentic AI** category in the Linux taxonomy. Existing category values were replaced.

Matching includes established names (Postgres, Kata, Tesseract, Kong Gateway), both LlamaIndex listings, MinIO/MinIO OS, Docker/Docker CE, and the three upstream OpenTelemetry language SDKs. ONNX and Ampere Optimized ONNX Runtime are accepted replacements for the requested ONNX Runtime entry. OpenAI Whisper (openai-whisper) is the accepted match for Whisper.cpp, per follow-up request. Other enterprise editions, vendor distributions, clients, and related projects were excluded unless explicitly matched above. WRK is accepted as the match for wrk2, and vLLM as the match for vLLM Bench, per follow-up request. Both use Benchmarks / Evaluation. Because listings have one category, vLLM moves from the initially assigned Model Serving / Runtime subcategory to Benchmarks / Evaluation. The revised list removes Linux Arm64 and replaces PyTorch Profiler with PyTorch, categorized under Observability. The missing-project count refers to the revised 70 projects with these approved matches; ONNX Runtime and Whisper.cpp are covered by their accepted replacements.

## Packages not already on the Linux dashboard

| Requested package | Requested subcategory | Notes |
| --- | --- | --- |
| LangGraph | Agent Orchestration | No matching package listing found. |
| Temporal | Agent Orchestration | No matching package listing found. |
| AutoGen | Agent Orchestration | No matching package listing found. |
| FAISS | RAG / Vector Search | No matching package listing found. |
| rank-bm25 | RAG / Vector Search | No matching package listing found. |
| VectorDBBench | RAG / Vector Search | No matching package listing found. |
| tiktoken | RAG / Vector Search | No matching package listing found. |
| FastAPI | Tool / Action Execution | No matching package listing found. |
| Ory Oathkeeper | Identity & Security | Ory CORP - CLI exists, but is not Oathkeeper. |
| LiteLLM | Model Gateways / Routing | No matching package listing found. |
| OpenRouter | Model Gateways / Routing | No matching package listing found. |
| TGI | Model Serving / Runtime | No matching package listing found. |
| SGLang | Model Serving / Runtime | No matching package listing found. |
| Hugging Face Tokenizers | AI / Data Processing | No matching package listing found. |
| fastText | AI / Data Processing | No matching package listing found. |
| LangSmith | Observability | No matching package listing found. |
| Loki | Observability | No matching package listing found. |
| SWE-Bench | Benchmarks / Evaluation | No matching package listing found. |
| TAU-Bench | Benchmarks / Evaluation | No matching package listing found. |
| HammerDB | Benchmarks / Evaluation | No matching package listing found. |
| SPECjbb | Benchmarks / Evaluation | No matching package listing found. |
| pybench | Benchmarks / Evaluation | No matching package listing found. |
| ghz | Benchmarks / Evaluation | No matching package listing found. |
| h2load | Benchmarks / Evaluation | No matching package listing found. |
| Arm Kleidi | Arm Software | No matching Linux package listing found. |
| Arm Compute Libraries | Arm Software | Arm Compute Library is listed only on the Windows dashboard; it was not changed. |
| Arm SystemReady | Arm Software | No matching package listing found. |

## Changed category values

Previous categories are those before the Agentic AI changes. All rows apply to Linux.

| Requested project | Dashboard listing | Platform | Previous category | New subcategory (under Agentic AI) | Rationale and evidence |
| --- | --- | --- | --- | --- | --- |
| LangChain | [LangChain](../content/linux/opensource_packages/langchain.md) | Linux | Languages and Frameworks | Agent Orchestration | Supplied package list or explicitly approved match; see matching notes above. |
| LlamaIndex | [LLama-Index](../content/linux/opensource_packages/llama-index.md) | Linux | AI/ML | Agent Orchestration | Supplied package list or explicitly approved match; see matching notes above. |
| LlamaIndex | [LlamaIndex Core](../content/linux/opensource_packages/llamaindex.md) | Linux | AI/ML | Agent Orchestration | Supplied package list or explicitly approved match; see matching notes above. |
| Milvus | [Milvus](../content/linux/opensource_packages/milvus.md) | Linux | Data-format | RAG / Vector Search | Supplied package list or explicitly approved match; see matching notes above. |
| Qdrant | [Qdrant](../content/linux/opensource_packages/qdrant.md) | Linux | AI/ML | RAG / Vector Search | Supplied package list or explicitly approved match; see matching notes above. |
| OpenSearch | [Opensearch](../content/linux/opensource_packages/opensearch.md) | Linux | Databases - noSQL | RAG / Vector Search | Supplied package list or explicitly approved match; see matching notes above. |
| PostgreSQL | [Postgres](../content/linux/opensource_packages/postgres.md) | Linux | Database | Data / Memory / State | Supplied package list or explicitly approved match; see matching notes above. |
| Redis | [Redis](../content/linux/opensource_packages/redis.md) | Linux | Databases - noSQL | Data / Memory / State | Supplied package list or explicitly approved match; see matching notes above. |
| MinIO | [MinIO](../content/linux/commercial_packages/minio.md) | Linux | Storage | Data / Memory / State | Supplied package list or explicitly approved match; see matching notes above. |
| MinIO | [MinIO OS](../content/linux/opensource_packages/minio-os.md) | Linux | Storage | Data / Memory / State | Supplied package list or explicitly approved match; see matching notes above. |
| Kafka | [Kafka](../content/linux/opensource_packages/kafka.md) | Linux | Databases - noSQL | Data / Memory / State | Supplied package list or explicitly approved match; see matching notes above. |
| NATS | [NATS](../content/linux/opensource_packages/nats.md) | Linux | Messaging/Comms | Data / Memory / State | Supplied package list or explicitly approved match; see matching notes above. |
| MySQL | [MySQL](../content/linux/opensource_packages/mysql.md) | Linux | Database | Data / Memory / State | Supplied package list or explicitly approved match; see matching notes above. |
| MongoDB | [MongoDB](../content/linux/opensource_packages/mongodb.md) | Linux | Databases - noSQL | Data / Memory / State | Supplied package list or explicitly approved match; see matching notes above. |
| NGINX | [NGINX](../content/linux/opensource_packages/nginx.md) | Linux | Web Server | Tool / Action Execution | Supplied package list or explicitly approved match; see matching notes above. |
| Envoy | [Envoy](../content/linux/opensource_packages/envoy.md) | Linux | Containers and Orchestration | Tool / Action Execution | Supplied package list or explicitly approved match; see matching notes above. |
| Kong | [Kong Gateway](../content/linux/commercial_packages/kong-gateway.md) | Linux | Networking | Tool / Action Execution | Supplied package list or explicitly approved match; see matching notes above. |
| Firecracker | [Firecracker](../content/linux/opensource_packages/firecraker.md) | Linux | Containers and Orchestration | Tool / Action Execution | Supplied package list or explicitly approved match; see matching notes above. |
| gVisor | [GVisor](../content/linux/opensource_packages/gVisor.md) | Linux | Containers and Orchestration | Tool / Action Execution | Supplied package list or explicitly approved match; see matching notes above. |
| Kata Containers | [Kata](../content/linux/opensource_packages/kata.md) | Linux | Containers and Orchestration | Tool / Action Execution | Supplied package list or explicitly approved match; see matching notes above. |
| Wasmtime | [Wasmtime](../content/linux/opensource_packages/wasmtime.md) | Linux | Runtimes | Tool / Action Execution | Supplied package list or explicitly approved match; see matching notes above. |
| Keycloak | [Keycloak](../content/linux/opensource_packages/keycloak.md) | Linux | Security applications | Identity & Security | Supplied package list or explicitly approved match; see matching notes above. |
| OpenSSL | [OpenSSL](../content/linux/opensource_packages/openssl.md) | Linux | Crypto | Identity & Security | Supplied package list or explicitly approved match; see matching notes above. |
| Open Policy Agent | [Open Policy Agent](../content/linux/opensource_packages/Open-Policy-Agent.md) | Linux | Security applications | Identity & Security | Supplied package list or explicitly approved match; see matching notes above. |
| vLLM / vLLM Bench | [vLLM](../content/linux/opensource_packages/vllm.md) | Linux | AI/ML | Benchmarks / Evaluation | Supplied package list or explicitly approved match; see matching notes above. |
| wrk2 (WRK accepted match) | [WRK](../content/linux/opensource_packages/wrk.md) | Linux | Monitoring/Observability | Benchmarks / Evaluation | Supplied package list or explicitly approved match; see matching notes above. |
| Ollama | [Ollama](../content/linux/opensource_packages/ollama.md) | Linux | AI/ML | Model Serving / Runtime | Supplied package list or explicitly approved match; see matching notes above. |
| Tesseract OCR | [Tesseract](../content/linux/opensource_packages/tesseract.md) | Linux | AI/ML | AI / Data Processing | Supplied package list or explicitly approved match; see matching notes above. |
| FFmpeg | [FFmpeg](../content/linux/opensource_packages/ffmpeg.md) | Linux | Video | AI / Data Processing | Supplied package list or explicitly approved match; see matching notes above. |
| NumPy | [Numpy](../content/linux/opensource_packages/numpy.md) | Linux | AI/ML | AI / Data Processing | Supplied package list or explicitly approved match; see matching notes above. |
| pandas | [Pandas](../content/linux/opensource_packages/pandas.md) | Linux | Miscellaneous | AI / Data Processing | Supplied package list or explicitly approved match; see matching notes above. |
| OpenBLAS | [OpenBLAS](../content/linux/opensource_packages/openblas.md) | Linux | AI/ML | AI / Data Processing | Supplied package list or explicitly approved match; see matching notes above. |
| protobuf | [Protobuf](../content/linux/opensource_packages/protobuf.md) | Linux | Data-format | AI / Data Processing | Supplied package list or explicitly approved match; see matching notes above. |
| Prometheus | [Prometheus](../content/linux/opensource_packages/prometheus.md) | Linux | Monitoring/Observability | Observability | Supplied package list or explicitly approved match; see matching notes above. |
| Grafana | [Grafana](../content/linux/opensource_packages/grafana.md) | Linux | Monitoring/Observability | Observability | Supplied package list or explicitly approved match; see matching notes above. |
| OpenTelemetry | [Opentelemetry-cpp](../content/linux/opensource_packages/opentelemetry-cpp.md) | Linux | Monitoring/Observability | Observability | Supplied package list or explicitly approved match; see matching notes above. |
| OpenTelemetry | [opentelemetry-go](../content/linux/opensource_packages/opentelemetry-go.md) | Linux | Monitoring/Observability | Observability | Supplied package list or explicitly approved match; see matching notes above. |
| OpenTelemetry | [opentelemetry-python](../content/linux/opensource_packages/opentelemetry-python.md) | Linux | Monitoring/Observability | Observability | Supplied package list or explicitly approved match; see matching notes above. |
| Jaeger | [Jaeger](../content/linux/opensource_packages/jaeger.md) | Linux | Monitoring/Observability | Observability | Supplied package list or explicitly approved match; see matching notes above. |
| containerd | [Containerd](../content/linux/opensource_packages/containerd.md) | Linux | Runtimes | Platform / Infrastructure | Supplied package list or explicitly approved match; see matching notes above. |
| Docker | [Docker CE](../content/linux/opensource_packages/docker-ce.md) | Linux | Containers and Orchestration | Platform / Infrastructure | Supplied package list or explicitly approved match; see matching notes above. |
| Docker | [Docker](../content/linux/opensource_packages/docker.md) | Linux | Containers and Orchestration | Platform / Infrastructure | Supplied package list or explicitly approved match; see matching notes above. |
| Kubernetes | [Kubernetes](../content/linux/opensource_packages/kubernetes.md) | Linux | Containers and Orchestration | Platform / Infrastructure | Supplied package list or explicitly approved match; see matching notes above. |
| gRPC | [gRPC](../content/linux/opensource_packages/gRPC.md) | Linux | Messaging/Comms | Platform / Infrastructure | Supplied package list or explicitly approved match; see matching notes above. |
| ONNX (follow-up) | [Open Neural Network Exchange (ONNX)](../content/linux/opensource_packages/onnx.md) | Linux | AI/ML | Model Serving / Runtime | Supplied package list or explicitly approved match; see matching notes above. |
| Ampere Optimized ONNX (follow-up) | [Ampere Optimized ONNX Runtime](../content/linux/opensource_packages/ampere-optimized-onnx.md) | Linux | AI/ML | Model Serving / Runtime | Supplied package list or explicitly approved match; see matching notes above. |
| openai-whisper (follow-up) | [Whisper](../content/linux/opensource_packages/whisper.md) | Linux | AI/ML | AI / Data Processing | Supplied package list or explicitly approved match; see matching notes above. |
| PyTorch | [PyTorch](../content/linux/opensource_packages/pytorch.md) | Linux | AI/ML | Observability | Supplied package list or explicitly approved match; see matching notes above. |
| Dify (AI/ML review) | [Dify](../content/linux/opensource_packages/dify.md) | Linux | AI/ML | Agent Orchestration | Combines agent workflows, tools, and RAG in an application builder. [Primary source](https://github.com/langgenius/dify) |
| Langflow (AI/ML review) | [Langflow](../content/linux/opensource_packages/langflow.md) | Linux | AI/ML | Agent Orchestration | Builds tool-calling agents and exposes flows through MCP. [Primary source](https://docs.langflow.org/components-agents) |
| Haystack (AI/ML review) | [Haystack](../content/linux/opensource_packages/haystack.md) | Linux | AI/ML | Agent Orchestration | Orchestrates LLM, retrieval, and agent pipelines. [Primary source](https://haystack.deepset.ai/) |
| NVIDIA NeMo Agent Toolkit (AI/ML review) | [NVIDIA NeMo Agent Toolkit](../content/linux/opensource_packages/nemo-agent-toolkit.md) | Linux | AI/ML | Agent Orchestration | Composes and operates agent workflows across frameworks. [Primary source](https://docs.nvidia.com/nemo/agent-toolkit/1.2/index.html) |
| Open WebUI (AI/ML review) | [Open WebUI](../content/linux/opensource_packages/open-webui.md) | Linux | AI/ML | Agent Orchestration | Connects LLMs with tools and knowledge in a self-hosted application platform. [Primary source](https://docs.openwebui.com/) |
| RAGflow (AI/ML review) | [RAGflow](../content/linux/opensource_packages/ragflow.md) | Linux | AI/ML | RAG / Vector Search | Provides document retrieval and context for LLM and agent applications. [Primary source](https://github.com/infiniflow/ragflow) |
| Vespa (open source) (AI/ML review) | [Vespa (open source)](../content/linux/opensource_packages/vespa-open-source.md) | Linux | AI/ML | RAG / Vector Search | Combines vector and lexical retrieval with ranking for RAG. [Primary source](https://vespa.ai/) |
| Vespa Cloud (AI/ML review) | [Vespa Cloud](../content/linux/commercial_packages/vespa.md) | Linux | AI/ML | RAG / Vector Search | Managed version of the same retrieval engine used for RAG. [Primary source](https://vespa.ai/) |
| CuVS (AI/ML review) | [CuVS](../content/linux/opensource_packages/cuvs.md) | Linux | AI/ML | RAG / Vector Search | Vector similarity search is a direct retrieval-layer fit, consistent with the requested FAISS category. [Primary source](https://github.com/NVIDIA/cuvs) |
| Ampere AI Text-to-SQL (AI/ML review) | [Ampere AI Text-to-SQL](../content/linux/opensource_packages/ampere-ai-text-to-sql.md) | Linux | AI/ML | Tool / Action Execution | Uses LlamaIndex and Open WebUI to turn natural-language requests into database queries. [Primary source](https://github.com/AmpereComputingAI/ampere-ai-text2sql) |
| Ampere Optimized Ollama (AI/ML review) | [Ampere Optimized Ollama](../content/linux/opensource_packages/ampere-optimised-ollama.md) | Linux | AI/ML | Model Serving / Runtime | Arm-optimized Ollama distribution for serving LLMs; consistent with the existing Ollama move. [Existing package description](../content/linux/opensource_packages/ampere-optimised-ollama.md) |
| Ampere Optimized Llama.cpp (AI/ML review) | [Ampere Optimized Llama.cpp](../content/linux/opensource_packages/ampere-optimized-llama.md) | Linux | AI/ML | Model Serving / Runtime | Arm-optimized llama.cpp distribution for LLM inference. [Primary source](https://github.com/AmpereComputingAI/llama.cpp) |
| nm-vllm (AI/ML review) | [nm-vllm](../content/linux/commercial_packages/nm-vllm.md) | Linux | AI/ML | Model Serving / Runtime | LLM serving distribution; classified by its serving role, while the requested upstream vLLM benchmark match stays in Benchmarks / Evaluation. [Primary source](https://github.com/neuralmagic/nm-vllm) |
| Modular Accelerated Xecution (MAX) (AI/ML review) | [Modular Accelerated Xecution (MAX)](../content/linux/commercial_packages/modular.md) | Linux | AI/ML | Model Serving / Runtime | MAX supplies an optimized inference and serving framework for generative models. [Primary source](https://max.modular.com/) |
| BentoML (AI/ML review) | [BentoML](../content/linux/opensource_packages/bentoml.md) | Linux | AI/ML | Model Serving / Runtime | Documents LLM endpoints, RAG deployments, and agent deployment examples. [Primary source](https://docs.bentoml.com/en/latest/) |
| llm-d (AI/ML review) | [llm-d](../content/linux/opensource_packages/llm-d.md) | Linux | AI/ML | Model Serving / Runtime | Distributed LLM inference and serving on Kubernetes. [Primary source](https://github.com/llm-d/llm-d) |
| TensorRT-LLM (AI/ML review) | [TensorRT-LLM](../content/linux/opensource_packages/tensorrt-llm.md) | Linux | AI/ML | Model Serving / Runtime | Dedicated LLM inference optimization and runtime. [Primary source](https://docs.nvidia.com/tensorrt-llm/index.html) |
| Transformers (Hugging Face) (AI/ML review) | [Transformers (Hugging Face)](../content/linux/opensource_packages/huggingface_trasformers.md) | Linux | AI/ML | Model Serving / Runtime | Loads and runs pretrained language models that underpin LLM applications; classified by inference use despite also supporting training. [Primary source](https://huggingface.co/docs/transformers/index) |
| MLflow (AI/ML review) | [MLflow](../content/linux/opensource_packages/mlflow.md) | Linux | AI/ML | Observability | Dedicated agent tracing captures retrieval, tool calls, and model responses; also supports evaluation. [Primary source](https://mlflow.org/docs/latest/genai/) |

## AI/ML review criteria

Reviewed 112 remaining Linux AI/ML listings. Moved 19 to Agentic AI; retained 93 in AI/ML. Of these 19 moves, 18 are displayed on the dashboard: nm-vllm remains hidden because its existing `works_on_arm` flag is false. The resulting total is 67 categorized source listings and 66 visible Agentic AI entries.

These are editorial best-fit decisions based on package purpose, current primary-source documentation, and the already approved taxonomy. Documentation demonstrates direct applicability, not measured deployment frequency. Move agent builders, retrieval engines, LLM inference components, and dedicated agent tracing tools. Retain general ML training, statistics, forecasting, scientific computing, computer vision, and broad infrastructure unless a direct agent/LLM role provides a stronger category fit.

Previously approved assignments remain in place, including PyTorch under Observability and vLLM under Benchmarks / Evaluation. Runtime distributions are classified by their own role. Package support claims and version data are unchanged; current documentation does not imply every listed minimum version supports every described feature.

## Retained in AI/ML

Classical ML examples include Scikit-learn, CatBoost, LightGBM, Statsmodels, Prophet, and forecasting libraries. TensorFlow, Keras, JAX, and Ampere Optimized PyTorch retain their general training/inference role. Computer vision, scientific, and domain-specific frameworks also remain here.

Broad platforms and infrastructure such as Ray, Anyscale, Databricks, ClearML, and MLRun can support agent workloads, but their general platform listings are retained conservatively. Training-focused DeepSpeed, NeMo, Megatron-Core, and torchtune remain AI/ML; NeMo Agent Toolkit is a distinct agent product. MLflow and BentoML move because their documented agent tracing and LLM deployment workflows provide a direct fit. This is not a claim that retained tools cannot support agents.

Full retained inventory:

- [Anaconda](../content/linux/commercial_packages/anaconda.md)
- [Anyscale Platform](../content/linux/commercial_packages/anyscale.md)
- [BigFix](../content/linux/commercial_packages/bigfix.md)
- [ClearML Enterprise](../content/linux/commercial_packages/clearml.md)
- [Databricks Data Intelligence Platform](../content/linux/commercial_packages/databricks.md)
- [DeepSparse](../content/linux/commercial_packages/deepsparse.md)
- [LandingLens](../content/linux/commercial_packages/landinglens.md)
- [Latent AI Efficient Inference Platform (LEIP)](../content/linux/commercial_packages/leip.md)
- [PagerDuty Operations Cloud](../content/linux/commercial_packages/pagerduty.md)
- [ThirdAI Platform](../content/linux/commercial_packages/thirdai.md)
- [Wallaroo](../content/linux/commercial_packages/wallaroo.md)
- [Nuclio](../content/linux/opensource_packages/Iguazio_Nuclio.md)
- [JAX](../content/linux/opensource_packages/JAX.md)
- [Kunpeng Acceleration Engine (KAE)](../content/linux/opensource_packages/Kunpeng_Acceleration_Engine.md)
- [Lachesis](../content/linux/opensource_packages/Lachesis.md)
- [Redundans](../content/linux/opensource_packages/Redundans.md)
- [Albumentations](../content/linux/opensource_packages/albumentations.md)
- [Ampere Optimized PyTorch](../content/linux/opensource_packages/ampere-optimized-pytorch.md)
- [Ampere Optimized TensorFlow](../content/linux/opensource_packages/ampere-optimized-tensorflow.md)
- [Antlr4](../content/linux/opensource_packages/antlr4.md)
- [NVIDIA BioNeMo-Framework](../content/linux/opensource_packages/bionemo-framework.md)
- [CatBoost](../content/linux/opensource_packages/catboost.md)
- [ClearML](../content/linux/opensource_packages/clearml-open-source.md)
- [Clipper](../content/linux/opensource_packages/clipper.md)
- [CuCIM](../content/linux/opensource_packages/cucim.md)
- [CuDF](../content/linux/opensource_packages/cudf.md)
- [CuDNN FrontEnd (FE)](../content/linux/opensource_packages/cudnn-fe.md)
- [CuGraph](../content/linux/opensource_packages/cugraph.md)
- [Cuml](../content/linux/opensource_packages/cuml.md)
- [CuOpt](../content/linux/opensource_packages/cuopt.md)
- [CuPy](../content/linux/opensource_packages/cupy.md)
- [CV-CUDA](../content/linux/opensource_packages/cv-cuda.md)
- [NVIDIA DALI](../content/linux/opensource_packages/dali.md)
- [Dask-CUDA](../content/linux/opensource_packages/dask-cuda.md)
- [DeepSpeed](../content/linux/opensource_packages/deepspeed.md)
- [DVC (Data Version Control)](../content/linux/opensource_packages/dvc.md)
- [Evalml](../content/linux/opensource_packages/evalml.md)
- [FastAI](../content/linux/opensource_packages/fastai.md)
- [Feast](../content/linux/opensource_packages/feast.md)
- [Featuretools](../content/linux/opensource_packages/featuretools.md)
- [Flyte](../content/linux/opensource_packages/flyte.md)
- [Gluten](../content/linux/opensource_packages/gluten.md)
- [Hawking](../content/linux/opensource_packages/hawking.md)
- [Holoscan SDK](../content/linux/opensource_packages/holoscan-sdk.md)
- [Kangas](../content/linux/opensource_packages/kangas.md)
- [Keras](../content/linux/opensource_packages/keras.md)
- [Kmerfreq](../content/linux/opensource_packages/kmerfreq.md)
- [KoBERT (SK Telecom)](../content/linux/opensource_packages/kobert.md)
- [LightGBM](../content/linux/opensource_packages/lightgbm.md)
- [Lime](../content/linux/opensource_packages/lime.md)
- [ManipulaPy](../content/linux/opensource_packages/manipulapy.md)
- [NVIDIA Megatron-Core](../content/linux/opensource_packages/megatron-core.md)
- [Metaflow](../content/linux/opensource_packages/metaflow.md)
- [Mindspore](../content/linux/opensource_packages/mindspore.md)
- [Miniasm](../content/linux/opensource_packages/miniasm.md)
- [Microsoft ML.NET](../content/linux/opensource_packages/mlnet.md)
- [MLRun](../content/linux/opensource_packages/mlrun.md)
- [Neural Modules (Nemo)](../content/linux/opensource_packages/nemo.md)
- [NeuralForecast](../content/linux/opensource_packages/neuralforecast.md)
- [Nx-cugraph](../content/linux/opensource_packages/nx-cugraph.md)
- [OneDNN](../content/linux/opensource_packages/onednn.md)
- [OpenCV](../content/linux/opensource_packages/opencv.md)
- [Optuna](../content/linux/opensource_packages/optuna.md)
- [OSMO](../content/linux/opensource_packages/osmo.md)
- [NVIDIA PhysicsNeMo](../content/linux/opensource_packages/physics-nemo.md)
- [Prophet](../content/linux/opensource_packages/prophet.md)
- [PyCaret](../content/linux/opensource_packages/pycaret.md)
- [Python-DLPy](../content/linux/opensource_packages/python-dlpy.md)
- [Python-Swat](../content/linux/opensource_packages/python_swat.md)
- [RAFT](../content/linux/opensource_packages/raft.md)
- [Ray](../content/linux/opensource_packages/ray.md)
- [NVIDIA Resiliency Extension](../content/linux/opensource_packages/resiliency-extension.md)
- [RAPIDS Memory Manager (RMM)](../content/linux/opensource_packages/rmm.md)
- [Salmon](../content/linux/opensource_packages/salmon.md)
- [Saspy](../content/linux/opensource_packages/saspy.md)
- [Scikit-learn](../content/linux/opensource_packages/scikit-learn.md)
- [Scipy](../content/linux/opensource_packages/scipy.md)
- [SHAP](../content/linux/opensource_packages/shap.md)
- [spaCy](../content/linux/opensource_packages/spacy.md)
- [NVIDIA Spark-Rapids](../content/linux/opensource_packages/sparks-rapids.md)
- [Stable Baselines3](../content/linux/opensource_packages/stable-baseline3.md)
- [StatsForecast](../content/linux/opensource_packages/statsforecast.md)
- [Statsmodels](../content/linux/opensource_packages/statsmodels.md)
- [TabPFN](../content/linux/opensource_packages/tabPFN.md)
- [Tabpfn-time-series](../content/linux/opensource_packages/tabpfn-time-series.md)
- [Tensorflow Serving](../content/linux/opensource_packages/tensorflow-serving.md)
- [Tensorflow](../content/linux/opensource_packages/tensorflow.md)
- [TensorRT](../content/linux/opensource_packages/tensorrt.md)
- [torchtune](../content/linux/opensource_packages/torchtune.md)
- [Triton](../content/linux/opensource_packages/triton.md)
- [Ultralytics](../content/linux/opensource_packages/ultralytics.md)
- [Warp](../content/linux/opensource_packages/warp.md)
- [Ydata-profiling](../content/linux/opensource_packages/ydata-profiling.md)

## Validation

- Verified all 67 Linux package edits change only the category field and map to Agentic AI.
- Windows package files, category taxonomy, generated category mapping, and shared dashboard template were unchanged by implementation commit `13ac51dd4`.
- Category mapping unit tests: 3 passed. Linux package category validation passed.
- Hugo build passed; Linux HTML includes the Agentic AI filter and package category labels, while Windows HTML contains no Agentic AI category.
- Hugo emitted existing layout and IsSet warnings, also seen before the changes.
- `git diff --check` passed.
