# Phase 4 Architecture Contracts

规范标识：`P4.0-FREEZE-1`。Architecture review: ACCEPTED；implementation: P4.1–P4.3 尚待验证。基线 commit：`9c8b2ba1bb5b44e9aca274b0f29f3df692206fc9`。

本文件各节编号与完整架构审查报告一致；省略本地取证/环境历史及工作流操作说明。§9–12的ADR在 `../adr/` 分文件保存。

# 2. Final Architecture

采用**配置边界不动、共享值合同在下、六类插件各司其职、单一 registry 显式装配、Core 只调度操作适配器**的结构。

```text
CLI（保留已有命令）               tests / Fake composition
          │                              │
          ▼                              │
Phase-3 config                           │
          │                              │
          └──────► application / composition ◄──── concrete plugins
                          │          │                     │
                          │          └── register ─────────┘
                          ▼
                  sealed PluginRegistry
                          │
                          ▼
                 Core runtime / executor
                    │          │
                    ▼          ▼
          execution contracts  provenance storage
                    │
                    ▼
           six family Protocols / operation ports
                    │
                    ▼
             Product / domain records
                    │
                    ▼
        primitive values / identity / safe errors
                    │
                    ▼
        existing core.exceptions.InSARForgeError
        （唯一允许的历史基础叶模块；不导入执行器）
```

图中的 concrete plugins 依赖合同，而不是运行时内部。composition 构造它们并注册 factory/operation bindings；Core 从注册记录取得统一的**操作适配器**，不调用一个虚构的“所有插件通用 run()”。

`contracts/` 采用**模块级有向无环依赖**，不是要求其所有模块处于同一层：`values/identity/errors` 是基础叶；`plugins/execution/operations` 是依赖 Product 的上层合同。各 `__init__.py` 保持轻量，不以全量重导出制造隐式循环。

P4 的边界不是“提前支持所有 YAML 插件值”。运行时扩展通过注册测试；用户配置支持矩阵以后按 Phase 逐个扩展。


# 3. Final Decision Register

`FROZEN` 指本项目内部冻结合同，非 v1.0 永久对外承诺。破坏性变更需要 ADR 修订与受影响回归，不可在后端迁移中静默改动。除表中明确延期项外，所有行本轮均无须用户选择科学值。

| ID | Topic | Final decision | Rationale | Stability | User science approval NOW | Future Phase |
|---|---|---|---|---|---|---|
| P4D-001 | Core | 通用编排；无具体 mission/backend 分支 | 防科学耦合 | FROZEN | NO | — |
| P4D-002 | 接口机制 | 六类 Protocol；无强制共同 ABC/run | 职责不同 | FROZEN | NO | — |
| P4D-003 | 插件身份 | kind/id/API 与代码、原生执行身份分离 | 版本不能混用 | FROZEN | NO | — |
| P4D-004 | Registry | 显式注册；seal 后只读；精确查找 | 无扫描副作用 | FROZEN | NO | — |
| P4D-005 | Mission | 解释采集/传感器元数据 | 不下载、不编排 | FROZEN | NO | 科学映射5/9/10 |
| P4D-006 | Provider | 目录、访问、获取、源缓存 | 不选科学参数 | FROZEN | NO | 实现5/8/9 |
| P4D-007 | Processor | 原生配置/执行/输出映射 | 不改 Core | FROZEN | NO | 实现5起 |
| P4D-008 | Correction | 明确域及阶段的派生输出 | 不覆盖原始结果 | FROZEN | NO | 科学接口12 |
| P4D-009 | Analyzer | 兼容输入→时序/分析结果 | 不重做前端 | FROZEN | NO | 实现11 |
| P4D-010 | QC | 独立评估报告 | 成功执行≠科学通过 | FROZEN | NO | 科学阈值5起 |
| P4D-011 | Product | 版本化 manifest + native refs + 分层语义 | 不复制大数据 | FROZEN | NO | profiles分期 |
| P4D-012 | 科学表示 | typed descriptors；KNOWN/UNKNOWN/NOT_APPLICABLE | 不用默认值掩盖未知 | FROZEN | NO | 数值分期 |
| P4D-013 | Context | attempt 级窄上下文；无 registry/state/config bag | 防隐藏依赖 | FROZEN | NO | — |
| P4D-014 | Task | immutable TaskSpec；状态/attempt 分离 | 可审计、可恢复 | FROZEN | NO | — |
| P4D-015 | Plan | 校验后不可变 DAG；完整版本化存盘 | 重启不用猜图 | FROZEN | NO | — |
| P4D-016 | 指纹 | recipe + 实际上游语义结果 + 执行身份 | 防伪复用 | FROZEN | NO | — |
| P4D-017 | Cache | 匹配配方且结果、manifest、资产复验 | 目录存在不够 | FROZEN | NO | 强身份扩展5 |
| P4D-018 | Error/retry | 显式 transient 才重试；预算有限 | 防确定性死循环 | FROZEN | NO | — |
| P4D-019 | State | 5种task状态；attempt与completion独立 | 去除状态膨胀 | FROZEN | NO | — |
| P4D-020 | Invalidation | 由结果摘要传播，不设第二套失效树 | 保持分支局部性 | FROZEN | NO | — |
| P4D-021 | Provenance | run/attempt/product分别拥有事实 | 防多份真源 | FROZEN | NO | — |
| P4D-022 | 资源 | CPU/GPU/可选memory；仅准入账本 | 不装成HPC | FROZEN | NO | 其他hint延期 |
| P4D-023 | 序列化 | 冻结值对象+显式strict JSON | 不依赖Pydantic运行时 | FROZEN | NO | — |
| P4D-024 | Composition | 配置到任务的装配在应用层 | 保持CLI/Core薄 | FROZEN | NO | 真配置映射5 |
| P4D-025 | 公共面 | 文档化模块路径；根包仍仅版本 | 避免无意API | FROZEN | NO | — |
| P4D-026 | 操作桥 | OperationBinding衔接不同family方法与Core | 不强迫统一run | FROZEN | NO | — |
| P4D-027 | 中间记录 | ArtifactRef适用于Product/目录/metadata/QC | 非Product不伪装成SAR | FROZEN | NO | — |
| P4D-028 | Dry-run | 纯计划；未知执行指纹显式UNRESOLVED | 不假装环境已检验 | FROZEN | NO | — |
| P4D-029 | 提交 | attempt隔离目录+最后提交receipt | 防半成品变缓存 | FROZEN | NO | — |
| P4D-030 | Resume | 新run引用旧run；不重写旧成功记录 | 留住历史证据 | FROZEN | NO | — |
| P4D-031 | 并行 | 单协调器+受限本地线程worker | 真并行但无分布式 | FROZEN | NO | — |
| P4D-032 | Fake/配置 | 程序化Fake；不加fake YAML值 | 保持515测试边界 | FROZEN | NO | — |
| P4D-033 | 异常叶 | 允许依赖既有core.exceptions，禁止core整体重导出 | 不搬动Phase3 | FROZEN | NO | — |
| P4D-034 | 存储 | 工作区单writer锁；JSON记录；cache为派生索引 | 简单可恢复 | FROZEN | NO | — |
| P4D-035 | 资产路径 | 显式anchor；非cwd；输出所有权检查 | 防错路径及覆盖 | FROZEN | NO | — |
| P4D-036 | 动态发现 | 发现和处理用两个固定plan段 | 不让Core选SAR日期 | FROZEN | NO | 首用5 |
| P4D-037 | 部署信息 | 软件路径/凭据只在组合时注入 | 不进语义参数或日志 | FROZEN | NO | 后端5起 |
| P4D-038 | 完整性 | P4完整内容校验；弱身份禁用缓存，不强迫扫描大数据 | 安全降级 | FROZEN | NO | 强不可变身份5起 |
| P4D-039 | 第三方发现 | entry points暂不实现 | 当前无需要 | DEFERRED | NO | 首个第三方包时 |
| P4D-040 | 详细科学profiles | 不冻结实际Pair/Stack/Official科学字段值 | 尊重真实验证阶段 | DEFERRED | NO | 5/8/10/11/12/16 |
| P4D-041 | 调度扩展 | scratch/walltime/cluster字段暂不加稳定类 | 避免虚构执行保证 | DEFERRED | NO | 需要时ADR修订 |


