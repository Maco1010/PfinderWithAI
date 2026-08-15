# Pfinder 元数据 API 梳理

> 文档状态：基于 Pfinder 元数据接口页面整理，读取日期为 2026-08-15；源页面标注的最后修改时间为 2026-08-14 14:00:56。为避免在仓库中保存内部站点地址，本文只记录源页面相对路径 `/apm/api/meta.html` 和 API 相对路径。

## 1. 面向本项目的结论

该页面共描述 12 个只读元数据接口，能力可以分为五类：

1. 查询或遍历 Pfinder 应用，获得应用 ID、应用名、部署平台和拓扑 `nodeId`。
2. 根据 ID 或名称查询 Metric，获得组件、方向类型以及是否出现在 Trace 中。
3. 查询组件及组件分类，识别 RPC、HTTP、MQ 等协议和调用方向。
4. 根据应用坐标、IP、Runtime Info、标签和时间范围查询应用实例。
5. 查询 Runtime Info 以及分页或游标遍历 JVM 实例。

对 PfinderWithAI 最直接的价值是把用户提供的系统名解析为 Pfinder 能识别的应用和拓扑节点，并为后续 Trace、拓扑及实例调查提供稳定标识。

这份 API **不能独立满足** 当前 `MetadataProvider` 的完整契约：页面没有提供 Git 仓库地址、故障时线上版本或日志源。项目仍需要其他受控元数据源，或者使用组合 Adapter 汇总这些信息。

## 2. 接口总览

| 能力 | 方法 | 相对路径 | 主要输入 | 主要输出 | 第一阶段用途 |
|---|---|---|---|---|---|
| 遍历应用 | GET | `api/v2/naming/iterator/app` | `index` | 应用列表、`hasNext`、`nextIndex` | 构建候选应用目录 |
| 精确查询应用 | GET | `api/v2/naming/info/app` | `name`、`platform` | `id`、`name`、`platform`、`nodeId` | 解析 Pfinder 应用身份，P0 |
| 按 ID 查询 Metric | GET | `api/v2/naming/info/metric/{metricId}` | `metricId` | Metric 和组件属性 | 解释 Trace 或拓扑中的监控点 |
| 按名称查询 Metric | GET | `api/v2/naming/info/metric` | `name`、`desensitized` | Metric 和组件属性 | 从日志或代码中的监控点名反查 ID |
| 查询组件列表 | GET | `api/v2/component/components` | 应用坐标、活跃周期、空组件过滤 | 组件、协议、方向、Metric 数量 | 识别调用类型 |
| 查询组件分类 | GET | `api/v2/component/component-categories` | 应用坐标、排除组件、活跃周期 | 分类和分类下组件 | 对组件进行业务分组 |
| 搜索实例 | POST | `api/v2/meta/instance/search` | 应用坐标、IP、Runtime Info、时间、分页 | 实例、标签、Runtime Info | 缩小实例调查范围，P1 |
| 查询实例 Runtime Info | GET | `api/v2/meta/instance/runtime-info` | 应用、平台、实例 ID、可选 Key | Runtime Info 列表 | 获取指定实例运行属性 |
| 查询 Runtime Info Keys | GET | `api/v2/meta/runtime-info/keys` | 应用坐标 | Key、描述、是否可汇总 | 构建可查询字段白名单 |
| 查询 Runtime Info Values | GET | `api/v2/meta/runtime-info/values` | 应用坐标、Key | 去重后的值列表 | 构建过滤条件候选 |
| JVM 实例分页列表 | GET | `api/v2/extend/meta/jvm/instance/list` | 应用、平台、分页、IP、实例 ID、展示字段 | JVM 实例和页数 | 小范围 JVM 实例查询 |
| JVM 实例迭代查询 | POST | `api/v2/extend/meta/jvm/instance/iterate` | 应用、平台、过滤器、批量大小、游标 | JVM 实例、`hasNext`、`nextToken` | 大批量或可恢复遍历 |

## 3. 应用与拓扑标识

### 3.1 应用迭代器

`GET api/v2/naming/iterator/app`

请求参数：

| 字段 | 必选 | 类型 | 语义 |
|---|---:|---|---|
| `index` | 否 | `int` | 首次请求可省略；后续使用上一次响应的 `nextIndex` |

响应字段：

| 字段 | 类型 | 语义 |
|---|---|---|
| `data[]` | `array` | 本批应用 |
| `data[].id` | `integer` | 应用 ID |
| `data[].name` | `string` | 应用名 |
| `data[].platform` | `string` | 部署平台 |
| `data[].createTime` | `datetime string` | 创建时间 |
| `data[].updateTime` | `datetime string` | 更新时间 |
| `hasNext` | `boolean` | 是否存在下一批 |
| `nextIndex` | `integer` | 下一次迭代索引 |

