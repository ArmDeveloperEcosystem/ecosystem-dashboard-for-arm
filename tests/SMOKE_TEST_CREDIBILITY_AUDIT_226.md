# Smoke Test Credibility Audit For The Remaining 226 Packages

This document is the planning record for packages outside the current clean smoke-test bucket.

The goal is not to make every package look green. The goal is to make every package produce the strongest honest Arm validation possible, with no metadata-only checks presented as runtime proof.

## Current Count

Source report: `/tmp/smoke-test-credibility-report.tsv`

| Group | Count | Meaning |
|---|---:|---|
| `FULL_RUNTIME_CURRENT_AND_NEXT` | 349 | Current and next version have runtime validation. |
| `FULL_RUNTIME_CURRENT_SAFE_SKIP` | 387 | Current version has runtime validation, and Test 6 is safely not applicable or no newer stable version exists. |
| Clean bucket | 736 | Do not disturb in this phase. |
| Remaining audit scope | 226 | Needs upgrade, clarification, or scoped validation. |

## Production Standard

We should describe validation in three levels.

| Level | What It Means | Example |
|---|---|---|
| Full Arm runtime smoke | Install/build and run package behavior on Ubuntu Arm. Test 6 validates next version or has a safe skip. | `nginx`, `zookeeper`, `hiredis`, `leveldb` |
| Scoped Arm smoke | Run a real package surface on Arm, but not the full product environment. | GPU package import, CLI help, controller `--help`, CPU sample, source compile |
| Specialized validation required | Generic Ubuntu Arm cannot honestly prove the product behavior. | GPU execution, Kubernetes reconcile, cloud operations, OS boot, FPGA/JTAG |

The main rule: source, release notes, docs, image manifest, or metadata alone is not a real smoke test. It can support evidence, but something package-specific should run or be verified on Arm.

## Work Plan For The 226

| Current Bucket | Count | Plan |
|---|---:|---|
| `FULL_RUNTIME_CURRENT_UNCLEAR_TEST6` | 32 | Most are report undercounts. Fix classification first, then implement real lanes for the true gaps. |
| `LIMITED_CPU_SOURCE_ARTIFACT` | 64 | Upgrade package by package from source/artifact checks to real Arm behavior where possible. |
| `DEFERRED_SPECIAL_INFRA` | 38 | Add minimal Arm proof where honest, keep a clear caveat for full runtime. |
| `BROKEN_UNCLEAR` | 92 | Deep repair. Many can become full runtime with package-specific install/run tests. |

## Test 6 Policy

| Package Type | Test 6 Strategy |
|---|---|
| Package-manager install | `not_applicable_package_manager`, because repo package manager already resolves current supported Arm package. |
| One stable release only | `no_newer_stable_available`, with clear evidence. |
| Source/binary direct install | Install or build the next stable candidate and run the same bounded proof. |
| GPU/Kubernetes/cloud/GUI/OS/device | Run best generic Arm proof, then mark full end-to-end validation as specialized if required. |

## Bucket 1: `FULL_RUNTIME_CURRENT_UNCLEAR_TEST6` - 32 Packages

These are not all bad. The audit found several are already real runtime tests and are only undercounted by the static report.

### Likely Report-Undercounted Full Runtime

| Package | Current Reality | Next Action |
|---|---|---|
| `bazel` | Installs Arm64 Bazel, builds sample, validates next binary. | Fix classifier/report markers. |
| `calico` | Installs `calicoctl` Arm64, validates next CLI. | Fix classifier/report markers. |
| `cert-manager` | Installs `cmctl` Arm64, validates next CLI. | Fix classifier/report markers. |
| `chef-infra` | Installs Chef Arm64 package, validates next package. | Fix classifier/report markers. |
| `CP2K` | Builds CP2K source and next source. | Fix classifier/report markers; keep timeout realistic. |
| `crossplane` | Installs Crossplane Arm64 CLI, validates next CLI. | Fix classifier/report markers. |
| `Dgraph-Labs` | Installs Arm64 tarball, validates next tarball. | Fix classifier/report markers. |
| `emqtt` | Builds `emqtt-bench` from source and next tag. | Fix classifier/report markers. |
| `Flume` | Extracts Apache tarball, checks runnable distribution and next tarball. | Consider adding tiny agent start for stronger proof. |
| `gRPC-java` | Uses Linux AArch64 Maven plugin and next artifact. | Fix classifier/report markers. |
| `H2` | Runs H2 SQL/current and next jar. | Make Test 6 rerun SQL for symmetry. |
| `haskell-nix` | Runs AArch64 nix tool sample and next tools. | Fix classifier/report markers. |
| `salmon` | Builds and runs tiny index/quant current and next. | Fix classifier/report markers. |
| `solr` | Starts Solr locally and validates next admin endpoint. | Fix classifier/report markers. |
| `vvdec` | Builds current and next `vvdecapp`. | Add tiny decode sample if available. |