# 4. Core Contract

Core 拥有图校验、ready 集合、资源准入、attempt 生命周期、有限重试、cache 选择/复验、commit receipt、恢复和 provenance 编排。Core 读取的是冻结合同、已解析输入和 registration，不读取 Phase3 Pydantic 模型，不解释 acquisition 日期选择、波长、地理网格、phase-to-LOS 或校正公式。

Core 可以把 plugin ID、operation ID、profile ID 当作不透明查找键；不可按其中的具体名称执行科学分支。通用字段检查、schema版本、文件/目录种类分派不属于科学特例。

**统一的是 Task 操作端口，不是六类插件 API。** `OperationBinding` 是一条明确注册的适配记录：把冻结的任务参数/ArtifactRefs变成某一family的typed request，调用它的family方法，再把结果变成受检ArtifactDraft。新插件带来注册记录/适配器/测试，不能要求改 executor 的分支。

稳定的是类型语义、输入输出端口、版本和状态行为。worker池内部、cache索引布局优化、JSON暂存文件命名等为内部实现；不得改变提交点和恢复语义。P4不增加公共 `run/resume/plan` CLI；这些能力先由Python API与Fake integration使用。


# 5. Six Plugin Contracts

所有插件都提供无副作用的 immutable `descriptor`。实例由 composition 注入明确依赖后构造；registry注册不实例化它们。默认每次task预检/attempt执行创建独立实例，不共享可变插件状态。运行预检可创建短生命周期实例，cache命中仍不得虚构执行attempt。type hints不替代显式验证，`runtime_checkable`也不能证明完整签名/科学正确性。

以下为冻结的family入口；`parameters` 是经该operation的版本化validator验证的FrozenJSON，不是未检查的任意配置字典。上下文是第7节的窄 `ExecutionContext`。

## Mission

`inspect(request: InspectionRequest, context: ExecutionContext) -> AcquisitionMetadata`

拥有产品/传感器/采集元数据解释与来源标注。输入为一个已取得的raw/source Product及检查参数；输出包含采集标识、时间、mode、frequency/polarization等可表达的metadata和证据引用。能力声明包括能解释的source/profile/mode，不包括下载权限。

禁止下载、凭据处理、调用Processor、生成调度图。缺少元数据可以显式UNKNOWN，但消费该字段的处理器必须拒绝不充分输入。具体任务命名、参数值和物理约定在Phase5/9/10冻结。

## Provider

`search(request: SearchRequest, context: ExecutionContext) -> CatalogSnapshot`

`acquire(request: AcquireRequest, context: ExecutionContext) -> ProductDraft`

search取得目录快照；acquire取得一个明确选中的catalog条目，其多个文件可以作为同一个source Product的assets。多景获取由多个Task表示。Provider管理传输、校验、源缓存与访问状态；credentials仅委托系统/专用凭据机制，不能返回到持久化记录。

**访问不是单一互斥枚举。** 冻结 `AccessStatus(availability=AVAILABLE|UNAVAILABLE|UNKNOWN, delivery=DIRECT|ORDER_REQUIRED|CATALOG_ONLY|UNKNOWN, authentication_required=bool|unknown, reason_code)`。一个条目可以既需鉴权又需订购；不得强迫它在AUTHENTICATED与ORDER_REQUIRED二选一。

Provider不决定参考影像、InSAR looks或科学配对。query只表达显式选择器及其schema；结果先持久化，再由应用层做选择。search默认 `cache_policy=DISABLED`，避免目录更新后仍当静态结果复用；已保存CatalogSnapshot可作为明确外部输入。

## Processor

`process(request: ProcessingRequest, context: ExecutionContext) -> tuple[ProductDraft, ...]`

输入包括按角色命名的source Products、AcquisitionMetadata、DEM/orbit等ArtifactRefs、明确purpose/profile和语义参数。拥有原生配置生成、外部调用、native输出验证与标准Product映射。所用native defaults及影响结果的软件设置必须在执行前进入SemanticExecutionIdentity；写出的native config作为证据保存并校验与准备阶段一致。

返回输出前必须结束/关闭其写入者；Core只在所有声明输出通过验证后发布receipt。Processor可复用原生checkpoint，但不让Core管理某个后端每一个内部算法步骤。不拥有下载账号，不覆写通用状态机，不把私有路径树提升为API。

## Correction

`correct(request: CorrectionRequest, context: ExecutionContext) -> tuple[ProductDraft, ...]`

输入为明确目标Products/layers、外部模型数据ArtifactRefs，以及 `CorrectionSpec`：方法id、input/output domain、application stage、unit/sign/frequency要求、field-only或apply的操作能力。field和corrected输出端口在计划中明确；Core不代为执行减法、投影或单位换算。

输出必须是派生产品，继承可追溯lineage。输入资产禁止修改；未变化的只读geometry可引用，已校正的层必须指向新资产。重复施加同一校正也必须是显式参数/lineage决定，不可隐式自动累加。方法物理定义和比较阈值延期Phase12/15。

## Analyzer

`analyze(request: AnalysisRequest, context: ExecutionContext) -> tuple[ProductDraft, ...]`

接收已声明兼容profile的Products及必要辅助输入，完成私有格式转换、配置、分析和结果映射。输入兼容性检查必须早于真实运行；不能用“kind叫stack”代替SLC/IFG、参考和时间轴的兼容声明。

禁止上游重新下载/原始配准、要求Core识别StaMPS/MintPy目录。P4只实现synthetic profile；真实StackProduct的首版由Phase5产出阶段定义，Phase11按版本扩展，不静默改写既有profile。

## QC

`assess(request: QCRequest, context: ExecutionContext) -> QCReport`

