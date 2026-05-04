# Arm Smoke Preflight Plan For 68 Scoped Packages

This document is a design proposal only. It does not represent workflow changes yet.

The goal is to convert the remaining scoped/deferred packages into honest package-specific Arm validation. For these packages, green must mean one of two things:

| Green Type | Meaning |
|---|---|
| Full local runtime green | The package installs/builds and runs meaningful product behavior on generic `ubuntu-24.04-arm`. |
| Arm preflight green | The workflow proves real Arm package compatibility, but the full end-to-end product needs GPU, Kubernetes, OS boot, Windows, cloud credentials, model weights, GUI/display, or device infrastructure. |

The main rule is simple: metadata, docs, release notes, source file existence, or manifest inspection alone cannot be green. Those checks can support a result, but each package needs a package-specific binary, import, container, CLI, local service, compile, chart-render, artifact, or bounded runtime proof on Arm.

## Standard Five Tests Plus Test 6

| Test | Purpose |
|---|---|
| Test 1 | Acquire the real baseline artifact, source, package, wheel, chart, image, or release asset for the selected stable version. |
| Test 2 | Prove version and Arm identity, usually through `file`, `readelf`, package metadata, image manifest, or runtime arch checks. |
| Test 3 | Exercise the package entrypoint: CLI help/version, Python import, library load, chart render, binary startup, or app bootstrap. |
| Test 4 | Verify runner and dependency assumptions on `ubuntu-24.04-arm`; fail honestly if required generic prerequisites are unavailable. |
| Test 5 | Run the strongest bounded package-specific behavior available without special infrastructure. |
| Test 6 | Repeat the same proof against the next stable candidate, or emit an honest `no_newer_stable_available` / specialized-runtime decision. |

## Summary

| Outcome | Count | Packages |
|---|---:|---|
| Full local runtime candidate | 4 | `ocm`, `owncast`, `playwright`, `prophet` |
| Arm preflight green candidate | 61 | Most GPU, Kubernetes, OS-image, cloud, model, GUI, and service packages can run a real scoped Arm proof. |
| Needs dedicated proof before green | 3 | `hue`, `oregano`, `velox` |

The 61 Arm preflight packages can be green only if the dashboard/result wording clearly says scoped/preflight validation, not nginx-level full runtime.

## Full Local Runtime Candidates

These can reasonably reach nginx-style local runtime credibility on generic Ubuntu Arm because the workflow can run an actual package behavior without special external infrastructure.

| Package | Proposed Tests 1-5 | Test 6 Strategy | Caveat |
|---|---|---|---|
| `ocm` | Download Linux Arm64 OCM CLI, verify AArch64, run `ocm version`, create a local component archive, add a local blob resource, query it back, and transfer it to another local archive. | Download latest stable Arm64 CLI and rerun the local component/resource roundtrip. | Does not prove remote OCI registry auth or controller integration. |
| `owncast` | Download/build Linux Arm64 Owncast, verify binary arch/version, start local server, curl web UI, curl local status/API, and check RTMP port is listening. | Repeat binary/build/start/curl against latest stable release. | Does not prove real live video ingest or transcoding quality. |
| `playwright` | Install Node on Arm, install `@playwright/test`, install Chromium dependencies, serve a tiny local HTML page, run a real headless Chromium test, and assert DOM output/screenshot artifact. | Repeat with next stable Playwright npm version and rerun the browser test. | Chromium-only unless Firefox/WebKit are separately validated. |
| `prophet` | Create venv, install Prophet, import/version check, fit a tiny CPU dataframe, forecast, assert numeric `yhat`, and serialize/deserialize the model. | Install latest stable Prophet and rerun the tiny fit/predict flow. | Bounded CPU model only, not performance or large Stan workload. |

## Arm Preflight Green Candidates

These should become green only as scoped Arm preflight results. They run or verify a real package surface on Arm, but they do not prove the full product environment.

