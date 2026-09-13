# Screen 环境合并实验（2026-09-08）

空白集群请优先使用[一键安装指南](install_zh.md)；本文原有环境配置/迁移方法仍供参考。

目标是保留全部九个评分模型、原权重和 Pro4S 表面预处理，尽量合并 Python/PyTorch 安装。
**本次实际验证的最少配置为两个 conda 环境。**
独立 `screen2` 主控启动的九模型统一运行全部成功（9/9，退出码 0）；
主环境 `pip check` 无冲突、14 项 unittest 全通过。公开 1UBQ 验收后，追加两台 Linux GPU 节点的10设计批量验证：90/90模型状态通过，120个主要指标有效（其中一节点修复APBS依赖后仅补跑Pro4S）。

| 运行部分 | 已验证运行环境 |
|---|---|
| 主控、NetSolP、RP3Net、GATSol、Pro4S 推理、TemBERTure、TemStaPro、ESMC、ESM3 | screen2：Python 3.10.21、Torch 2.5.1 CUDA 11.8、Transformers 4.46.3、NumPy 1.26.4 |
| Pro4S 的 MaSIF/PyMesh 表面预处理 | 现有 masif：Python 3.7 |
| EvoEF2 | 原生 C++ 可执行程序，由主控调用，不需要第三个 Python 环境 |

## 已解决的兼容性问题

- **TemBERTure**：AdapterHub 官方提交 `702381ed5c581af3c488ce7e8663b3d94f0fac42`
  明确依赖 `transformers~=4.46.3`。其包版本虽为 `adapters 1.0.1`，
  **不能用 PyPI 同版本替代**，后者要求 Transformers 4.45。
  Screen runner 补齐 adapter 目录末尾斜杠，并支持 `TEMBERTURE_BASE_MODEL` 本地权重路径。
- **TemStaPro**：旧代码把 `pytorch_model.bin` 文件传给 `from_pretrained`，
  新 Transformers 要求模型目录。只修改加载入口，保留原编码器、分类器与评分算法。
- **ESM**：采用 SDK `esm==3.1.1`，其要求 `transformers<4.47`；
  3.1.6 在此组合中有 tokenizer 属性冲突。ESMC runner 根据 SDK 接口决定是否传递
  `use_flash_attn`，旧 SDK 使用原生注意力实现。
- **NumPy / 表面文件**：Biotite 0.41.2 配合 NumPy 1.26.4，
  `plyfile` 固定为 1.1；新版 1.1.5 要求 NumPy 2，不能直接共用。
- **命名空间隔离**：ESM SDK 和 fair-esm 都占用 `esm` 包名，不能一起装入默认
  site-packages。SDK 安装到独立目录，仅 ESMC/ESM3 子进程用 `PYTHONPATH` 选择它；
  仍共享同一 Python 和 Torch，但不是完全无隔离的单目录安装。

## 在现有可运行安装上复现

本配方克隆已运行成功的 screening 环境；不修改原环境。
它不是从空白 Linux 系统安装所有第三方模型的完整配方。

```bash
conda create -n screen2 --clone screening
conda activate screen2
python -m pip install -r envs/minimal-core-requirements.txt
python -m pip install -e .
python -m pip install --no-deps --target "$PWD/.local/esm-sdk-3.1.1" esm==3.1.1
python scripts/prepare_temstapro_compat.py /path/to/TemStaPro "$PWD/.local/temstapro-compat"
python -m pip check
python -m unittest discover -s tests -v
```

克隆后还需核查可执行脚本的 shebang，不能回指源环境；本机历史安装混用了
两个挂载路径，已在新环境中修正残留入口。原 screening 的 NumPy 仍为 2.2.6，未被修改。

`screening` 克隆源需为 Python 3.10.12+（3.10 系列），并已有可运行的
NetSolP/RP3Net/GATSol/Pro4S 依赖。配置中的现代模型 `*_py` 全部设为
`screen2/bin/python`；`masif_py` 保留旧环境。
`temstapro` 指向生成的新 launcher，`temstapro_dir` 仍指向原完整仓库。
ESMC/ESM3 的 `env.<model>.PYTHONPATH` 指向 SDK 目录；
TemBERTure 的 `PYTHONPATH` 指向上游包含 `temBERTure.py` 的目录，
`TEMBERTURE_BASE_MODEL` 指向完整 ProtBERT-BFD 本地快照。
ESM3 的 `HF_HUB_CACHE` 必须包含完整模型快照，只有结构编码器权重不够。