输入Products/记录、明确metric/profile、阈值和对比基准引用；输出 `PASS|WARN|FAIL|NOT_EVALUATED`、各指标值/单位、发现项safe code、方法/版本及输入引用。指标计算中的失败是ExecutionError；有效QCReport中的FAIL是质量发现，不是应重试的计算异常。

Task执行成功、Product结构有效、QC通过是三个不同结论。P4的RunResult保留execution_status与QCReportRefs，不制造一个同时声称科学接受的success布尔量。是否以QC发现阻断科学发布由后续显式QualityPolicy决定；P4不暗设“方差越小越好”。


# 6. Product Contract Freeze

## 6.1 层次与字段

**Product不是任意JSON包，也不要求所有任务都产出SAR Product。** CatalogSnapshot、AcquisitionMetadata和QCReport是独立typed records；它们与Product都能通过轻量ArtifactRef连接Task。只统一引用/持久化机制，不抹平数据语义。

| 类型 | 冻结字段/约束 |
|---|---|
| `ArtifactRef` | `record_id, schema_id, schema_version, semantic_digest: str|None, manifest_digest, locator`；定义于基础`contracts/values.py`，不回引Product；定位与语义身份分开 |
| `ProductDraft` | `product_kind, profile_id, profile_version, assets, layers, geometries, acquisition_refs, semantic_metadata, extensions`；不自行伪造run/producer/lineage |
| `Product` | ProductDraft内容，加 `schema_id, schema_version, product_id, producer, produced_by, lineage, provenance_ref`；由Core最终封装 |
| `ProducerRef` | plugin kind/id/API、implementation identity、SemanticExecutionIdentity digest |
| `ProductionRef` | task fingerprint、output port、产生它的attempt reference |
| `LineageEntry` | input port/role、实际ArtifactRef、输入semantic digest；Core由声明输入完整生成 |
| `NativeAsset` | `asset_id, asset_kind, location, media_type, size_bytes, integrity, member_manifest_ref`；file/directory区分 |
| `DataLayer` | `layer_id, role, asset_id, selector, quantity, unit, sign, geometry_ref, nodata, dimensions` |
| `GeometryDescriptor` | `geometry_id, domain, coordinate_reference, axes, shape, grid_definition, registration, reference` |
| `SemanticValue[T]` | `status, value, reason_code, evidence_refs`；明确known/unknown/not-applicable |

`schema_id` 是具体可解析记录结构的版本标识；`profile_id/profile_version` 是科学内容/消费兼容约束，不与包版本、plugin API混用。P4内置只需通用Product envelope及Fake profiles；不创建空壳Pair/Stack/Official类冒充已支持。

`product_id/record_id` 是不可变实例ID，可使用UUID；不是缓存键。`semantic_digest` 标识对计算有意义的内容与产生它的recipe；`manifest_digest` 校验完整记录字节，包含路径/来源等审计信息。后两者不能互相替代。

## 6.2 原生容器和逻辑层必须分开

一个HDF5文件或native目录可以包含多个不同单位/网格的层。因此unit/sign/geometry放在DataLayer及其GeometryDescriptor，不能只在Product顶层放一个unit/sign然后声称全部层相同。

`selector` 为 `None` 或受控的 `LayerSelector(format_id, selector_string)`；例如子数据集路径仅作为标识，不执行表达式，也不要求Core导入h5py。层语义不能从文件扩展名、文件名或backend目录猜测。

`SemanticValue`约束：KNOWN必须有匹配类型的value；UNKNOWN必须有原因；NOT_APPLICABLE也必须有原因且value为空。未知不是零，不适用不是未知。通用manifest允许合理的未知值；消费operation的profile requirements必须在缺少必要信息时拒绝处理。

结构化科学descriptor采用以下最小形态：

| 类型 | 表示什么；不做什么 |
|---|---|
| `UnitSpec` | 受控/命名空间化unit id、quantity kind、定义引用；允许注册新单位，不做自动换算 |
| `SignSpec` | convention id、observable、positive_direction、可选有序差分`minuend/subtrahend`引用、定义证据；不替用户选正方向 |
| `PhysicalQuantity` | 有限数值、UnitSpec、source/evidence引用；无硬编码默认波长 |
| `GeometryDescriptor` | radar/geocoded/point/scalar/other的显式域、坐标/网格定义引用、轴语义及registration；不强制一律affine/经纬网格 |
| `ConversionRecord` | 已实际应用的rule id、源/目标层、量纲与系数证据、操作说明；公式字符串仅供记录，Core不得eval |
| `NoDataSpec` | mask reference、finite sentinel或明确`nan`标识；JSON不得写裸NaN |

geometry可共享，但每个层须明确引用。不同频率/极化/网格不得仅因属于同一Product就被隐式合并。source metadata优先及fallback来源披露遵循路线图；具体默认物理值仍在真实Mission/Backend阶段批准。

## 6.3 路径、资产身份和覆盖保护

`AssetLocation`仅有三类：`MANIFEST_RELATIVE`、`ABSOLUTE_LOCAL`、`REMOTE_REFERENCE`。相对路径以持有manifest的显式基址为anchor，不以进程cwd为anchor；禁止`..`逃逸、无声明基址和隐式环境变量展开。允许绝对本地输入引用，但不会将其当作可写输出。

REMOTE_REFERENCE在P4仅存档标识；读取远端数据必须经Provider显式materialize，Core不得自动联网。URI中禁止userinfo、token和预签名凭据；应保存稳定无敏感信息的产品标识/位置，不保存临时鉴权链接。

新科学输出只能写入当前attempt拥有的artifact目录；插件可以只读引用上游已存在资产。校正、分析不得写回上游路径，包括解析后相同的symlink/hardlink目标。运行验证使用真实路径/同文件检查做所有权判定，但**不改变Phase3的词法路径规范化**。插件代码是受信任扩展，这些规则及测试不构成恶意Python代码的隔离沙箱。

目录资产必须明确其成员范围和member manifest。不能拿目录mtime或目录路径当内容指纹。若后端隐式glob目录，成员集合就是语义输入，不能把新增/删除成员当无关变化。

## 6.4 验证、质量和不可变性

验证分三层：通用结构校验（纯内存）；资产/提交完整性校验（明确I/O）；operation/profile兼容验证。QC不替代前三者，前三者也不意味着科学有效。验证报告单独保存并引用Product digest；不可每次QC后回写Product的可变`validated=true`，否则会污染身份/lineage。

Product及Task等值对象使用冻结dataclass，并将容器递归复制为只读映射/tuple。仅写`frozen=True`不足以防嵌套dict/list被修改。字段构造与反序列化都必须验证。

extensions采用命名空间化FrozenJSON；默认全部属于语义内容并参与digest。纯诊断注释必须放独立provenance区域；未知extension不得使消费方默认为“理解了该科学语义”。无注册validator支持的关键profile应明确拒绝。

## 6.5 序列化和摘要