| Package | Proposed Tests 1-5 | Test 6 Strategy | Why Not Full Runtime |
|---|---|---|---|
| `amazon-vpc-cni-k8s` | Checkout pinned tag, run Go package discovery, build CNI binaries with `GOARCH=arm64`, verify AArch64 ELF headers, run CNI `VERSION` command with minimal CNI JSON, validate upstream DaemonSet manifests, and inspect referenced images for Arm64. | Resolve next non-prerelease tag, rebuild binaries, rerun CNI protocol and manifest/image checks. | Real pod networking needs Kubernetes plus AWS VPC/ENI environment. |
| `ampere-ai-text-to-sql` | Inspect Arm64 container manifest, pull Arm image, inspect entrypoint, run container help or module import, and if startup is possible curl health; otherwise require a clean missing-config error. | Discover latest stable image tag and repeat manifest, pull, help/import, and health or missing-config behavior. | Full Text-to-SQL needs DB, model, and service configuration. |
| `ampere-optimized-llama` | Clone/build Arm `llama.cpp` variant, configure with CMake, build `llama-cli`, verify AArch64 binary, run CLI help, and optionally run a tiny GGUF prompt only if a fixture exists. | Repeat build/help against latest stable release tag. | Real inference needs model weights and longer runtime. |
| `ampere-optimized-onnx` | Inspect/pull Arm64 image, import ONNX Runtime inside it, run a tiny CPU ONNX add/matmul inference, and inspect native libraries as AArch64. | Repeat on latest stable image tag and rerun CPU inference. | Does not prove optimized execution provider performance. |
| `ampere-optimized-pytorch` | Inspect/pull Arm64 image, import PyTorch, run CPU tensor add/matmul, assert result, and inspect native Torch libraries as AArch64. | Repeat on latest stable image tag and rerun tensor operation. | Does not prove distributed, GPU, or optimized-kernel performance. |
| `ampere-optimized-tensorflow` | Inspect/pull Arm64 image, import TensorFlow, run CPU constant/matmul, assert result, and inspect native TensorFlow libraries as AArch64. | Repeat on latest stable image tag and rerun tensor operation. | Does not prove accelerator or tuned graph performance. |
| `azurelinux` | Inspect official Azure Linux base image manifest for Arm64, run the container on Arm, check `/etc/os-release`, query RPM architecture, run `tdnf makecache`, and run a non-root process smoke. | Test newest stable Azure Linux image tag with the same container, RPM, and `tdnf` checks. | Does not boot kernel/init or validate Azure VM hardware. |
| `bionemo-framework` | Inspect/pull Arm64 NGC image or install Arm wheel, import BioNeMo, compile package sources, and run CLI/help or a lightweight config import. | Repeat on latest stable BioNeMo tag/image and fail if Arm artifact/import disappears. | Training/inference needs NVIDIA GPU, data, and model assets. |
| `blobfuse2` | Download Arm64 package asset, inspect package and binary as AArch64, install it, run `blobfuse2 --version` and help commands, parse a minimal YAML config, and run a bounded fake-credential/FUSE-gated mount attempt. | Require latest stable Arm64 asset and repeat package, CLI, config, and FUSE-gated checks. | Real Azure Blob mount needs FUSE plus Azure Storage credentials/service. |
| `cccl` | Clone CCCL tag, install/use CUDA compiler, compile minimal `cuda::std` or Thrust translation unit, compile a CUB include sample, and verify produced object is AArch64. | Repeat compile matrix on latest stable CCCL release. | No GPU kernel launch or CUDA algorithm runtime. |
| `chiaki-ng` | Install/download or build Linux Arm64 artifact, verify binary as AArch64, run version/help, launch help under Xvfb/offscreen Qt, and verify media/runtime dependencies such as FFmpeg, SDL, or Qt. | Resolve next stable release and repeat artifact, arch, help, Xvfb launch, and dependency probe. | Does not prove PS4/PS5 registration, controller input, or real stream decode. |
| `clara-viz` | Download/install Arm wheel or build package metadata, inspect native libraries, import `clara.viz`, run CPU-safe initialization or version query, and run CLI/help if available. | Repeat against latest stable release and fail if Arm wheel/import is absent. | Actual volume rendering needs CUDA-capable NVIDIA GPU. |
| `cloud-native-stack` | Locate chart, build dependencies, render Helm chart, validate YAML with `kubeconform`/dry-run, extract all images, and require Arm64 manifests with no amd64-only scheduling. | Resolve next stable release and repeat render, schema, dry-run, and image manifest checks. | Does not deploy Kubernetes or reconcile GPU/network operators. |
| `cloudypad` | Checkout tag, install/build TypeScript CLI, run CLI version/help, run dummy/local provider create/list/get/destroy if supported, and verify generated state/config. | Repeat install/build/CLI/dummy-provider flow on next stable tag. | Real streaming VM needs cloud credentials, GPU/display host, and Sunshine/Wolf. |
| `cucim` | Install/download RAPIDS Arm package, inspect native libraries as AArch64, import `cucim`, run a tiny CPU-safe image/read path if available, and compile Python sources. | Repeat on latest stable RAPIDS release package. | GPU-accelerated image processing is not covered. |
| `cuda-gdb` | Install Arm CUDA-GDB package, run `cuda-gdb --version`, verify binary as AArch64, run batch quit, and optionally debug a trivial non-CUDA C binary. | Repeat with latest CUDA package and rerun version/batch/CPU-debug check. | Real CUDA debugging needs driver, GPU, and CUDA target program. |
| `cuda-python` | Install `cuda-python` or current CUDA bindings on Arm, inspect extension modules as AArch64, import bindings, call safe no-device version/API symbols, and verify package metadata. | Repeat install/import/readelf against latest non-prerelease PyPI version. | Driver/runtime calls need NVIDIA driver and GPU. |
| `cudf` | Download/install linux-aarch64 RAPIDS package, inspect `libcudf` native libraries, compile Python sources, attempt guarded `import cudf`, and accept only documented driver-boundary failure after package load. | Repeat on latest stable RAPIDS release and compare package availability/readelf/import boundary. | Real dataframe operations require CUDA driver and GPU. |
| `cugraph` | Download/install linux-aarch64 package, inspect graph libraries, compile Python sources, attempt guarded import, and validate package version/dependency metadata. | Repeat on latest stable RAPIDS release. | Graph algorithms require RAPIDS GPU runtime. |
| `cuml` | Download/install linux-aarch64 package, inspect native ML libraries, compile Python sources, attempt guarded import, and verify Arm dependency closure. | Repeat on latest stable RAPIDS release. | ML training/inference requires CUDA GPU. |
| `cuopt` | Inspect/pull Arm container or install Arm client package, run CLI/help or Python client import, inspect native binaries/libraries, and run local schema/config validation if available. | Repeat on latest stable cuOpt artifact. | Solver runtime needs NVIDIA GPU/service stack. |
| `cutile-python` | Install CUDA Tile package on Arm, inspect native extensions, import module, run compiler/help or create minimal DSL object without launch, and verify package metadata. | Repeat on latest non-prerelease PyPI version. | Tile kernel execution needs CUDA runtime/GPU. |
| `cutlass` | Clone CUTLASS tag, configure CMake include project, compile a tiny host/device translation unit, build a lightweight example target if feasible, and verify AArch64 object/binary. | Repeat against latest stable CUTLASS tag. | No GPU GEMM kernel launch or performance validation. |
| `cuvs` | Download/install linux-aarch64 cuVS package, inspect native libraries, compile Python sources, attempt guarded import, and validate RAFT/RMM dependency architecture. | Repeat on latest stable RAPIDS release. | Vector search runtime needs CUDA GPU. |
| `cv-cuda` | Download/install Arm CV-CUDA wheel or package, inspect native libraries, import `cvcuda`, run CPU-safe version/query API, and compile/import sample scripts without execution. | Repeat on latest stable CV-CUDA release. | Image/video operations require CUDA GPU. |
| `dali` | Install Arm DALI package, inspect native libraries, import `nvidia.dali`, run CPU-only pipeline with `external_source` if available, and verify package/plugin discovery. | Repeat on latest stable DALI package. | GPU decode/augmentation paths are not covered. |
| `dask-cuda` | Install Arm package, import `dask_cuda`, run CLI/module help, call safe GPU-discovery logic and require graceful zero-GPU behavior, and compile package sources. | Repeat on latest stable RAPIDS/dask-cuda release. | Real scheduling requires CUDA GPUs and workers. |
| `dcgm-exporter` | Inspect Arm64 exporter image manifest, pull image, run exporter help/version, inspect binary architecture inside image, and render/sample default metrics config. | Repeat on latest stable exporter tag and fail if Arm64 image/help is absent. | Real metrics need DCGM, driver, and GPU. |
| `dcgm` | Install/extract Arm DCGM package or image, run `dcgmi` or `nv-hostengine` version/help, inspect binaries/libraries as AArch64, and verify service/library paths exist. | Repeat against latest stable DCGM package/container. | Diagnostics and telemetry need driver and NVIDIA GPU. |
| `dify` | Clone pinned release, compile backend source, validate official Docker Compose config, check required services, and build/dry-build a bounded service image such as API. | Repeat source compile, compose config, and bounded image build on latest stable tag. | Full app needs DB, Redis, vector store, web, worker, and LLM config. |
| `flyte` | Download Arm64 `flytectl`, verify checksum and AArch64, run client version/help/config init, run a tiny local `flytekit` workflow, and render/validate Flyte chart manifests. | Resolve next stable CLI/chart pair and repeat binary, local workflow, and manifest validation. | Does not start Flyte control plane or Kubernetes execution backend. |
| `garden-linux` | Download/checksum Arm release artifact, inspect image/rootfs, extract OS identity, verify AArch64 userspace ELF, and optionally import/run rootfs container if a tar is available. | Repeat on next stable Garden Linux release artifact. | Does not boot OS, validate systemd, kernel modules, or cloud-init. |
| `gdrcopy` | Clone tag, build user-space library/tools with CUDA headers, inspect built libs/tools as AArch64, run tool help, and explicitly skip or defer kernel module build. | Repeat build/help on latest stable GDRCopy tag. | Kernel module, GPUDirect RDMA, and GPU copy tests need privileged GPU host. |
| `holoscan-sdk` | Install Arm wheel/container artifact, inspect native libraries, import `holoscan`, run CLI/version query, and instantiate a no-op application graph if CPU-safe. | Repeat on latest stable Holoscan release. | Real pipelines need NVIDIA GPU, drivers, sensors, or media stack. |
| `nvidia-container-toolkit` | Install Arm package or build Go binaries, run `nvidia-ctk --version`, run help/dry-run runtime config generation, verify AArch64 binary, and avoid host runtime mutation. | Repeat on latest stable toolkit release. | GPU container pass-through needs NVIDIA host runtime and GPU. |
| `nvidia-gpu-driver-container` | Inspect driver container Arm64 manifest, pull image, inspect labels/env, inspect driver userspace libraries or kernel modules as Arm64 artifacts, and run a non-privileged command if available. | Repeat on latest production branch tag. | Cannot load kernel driver without privileged matching NVIDIA host. |
| `nvidia-gpu-operator` | Pull chart, render with CRDs, validate YAML/dry-run, extract all images, require Arm64 manifests, and check operator resources with no amd64-only selectors. | Use latest stable chart and repeat render, schema, dry-run, and image manifest checks. | Does not install drivers, reconcile operator, or validate GPU nodes. |
| `nvimagecodec` | Install Arm package/wheel, inspect native libraries, import `nvimgcodec`, run version/query API, and decode tiny CPU-safe fixture only if supported without CUDA. | Repeat on latest stable nvImageCodec release. | GPU decode/encode acceleration needs CUDA GPU. |
| `nvsentinel` | Render chart or official manifests, validate YAML/dry-run, extract images, require Arm64 manifests, and run controller/container `--help` where possible. | Repeat chart/render/schema/image/container-entrypoint checks on next stable release. | Does not prove GPU fault detection, node remediation, or Kubernetes reconciliation. |
| `nvshmem` | Download Arm SBSA NVSHMEM package, inspect `libnvshmem`, run info/version/help if available, compile/link a minimal include-only program, and verify Arm64 SBSA targeting. | Repeat on latest stable NVSHMEM package. | Multi-GPU, NVLink, and InfiniBand runtime are not covered. |
| `nx-cugraph` | Install Arm package, import `nx_cugraph`, verify NetworkX backend entry point metadata, run backend registration/query without GPU algorithm execution, and compile package sources. | Repeat on latest stable RAPIDS release. | Accelerated graph execution requires cuGraph/RAPIDS GPU stack. |
| `ollama` | Install official Arm64 binary or container, run version, start `ollama serve`, curl `/api/version`, curl `/api/tags`, and run `ollama list`. | Repeat Tests 1-5 against latest stable release; optional model generation only if tiny cached model is provided. | No LLM generation unless a tiny model is cached or explicitly allowed. |
| `openlane` | Install actual OpenLane CLI/container, run version/help, validate bundled tiny design config, run bounded config-prep/dry-run, and run tiny synthesis only if toolchain/PDK is available. | Repeat CLI install and config/dry-run on latest stable candidate, with PDK-backed flow deferred. | Full RTL-to-GDSII needs PDK and full toolchain. |
| `opennow` | Download Linux Arm64 package/AppImage, verify checksum, inspect package/native payloads as Arm64, run headless Electron startup under Xvfb, and typecheck/build source where feasible. | Resolve next stable release and repeat checksum, architecture, headless startup, and source build/typecheck. | Does not log in to GeForce NOW or start a cloud gaming session. |
| `osmo` | Install official CLI/source on Arm, run version/help, validate minimal YAML workflow, run local dry-run/plan without cluster submission, and inspect/run Arm image if published. | Repeat CLI install, YAML validation, dry-run, and image proof on next release. | Does not prove GPU, Kubernetes, simulator cluster, or distributed workflow execution. |
| `physics-nemo` | Inspect/pull Arm container or install Arm package, import PhysicsNeMo, compile package sources, instantiate lightweight config/model object on CPU if documented, and inspect native deps. | Repeat on latest stable PhysicsNeMo release. | Training/inference requires GPU and model/data assets. |
| `playit` | Download Arm64 agent package/binary, inspect as AArch64, install/run version/help, run controlled invalid-token startup, and verify deterministic config/help/list behavior. | Resolve next stable playit-agent release and rerun asset, architecture, CLI, and invalid-token startup preflight. | Does not create a real tunnel, authenticate account, or pass external traffic. |
| `raft` | Download/install Arm RAFT/libraft package, inspect native libraries, compile small C++ include/link smoke if headers/libs exist, import `pylibraft` if present, and verify dependency architecture. | Repeat on latest stable RAPIDS release. | Algorithms need CUDA GPU for real execution. |
| `ragflow` | Clone release tag, compile Python service dirs, validate official Docker Compose config, inspect/build bounded Arm service image where available, and run CPU-only module/bootstrap check. | Repeat source compile, compose validation, and bounded image/build probe on latest stable tag. | Full RAGFlow service needs DB/vector/LLM stack. |
| `resiliency-extension` | Install Arm Python package or build wheel, import package, compile sources, run documented CLI/help or config parse, and inspect native extensions if present. | Repeat on latest stable release. | Real behavior needs distributed GPU training workload. |
| `rmm` | Download/install Arm RMM package, inspect `librmm`, guarded import, compile package sources, and verify allocator library links against Arm CUDA deps. | Repeat on latest stable RAPIDS release. | Actual allocation tests need CUDA driver/GPU. |
| `sparks-rapids` | Download RAPIDS Accelerator jar, verify plugin classes with `jar tf`, run Arm JVM classload smoke, optionally start local Spark in CPU-safe mode with plugin jar, and verify jar version metadata. | Repeat on latest stable Spark RAPIDS jar. | GPU acceleration needs Spark plus RAPIDS CUDA executor environment. |
| `sunshine` | Install/download Linux Arm64 artifact, verify binary arch/version/help, generate config/credentials if supported, start under Xvfb/headless config, and probe local web UI health. | Resolve next release and repeat artifact, CLI, config generation, and web UI health. | Does not prove Moonlight pairing, real video encode, GPU capture, or controller streaming. |
| `tabpfn-time-series` | Create venv, install package, import package, verify CPU Torch operation, compile installed package, instantiate public predictor API, and only run tiny forecast if weights are cached/local. | Repeat install/import/CPU preflight on latest stable; forecast remains gated on cached weights. | No zero-shot forecast claim without model weights. |
| `tabPFN` | Install package, import `tabpfn`, verify CPU Torch operation, compile package, instantiate CPU classifier/regressor API, and run tiny fit/predict only with cached/local weights. | Repeat install/import/CPU preflight on latest stable; inference gated on cached weights. | No classification inference claim without model weights. |
| `tensorrt-llm` | Inspect/pull Arm container or install Arm wheel, inspect native libraries, import `tensorrt_llm`, run `trtllm-build --help` or module help, and validate example config parsing without model load. | Repeat on latest stable TensorRT-LLM release. | Model build/inference needs TensorRT, CUDA GPU, and weights. |
| `tensorrt` | Install/extract Arm TensorRT package, inspect TensorRT libraries, import `tensorrt`, create logger/builder if no GPU is required, and run `trtexec --help` if available. | Repeat on latest stable TensorRT release. | Engine build/inference may require CUDA driver/GPU. |
| `tilelang` | Install Arm package/wheel, import `tilelang`, inspect native/compiler extensions, run compiler/help or parse minimal kernel definition, and compile package sources. | Repeat on latest non-prerelease release; execute kernel only on GPU/accelerator runner. | Generated kernel execution needs CUDA/accelerator runtime. |
| `turbovnc` | Install/download Arm package, verify Xvnc binary, run `vncserver`/`Xvnc` version, start a local VNC server, query display with `xdpyinfo` or `xset`, and stop cleanly with log check. | Resolve next release and repeat package install, Xvnc start, display query, and clean shutdown. | Does not prove WAN client performance, VirtualGL, or 3D remoting. |
| `ubuntudesktop` | Resolve official Arm64 desktop image, verify checksum, inspect image structure, inspect squashfs/rootfs metadata, verify AArch64 userspace ELF, and confirm GNOME/desktop payload in manifest. | Resolve next stable Ubuntu Desktop Arm64 image and repeat checksum, rootfs architecture, and desktop manifest checks. | Does not boot ISO/image or start graphical desktop session. |
| `wsl` | Download WSL Arm64 MSI/MSIX asset, extract package, inspect manifest for Arm64, inspect PE binaries for ARM64/AA64 machine type, and verify expected WSL payload completeness. | Resolve latest stable WSL release and repeat extraction, manifest, PE architecture, and payload checks. | Does not launch WSL or validate Windows on Arm integration. |

