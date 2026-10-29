# LIBLINEAR CPU 验收案例

来源：[JMLR 2008](https://www.jmlr.org/papers/v9/fan08a.html)、[作者仓库](https://github.com/cjlin1/liblinear)、[作者数据站](https://www.csie.ntu.edu.tw/~cjlin/libsvmtools/datasets/binary.html#news20.binary)。准备脚本固定源代码 commit、下载 URL 与 SHA256；作者代码保留 BSD-3-Clause 版权文件，不复制到本仓库分发。

本案例验收 paper Section 3.1 的数据准备、重新训练和预测链路。论文完整清单同时登记 Figure 1 的 news20 与 rcv1 比较，当前没有覆盖的核心实验必须在报告中暴露。三个版本、五个数据划分种子产生 15 次运行；LR 控制与正则化消融是 ArtiCheck 增加的控制项，不能替代论文中的 Pegasos/SVMperf 基线。

```bash
python -m pip install -e '.[reproduction]'
docker pull python:3.11-bookworm
case_base_image="$(docker image inspect --format '{{index .RepoDigests 0}}' python:3.11-bookworm)"
python scripts/prepare_liblinear_case.py --output runs/liblinear-input --base-image "$case_base_image"
python -m articheck reproduce --plan runs/liblinear-input/plan.json --output runs/liblinear-output
```

准备只下载和解析公开材料；作者代码仅在禁网 Docker 容器中编译/执行，没有本地降级。先下载基础镜像，再从 immutable RepoDigest 构建。

主要偏差：现代作者版本不是原论文年代的代码；原始划分 ID 未找回，当前用明确的 80/20 seeded split；未重复 Figure 1 的调参与计时曲线、rcv1 和外部求解器。参考准确率只做带容差的对照，不能证明同一划分或论文完整结论。实际结果以 GitHub Actions 的 `liblinear-cpu-reproduction` 作业及下载证据为准，文档不预填成绩。
