# ADR-0003 — Product, NativeAsset and Scientific Metadata Representation

**Status: ACCEPTED**。

**Context.** 未来Pair/Stack/Official/Correction产品的科学层、容器、单位和几何并不一一对应。统一目录树或Product顶层单一unit会丢掉语义；完全自由metadata又不可校验。

**Decision.** 采用第6节的Product/ProductDraft、NativeAsset、DataLayer、GeometryDescriptor。manifest引用原生数据而不强制复制；科学字段按层表达known/unknown/not-applicable；typed profiles验证消费条件。instance id、semantic digest、完整manifest digest分开。目录/metadata/QC是独立typed records，通过ArtifactRef参与Task，不强制成为SAR Product。

**Rationale.** 冻结可表达的结构而不捏造真实物理约定，保护大数据效率、层级差异和来源追踪。

**Alternatives rejected.** 产品全部转成一种raster/复制目录；所有字段顶层必填；忽略单位/符号；把未知当默认零；所有输出塞进dict；根据扩展名推断科学意义。

**Consequences.** 消费方必须声明profile requirements；未知语义可以存档，但必要字段未知时拒绝计算。未来科学profile有独立版本，不需要Core加mission分支。

**Invariants.** 相对路径有固定anchor；新输出不覆盖上游；critical语义不能藏在annotations；QC不修改旧manifest；所有实际输入进入lineage；原生资产的完整性有可检查依据。

**Non-goals.** phase-to-LOS换算、自动重投影/单位换算、真实Stack标准、云存储框架。

**Deferred.** Phase5 Pair/Stack最小科学profile；Phase8 Official；Phase10多频率；Phase11 Analyzer；Phase12 Correction；Phase16 NISAR Stack科学约定。

**Enforcement.** round-trip、缺字段/错版本、同容器多层、两网格不同reference、unknown消费失败、symlink/hardlink覆盖、same-size corruption、完整性/semantic两类digest区别测试。


规范性细节：`../architecture/phase4-contracts.md` 对应主题。本文为 `P4.0-FREEZE-1` 的已接受架构决定，生产实现尚未完成。