### Likely Safe-Skip Full Runtime

| Package | Current Reality | Next Action |
|---|---|---|
| `AvxToNeon` | Builds and runs Arm sample; no newer stable candidate. | Mark as safe skip. |
| `pmdk` | Builds/runs PMDK smoke; no newer release. | Mark as safe skip. |
| `popins2` | Builds/runs PopIns2 command; only release. | Mark as safe skip. |

### True Gaps In This Bucket

| Package | Best Real Arm Proof | Nginx-Level On Generic Arm? | Reason |
|---|---|---|---|
| `enroot` | Install Arm release package, run version/help, bounded rootless import/list. | Partial | Full GPU/container runtime needs more infra. |
| `gem5` | Build `ARM/gem5.opt`, run `--version` and a tiny config. | Partial | Build cost is high, but CPU proof is possible. |
| `ghdl` | Install package and run tiny VHDL analyze/elaborate/run. | Partial | Package-manager lane may be enough; source next build is heavier. |
| `gluten` | Spark local SQL with Gluten/Velox backend. | No | Needs heavy Spark/Velox runtime. |
| `ord-provider-server` | Run Arm container and curl health/ORD endpoint. | Partial | Needs real service lane. |
| `ovirt` | Keep as limited CPU helper proof or build disposable engine lane. | Partial | Full engine requires DB/system services. |
| `qflow` | Install `qflow`, run help plus tiny Verilog flow. | Partial | Full ASIC flow is toolchain-heavy. |
| `qrouter` | Install `qrouter`, route tiny LEF/DEF fixture. | Partial | Needs fixture and routing setup. |
| `ragflow` | Run official Arm container/compose and curl health. | No | Heavy app/LLM/vector dependencies. |
| `rav1e` | Download Arm release and encode one-frame Y4M. | Partial | Current path is source-only. |
| `restreamer` | Run Arm container and curl HTTP UI/health. | No | Requires reliable Docker service lane. |
| `tensorflow-serving` | Build current/next `tensorflow_model_server`, serve model, query REST. | No | Long Bazel build; needs dedicated bounded lane. |
| `velox` | Source build plus small unit/query binary. | Partial | Heavy C++ dependency lane. |
| `verible` | Download AArch64 release; format/lint tiny SystemVerilog. | Partial | Current path is source-only. |

## Bucket 2: `LIMITED_CPU_SOURCE_ARTIFACT` - 64 Packages

### Strong Upgrade Candidates

These can likely become full Arm runtime smoke tests on generic Ubuntu Arm.

| Package | Proposed Full/Strong Smoke |
|---|---|
| `ampere-optimised-ollama` | Start container or binary, curl `/api/version` or `/api/tags`. |
| `ampere-optimized-onnx` | Run container and execute tiny ONNX Runtime CPU inference. |
| `ampere-optimized-pytorch` | Run container and execute tiny PyTorch tensor operation. |
| `ampere-optimized-tensorflow` | Run container and execute tiny TensorFlow tensor operation. |
| `azurecli` | Install `az`, run `az --version` and non-auth help command. |
| `catboost` | Install package, train/predict tiny CPU model. |
| `feast` | Run local feature store with file/SQLite backend. |
| `gdsfactory` | Generate/write/read a tiny GDS layout. |
| `litex` | Generate minimal SoC or run `litex_sim` bounded smoke. |
| `mediamtx` | Start server and curl local health/API endpoint. |
| `migen` | Run simulation or generate simple Verilog. |
| `mlflow` | Start local server with SQLite backend and curl health. |
| `mlnet` | Run tiny .NET ML console sample. |
| `myhdl` | Convert simple design to Verilog. |
| `ocm` | Build/install CLI and validate local component descriptor. |
| `ollama` | Start `ollama serve` and curl local API. |
| `owncast` | Start server and curl local web/API endpoint. |
| `shap` | Train tiny model and compute SHAP values. |
| `veriloggen` | Generate simple Verilog. |
| `vidgear` | Process synthetic frame/video path with CPU dependencies. |

