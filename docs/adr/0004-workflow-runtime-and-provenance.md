# ADR-0004 — Task, WorkflowPlan, State, Fingerprint, Cache, Retry and Provenance

**Status: ACCEPTED**。

**Context.** 当前没有runtime，候选将READY/RETRYABLE_FAILED/CACHED/SKIPPED全当state，并未解决native版本、dry-run未知输入、crash提交窗口或旧lineage复用。

**Decision.** immutable TaskSpec和保存的immutable DAG；5种task state、独立attempt/outcome/completion；显式transient且安全重跑才有限retry。最终recipe由实际输入semantic digests和完整execution identity生成。cache必须复验已提交结果，不使用路径存在或仅stat。单协调器/单workspace writer，本地有限thread worker；成功receipt最后发布。resume创建新run保留旧记录、累计预算。dry-run纯计划且允许最终fingerprint未解析。

**Rationale.** 将计划、执行、结果和审计身份分开，可安全解释失败/复用/恢复，不引入数据库或分布式系统。

**Alternatives rejected.** mutable Task承载全部状态；任意异常retry；仅wrapper version/path作fingerprint；整config/plan hash使全图失效；先记SUCCEEDED再保存输出；复用时重写producer；每次resume重置retry预算；全局CWD线程执行。

**Consequences.** 弱身份会禁用cache而不是伪造保证；native版本/有效设置必须有通用执行身份；current runtime只支持经测试的本地POSIX workspace。内部native checkpoint由插件管理。

**Invariants.** 无有效receipt无成功；task语义与attempt信息不混；未知native身份不安全复用；上游真实结果变动传播；独立分支不被无关失败拖垮；旧成功记录不被当前损坏改写；参数/证据不得泄密。

**Non-goals.** distributed locking、database state、Slurm/PBS、exactly-once外部副作用保证、全面native child-process管理、自动clean。

**Deferred.** Phase5具体外部程序恢复安全检查及强不可变大数据校验策略；将来有必要时拓展资源字段。

**Enforcement.** 第15节完整故障注入矩阵，尤其receipt前后crash、resume预算、独立并发、cache poisoning/损坏、dry-run零副作用、版本改变及秘密材料处理。


规范性细节：`../architecture/phase4-contracts.md` 对应主题。本文为 `P4.0-FREEZE-1` 的已接受架构决定，生产实现尚未完成。