该接口适合离线同步应用目录或在精确解析失败时生成候选，不适合在每次调查中无界遍历全部应用。

### 3.2 精确查询应用

`GET api/v2/naming/info/app`

请求参数：

| 字段 | 必选 | 类型 | 语义 |
|---|---:|---|---|
| `name` | 是 | `string` | 应用名 |
| `platform` | 是 | `string` | 部署平台 |

响应字段：

| 字段 | 类型 | 语义 |
|---|---|---|
| `id` | `integer` | Pfinder 应用 ID |
| `name` | `string` | 应用名 |
| `platform` | `string` | 部署平台 |
| `nodeId` | `string` | 拓扑相关接口使用的节点 ID |

`name` 不能单独完成精确查询，调用方还必须知道 `platform`。因此当前只有 `system: str` 的输入不足以保证唯一解析，Adapter 需要受控的系统名到平台映射，或者明确返回多个候选并请求补充信息。

## 4. Metric 元数据

### 4.1 按 ID 查询

`GET api/v2/naming/info/metric/{metricId}`

路径参数 `metricId` 为必填字符串。响应包含：

| 字段 | 类型 | 语义 |
|---|---|---|
| `id` | `integer` | Metric ID |
| `name` | `string` | Metric 名称 |
| `updateTime` | `integer` | 更新时间戳 |
| `createTime` | `integer` | 创建时间戳 |
| `componentId` | `string` | 组件 ID |
| `componentType` | `string enum` | 组件方向或角色 |
| `isOnTrace` | `boolean` | 是否存在于调用链上 |

页面列出的 `componentType` 值包括：

- `IN_BOUND`
- `OUT_BOUND`
- `LOCAL`
- `THIRD_PARTY_INVOKER`
- `MQ_CONSUMER`
- `MQ_PRODUCER`
- `UNKNOWN`

### 4.2 按名称查询

`GET api/v2/naming/info/metric`

| 字段 | 必选 | 类型 | 语义 |
|---|---:|---|---|
| `name` | 是 | `string` | Metric 名称 |
| `desensitized` | 否 | `boolean` | 名称是否已经脱敏，文档标注默认值为 `true` |

响应结构与按 ID 查询一致。Adapter 不应假定名称全局唯一；唯一性、大小写和脱敏算法需要另行确认。

## 5. 组件和协议元数据

### 5.1 组件列表

`GET api/v2/component/components`

| 字段 | 必选 | 文档类型 | 默认值 | 语义 |
|---|---:|---|---|---|
| `app_coord` | 否 | `string` | 无 | 目标应用坐标 |
| `active_time_duration` | 否 | `string` | `P7D` | ISO-8601 Duration，只保留周期内活跃的监控点 |
| `skip_empty` | 否 | `string` | `true` | 指定应用后是否过滤无监控点组件 |

每个组件包含：

- `id`
- `componentType`
- `componentCategory`
- `protocol`
- `displayName`
- `description`
- `metricCount`，仅在指定 `app_coord` 时有效

### 5.2 组件分类

`GET api/v2/component/component-categories`

| 字段 | 必选 | 类型 | 默认值 | 语义 |
|---|---:|---|---|---|
| `app_coord` | 否 | `string` | 无 | 目标应用坐标 |
| `exclude_components` | 否 | `string` | 无 | 逗号分隔的组件 ID |
| `active_time_duration` | 否 | `string` | `P7D` | ISO-8601 Duration |

响应按分类返回 `key`、展示名称、描述和组件列表。页面示例显示分类可以表达服务提供方、服务依赖方、MQ 生产者和 MQ 消费者等语义。

## 6. 实例与 Runtime Info

### 6.1 实例搜索

`POST api/v2/meta/instance/search`

请求 Body：

| 字段 | 必选 | 语义 |
|---|---:|---|
| `appCoord` | 是 | 应用坐标 |
| `ip` | 否 | 按一个或多个 IP 精确过滤，多个值以逗号分隔 |
| `ipLike` | 否 | IP 模糊匹配 |
| `filterRuntimeInfoKV` | 否 | Runtime Info Key 到允许值列表的过滤映射 |
| `queryRuntimeInfoKeys` | 否 | 希望在响应中返回的 Runtime Info Keys |
| `isQueryLabels` | 否 | 是否返回实例标签，文档标注默认 `false` |
| `begin` | 否 | 查询开始时间；文档称默认查询最近 15 分钟 |
| `end` | 否 | 查询结束时间；文档称默认查询最近 15 分钟 |
| `pageIndex` | 否 | 页码，默认第一页 |
| `pageSize` | 否 | 每页数量，默认 10 |