## Needs Dedicated Proof Before Green

These should not become green from metadata/source/doc checks. They need a heavier package-specific implementation before the dashboard can show them as passing.

| Package | Required Tests 1-5 Before Green | Test 6 Strategy | Blocker |
|---|---|---|---|
| `hue` | Clone release tag, install/build enough Hue runtime to run real CLI or container, start bounded Hue server or container, curl local Hue UI/health endpoint, and fail if only script syntax/source checks are possible. | Repeat against next stable release only after runtime/container startup works. | Current source/container-script validation is not enough; real Hue runtime lane is needed. |
| `oregano` | Build Oregano from tagged source or package lane, run version/help, launch under Xvfb, run `ngspice` batch circuit, open/load tiny schematic under Xvfb, and verify no fatal logs. | Repeat source build/Xvfb/ngspice integration on next tag, or mark no newer stable if archived. | No reliable Ubuntu 24.04 Arm package path; old GUI dependencies need proof. |
| `velox` | Clone tag, run CMake dependency/configure on Arm, build bounded Velox library/test target, compile tiny C++ fixture linked to Velox, and run fixture that creates a vector/expression. | Repeat configure/build/fixture against latest stable candidate. | Heavy C++ dependency build; source markers must stay non-green. |

## Implementation Notes

For implementation, each workflow should set explicit outputs that explain scope:

| Output | Expected Usage |
|---|---|
| `regression_result=Full Arm runtime smoke passed` | Only for packages that run meaningful product behavior locally. |
| `regression_result=Arm preflight smoke passed; full runtime requires ...` | For GPU, Kubernetes, OS, cloud, GUI, model, and device packages. |
| `status=skipped` plus rationale | Only when no newer stable version exists or specialized infrastructure blocks full Test 6. |
| `status=failed` | If the workflow cannot run the promised package-specific proof. |

Recommended review order:

1. Implement the 4 full local runtime candidates first.
2. Implement Arm preflight packages by category: containers/images, Python/wheels, RAPIDS/CUDA, Kubernetes/Helm, OS artifacts, GUI/headless tools.
3. Keep `hue`, `oregano`, and `velox` non-green until their dedicated runtime/build lanes are proven.
4. After implementation, rerun YAML parse, `actionlint -shellcheck=`, and targeted Arm spot checks on `test2`.