SDK 使用 `--no-deps` 是有意的：这里只部署 Screen 调用的推理路径。
SDK 元数据还声明 torchvision/torchtext，但这些模块未被所测 ESMC/ESM3 路径导入；
不声称此配置支持 SDK 的所有功能。主环境 `pip check` 也不校验独立 SDK 目录。

## 单环境的剩余障碍

现有 PyMesh Linux 扩展绑定旧 Python ABI。此次检查到的 PyPI pymesh2 0.1.6 wheel
实际包含 macOS Mach-O 二进制；conda-forge 的 pymesh2 Linux 构建只支持 Python 3.6。
这些现成包不能直接并入 Python 3.10。当前 Pro4S 预处理路径未直接导入 TensorFlow，
不能仅因旧环境装有 TF1 就断言必须拆分。
若要进一步压缩为一个环境，需要另外构建现代 Linux/Python 的 PyMesh 并验证完整表面流程；
本实验不证明这样的构建不可能。

本机克隆源已有 DGL GraphBolt 兼容处理；部分可选 PyG 扩展会因 GLIBC 版本被禁用。
因此真实模型推理验收比仅检查包能否安装更重要，不能把克隆成功等同于通用全新安装成功。

## 分模型兼容性预验证

以下使用公开 1UBQ（76 aa），f101 GPU，基于原现代解释器加独立依赖目录，
不是最终克隆环境验收。TemBERTure/TemStaPro 使用上述加载修复。

| 模型 | 兼容组合结果 | 原环境参考 |
|---|---|---|
| TemBERTure | Tm 52.0801，分类 0.0189 | 导出精度下一致 |
| TemStaPro | t40 0.5527，t55 0.05549，t65 0.0112 | 导出精度下一致 |
| ESMC 300m | pseudo-perplexity 1.040203 | 1.040203 |
| ESM3 small | pseudo-perplexity 1.021596 | SDK 3.3.0：1.021286 |
| GATSol | 1.1502755 | 本轮未做独立环境数值对照 |
| Pro4S | 0.8713930249214172，完整表面流程通过 | 本轮未做独立环境数值对照 |

ESM3 的 SDK/Torch 组合改变后存在约 0.0304% 数值差异，不宣称逐位一致；
单条公开蛋白验证不能替代批量排序稳定性或生物学准确性验证。

## 独立两环境最终验收

现代模型和主控全部使用 `screen2/bin/python`，仅 MaSIF 使用旧 `masif`。

| 指标 | 1UBQ 实测值 |
|---|---|
| `netsolp_score`（ESM1b ensemble） | 0.8128094235944641 |
| `rp3net_score` | 0.9142355918884277 |
| `temberture_tm` | 52.0801 |
| `temberture_class_score` | 0.0189 |
| `temstapro_t40_raw` | 0.5527 |
| `temstapro_t55_raw` | 0.05549 |
| `temstapro_t65_raw` | 0.0112 |
| `esmc_perplexity` | 1.040203 |
| `esm3_perplexity` | 1.021596 |
| `gatsol_score` | 1.1502755 |
| `pro4s_score` | 0.8713943958282471 |
| `evoef2_energy` | -337.41 |

所有九模型状态均为 `ok`，没有跳过或用启发式评分替代；EvoEF2 成功解析 1/1。
该结果验证这台 Linux/CUDA 机器上的环境与流程兼容性，不证明跨平台安装或任意输入均已验收。

NetSolP 此处使用默认 ESM1b ensemble，与历史同模型 CPU 结果 0.81280947 一致到浮点误差；
v0.1.0 验收中的 0.8273101 来自 Distilled 配置，不能直接当作同模型环境对照。

## 公开入口与两环境配置

在仓库根目录运行；以下 `/path/to` 都需要替换为实际绝对路径。

```bash
conda activate screen2
export SCREEN_CORE_PREFIX="$CONDA_PREFIX"
export SCREEN_MASIF_PREFIX=/path/to/conda/envs/masif
export SCREEN_MODELS=/path/to/model-repositories
export SCREEN_COMPAT="$PWD/.local/temstapro-compat"
export SCREEN_ESM_SDK="$PWD/.local/esm-sdk-3.1.1"
export SCREEN_HF_CACHE=/path/to/huggingface/hub
export SCREEN_PROTBERT=/path/to/complete/prot_bert_bfd/snapshot
export SCREEN_APBS_ROOT=/path/to/apbs15
mkdir -p .local
cp examples/config.screen2.json .local/config.json
bash scripts/screen.sh doctor
bash scripts/screen.sh run examples/1ubq.fasta examples/1ubq.pdb \
  --models netsolp rp3net temberture temstapro esmc esm3 gatsol pro4s evoef2 \
  --device cuda -o output/1ubq.csv
```