### Scoped Or Minimal Arm Proof

These should run a real package-specific surface on Arm but should not be marketed as full product runtime.

| Package | Proposed Scoped Proof | Caveat |
|---|---|---|
| `ampere-ai-text-to-sql` | Pull/run image or app health if available. | Real Text-to-SQL needs DB and model/service config. |
| `ampere-optimized-llama` | Build/run `llama.cpp` help or tiny GGUF inference if fixture exists. | Real inference needs model weights. |
| `blobfuse2` | Install and run version/help; optional FUSE mount if privileges allow. | Real mount needs FUSE and Azure storage/emulator. |
| `cccl` | Header/source compile sanity. | CUDA compiler/GPU needed for real runtime. |
| `cloudypad` | Install CLI and run help/config validation. | Real streaming VM needs cloud credentials. |
| `cucim` | CPU-safe import if installable. | Real image acceleration needs CUDA/GPU. |
| `cuda-gdb` | Install binary and run `--version`. | Real debug session needs CUDA/GPU. |
| `cuda-python` | Install/import bindings and report version. | CUDA driver calls need GPU stack. |
| `cuda-qx` | Source/import/help probe if installable. | CUDA-QX runtime not generic. |
| `cudnn-fe` | Header compile/preprocessor proof. | cuDNN runtime needs CUDA/GPU. |
| `cupy` | Guarded import/version or source compile. | Array runtime needs CUDA libs/GPU. |
| `cutile-python` | Wheel install/import if possible. | CUDA Tile runtime needs CUDA stack. |
| `cutlass` | CMake configure/header compile. | Kernels need nvcc/GPU. |
| `deepspeed` | Install with ops disabled; import/config parse. | Training needs GPU/distributed stack. |
| `dify` | Docker compose config and bounded health if reliable. | Full app needs DB/Redis/vector/LLM. |
| `flyte` | CLI/local workflow or targeted build/test. | Full control plane needs Kubernetes. |
| `geda` | Apt install, CLI/netlist/ngspice smoke. | GUI not covered. |
| `holoscan-sdk` | Configure/import if CPU-safe. | Real pipeline needs NVIDIA runtime. |
| `horizon-eda` | Install/build CLI version under Xvfb. | GUI workflow not covered. |
| `iceberg` | Local Java table/unit test. | Full engines need Spark/Flink/catalog. |
| `ironcore` | Run controller image `--help` or envtest. | Real control plane needs Kubernetes. |
| `kasmvnc` | `Xvnc -version` plus bounded headless start. | Full VNC session not covered. |
| `librecad` | `--version` under Xvfb or open/export fixture. | GUI CAD workflow not covered. |
| `lima` | `limactl --version/help`. | VM launch needs virtualization privileges. |
| `luigi` | npm install/build package fixture. | Browser/app runtime not covered. |
| `mdl-sdk` | CMake configure or CPU example if feasible. | Full SDK/rendering heavy. |
| `megatron-core` | Import/version or config object. | Training needs GPU/distributed stack. |
| `msquic` | Build sample or loopback handshake. | Full protocol/perf coverage not included. |
| `nvidia-container-toolkit` | Install `nvidia-ctk`, run version/help. | GPU container pass-through needs NVIDIA host. |
| `nx-cugraph` | Import/package metadata if installable. | Real graph acceleration needs RAPIDS/GPU. |
| `openlane` | CLI/help or tiny design if toolchain available. | Full ASIC flow needs PDK/toolchain. |
| `openmcp-control-plane-operator` | Run image help or envtest. | Kubernetes reconcile not generic. |
| `openmfp-portal` | Container entrypoint/health if self-contained. | May need backend config. |
| `oregano` | `--version` under Xvfb if installable. | GUI circuit workflow not covered. |
| `osmo` | Source/config/import/help proof. | Likely GPU/cluster runtime. |
| `platform-mesh-operator` | Image help/envtest. | Kubernetes reconcile not generic. |
| `playit` | Install agent and run version/help. | Real tunnel needs account token. |
| `playwright` | CLI install/version; browser test only if verified on Arm. | Official browser bundles can be Arm-limited. |
| `prophet` | Import/version, optional tiny fit if bounded. | Stan/cmdstan can be slow. |
| `resiliency-extension` | Import package/config proof. | Real behavior needs GPU/distributed training. |
| `tabpfn-time-series` | Import/version, avoid model download unless cached. | Model weights and CPU cost. |
| `tabPFN` | Import/version, tiny inference only with cached weights. | Model download and PyTorch stack. |
| `tilelang` | Import/compiler help if installable. | Accelerator compiler/runtime. |
| `turbovnc` | `Xvnc -version` and bounded headless start. | Full remote session not covered. |

