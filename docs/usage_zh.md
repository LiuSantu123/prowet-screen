# 中文使用说明

空白集群请优先使用[一键安装指南](install_zh.md)；本文原有环境配置/迁移方法仍供参考。

ProWet 将原来的九模型 screen 脚本整理为可安装、可配置的 CLI/Python 工具。
输入为 FASTA，可附 PDB/mmCIF；输出为含原始分数、状态、模型覆盖率和排序的 CSV。

全部九模型推荐参考[两环境安装与配置](minimal_environment_zh.md)：`screen2 + masif`，
包含公开启动脚本、两环境配置模板、APBS依赖及10设计90/90验收说明。下方是仅主控的轻量安装。

## 安装主环境

```bash
git clone https://github.com/LiuSantu123/prowet-screen.git
cd prowet-screen
conda env create -f environment.yml
conda activate prowet
prowet rank examples/scores.csv -o output/ranked.csv
```

主环境负责调度、结构处理和结果汇总，不包含九个模型的权重及所有推理依赖。
模型环境按 `docs/models.md` 安装或复用，再修改 `examples/config.json`。
MaSIF 的旧依赖不能直接塞进现代 PyTorch 环境。

## 预测

```bash
prowet doctor --config config.json --models netsolp rp3net
prowet run input.fasta --config config.json \
  --models netsolp rp3net --device cuda -o output/screen.csv
```

有结构时增加 `--structures structures/`。模型可选：netsolp、rp3net、temberture、
temstapro、esmc、esm3、gatsol、pro4s、evoef2。
GATSol/Pro4S 适配器需要 GPU；EvoEF2 为 CPU 程序。
支持参数详见 `prowet run --help`，Python API 见主 README。

FASTA 使用唯一、简短 ID，仅支持字母、数字、点、下划线、连字符和20种标准氨基酸。
结构文件按 ID 精确匹配，例如 `design1.cif`，不再用可能混淆 design1/design10 的前缀匹配。
结构必须包含唯一的完整序列匹配；仅在序列身份确认后去掉末端标签。
当前是单蛋白可开发性筛选，不计算多链诱导或配体结合功能。

缺权重、程序报错、无结果会写入对应状态，缺值为 nan；默认返回码2。
`--allow-partial` 允许部分结果时返回0。`doctor` 仅检查路径，不代表模型跑通。

综合分保留旧版批次百分位加权公式，方便历史比较，但不是实验成功概率。
单条序列综合分通常为0.5；不同批次或模型覆盖率不同不能直接比较。
热稳定性原始共识混合了不同单位，仅兼容保留，应优先看各模型原始指标和标准化共识。