模板假定模型目录名为 NetSolP、RP3Net、TemBERTure、TemStaPro、GATSol、Pro4S、EvoEF2；
按自己的安装修改 JSON。所有变量必须先设置；`env` 中的路径使用绝对路径。
ESMC 和 ESM3 可在 JSON 中分别指定不同的缓存目录，均需完整权重。
`SCREEN_CONFIG` 可覆盖配置文件位置，`SCREEN_PYTHON` 可指定 screen2 的绝对解释器路径；
脚本默认使用当前激活环境的 python，不会自动激活或创建 conda 环境。
直接使用 `protein-screen run` 时，需自行传入 `--config`、`--apbs-bin`、`--multivalue-bin`。

## Conda 与原生依赖边界

- 已验证安装路线：克隆现有可运行的 Python 3.10 screening，再应用
  `envs/minimal-core-requirements.txt`；Torch明确固定为CUDA11.8构建 `2.5.1+cu118`。
- `envs/screen2-bootstrap.yml` 仅创建 Python 与合并依赖的起始环境，
  运行命令为 `conda env create -f envs/screen2-bootstrap.yml`（仓库根目录）。
  尚未从空白环境验收；仍需第三方模型依赖、DGL兼容处理、模型源码和权重。
- `envs/screen2-observed.tsv`、`envs/masif-observed.tsv` 记录实测环境的包名、版本、构建。
  这是环境盘点，不是锁文件；不能恢复本机二进制补丁、editable源码或外置SDK。
- masif继续复用已工作的Python3.7/PyMesh环境；未提供声称可从零重建的MaSIF配方。
  使用上游支持的旧环境，并验收完整表面预处理。
- EvoEF2、MSMS、PDB2PQR、APBS与multivalue是外置原生/命令行依赖，不计为额外conda环境。

APBS必须使用**匹配的二进制和动态库**。本次APBS1.5目录结构为：

```text
apbs15/
  bin/apbs
  bin/multivalue
  lib/libapbs_routines.so
  lib/libapbs_generic.so
  lib/libapbs_mg.so
  lib/libapbs_pmgc.so
  lib/libmaloc.so
```

在每个计算节点检查：

```bash
LD_LIBRARY_PATH="$SCREEN_APBS_ROOT/lib:${LD_LIBRARY_PATH:-}" ldd "$SCREEN_APBS_ROOT/bin/apbs"
LD_LIBRARY_PATH="$SCREEN_APBS_ROOT/lib:${LD_LIBRARY_PATH:-}" ldd "$SCREEN_APBS_ROOT/bin/multivalue"
```

不应存在 `not found`。Pro4S runner会把multivalue相邻的lib/lib64加入子进程动态库路径；
不要依赖某台节点的临时目录或系统loader配置。缺库时可能先生成DX文件，随后缺少电荷CSV，
最终报 `masif_no_surface`。`doctor`仅检查配置路径，不能替代这些原生依赖检查。
第三方二进制和库需按各自许可证安装，本仓库不分发。

## 10设计双节点补充验收

2026-09-08：私有历史测试集抽取10条66–269 aa设计，两个节点各跑5条不同设计。
节点A一次完成45/45，耗时282秒；节点B初跑八模型成功，Pro4S因multivalue缺少动态库失败，
初跑退出码2；配置共享APBS1.5后仅补跑Pro4S，5/5成功、退出码0。
最终90/90状态ok、120个主要数值有限；保留初跑失败记录并明确补跑来源，合并后重算10设计排名。
这不是同一设计跨节点重复实验。私有序列、结构、设计ID及原始结果未公开。

与历史同序列评分对照，最大相对差异：ESM3 0.194325%、ESMC 0.169139%、Pro4S 0.001477%；
EvoEF2、TemStaPro及TemBERTure分类分数完全一致。其余指标最大相对差异小于0.0011%。
差异可能同时受SDK、计算设置与结构处理影响；此次验证不证明生物学预测准确性或任意旧环境均可删除。