响应包含 `data[]` 和 `pageTotal`。实例字段包括：

- `id`：实例 ID
- `appId`：应用 ID
- `ip`：实例 IP，属于敏感运行数据，不应进入模型上下文或普通日志
- `path`：实例路径，属于内部运行信息，需要最小化保存
- `labels[]`：标签名、可读名称、值和可读值
- `runtimeInfo[]`：Key、展示名称和值

### 6.2 查询指定实例 Runtime Info

`GET api/v2/meta/instance/runtime-info`

| 字段 | 必选 | 类型 | 语义 |
|---|---:|---|---|
| `appName` | 是 | `String` | 应用名 |
| `platform` | 是 | `String` | 部署平台 |
| `instanceId` | 是 | `int` | 实例 ID |
| `key` | 否 | `String` | 指定 Runtime Info Key |

响应为 `{key, displayName, value}` 列表。

### 6.3 Runtime Info Keys 与 Values

`GET api/v2/meta/runtime-info/keys`

- 必填 `app_coord`
- 返回 `key`、`description`、`isSummative`

`GET api/v2/meta/runtime-info/values`

- 必填 `app_coord` 和 `key`
- 返回 `{value}` 列表

这两个接口适合先发现合法 Key 和候选值，再构造实例过滤请求，避免 Agent 任意猜测 Runtime Info 字段。

## 7. JVM 实例

### 7.1 分页列表

`GET api/v2/extend/meta/jvm/instance/list`

| 字段 | 必选 | 类型 | 语义 |
|---|---:|---|---|
| `appName` | 是 | `String` | 应用名 |
| `platform` | 是 | `String` | 部署平台 |
| `pageIndex` | 否 | `Integer` | 页码，默认第一页 |
| `pageSize` | 否 | `Integer` | 每页大小，默认 10 |
| `ip` | 否 | `String` | IP 模糊查询 |
| `ipList` | 否 | `String` | 逗号分隔的 IP 列表 |
| `instanceId` | 否 | `Integer` | 指定实例 ID |
| `displayRuntimeInfoKeys` | 否 | `String` | 逗号分隔的待返回 Runtime Info Keys |

响应包含实例 `id`、创建时间、IP、Runtime Info 和 `pageTotal`。

### 7.2 游标迭代

`POST api/v2/extend/meta/jvm/instance/iterate`

请求 Body：

| 字段 | 必选 | 语义 |
|---|---:|---|
| `appName` | 是 | 应用名 |
| `platform` | 是 | 部署平台 |
| `ipList` | 否 | IP 列表 |
| `instanceIdList` | 否 | 实例 ID 列表 |
| `runtimeInfoKeys` | 否 | 待返回字段列表 |
| `runtimeInfoFilters` | 否 | Runtime Info 过滤规则 |
| `batchSize` | 否 | 每批上限，文档标注默认 300 |
| `nextToken` | 否 | 首次省略；后续传上一次响应的 Token |

响应包含 `data[]`、`hasNext` 和 `nextToken`。相比页码分页，Token 更适合批量遍历和中断续查，但 Token 的有效期与一致性语义未记录。

## 8. 标识符及关系

```text
应用名 + 部署平台
        |
        v
Pfinder 应用：id / name / platform / nodeId
        |
        +----> 应用坐标 appCoord（格式只在示例中出现，规则待确认）
        |
        +----> Metric：metricId / componentId / componentType / isOnTrace
        |
        +----> 实例：instanceId / appId / labels / runtimeInfo
        |
        `----> JVM 实例：instanceId / runtimeInfo