公开持久化记录使用显式schema id/version和strict JSON；未知顶层字段或不支持版本拒绝，扩展仅在预留命名空间内。不同记录类型的schema版本互不联动。

`canonical_json_v1`：UTF-8、对象键排序、紧凑分隔符、`ensure_ascii=False`、`allow_nan=False`；反序列化拒绝重复key及非有限数值。字符串不做隐式Unicode语义改写；数组顺序保留，参考/次影像等有序含义不能排序抹去。只接受显式支持的JSON值，bool不能混充整数。原始1与1.0可产生不同摘要，宁可保守多算，不隐式科学等价化。

为防hash循环：`ArtifactRef`与`manifest_digest`保存在持有者/receipt，不把完整manifest的byte digest放进它自身；Product的provenance_ref是run/task/attempt标识指针，不要求包含将来finished记录的digest。同Product内部层/网格通过asset_id与selector引用，不构造指向自己的ArtifactRef。目录member manifest不得把它自身作为待hash成员。

Recipe/semantic digest均为 `SHA256(domain_tag || canonical_json_v1(projection))`，各用途有不同domain tag及算法revision。完整manifest digest为实际落盘bytes的SHA256；不用Python内置hash、repr、pickle或仅路径字符串。时间、实例ID、locator、run/attempt引用不进入semantic projection，但它们仍受manifest digest保护。


# 7. Runtime Contract Freeze

## 7.1 身份、注册与操作端口

`PluginKind`恰好六值。`PluginRef(kind,id,api_version)`用于查找，Phase4 API精确匹配1；一个sealed registry中同一(kind,id)只能注册一次，不做“最新版本”猜选。`PluginDescriptor`还含implementation_version、display_name和排序后的namespaced capability IDs。capability描述是声明，不是软件已可运行的证据。

`PluginRegistration`包含descriptor、无副作用factory及operation bindings。registry的register/seal/resolve是唯一注册体系；输出codec/profile validators附属于bindings，不另建自动插件依赖求解器。

每个 `OperationBinding`固定：`operation_id, operation_api_version, parameter_schema_id/version, input/output port contracts, required_capabilities, validator_revision, handler`。handler端口为：

- `validate_spec(parameters, input/output declarations) -> ValidationReport`：纯检查，供构图/dry-run使用。
- `prepare(plugin, resolved_inputs, parameters, probe_context) -> PreparedExecution`：明确运行预检；解析兼容性、必要native身份及effective scientific settings，不产出科学资产。
- `invoke(plugin, prepared, resolved_inputs, parameters, context) -> TaskOutcome`：调用family方法。

`PreparedExecution`包含可审计的SemanticExecutionIdentity和明确执行准备；native路径/活句柄不塞入其持久化projection。Typed输入/输出通过本operation的codec/validator绑定，禁止从JSON反射import任意类/函数或`getattr(plugin,user_string)`执行。

`TaskOutcome.outputs`是按声明port命名的ArtifactDraft集合。Draft由typed record的绑定codec生成，经过记录schema、Product profile、资产和数量验证后，Core添加身份/lineage、写manifest和receipt。不能以“插件返回成功”跳过验证。

## 7.2 ExecutionContext

稳定字段只保留：`run_id, task_id, attempt_id, attempt_dir, artifact_dir, scratch_dir, allocated_resources, logger, cancellation_requested`。

它不包含registry、StateStore、CacheStore、完整requested/resolved config、任意services字典、凭据或共享可变science state。完整服务由executor内部的RunContext持有；插件需要的science输入在typed request中，部署路径/credential resolver由composition注入factory。插件不得把context中的run_id、临时时间或task_id暗中当随机种子/科学参数；所需seed必须显式进入语义请求和执行身份。native config和安全证据通过TaskOutcome返回，由协调器统一登记。

dry-run不创建ExecutionContext；不靠一个布尔flag要求插件“自觉不写”。并行worker不得调用全局chdir、改os.environ或配置全局logger；原生命令使用显式cwd/env，实际外部调用留Phase5。

## 7.3 TaskSpec 与 WorkflowPlan

`TaskSpec`冻结字段：

| 字段 | 含义 |
|---|---|
| `schema_version, task_id` | 任务描述版本；plan内唯一id，不等于缓存键 |
| `plugin_ref, operation_id, operation_api_version` | 精确匹配注册端口 |
| `inputs` | 唯一命名的input ports；每个含有序ArtifactRef或OutputRef集合；OutputRef解析为其port的有序记录tuple，按声明次序展开 |
| `outputs` | 明确port、schema/profile、固定正整数cardinality；与registration一致。可变catalog条目放一个CatalogSnapshot，不动态改变port数量 |
| `semantic_parameters` | 经版本化validator校验的FrozenJSON；只放相关解析后参数 |
| `resources` | ResourceRequest，不搬用配置中的num_proc=0 |
| `retry_policy` | max_attempts、backoff_seconds |
| `restart_safety` | RESTARTABLE / UNSAFE |
| `cache_policy` | AUTO / DISABLED |

`OutputRef(task_id,port)`形成图的数据依赖；不保存第二份可能矛盾的depends_on图。P4不需要无数据的任意控制边。所有task至少声明一个结果record；QC/metadata任务同样可有record输出。optional功能在应用层编译时省略节点；不引入SKIPPED成功状态、不虚构其输出。

WorkflowPlan持有不可变TaskSpec集合、精确external input refs、schema_version和plan digest。校验唯一id/端口、存在的引用、输入输出schema/profile兼容、无cycle、registry可解析、retry/resource合法。依赖边由OutputRefs推导；序列化顺序以task_id稳定排序，**input port内有序来源不排序**。

完整计划以JSON保存，不只有一个hash。缓存不采用整个plan hash，因此无关节点变化不使全图失效。运行期DAG不可原地改写。目录发现后才知道景数时，先完成discovery plan并保存CatalogSnapshot，再由应用层创建processing plan；segment用provenance和ArtifactRefs连接。Core不选参考日期、不增删SAR任务。

## 7.4 状态机、attempt和终止语义

TaskState只保留：`PENDING, RUNNING, SUCCEEDED, FAILED, BLOCKED`。

READY是从依赖成功、retry时间到达和资源可用推导的集合，不持久化。CompletionDisposition为`EXECUTED | CACHE_REUSED`；缓存命中不虚构一次执行attempt。

AttemptOutcome为`SUCCEEDED | FAILED | INTERRUPTED`。attempt开始记录先写，结束记录后写；retryability属于错误分类，不是TaskState。

| 起点 | 条件 | 终点 / 记录 |
|---|---|---|
| PENDING | 依赖就绪、预检通过且缓存通过复验 | SUCCEEDED / CACHE_REUSED；记录引用旧receipt |
| PENDING | 依赖就绪、资源已分配、实际开始 | RUNNING；创建新attempt |
| PENDING | 本任务确定性预检失败 | FAILED；保存安全预检报告，不伪造attempt |
| PENDING | 数据依赖已FAILED或BLOCKED | BLOCKED；保存阻塞链 |
| RUNNING | 输出验证且成功receipt已提交 | SUCCEEDED / EXECUTED |
| RUNNING | 显式transient、可安全重跑、预算尚有 | 结束FAILED attempt；Task回PENDING并登记next_ready |
| RUNNING | permanent/contract/输出错误或预算耗尽 | FAILED |
| RUNNING | 中断/进程死亡得到恢复确认 | 旧task投影为FAILED且原因INTERRUPTED；attempt为INTERRUPTED；旧run记INTERRUPTED；新run另行决定是否重跑 |