## Bucket 3: `DEFERRED_SPECIAL_INFRA` - 38 Packages

These need special infrastructure for full end-to-end validation. The right move is to add a real minimal Arm proof where possible and keep the caveat visible.

### One Full Upgrade Candidate

| Package | Proposed Full Smoke |
|---|---|
| `gnucap` | Install on Arm and run a batch SPICE/circuit simulation. |

### Minimal Arm Proof Candidates

| Package | Proposed Minimal Proof | Full Runtime Blocker |
|---|---|---|
| `amazon-vpc-cni-k8s` | Build Go CNI binaries and assert AArch64 ELF. | Needs AWS VPC/Kubernetes pod networking. |
| `azurelinux` | Inspect/run official Arm64 image/container artifact. | Full OS boot needed. |
| `bionemo-framework` | Inspect NGC image manifest for Arm64. | NVIDIA GPU/CUDA runtime. |
| `chiaki-ng` | CMake build and assert AArch64 binary. | GUI/Remote Play session. |
| `clara-viz` | Inspect/build Arm wheel/libs or CPU-safe import. | NVIDIA GPU rendering. |
| `cloud-native-stack` | Render charts and check referenced images for Arm64. | GPU Kubernetes cluster. |
| `cudf` | Verify linux-aarch64 package/native libs with `readelf`. | CUDA/GPU dataframe runtime. |
| `cugraph` | Verify linux-aarch64 package/native libs. | CUDA/GPU graph runtime. |
| `cuml` | Verify linux-aarch64 package/native libs. | CUDA/GPU ML runtime. |
| `cuopt` | Inspect Arm package/container artifact. | NVIDIA GPU solver runtime. |
| `cuvs` | Verify Arm package/native libs. | CUDA/GPU vector search runtime. |
| `cv-cuda` | Build/inspect Arm native library or wheel. | CUDA/GPU image/video ops. |
| `dali` | Install/inspect Arm DALI wheel; CPU-safe import if reliable. | CUDA/GPU pipeline runtime. |
| `dask-cuda` | Install package and CPU-safe import/version. | GPU worker scheduling. |
| `dcgm-exporter` | Verify Arm64 exporter image manifest. | DCGM/driver/GPU metrics. |
| `dcgm` | Verify Arm package/container/native libs. | NVIDIA driver/GPU diagnostics. |
| `garden-linux` | Verify Arm release image/container artifact. | Booted OS validation. |
| `gdrcopy` | Build/inspect Arm native library. | GPUDirect/CUDA/GPU. |
| `k8s-device-plugin` | Build plugin or verify Arm64 container manifest. | GPU Kubernetes node. |
| `llm-d` | Render manifests and check image architecture. | K8s model serving. |
| `microcloud` | Build CLI and run version/help. | Privileged multi-node LXD services. |
| `mig-parted` | Build CLI and parse config/help. | MIG-capable NVIDIA GPU. |
| `nvidia-gpu-driver-container` | Verify Arm64 driver container digest. | Privileged driver/kernel host. |
| `nvidia-gpu-operator` | Helm template and image Arm64 checks. | GPU Kubernetes reconcile. |
| `nvimagecodec` | Inspect/install Arm package/libs. | CUDA/GPU codec runtime. |
| `nvsentinel` | Helm template plus image Arm64 checks. | GPU Kubernetes runtime. |
| `nvshmem` | Verify Arm package/native libs. | Multi-GPU NVSHMEM environment. |
| `opennow` | Build/package on Arm. | Cloud/game/display context. |
| `physics-nemo` | Inspect container/wheel for Arm64. | NVIDIA GPU training/inference. |
| `raft` | Verify Arm RAFT libs. | CUDA/GPU algorithms. |
| `rmm` | Verify Arm RMM libs. | CUDA/GPU allocator runtime. |
| `sparks-rapids` | Verify Arm jar/package and class load. | Spark plus RAPIDS GPU stack. |
| `sunshine` | Build or inspect Arm package; run version/help. | Display/encoder/GPU streaming. |
| `tensorrt-llm` | Verify Arm wheel/container/native libs. | CUDA/GPU model inference. |
| `tensorrt` | Verify Arm TensorRT package/native libs. | CUDA/GPU engine build/inference. |
| `ubuntudesktop` | Verify Arm desktop image/checksums. | Booted graphical desktop. |
| `wsl` | Inspect WSL release bundle for ARM64 payload. | Windows on Arm host. |

