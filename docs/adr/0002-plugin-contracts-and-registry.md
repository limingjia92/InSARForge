# ADR-0002 — Plugin Contracts, Identity, Registry and Discovery

**Status: ACCEPTED**。

**Context.** 六family职责和返回类型不同；单一run接口会让Mission/Provider/QC伪装成Processor，而自动import发现会把副作用带入Core。

**Decision.** 使用六类Protocol，共享immutable PluginDescriptor而无统一业务run/强制ABC。显式注册(kind,id)及精确API版本；seal后只读。每个operation binding固定输入/输出/schema/validator及prepare/invoke适配端口。每attempt独立factory实例；部署工具路径/credential resolver由composition注入，不持久化为science参数。

**Rationale.** 统一编排不等于统一业务接口。通过可检验的薄适配器衔接，使新插件只增加自身实现、binding及tests。

**Alternatives rejected.** 强制所有插件继承一个大ABC；Core逐family/具体id硬编码调用；装饰器import即注册；filesystem扫描；版本自动择新；另建多层插件依赖求解框架。

**Consequences.** 注册方承担typed codec及契约测试义务；type hints并非运行时保证。Unknown/duplicate/version/capability错误均有稳定typed结果。

**Invariants.** 注册不实例化、不联网、不跑native；dry-run不调用factory/prepare；重复(kind,id)拒绝；未知id不回落默认插件；factory和binding不是从用户JSON动态import。

**Non-goals.** 不可信插件隔离、安全沙箱、依赖求解、第三方安装器。

**Deferred.** 首个实际第三方插件包需要时再加入packaging entry points；发现机制仍不能改executor科学逻辑。

**Enforcement.** 六family正/反向contract tests、无继承Fake、unknown/duplicate/version错误、seal不可变、concurrent instance隔离、第二组未知ID注册通过。


规范性细节：`../architecture/phase4-contracts.md` 对应主题。本文为 `P4.0-FREEZE-1` 的已接受架构决定，生产实现尚未完成。