普通执行中terminal task不反向跳转。run执行状态为`RUNNING | SUCCEEDED | FAILED | INTERRUPTED`；所有选定task成功才SUCCEEDED，最终failed/blocked导致FAILED；用户/进程中断优先明确INTERRUPTED。独立分支默认继续，不因其他分支失败全部取消；显式全局取消另算中断。

## 7.5 Error 与 Retry

保留原 `InSARForgeError` 类及 `ConfigurationError` 语义。新增合同错误在`contracts/errors.py`定义，继承精确的旧base。最小类型：`ContractError`（含未知/重复插件、版本或端口错）、`CapabilityUnavailableError`、`InputValidationError`、`ExecutionError`、`RetryableExecutionError`、`OutputValidationError`、`WorkflowStateError`、`WorkspaceError`。

只有 `RetryableExecutionError` 可以自动重试，同时必须 `restart_safety=RESTARTABLE` 且未耗预算。普通Exception/TimeoutError/OSError不自动被判transient，具体插件必须明确定义分类。未知异常变为安全code的不可重试执行错误；不将原始str(exc)、命令、环境或token写进公开日志/manifest。

RetryPolicy默认为`max_attempts=1, backoff_seconds=0`；max_attempts包含第一次执行，所有值严格类型/范围检查。P4采用固定有限backoff、不引入jitter框架。retry不同于native处理器自己的checkpoint；后者由插件管理并记录。

## 7.6 Fingerprint 与结果身份

区分三件事：`TaskSpec/plan digest`用于重建描述；`task fingerprint`是缓存recipe；`artifact semantic digest`是实际结果身份。最终task fingerprint只在输入ArtifactRefs已解析且执行身份准备完成后生成，不写死在初始TaskSpec中。

```text
F_task = H("insarforge.task.recipe.v1", {
  core_semantics_revision,
  engine_code_identity,
  operation_id, operation_api_version, validator_revision,
  plugin_kind, plugin_id, plugin_api_version,
  plugin_implementation_identity,
  semantic_execution_identity,
  validated_semantic_parameters,
  ordered_input_ports: [(role, [input.semantic_digest, ...]), ...],
  declared_output_contracts
})

F_artifact = H("insarforge.artifact.semantic.v1", {
  schema_id, schema_version, profile_id/version,
  producer_task_fingerprint, output_port,
  typed_semantic_projection,
  referenced_scientific_asset_content_identities,
  ordered_input_lineage_semantic_digests
})
```

上述F公式仅在语义/完整性身份齐备时生成可复用摘要。任一必要identity不充分，`FingerprintResult(value=None, reusable=False, reasons=...)`；相关输出ArtifactRef的semantic_digest为None，下游也必须禁用缓存，不能把None或UNKNOWN固定字符串hash成可复用输入。执行仍以唯一record_id/attempt_id完整追溯，不阻止正常非缓存计算。`cache_policy=DISABLED`本身不等于身份弱：search虽每次重做，但其完整CatalogSnapshot有内容强身份时可以给下游正常的semantic_digest。

F_artifact包含真实资产/语义结果，不只是F_task。相同recipe因非确定性得到不同实际结果时，必须影响下游；变化的上游recipe即使偶然生成相同bytes，也按本项目保守规则传播。

必须排除时间、attempt次数、run/task实例ID、日志/temp/work目录、纯展示标签、全量requested/resolved文件hash、未影响科学的调度顺序。role与有序输入必须保留。相关的resolved参数逐项投影进task，不整包hash导致无关更改全失效。

`SemanticExecutionIdentity`必须覆盖：wrapper/adaptation代码内容身份；native程序及必要build/runtime依赖身份；实际native defaults/配置的语义projection；影响结果的CPU/GPU/precision/threading/random seed等设置；实际使用的外部科学资料身份（资料本身优先作为inputs）。原生路径是deployment binding，不把同名版本或路径当可靠实现身份证明。

`engine_code_identity`对Core及其共同合同/Product/provenance实现的代码/资源内容取摘要，不纳入无关具体plugin、tests或docs；具体binding及其实际helper/dependency身份归plugin implementation identity。包版本及git commit同时保留provenance，但commit不是唯一科学缓存依据。docs-only提交不必失效；实际执行代码变更必须失效。开发/dirty/`0+unknown`不直接禁止执行：有完整代码digest可用，否则此次task不可缓存。native身份未知也同理。不可用运行环境在本阶段是预检失败；不支持“依赖未安装但猜旧版本后跳过producer任务”。已验证旧Product作为external input时，不需要加载其历史producer。

默认把实际分配的CPU/GPU计数纳入执行身份，以免未知并行模式改变数值；binding仅在有明确合同/测试证明不影响结果时可声明某项为非语义。memory是准入预算，不承诺科学影响；任何根据memory选择的算法分块若影响数值，实际算法配置必须进入执行身份。

## 7.7 Cache与完整性策略

cache命中须同时满足：F_task匹配；存在完整committed receipt；manifest完整byte hash匹配且schema可解析；所有required outputs存在并符合当前合同；profile兼容；每个相关资产/成员集合的内容身份复验；当前input semantic digests与被记录的计算输入等价；执行身份可靠一致。

P4只实现本地`SHA256`与显式目录member manifest的完整内容验证。Fake使用很小的文件，必须检测“同大小、mtime恢复”的内容改变。仅size/mtime、URL、文件名、未声明语义的ETag不构成安全内容身份。

不强制Core为所有未来大数据无条件全盘扫描：插件可在写入/下载流中生成digest，并精确声明实际消费文件范围。若大资产暂时没有可验证强身份，`cache_policy=AUTO`自动降为不读写持久cache并记录原因，任务仍可运行。未来可信不可变snapshot/版本化数据源须在Phase5起提供真实验证策略后启用，不能现在给一个空check函数。**省I/O与完整性保证的取舍必须显式，不可把弱stat偷偷叫content hash。**

AUTO只允许结构/身份完备时复用；DISABLED每次执行且不发布可复用cache索引。目录搜索默认禁用缓存。损坏的候选结果拒绝复用，保留原始证据，不删除原Product；可安全重跑时产生新attempt，否则明确失败。

## 7.8 Idempotency与downstream invalidation

restartable意味着同一语义输入重复执行不会损坏既有有效输入/输出，不意味着浮点bytes一定一样。每次attempt有唯一输出所有权范围；不能通过`rm -rf`旧结果来实现“幂等”。

