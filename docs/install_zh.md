# 空白集群安装

目标：Linux x86_64、可联网、普通用户权限。无需预装 Python/conda；需要
`bash`、`git`、`curl`、`sha256sum`。没有 conda 时自动下载固定版 Miniforge
26.5.3-0 并核对官方 SHA-256。模型推理需要合适的 NVIDIA 驱动/GPU；安装
可以在登录节点进行，但请按集群规定将大下载、编译、推理放到允许的节点。
预留至少 100 GB，并留意共享盘配额；全模型下载包含多个 GB 级权重。

## 一条命令克隆并安装

```bash
git clone https://github.com/LiuSantu123/protein-screen.git && bash protein-screen/install.sh --prefix "$HOME/software/protein-screen-runtime"
```

也提供独立 `scripts/bootstrap-cluster.sh`：先下载并查看脚本，再执行
`bash bootstrap-cluster.sh protein-screen --prefix "$HOME/software/protein-screen-runtime"`。
已有目标目录时该脚本拒绝覆盖；断点重跑直接使用仓库内的 `install.sh`。
`--prefix` 必须是专用的新目录；不会修改已有命名环境或 shell 启动文件。

```bash
bash protein-screen/install.sh --plan
bash protein-screen/install.sh --prefix "$HOME/software/protein-screen-runtime" --conda /path/to/conda
```

默认安装九模型，建立 `PREFIX/envs/screen2`（Python 3.10）与
`PREFIX/envs/masif`（Python 3.7）。ESM SDK 3.1.1 置于独立模块目录，仍使用
screen2 的 Python；iFeatureOmegaCLI 所需的旧 matplotlib 3.4.3 由 conda 安装预编译包，避免 Python 3.10 上临时编译。EvoEF2 直接编译，不增加第三个环境。固定 adapters
上游提交；DGL 2.1 的未使用 GraphBolt 加载入口做窄范围兼容修改并保留原文件。
MaSIF 从官方 PyMesh 0.3 Linux cp37 wheel 安装，同时由 conda 安装 APBS 1.5
与 MSMS 2.6.1，并用 APBS 包附带源码编译 `multivalue`（校验源码、生成
禁用可选求解器/MPI 的独立工具配置头）。另从 `rlabduke/reduce` 固定提交
构建加氢工具及字典，不依赖旧机器隐藏的 Amber/base 安装。原生库兼容性会因宿主系统而异，必须完成结构实跑验收。

## 权重与源码边界

六个 MIT/BSD 项目的必要源码已放入 [third_party](../third_party/README.md)，
包括许可证、固定提交与逐文件校验值。不是完整训练仓库，不含模型权重。
Pro4S 直接从上游获取固定提交，ESM SDK 从 PyPI 安装；其版本/模型许可需
分别遵守。特别是 Pro4S 全仓库授权尚不明确、旧 ESM 权重存在版本相关条款、
MSMS 限学术用途，不能把本仓库 MIT 当作所有组件的授权。

| 模型 | 安装器的权重处理 |
|---|---|
| NetSolP | 下载官方 alphabet；ONNX 包需从 [DTU Downloads](https://services.healthtech.dtu.dk/service.php?NetSolP) 取得后用 `--netsolp-models DIR` 导入 |
| RP3Net | EBI FTP 官方 `rp3net_v0.1_d.ckpt` |
| TemBERTure | 固定 Git 提交中的三组 TM/一组 CLS adapter + HF ProtBERT-BFD |
| TemStaPro | 固定 Git 提交中的 40/55/65 × 5 个分类器 + HF ProtT5 |
| ESMC | HF 官方 300M/600M 完整快照 |
| ESM3 | HF 官方 esm3-sm-open-v1 完整快照；可能需账号访问授权 |
| GATSol | 官方 Google Drive checkpoint + fair-esm ESM1b；可用 `--gatsol-checkpoint FILE` 导入 |
| Pro4S | HF qj666/Pro4S finetune.ckpt + fair-esm ESM2-3B；可用 `--pro4s-checkpoint FILE` 导入 |
| EvoEF2 | 固定提交的 library 参数表，无神经模型权重 |

HF 需要授权时，先在官方模型页面申请/接受对应条款，再在当前 shell 设置
`HF_TOKEN` 后重跑。安装器不会把 token 写入配置。网络不可达、Google Drive
限额、缺 ONNX 等会使安装返回非零，并写出 `PREFIX/install-report.json`（日志为 `PREFIX/install.log`）；
处理已列出的缺项后重跑，不应忽略失败状态。GitHub 资产有哈希校验；HF
保留缓存快照提交，但目前配方不属于包含全部权重校验值的离线锁定包。

```bash
bash protein-screen/install.sh --prefix "$HOME/software/protein-screen-runtime" \
  --netsolp-models /path/to/downloaded/models \
  --gatsol-checkpoint /path/to/best_model.tar.gz
```

默认 NetSolP 使用 ESM1b，需 `ESM1b_alphabet.pkl` 和
`Solubility_ESM1b_{0,1,2,3,4}_quantized.onnx`。若只下载 Distilled 权重，
运行时需显式指定 `--netsolp-model-type Distilled`，不能用于默认全模型验收。

## 分阶段与排错

`--models evoef2` 可先验证无大模型权重的完整安装链；或选择逗号分隔的模型。
`--stage sources|envs|weights|config|check` 支持按阶段重跑，顺序如列出所示；
`all` 为默认。环境阶段尚不是事务式恢复：下载完整的软件包可复用，失败的
依赖安装会再次执行；没有把失败阶段标记为成功。模型权重逐个处理，某一模型
失败不会阻止其他权重下载。请保留所选模型列表与外部工具参数以便重跑。

如果集群已提供原生工具，可覆盖路径：

```bash
bash protein-screen/install.sh --prefix "$HOME/software/protein-screen-runtime" \
  --msms-bin /path/to/msms --apbs-bin /path/to/apbs --multivalue-bin /path/to/multivalue
```

APBS 需要相邻 `../lib` 或 `../lib64` 下的共享库；运行器会加入库搜索路径。
这三个参数被写入生成的 launcher；以后运行时也可通过同名参数覆盖。
源码校验不符时拒绝覆盖用户修改，请保留旧目录并使用新 prefix。

## 使用与验收

```bash
source "$HOME/software/protein-screen-runtime/activate.sh"
screen doctor --models evoef2
screen run protein-screen/examples/1ubq.fasta protein-screen/examples/1ubq.pdb \
  --models evoef2 -o /tmp/1ubq-evoef2.csv
# 在 GPU 作业中验收九模型；逐列检查 *_status 和原始分数
screen run protein-screen/examples/1ubq.fasta protein-screen/examples/1ubq.pdb \
  --models netsolp rp3net temberture temstapro esmc esm3 gatsol pro4s evoef2 \
  -o /tmp/1ubq-all.csv
```

安装器的 `check` 检查包、路径和关键导入，不等于九模型推理通过。
已有环境在 f101/f102 的 90/90 验收不能作为本次空白集群安装的验收证据。
本次自动化验证范围见 [validation.md](validation.md)；只有新机器公共结构
九模型均成功后，才能讨论归档旧环境。
