# ADR-0001 — Core Boundaries and Dependency Direction

**Status: ACCEPTED**。架构审查接受；仓库落库和实现Gate仍分别执行。

**Context.** Phase3已经有严格配置与异常基础，而没有通用执行器。若把其Sentinel-1/ISCE2 literals、默认值解析、目录名复制进Core，会使后续多任务扩展依赖改Core。

**Decision.** Core只消费中立合同和sealed registry；配置到Task的映射在application；Fake程序化组装。按第8节模块级DAG约束imports，点名保留旧core.exceptions基础叶例外。根包不扩大exports。动态目录发现分为两个不可变plan段，科学选择不归Core。

**Rationale.** 保留现有515测试边界，在不移动旧基础类、不假装通用YAML已经存在的情况下建立依赖倒置。

**Alternatives rejected.** Core直接接收Pydantic Config并按mission分支；将Fake值加入生产schema；一次性搬动全部config/errors/logging；运行时自动扩图并让executor选SAR日期。

**Consequences.** 插件需要显式operation adapter；多一层薄assembly，但Core不随mission改变。允许的旧异常叶引用必须被静态规则精确表达。

**Invariants.** Core不import具体插件；config行为/默认值/保存合同不变；公共轻量imports不触发SAR/Pydantic/YAML导入或日志配置；没有隐式CWD依赖。

**Non-goals.** GUI、真实数据选择、生产CLI扩充、native算法迁移。

**Deferred.** Phase5具体YAML→runtime适配及两段plan案例；新科学profile按真实Phase批准。

**Enforcement.** P4.1 import tests、P4.2图静态性、P4.3新plugin不改Core测试；全过程原515回归保持通过。


规范性细节：`../architecture/phase4-contracts.md` 对应主题。本文为 `P4.0-FREEZE-1` 的已接受架构决定，生产实现尚未完成。