上游参数、metadata、代码、native身份、外部资料或实际结果摘要变化，使相关F_artifact变化，再改变下游F_task。无关分支不改变，不做全workspace purge。全量config hash和全plan hash不得进入每个任务的recipe。

复用旧结果时保持原producer、原attempt和原lineage；新run记录CACHE_REUSED及原receipt引用，不把旧Product伪装成本次生成。新输入实例与原输入semantic digest相同允许等价复用，但这不授权改写旧lineage。

## 7.9 提交与持久化

Phase4采用**工作区级一个协调器/一个writer**。本地POSIX文件锁保护整个workspace的state/cache更新，第二个writer明确拒绝。可用`fcntl.flock`，不做分布式锁；必须验证运行文件系统支持所需语义。

建议内部布局（文件名可内部调整，不改变语义）：

```text
<workspace>/.insarforge/
  workspace.lock
  runs/<run_id>/
    run.json
    plan.json
    config_refs.json
    attempts/<task_id>/<attempt_id>/
      started.json
      artifacts/       # 保持原生布局，结果提交后就地保留
      scratch/
      manifests/
      result.json      # 最后发布的成功receipt
      finished.json    # 结束/失败记录；可由receipt恢复派生状态
    resolutions/<task_id>.json  # executed/cache/blocked resolution
  cache/<task_fingerprint>/<result_id>.json  # 可重建索引
```

worker仅写自己拥有的attempt目录；state/cache/receipt只能由协调器发布。输入只读。插件返回前关闭写入者；协调器完成输出/manifest验证和必要flush，再通过同目录临时文件+fsync+原子replace发布小型receipt。receipt是成功提交点，不能先写SUCCEEDED后写产品。多文件整体不是一个神奇的原子事务；我们只承诺“没有有效receipt就不算已提交”。

crash在receipt前：半成品不复用，保留。crash在receipt后但run状态前：恢复验证receipt并认定该结果已提交，不无故重算。不能因为cache索引缺失而否认有效receipt；索引是可重建派生数据。P4不实现clean，不删除唯一结果或旧目录。原生数据无需为标准化而复制。

文件锁与atomic replace要求的是此执行文件系统经测试的本地POSIX能力；不声称已保证NFS/SMB/任意断电场景。遇到不支持语义的workspace应明确拒绝，而非降级无锁写入。

## 7.10 Resume

`resume(source_run)`创建新run_id并记录resume_of。旧成功/失败事实不被重置。对未闭合旧attempt添加显式恢复记录；有有效receipt则采用提交事实，无receipt则记INTERRUPTED。旧run不继续永远显示RUNNING。

新run用保存的plan、已验证input refs、当前精确execution identity评估复用。当前实现/identity/科学输入若已改变，必须创建replan的新运行并引用前次，不能声称对旧计划原样resume。

对相同resume链/TaskSpec/recipe，用`attempt_scope_id`累计attempt序号和已耗预算，包括已实际启动而中断的attempt，避免每次resume把max_attempts清零。默认max_attempts=1时，已耗掉的中断attempt不会被resume暗中追加机会；需明确批准新的execution scope，或最初即给足有限重试预算。身份不充分时不得声称精确resume同一计算，应启动标明不可复用身份的新运行。中断后的再次执行只有restartable、预算足够、无活动旧writer才允许。permanent失败或预算耗尽不自动重试；用户明确retry/replan创建新的execution scope并引用旧scope。

若旧成功资产后来损坏：不修改旧成功事实；新run拒绝复用并按重跑安全规则处理。Phase4仅in-process Fake；Phase5外部程序必须在binding恢复检查中证明旧进程/原生writer已停止，不能由Core猜测或盲目kill。

## 7.11 Dry-run

`dry_run(plan, sealed_registry) -> PlanReport`只校验声明、版本、端口、DAG、静态capability声明、资源请求可满足性，生成确定的plan摘要。不实例化插件、不调用prepare/invoke、不探测native程序、不读取凭据、不访问网络、不创建run/state/cache/output目录。显式请求导出PlanReport时，只写指定报告文件。

未产生的上游结果、未probe的native identity不能拥有最终F_task。返回`UNRESOLVED`与原因（如`UPSTREAM_OUTPUT_PENDING`、`EXECUTION_IDENTITY_UNPROBED`），不可拿占位hash当缓存键。静态advertised capability与运行环境可用性分列；后者在dry-run中为UNCHECKED。

## 7.12 真并行与资源

Phase4实现一个coordinator和有限ThreadPoolExecutor。线程用于编排独立操作，不承诺Python数值计算加速；真实CPU/GPU处理仍由后端拥有。不能只检查“有两个ready节点”就宣称并行通过；Fake测试用barrier/events证明同时在执行区间。

`ResourceRequest(cpu_cores:int=1, memory_bytes:int|None=None, gpu_count:int=0)`；bool不视作int，CPU≥1，memory已给定时>0，GPU≥0。运行Budget由composition显式给定；已知预算之和不能超配。memory请求存在但预算未知时预检拒绝；不假装已检测/限制实际RSS。预算约束只是声明准入，不是OS硬限制。

scratch/walltime/Slurm/PBS字段不进入P4稳定ResourceRequest。Phase3的`num_proc=0`仍保留“自动”的用户配置意图，Phase5由应用层翻译为运行预算，不能被Core误读为零CPU或通用per-task字段。

## 7.13 Provenance事实归属

| 事实 | 唯一主记录 | 其他地方如何使用 |
|---|---|---|
| 用户原始/解析配置及解析来源 | Phase3三文件原合同 | Run保存ArtifactRef/byte digest，不重造配置历史 |
| 程序化Fake配置来源 | 明确`source_kind=programmatic`的run输入记录 | requested/resolved可以不适用，不能伪造YAML来源 |
| 图、task参数、policy | 保存的WorkflowPlan/TaskSpec | attempt引用spec/plan digest |
| 实际执行软件/配置身份 | PreparedExecution/attempt执行身份记录 | receipt/Product引用其digest |
| native config内容 | attempt证据文件及byte digest | execution identity包含其语义projection；路径另存 |
| 开始/结束、重试错误/中断 | append-only attempt开始/终结记录 | task/run只作投影，不重复发明时间 |
| 输出内容/科学结构/lineage | Product/typed record manifest | receipt记录manifest digest，QC只引用 |
| 提交事实 | 成功receipt | cache/run状态引用，不反向制造成功 |
| 本次采用旧结果 | 新run的resolution record | 保留原producer和旧receipt |
| 当前进度/最终执行状态 | Run/Task投影 | 可由attempt/receipt恢复，不替代它们 |

所有持久化只能写已声明安全字段。扩展值也必须通过秘密材料检查；禁止原始认证环境、完整credential URL、私钥或未经清理的异常文本。Core不得为了复用扫描器而import依赖Pydantic的`config._values`。P4实现一个标准库内部持久化安全校验器，并以测试覆盖与Phase3已冻结的可识别秘密模式；不在本阶段移动或修改Phase3扫描器。