```

目前不能确认以下标识是否可以互换：

- `id` 与 `appId`
- `nodeId` 与 `appCoord`
- `app_coord` 与请求 Body 中的 `appCoord`
- 普通实例 ID 与 JVM 实例 ID

Adapter 必须保留字段原义，不应在缺少文档依据时相互转换。

## 9. 分页与查询边界

页面展示了三种遍历方式：

| 类型 | 接口 | 继续查询字段 | 终止条件 |
|---|---|---|---|
| 索引迭代 | 应用迭代器 | `nextIndex` | `hasNext == false` |
| 页码分页 | 实例搜索、JVM 实例列表 | `pageIndex` | 达到 `pageTotal`，但其确切含义待确认 |
| Token 迭代 | JVM 实例迭代查询 | `nextToken` | `hasNext == false` |

项目 Adapter 需要额外施加最大页数、最大结果数、超时和 UsageMonitor 预算，不能因为服务端仍有下一页就无界读取。

## 10. 文档未明确或存在歧义的部分

以下事项在实现前必须通过公共 API 说明、接口负责人或脱敏 Smoke Test 确认：

1. Base URL、认证方式、权限模型、公共请求头和调用身份。
2. 成功响应是否存在统一 Envelope，以及错误码和错误响应 Schema。
3. 限流规则、推荐超时、重试建议和幂等语义。
4. `platform` 的合法值、大小写规则，以及同名应用跨平台的唯一性。
5. `appCoord` 的正式格式、转义规则，以及它和 `nodeId` 的关系。
6. `skip_empty` 被记录为 `string`，但语义像布尔值，真实传输类型需要确认。
7. 实例搜索示例把布尔值、时间戳和分页数字写成字符串，真实 JSON 类型需要确认。
8. `pageTotal` 表示总页数还是总记录数。
9. Metric 名称的唯一性、脱敏算法以及 `desensitized=true` 的精确行为。
10. 应用和实例迭代器的排序稳定性、游标或 Token 有效期，以及遍历期间数据变化的一致性。
11. JVM 迭代响应示例重复出现 `createTime`，其中一个注释声称是更新时间，疑似文档笔误。
12. 时间戳单位、时区和时间格式并不统一，需要在 DTO 层显式验证。

## 11. 与 PfinderWithAI 领域模型的映射

| 项目字段 | 可用来源 | 映射结论 |
|---|---|---|
| `SystemContext.system` | `name` | 可以映射，但还需保留 `platform` 才能再次精确查询 |
| `SystemContext.trace_service` | `nodeId` 或应用坐标 | 候选映射；必须结合 Trace/Topology API 契约确认后再定 |
| `SystemContext.source_locator` | 应用 ID、查询条件或控制台链接 | 页面没有定义稳定链接格式，需要另行设计 |
| `SystemContext.repository_url` | 无 | 此 API 不提供，需要代码仓库元数据源 |
| `SystemContext.revision` | 无 | 此 API 不提供，需要发布或部署元数据源 |
| `SystemContext.log_source` | 无 | 此 API 不提供，需要日志平台元数据源 |
| `SystemContext.revision_is_assumption` | 无 | 由项目在无法获取真实版本时明确设置 |

不建议直接把 `nodeId` 填入 `trace_service` 后立即固化实现。更稳妥的方式是先定义 Adapter 内部的供应商 DTO：

```text
PfinderAppRef
  - id
  - name
  - platform
  - node_id
  - app_coord（若后续契约确认）
```

待 Trace 和 Topology 文档确认真正需要的标识后，再在 Adapter 边界转换为领域字段，避免供应商字段泄漏到核心流程。

## 12. 建议的 Adapter 边界

```text
ContextResolver
      |
      v
CompositeMetadataProvider
      |
      +---- PfinderMetadataAdapter
      |       app / node / metric / instance metadata
      |
      +---- RepositoryMetadataAdapter
      |       repository URL / deployed revision
      |
      `---- LogMetadataAdapter
              log source / query scope
```

第一阶段可以只实现 Pfinder 应用精确查询，并把其他接口保留在供应商 Client 中按需求逐步开放。不要让核心 `MetadataProvider` 暴露所有 Runtime Info 或 JVM 字段，也不要把实例 IP、路径和完整标签放入 LLM 上下文。

## 13. 建议的最小实现顺序

1. 确认 Base URL、认证、统一错误结构、`platform` 来源和 `appCoord` 格式。
2. 定义供应商 DTO 和受控 HTTP Client，不让原始 JSON 进入领域层。
3. 实现 `name + platform -> PfinderAppRef` 精确查询。
4. 为无结果、同名多平台、认证失败、限流、超时和格式错误建立 Contract Tests。
5. 使用合成或彻底脱敏的应用名进行真实 Smoke Test，并只输出非敏感标识摘要。
6. 结合 Trace/Topology API 确认 `nodeId` 或 `appCoord` 的实际用途。
7. 只有真实调查场景需要时，再接入 Metric、组件、实例和 JVM 查询。

完成上述验证后，才能决定是让 `PfinderMetadataAdapter` 直接提供部分 `SystemContext`，还是引入组合 Metadata Provider 汇总 Pfinder、代码仓库和日志平台元数据。