## Bucket 4: `BROKEN_UNCLEAR` - 92 Packages

The earlier audit found many here can become real full Arm smoke tests with package-specific work. This is the highest-value implementation backlog after report cleanup.

### Likely Full Runtime Candidates

`adoptopenjdk`, `airflow`, `antlr4`, `apache-shiro`, `arthas`, `benchmark`, `bishengjdk`, `brpc`, `cashpack`, `cgal`, `docker`, `DPDK`, `dubbo-go`, `eclipse_temurin`, `eigen`, `emqx`, `fmt`, `freeglut`, `freeimage`, `freetype`, `freetype2`, `glog`, `gmp`, `golang`, `googletest`, `gRPC`, `hal`, `highwayhash`, `hiredis`, `httpcomponents-client`, `iniParser`, `jemalloc`, `lapack`, `leveldb`, `libaom`, `libconfig`, `libev`, `libevent`, `libgav1`, `libjpeg`, `libmpc`, `libunwind`, `libuv`, `libxcb`, `libXext`, `log4cpp`, `mpfr`, `onednn`, `opencascade`, `openfeature_go`, `psutil`, `qiniu-qshell`, `re2`, `reveal`, `RoaringBitmap`, `rubyonrails`, `sennajs`, `sentry-go`, `sentry-javascript`, `shiny`, `spdlog`, `spring-cloud-sleuth`, `spring_cloud_task`, `srs`, `tbb`, `tinyxml`, `xerces`, `zookeeper`

Typical fix pattern: install/build the actual package, run a tiny local operation, and make Test 6 install/build the next version or emit a safe skip.

### Scoped Or Minimal Candidates

`apache_kudu`, `buildkite-elastic-ci-stack-for-aws`, `caffe`, `dynatrace`, `elastic-quark`, `enigmaJS`, `font-awesome`, `hue`, `igniteui`, `libdrm`, `mongoose`, `nebula_graph`, `oceanbase`, `picassoJS`, `Redundans`, `seastar`, `sendbird-uikit`, `spark-sql-kinesis`, `uui`, `zerotier`

Typical fix pattern: build/install and run the strongest local package surface. Keep the caveat that full cluster/cloud/GUI/network value is outside generic runner scope.

### Specialized Or Deferred Candidates

`dentos`, `freebsd`, `weavenet`, `xen_ci`

Typical fix pattern: add a real minimal Arm proof, but keep full runtime marked as requiring OS/network/hypervisor-level infrastructure.

## Immediate Implementation Order

1. Fix report underclassification for the `FULL_RUNTIME_CURRENT_UNCLEAR_TEST6` packages that are already real.
2. Convert obvious full-runtime candidates in `BROKEN_UNCLEAR` using small local fixtures.
3. Upgrade `LIMITED_CPU_SOURCE_ARTIFACT` packages that can run actual CPU behavior.
4. Add minimal Arm proof for GPU/Kubernetes/cloud/OS packages and keep caveats explicit.
5. Only after this audit is reviewed, apply workflow changes package by package.

## Manager Summary

We are not blocked, but the validation language needs to be precise. The clean `736` should remain untouched. The remaining `226` need one of three outcomes: full runtime proof, scoped/minimal Arm proof, or explicit specialized-infra rationale. The production-grade path is to stop treating metadata as smoke testing and ensure every package runs or verifies a real package-specific surface on Arm.

## Implementation Pass Results - 2026-05-03

The full 226-package audit scope was reviewed. The implementation pass strengthened or corrected 194 workflows from the old non-clean buckets, and the remaining 32 workflows were reviewed and left unchanged because they already had credible runtime probes or an honest scoped proof.

This pass does not mean every package is now nginx-level full runtime. It means each reviewed package now falls into a more honest production-grade category: full Arm runtime, scoped Arm proof, or specialized-runtime deferred with rationale.