native checkpoint仍属于Processor内部。不要把每个原生算法子阶段当作可公开缓存的Product，也不能在一个目录尚被后续native步骤持续修改时将其宣布为不可变资产。Phase5优先选取足够粗粒度的backend Task封装内部工作流；原生resume只能在有明确所有权/终止确认且不破坏已提交产品时使用。


# 8. Dependency and Import Rules

## 8.1 稳定路径与允许依赖

| 模块区域 | 可以依赖 |
|---|---|
| `core/exceptions.py` | 标准库；保持现有base不动 |
| `contracts/values.py`, `contracts/identity.py`, `contracts/errors.py` | 标准库、同层叶模块；errors允许旧core.exceptions叶 |
| `products/assets.py`, `products/semantics.py`, `products/models.py`, `products/validation.py`, `products/serialization.py` | 基础contract叶模块、同层Product模块、标准库 |
| `contracts/records.py` | 基础叶和Product的引用/资产值对象；目录/metadata/QC typed records |
| `contracts/context.py` | 基础叶；ResourceRequest/Allocation、窄context |
| `contracts/plugins.py` | Product、records、context；六类request/Protocol |
| `contracts/execution.py` | 基础叶、context、ArtifactRef；TaskSpec/WorkflowPlan/AttemptState等值模型 |
| `contracts/operations.py` | execution/plugins/records与Product；registry entry、handler/codec端口 |
| `provenance/` | 中立合同与值模型；不导入Core执行器 |
| `core/registry.py`, 其他Core runtime模块 | 上述合同、Product验证、provenance实现和标准库 |
| `missions/providers/processors/corrections/analyzers/qc`的具体模块 | 自己的family合同、Product、records；必要依赖延迟导入 |
| `application/` | config、Core、contracts、具体插件；唯一正常assembly位置 |
| 现有 `config/` | 保持原依赖；例外只有既有core.exceptions基础叶 |

## 8.2 禁止依赖及检查

禁止Core导入任意具体family实现模块；禁止Product导入contracts.plugins/operations、Core执行器或具体插件；禁止基础contract叶导入上层Product/runtime；禁止provenance回指Core执行器；禁止config依赖新增runtime或具体插件。具体插件禁止直接改Core状态、cache索引或run records。

`contracts/errors.py -> core.exceptions`和既有`config/errors.py -> core.exceptions`是**点名的叶模块例外**，不是允许`contracts -> core.*`。保持`core/__init__.py`无executor重导出，防Python导入父包时形成隐藏循环。

测试使用AST规范化绝对/相对import，按**模块而非目录粗粒度**检查上表；在独立进程中阻断重依赖并导入全部public contracts/Core。再扫描Core控制流中的具体ID比较/映射，并用未预知plugin ID的额外Fake证明扩展。字符串grep只能辅助，注释中的后端名字不单独判错。不宣称有限静态规则能证明任意恶意动态代码都无科学分支。


# 13. P4.1 Implementation Specification

## 13.1 允许实现

只实现合同/值对象、显式schema验证、Product serializer、pure structural validation、registry和测试。稳定public模块按第8节。`contracts/records.py`须有CatalogSnapshot/AcquisitionMetadata/QCReport的最小typed envelope；在profile尚未定义的科学内容用明确SemanticValue/证据引用，不invent默认物理值。

`contracts/plugins.py`中六类request最小字段固定如下：

| request | 必需内容 |
|---|---|
| InspectionRequest | source Product/ArtifactRef、parameters |
| SearchRequest | query_schema_id/version、typed validated selectors |
| AcquireRequest | 明确catalog ArtifactRef和entry_id、获取参数 |
| ProcessingRequest | purpose/profile、命名Product inputs、AcquisitionMetadata refs、辅助资料refs、parameters |
| CorrectionRequest | source Products/layer roles、external inputs、CorrectionSpec、parameters |
| AnalysisRequest | input Products、auxiliary refs、目标analysis profile、parameters |
| QCRequest | target refs、metric/profile、阈值/对照refs、parameters |

请求持有实际已解析typed输入及其ArtifactRefs；不能只给任意路径让插件偷偷找未声明science输入。请求的structured参数schema、input/output ports和codec必须随OperationBinding版本一起验证。

P4.1中的ExecutionContext仅是类型定义，不创建state/cache。ResourceRequest及allocation是值对象。registry实现register/seal/resolve和必要纯校验；OperationBinding/handler只是端口与注册数据，不执行scheduler。TaskSpec/WorkflowPlan字段规范已在此冻结，但其可执行校验/序列化实现统一留P4.2，避免P4.1提前做完整runtime。

## 13.2 必测

深冻结（包括嵌套容器）、错误类型、注册冲突/未知/API不匹配、seal不可修改、所有family的typed request/result正反例、Product多层/多网格、schema与profile版本区分、UNKNOWN与NOT_APPLICABLE、relative anchor不依赖cwd、strict JSON重复key/非有限值、secret字符串不得持久化、轻量静默import、已有Phase3行为不变。

## 13.3 禁止

不写真实Mission/Provider/Processor；不放宽Phase3；不实现图executor、cache、retry loop、native命令、服务器验证、真实Pair/Stack科学profile；不增加Pydantic为Core依赖。内部helper函数/临时文件名可由Codex选择，但不得改public import paths或合同语义。


# 14. P4.2 Implementation Specification

实现TaskSpec与WorkflowPlan验证/strict序列化、单workspace锁、coordinator+bounded threads、资源准入、OperationBinding的执行路径、state/attempt、retry预算、semantic recipe、资产复验、成功receipt、cache lookup/index、resume、provenance及pure dry-run。

必须先有serial模式作为参考，再用相同semantics执行并行。选择ready任务时使用稳定task_id次序；完成记录保留真实完成顺序，不人为伪装串行日志。Clock/sleeper和故障注入点作为内部测试依赖注入，不暴露成全局service locator。

基础测试使用极小dummy operation即可，不必等待P4.3全部六family装配。此阶段必须已证明真实并发、故障提交窗口、canonical fingerprint、恢复预算和数据损坏识别；P4.3负责把这些组合到完整六类Fake工作流并验证整体边界，而不是首次补上正确状态语义。

不实现生产CLI、不改Phase3文件、不调用真实SAR软件。若发现旧合同冲突，停在受影响处，不能通过改515测试expected值过Gate。


# 15. P4.3 Final Gate Specification

完整Fake workflow必须使用registry、typed输入/输出、真正持久化/重新读取的manifest以及实际executor，不可把几个Fake函数顺序调用后称作E2E。

六角色必须参与，但不强迫错误的物理顺序。推荐已知两项Fake catalog fixture：两条`Provider.acquire -> Mission.inspect`独立支路汇合到`Processor -> Correction -> Analyzer -> QC`；额外测试`Provider.search`生成CatalogSnapshot后由应用层构建第二个固定plan。所有数据为小JSON/text/有限数组文本fixture，无native SAR、网络、账户或许可证。

| Gate ID | 场景 | 必须证明 |
|---|---|---|
| G01 | 正常六family工作流 | 所有声明输出提交、重读、schema/lineage正确 |
| G02 | pure dry-run | factory/prepare/invoke计数0；无I/O；未知F为UNRESOLVED |
| G03 | 并行支路 | barrier/events证明实际重叠执行，不只ready集合 |
| G04 | 资源 | 声明CPU/GPU/memory不超Budget；不可满足请求早失败 |
| G05 | transient后成功 | 失败attempt保留，有限retry得到成功 |
| G06 | permanent失败 | 一次执行即止，不消耗无意义retry |
| G07 | retry耗尽 | max_attempts含首试；最终FAILED |
| G08 | 上游失败 | 后继BLOCKED；阻塞链可追溯 |
| G09 | 无关分支 | 仍执行/复用，不全局fail-fast/purge |
| G10 | cache命中 | 无invoke、无伪attempt；引用原producer/receipt |
| G11 | 相关参数变化 | 新F_task和对应下游变化 |
| G12 | native身份变化 | wrapper不变也不能复用 |
| G13 | 实际输出变化 | 相同recipe不同内容改变下游，而非只用recipe hash |
| G14 | 无关config/显示路径变化 | 不使全部节点失效；数据身份不变则局部复用 |
| G15 | 缺失/损坏资产 | same-size+mtime恢复仍检出；不是只exists/stat |
| G16 | 目录成员变化 | 按声明member集合检测增删/内容变更 |
| G17 | manifest损坏 | duplicate key、bad schema/hash、缺port明确拒绝 |
| G18 | receipt前crash | 半成品永不cache；不先SUCCEEDED |
| G19 | receipt后crash | 恢复提交事实，不因summary未写而重复算 |
| G20 | resume | 新run引用旧run；旧lineage不重写 |
| G21 | 跨resume预算 | 不通过反复resume无限retry |
| G22 | 不安全恢复 | UNSAFE或旧writer活动时拒绝自动重跑 |
| G23 | duplicate/unknown plugin | typed错误；无默认fallback |
| G24 | contract/API/capability不符 | 执行前拒绝；不拿type hints冒充运行校验 |
| G25 | cycle/dangling/错port | Plan验证拒绝 |
| G26 | 新Fake插件 | 新mission/processor ID仅注册+实现+tests；Core源hash不变 |
| G27 | private layout变化 | 改Fake native子目录，consumer只靠manifest仍运行 |
| G28 | 多层科学语义 | 同容器不同单位/网格被保留；缺必要sign则拒绝消费 |
| G29 | Correction输入保护 | 原输入hash不变；新层新资产；检测别名覆盖 |
| G30 | QC FAIL | 计算可成功且报告FAIL；不伪装科学PASS，不retry |
| G31 | secret处理 | URL/参数/exception/native evidence不泄露识别出的凭据 |
| G32 | serialization | round-trip稳定；schema版本独立；嵌套不可变 |
| G33 | imports/分支 | AST+阻断重依赖+未知ID扩展联合证明 |
| G34 | 两段plan | discovery数据作为显式输入；Core不动态选景扩图 |
| G35 | 单writer | 第二coordinator拒绝；允许worker并行但不并行写state |
| G36 | 旧基线 | 原515测试全部保留通过；Ruff通过；Python矩阵按既有CI |

P4 Gate只证明工程与合同有效，不证明真实SAR输出科学可信。Phase5仍必须进行服务器Pair/Stack回归。


# 16. Scientific Decisions Explicitly Deferred

| Scientific topic | 现在冻结的结构 | 不在本轮选的科学值 | Target Phase | Later user approval |
|---|---|---|---|---|
| wrapped/unwrapped phase | SignSpec+layer quantity | 真实相位正负及参考乘积顺序 | 5；新后端6/7/10 | YES |
| LOS displacement | unit/sign/reference descriptors | 朝向/远离正号 | 5及后端接入 | YES |
| phase→LOS | ConversionRecord+PhysicalQuantity来源 | 具体公式与符号映射 | 5；9/10 | YES |
| wavelength/frequency | 已知/未知的值及来源证据 | 元数据缺失时的实际fallback值 | 5/9/10 | YES |
| range/azimuth offset | 量纲/方向/轴/来源字段 | 正方向及像元→米映射 | 5/6/7/8/10 | YES |
| radar/geocoded geometry | 显式domain+grid definition引用 | 各真实产品轴意义/变换 | 5/8/10 | YES |
| pixel/grid registration | registration语义槽位 | 具体backend栅格注册/GeoTransform映射 | 5/6/7/8 | YES |
| correction domain/sign | CorrectionSpec及输入/输出语义 | zenith/slant/LOS投影与加减号 | 12/15 | YES |
| radian/metre conversion | quantity/unit/conversion记录 | 使用哪个真实系数与约定 | 5/12 | YES |
| polarization/frequency | 独立层、acquisition、profile refs | 是否联合、如何匹配/处理 | 9/10/16 | YES |
| reference acquisition | 明确role和有序refs | 真实选景/参考策略 | 5/11/13/16 | YES |
| Stack SLC/IFG/network | profile id/version+必要记录refs | PS/SBAS、网络/参考细则 | 首版5，完善11/13/16 | YES |
| QC指标/阈值 | QCReport及metric/阈值来源 | 哪些阈值具有科学接受意义 | 5起、11/12/15 | YES |

这些值现在可以延期，因为P4只对typed结构、已知/未知传播及Fake契约作验证；没有真实后端执行。延期不是省略表示或让后端猜默认值。


# 17. Non-Goals / Rejected Over-Engineering

| Topic | Ruling | 边界 |
|---|---|---|
| local DAG+有限线程+单writer | INCLUDE NOW | P4退出条件需要真并发及可恢复 |
| 分布式scheduler/远程执行协议 | DEFER | 无真实需求及跨节点测试 |
| asyncio框架 | DEFER | 同步family方法+有限线程足够 |
| event bus / 图变换框架 | DEFER | 不为少量状态记录引入框架 |
| database state service | DEFER | 版本化文件+receipt足够 |
| cloud object-store | DEFER | 仅保留可引用位置，不实现存储层 |
| 插件依赖求解 | DEFER | 同一registry精确版本绑定即可 |
| 通用DI/service locator | REJECT FOR CURRENT ARCHITECTURE | 显式构造/窄context |
| filesystem自动发现/反射执行 | REJECT FOR CURRENT ARCHITECTURE | 无授权代码加载面 |
| entry points | DEFER | 第三方包出现时再实施 |
| Slurm/PBS特定模型 | DEFER | generic ResourceRequest不含queue/partition |
| 通用单位换算引擎 | DEFER | 只记录typed语义，不做物理换算 |
| 所有family统一run | REJECT FOR CURRENT ARCHITECTURE | 统一Task操作端口而非业务接口 |
| 生产SAR实现/服务器测试 | DEFER | Phase5起 |
| 新增public workflow CLI | DEFER | 当前只Python/Fake入口，保留旧CLI |