| Original Bucket | Count | Result |
|---|---:|---|
| `FULL_RUNTIME_CURRENT_UNCLEAR_TEST6` | 32 | All 32 addressed. Report undercounts were fixed or workflows were upgraded. Heavy packages like `gluten`, `ragflow`, and `velox` remain scoped/deferred instead of fake-green. |
| `LIMITED_CPU_SOURCE_ARTIFACT` | 64 | All 64 touched. Many now run real CPU/package behavior; GPU, model, cloud, or GUI-heavy packages keep scoped language where full runtime is not honest on generic Arm. |
| `DEFERRED_SPECIAL_INFRA` | 38 | All 38 touched. These now use bounded Arm proof where possible and explicitly state when GPU, Kubernetes, OS boot, Windows on Arm, or cloud infrastructure is required. |
| `BROKEN_UNCLEAR` | 92 | All 92 reviewed. 60 were changed; 32 were verified as already credible or already scoped appropriately. |

### Strong Runtime Examples Added Or Strengthened

Representative packages now run real package behavior on Arm rather than only checking metadata:

| Package | Runtime Proof Added Or Confirmed |
|---|---|
| `hiredis` | Compiles a Hiredis client and performs Redis `PING`, `SET`, `GET` roundtrip. |
| `CP2K` | Builds source and runs a real H2 Quickstep energy fixture; Test 6 repeats on next candidate. |
| `emqtt` | Builds actual EMQTT source and runs CLI pub/sub probes; Test 6 repeats on next source. |
| `gRPC-java` | Downloads Linux AArch64 Maven plugin, generates Java stubs from a proto fixture, validates next artifact. |
| `airflow` | Starts local Airflow webserver and curls `/health`. |
| `docker` | Runs a real `linux/arm64` container and checks `uname -m`. |
| `zookeeper` | Starts local server and probes `ruok`. |
| `openfeature_go` | Compiles and runs a Go flag-evaluation client; Test 6 repeats on next module. |
| `psutil` | Runs real CPU and memory functional probes; Test 6 installs next PyPI candidate and reruns. |
| `sentry-go` / `sentry-javascript` | Captures an event through a local custom transport; Test 6 repeats on next module/package. |
| Native C/C++ libraries | Many now compile and run tiny package-specific programs, for example `fmt`, `glog`, `leveldb`, `re2`, `tinyxml`, `lapack`, `jemalloc`, `libxcb`, `libXext`, and `opencascade`. |

### Scoped But Honest Examples

These packages now provide the best reasonable generic Arm proof, but should not be described as nginx-level full runtime:

| Package | Honest Scope |
|---|---|
| `enroot` | Builds/stages and runs version/list checks; full container import/start and GPU hooks still need dedicated runtime. |
| `gem5` | Builds a bounded `NULL/gem5.opt` and executes it; full ISA simulation remains heavier than a generic smoke lane. |
| `gluten` | Compiles JVM core modules on Arm; full Spark plus native Velox/ClickHouse backend remains specialized. |
| `ragflow` | Compiles source directories on Arm; full service stack is deferred due external services and non-Arm64 published images. |
| `velox` | Explicitly deferred; heavy C++ query-engine runtime is not fake-greened. |
| `seastar` | Source/scripts validated, but full Seastar framework runtime remains outside this bounded pass. |
| `hue` | Source/container-script validation only; full Hue service stack remains too heavy for generic smoke. |
| `freebsd`, `azurelinux`, `garden-linux`, `ubuntudesktop`, `wsl` | Arm artifact/source/release evidence is validated; OS boot/runtime is not claimed. |
| GPU/CUDA/RAPIDS packages | Source/package/container/catalog proof is scoped; CUDA execution remains deferred without NVIDIA GPU infrastructure. |
| Kubernetes operators and device plugins | Helm/source/image proof is scoped; real reconcile behavior requires a Kubernetes cluster and, for NVIDIA packages, GPU nodes. |

### Validation Performed

| Validation | Result |
|---|---|
| YAML parse across changed smoke workflows | Passed for 242 modified/new smoke workflows. |
| `actionlint -shellcheck=` across changed smoke workflows | Passed for 242 modified/new smoke workflows. |
| `git diff --check` across the worktree | Passed. |
| AWS Arm spot checks on `test2` | Confirmed `aarch64`; Hiredis Redis roundtrip passed; Kudu Arm64 atomic probe compiled/ran; Buildkite templates parsed with Arm64 references; Nebula next Arm64 binary downloaded and ran a local probe. |

### Remaining Real Blockers

Some packages cannot honestly be made nginx-level on a generic Ubuntu Arm runner:

| Blocker Type | Examples | What We Can Prove Now | What Requires More Infra |
|---|---|---|---|
| GPU/CUDA/RAPIDS | `cudf`, `cugraph`, `cuml`, `tensorrt`, `dcgm`, `raft`, `rmm` | Arm source/package/container evidence or CPU-safe import/build marker. | Real GPU execution, CUDA kernels, telemetry, or inference. |
| Kubernetes/GPU operators | `k8s-device-plugin`, `nvidia-gpu-operator`, `cloud-native-stack`, `llm-d` | Helm/source/image manifest proof. | Cluster deployment, DaemonSet behavior, reconcile loop, GPU node behavior. |
| OS images and platform runtimes | `freebsd`, `azurelinux`, `garden-linux`, `ubuntudesktop`, `wsl` | Arm image/release/source artifact validation. | Booted OS, graphical desktop session, Windows on Arm/WSL host. |
| Heavy distributed/service stacks | `ragflow`, `hue`, `gluten`, `velox`, `seastar` | Bounded source/build/module proof. | Full service cluster, query engine, Spark/Velox backend, or distributed runtime. |

### Team Talking Point

The earlier statement "all packages have smoke tests" is directionally true only if we include scoped proof. The more accurate production statement is:

> Most packages now have full Arm runtime smoke tests. Packages that require GPU, Kubernetes, OS boot, cloud credentials, GUI sessions, or large distributed services now have the strongest honest generic Arm proof we can run, and the dashboard should surface the scope instead of pretending they are full nginx-level runtime tests.

## Final Verification Pass - 2026-05-03

A second verification pass checked all 226 workflows again by bucket. The purpose was specifically to catch fake-green cases where a workflow only downloaded metadata, checked docs, or saw source files but still counted as passing.

| Verification Scope | Packages Checked | Extra Fixes Made | Outcome |
|---|---:|---:|---|
| `FULL_RUNTIME_CURRENT_UNCLEAR_TEST6` + `LIMITED_CPU_SOURCE_ARTIFACT` | 96 | 52 workflows changed | Metadata/source-marker-only Test 5 paths were converted to explicit deferred/failing paths; marker-only Test 6 proof was removed where it would overstate runtime validation. |
| `BROKEN_UNCLEAR` split A | 46 | 5 workflows changed | BiSheng JDK made package-specific, Go and EMQX Test 6 now run real next-version behavior, Hue marked scoped/deferred, FreeBSD wording made artifact-only. |
| `BROKEN_UNCLEAR` split B | 46 | 4 workflows changed | RoaringBitmap, Spark Kinesis, Spring Cloud Sleuth, and Spring Cloud Task Test 6 now rerun package-specific candidate behavior. |
| `DEFERRED_SPECIAL_INFRA` | 38 | 3 workflows changed | CuVS source proof fixed, NVIDIA driver-container multi-architecture proof added, Ubuntu Desktop Arm64 artifact proof added with boot/runtime explicitly deferred. |

### Additional Credibility Corrections

The verification pass intentionally reduced green count for workflows that still lacked a real package-specific runtime surface. Examples include `hue`, `velox`, multiple Ampere optimized image lanes, CUDA/GPU-adjacent packages, `blobfuse2`, `cccl`, `cloudypad`, `dify`, `flyte`, `holoscan-sdk`, `horizon-eda`, `iceberg`, `librecad`, `lima`, `megatron-core`, `mlnet`, `msquic`, `ocm`, `ollama`, `openlane`, `owncast`, `playit`, `playwright`, `prophet`, `tabPFN`, `tilelang`, and `turbovnc` where applicable.

For those packages, the production-grade behavior is no longer fake-green. They either run a bounded package-specific proof, or they are explicitly scoped/deferred with rationale.

### Final Validation

| Check | Result |
|---|---|
| YAML parse across changed smoke workflows | Passed for 247 modified/new smoke workflows. |
| `actionlint -shellcheck=` across changed smoke workflows | Passed for 247 modified/new smoke workflows. |
| `git diff --check` | Passed. |
| Agent manual review scope | All 226 non-clean packages rechecked. |

### Final Position

The correct final claim is:

> Every reviewed package now has either a real package-specific Arm smoke surface or an explicit scoped/deferred result explaining why generic Ubuntu Arm cannot honestly prove full runtime behavior. Metadata-only checks are no longer allowed to appear as green runtime validation in the audited 226-package scope.
