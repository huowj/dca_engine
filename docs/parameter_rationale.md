# DCA Engine 参数选择理由

> 本文档用于解释 DCA Engine 当前参数为什么这样设置。  
> 重点不是证明这些参数已经是最终最优值，而是说明：
>
> - 当前参数是什么
> - 为什么可以作为 baseline
> - 调大 / 调小会产生什么影响
> - 哪些参数未来必须依赖真实数据继续微调
>
> 本文档目标是让参数选择不是“拍脑袋”，而是“可解释、可复盘、可验收”。

---

## 0. 当前参数总表

以下参数来自当前 `dca_engine.py` baseline 实现。

| 类别 | 参数 | 当前值 | 是否固定 | 是否需要真实数据微调 |
|------|------|--------|----------|----------------------|
| Offset Observer | `alpha_NORMAL` | `0.1` | 可调 | 是 |
| Offset Observer | `alpha_RECOVERY` | `0.5` | 可调 | 是 |
| Offset Observer | `alpha_HOLDOVER` | `0.01` | 可调但建议保守 | 是 |
| Offset Observer | `median_window_size` | `5` | 固定 | 暂不调整 |
| Drift Observer | `drift_alpha_NORMAL` | `0.08` | 可调 | 是 |
| Drift Observer | `drift_alpha_RECOVERY` | `0.1` | 可调 | 是 |
| Drift Observer | `drift_alpha_HOLDOVER` | `0.001` | 可调但建议保守 | 是 |
| Drift Observer | `drift_ppm_limit` | `±50 ppm` | 可调 | 是，需要结合晶振规格 |
| Jitter / Stable PPS | `jitter_threshold_us` | `100 us` | 可调 | 是 |
| Outlier Detection | `static_threshold_us` | `300 us` | 可调 | 是 |
| Outlier Detection | `sigma_multiplier` | `3` | 可调 | 是 |
| Sigma Estimator | `sigma_ema_alpha` | `0.05` | 可调 | 是 |
| State Machine | `holdover_timeout_us` | `1_500_000 us` | 当前固定 | 是 |
| State Machine | `pps_loss_threshold_s` | `1.5 s` | 当前固定 | 是 |
| State Machine | `relock_required_pps` | `3` | 当前固定 | 后续可根据实机确认 |
| State Machine | `stable_required_pps` | `3` | 当前固定 | 后续可根据实机确认 |
| Confidence | `conf_normal_base` | `0.90` | 可调 | 是 |
| Confidence | `conf_normal_increment` | `0.01` | 可调 | 是 |
| Confidence | `conf_normal_cap` | `0.99` | 固定上限 | 暂不调整 |
| Confidence | `conf_recovery_base` | `0.70` | 可调 | 是 |
| Confidence | `conf_recovery_increment` | `0.05` | 可调 | 是 |
| Confidence | `conf_recovery_cap` | `0.90` | 固定上限 | 暂不调整 |
| Confidence | `conf_holdover_decay` | `0.95` | 可调 | 是 |
| Confidence | `confidence_bounds` | `[0.01, 0.99]` | 固定 | 暂不调整 |

---

## 1. 参数调优的最终目标

DCA Engine 参数调优的目标不是让某一条曲线最好看，而是在不改变行为契约的前提下，让系统同时满足以下工程目标：

```text
1. corrected_time_us 永不回退
2. PPS 正常时 offset 能稳定收敛
3. drift_ppm 能反映真实频偏趋势
4. jitter spike / outlier 不污染 offset 和 drift
5. PPS 丢失后进入 HOLDOVER，confidence 不假稳定
6. PPS 恢复后经过 RECOVERY 再重新信任
7. replay 同输入同输出，结果可复现
```

调参优先级：

```text
1. monotonic guarantee
2. HOLDOVER 稳定
3. NORMAL offset 收敛
4. JITTER 不污染系统
5. DRIFT 收敛
6. confidence 行为合理
```

注意：

```text
不允许为了优化 drift 而破坏 HOLDOVER
不允许为了过滤 jitter 而破坏 NORMAL 收敛
不允许为了提高 confidence 而掩盖 PPS 丢失
```

---

## 2. Offset Observer 参数

Offset Observer 用于估计：

```text
offset_us = reference_time_us - board_time_us
```

当前方法：

```text
5 点中值滤波 + EMA
```

---

### 2.1 alpha_NORMAL

**当前值**：`0.1`

**物理 / 工程意义**：

`alpha_NORMAL` 控制 NORMAL 状态下 offset 估计的更新速度。

公式含义：

```text
offset_us = offset_us + alpha * (median_residual - offset_us)
```

**为什么这样设**：

- NORMAL 状态下 PPS 应该稳定，不需要过快跟随单点 residual。
- `0.1` 属于较保守的 EMA 系数，可以平衡响应速度和噪声抑制。
- 配合 5 点中值滤波，可以避免单个 jitter spike 直接拉动 offset。

**调大影响**：

例如调到 `0.2 ~ 0.3`：

- 优点：offset 收敛更快。
- 风险：对 PPS jitter 更敏感，offset 曲线可能抖动。
- 可能导致 jitter 场景下 offset 被异常点污染。

**调小影响**：

例如调到 `0.05`：

- 优点：offset 更平滑。
- 风险：收敛变慢。
- 可能导致 normal 场景下较长时间 offset 无法进入 ±50us 范围。

**是否需要真实数据微调**：是。

需要根据真实 PPS residual 的标准差、99.7% 分位范围和收敛时间要求确认。

---

### 2.2 alpha_RECOVERY

**当前值**：`0.5`

**物理 / 工程意义**：

`alpha_RECOVERY` 控制 PPS 从 HOLDOVER 恢复后，offset 重新收敛的速度。

**为什么这样设**：

- HOLDOVER 后 offset 可能已经滞后。
- RECOVERY 需要比 NORMAL 更快地重新对齐 PPS。
- `0.5` 能让 offset 较快跟随恢复后的 reference time。

**调大影响**：

例如调到 `0.7 ~ 0.8`：

- 优点：恢复更快。
- 风险：如果 PPS 恢复初期仍不稳定，offset 可能过冲或被异常点拉偏。

**调小影响**：

例如调到 `0.2 ~ 0.3`：

- 优点：恢复更稳。
- 风险：RECOVERY 时间变长，系统更晚回到 NORMAL / LOCKED。

**是否需要真实数据微调**：是。

需要使用真实 PPS recovery 数据确认恢复时间和过冲情况。

---

### 2.3 alpha_HOLDOVER

**当前值**：`0.01`

**物理 / 工程意义**：

`alpha_HOLDOVER` 控制 HOLDOVER 状态下 offset 的更新速度。

**为什么这样设**：

- HOLDOVER 表示 PPS 已丢失或不可用。
- 此时不能继续强依赖 reference_time 更新 offset。
- `0.01` 基本相当于冻结 offset，避免无效数据污染 holdover snapshot。

**调大影响**：

- 优点：如果 HOLDOVER 期间仍有部分弱参考数据，可能慢速修正。
- 风险：无效 reference 可能污染 offset，导致 holdover prediction 发散。

**调小影响**：

- 优点：更接近冻结 offset，HOLDOVER 更保守。
- 风险：如果存在可用弱参考，系统无法利用。

**是否需要真实数据微调**：是，但建议保持保守。

当前阶段建议不轻易调大。

---

### 2.4 median_window_size

**当前值**：`5`

**物理 / 工程意义**：

5 点中值滤波用于抑制单点 outlier。

**为什么这样设**：

- 5 点窗口可以过滤单个异常点。
- 延迟仍然可接受。
- 不改变 offset observer 的基本结构。

**调大影响**：

- 抗 outlier 能力增强。
- 延迟增加，恢复速度变慢。

**调小影响**：

- 延迟降低。
- 抗 outlier 能力下降。

**是否需要真实数据微调**：暂不调整。

当前合同中建议固定为 5。

---

## 3. Drift Observer 参数

Drift Observer 用于估计 board clock 的频率偏差：

```text
drift_ppm = (delta_residual_us / delta_time_us) * 1e6
```

---

### 3.1 drift_alpha_NORMAL

**当前值**：`0.08`

**物理 / 工程意义**：

`drift_alpha_NORMAL` 控制 NORMAL 状态下 drift_ppm 估计的更新速度。

**为什么这样设**：

- drift 是慢变量，不能像 offset 一样快速跳变。
- 但如果 alpha 太小，drift 场景收敛会过慢。
- 当前从参考值 `0.05` 调整到 `0.08`，目的是提高 mock drift 场景下的收敛速度。
- 该调整仍未改变 drift 公式，只属于 tuning parameter 范围。

**调大影响**：

例如调到 `0.1 ~ 0.2`：

- 优点：drift_ppm 对真实 drift 变化响应更快。
- 风险：jitter spike 更容易污染 drift 估计。
- HOLDOVER 使用 drift_ppm 做预测，如果 drift 被污染，holdover drift 会变大。

**调小影响**：

例如调回 `0.05`：

- 优点：drift 估计更平滑，对 jitter 更稳健。
- 风险：drift 场景收敛慢，可能达不到 `±10ppm` 收敛目标。

**是否需要真实数据微调**：是。

必须同时验证：

```text
DRIFT 是否收敛
JITTER 是否不污染 drift
HOLDOVER 5s 内 drift 是否 < 500us
```

如果 `0.08` 只改善 drift 但破坏 jitter 或 holdover，应回退到 `0.05` 或选择折中值。

---

### 3.2 drift_alpha_RECOVERY

**当前值**：`0.1`

**物理 / 工程意义**：

控制 RECOVERY 状态下 drift_ppm 的更新速度。

**为什么这样设**：

- PPS 恢复后，drift 估计可能已经滞后。
- RECOVERY 需要比 NORMAL 稍快地重新估计 drift。
- `0.1` 能加快恢复，但仍低于过度敏感范围。

**调大影响**：

- 优点：PPS 恢复后 drift 重新收敛更快。
- 风险：恢复初期如果 residual 不稳定，会污染 drift。

**调小影响**：

- 优点：恢复更平滑。
- 风险：RECOVERY 后 drift 长时间不准，影响 holdover 再次发生时的预测。

**是否需要真实数据微调**：是。

需要 PPS recovery 实机数据。

---

### 3.3 drift_alpha_HOLDOVER

**当前值**：`0.001`

**物理 / 工程意义**：

控制 HOLDOVER 状态下 drift_ppm 的更新速度。

**为什么这样设**：

- HOLDOVER 中没有可靠 PPS reference。
- drift 不应被无效 residual 快速更新。
- `0.001` 基本冻结 drift，保护 holdover prediction。

**调大影响**：

- 风险较大，可能在 PPS 丢失期间用错误 residual 污染 drift。
- 会直接影响 holdover corrected_time_us。

**调小影响**：

- 更保守，更接近完全冻结 drift。
- 如果硬件 drift 在 HOLDOVER 中真实变化，系统无法及时跟踪。

**是否需要真实数据微调**：是，但建议优先保持保守。

---

### 3.4 drift_ppm_limit

**当前值**：`±50 ppm`

**物理 / 工程意义**：

限制 drift_ppm 的最大可信范围。

**为什么这样设**：

- `±50 ppm` 覆盖常见低成本晶振误差范围。
- 超过该范围时，说明 board clock 频偏可能异常，或者 residual 已被异常数据污染。
- 该限制可以避免 holdover prediction 被极端 drift 放大。

**调大影响**：

- 优点：允许更差的晶振或更大频偏。
- 风险：异常 drift 可能被当成正常，holdover 更容易发散。

**调小影响**：

- 优点：更早识别异常 drift。
- 风险：可能误判正常硬件频偏。

**是否需要真实数据微调**：是。

必须根据实际晶振规格、温漂范围和实机 drift 日志确认。

---

## 4. Jitter / Stable PPS 参数

### 4.1 jitter_threshold_us

**当前值**：`100 us`

代码中对应：

```text
stable_pps = valid_pps and abs(residual) < 100
```

**物理 / 工程意义**：

定义 PPS residual 小于多少时，可以认为 PPS 稳定。

**为什么这样设**：

- `100us` 作为 stable PPS 的工程阈值，能区分正常小抖动和明显异常。
- 它直接影响 RECOVERY -> NORMAL 的判断。
- 也影响 stable_pps_counter 的累计。

**调大影响**：

- 优点：更容易判定 stable，恢复更快。
- 风险：较大 residual 也被当成稳定，可能过早回到 NORMAL。

**调小影响**：

- 优点：LOCKED / NORMAL 更严格。
- 风险：正常 PPS 抖动稍大时无法稳定锁定，RECOVERY 时间变长。

**是否需要真实数据微调**：是。

需要真实 PPS residual 分布确认。

---

## 5. Outlier Detection 参数

当前 outlier 判断：

```text
outlier = abs(residual) > max(static_threshold_us, sigma_multiplier * sigma)
```

当前值：

```text
static_threshold_us = 300
sigma_multiplier = 3
```

---

### 5.1 static_threshold_us

**当前值**：`300 us`

**物理 / 工程意义**：

绝对硬阈值，用于识别明显异常的 residual。

**为什么这样设**：

- 正常 PPS residual 通常应远小于 300us。
- 300us 可以作为 jitter / drift 异常的保护带。
- 配合 `3 * sigma`，避免 sigma 初期估计不准导致误判。

**调大影响**：

- 优点：减少误杀正常 PPS。
- 风险：异常 residual 更容易进入 offset / drift observer。

**调小影响**：

- 优点：更早拒绝异常点。
- 风险：正常波动可能被误判为 outlier，影响锁定和恢复。

**是否需要真实数据微调**：是。

建议用真实数据统计：

```text
正常 residual 均值
正常 residual 标准差
正常 residual 99.7% 分位
异常场景 residual 最大跳变
```

---

### 5.2 sigma_multiplier

**当前值**：`3`

**物理 / 工程意义**：

动态阈值倍数，对应常见的 3σ 异常检测规则。

**为什么这样设**：

- 如果 residual 近似正态分布，3σ 可以覆盖大部分正常样本。
- 能自适应不同噪声水平。
- 与 static threshold 共同构成双阈值 outlier rejection。

**调大影响**：

例如 `3.5 ~ 4`：

- 优点：减少误杀。
- 风险：漏掉异常 spike。

**调小影响**：

例如 `2.5`：

- 优点：更敏感，异常更容易被拒绝。
- 风险：正常 jitter 被误判为 outlier。

**是否需要真实数据微调**：是。

如果真实噪声长尾明显，可能需要调整到 `3.5` 或 `4`。

---

### 5.3 sigma_ema_alpha

**当前值**：`0.05`

当前公式：

```text
sigma = sqrt(0.95 * sigma^2 + 0.05 * residual^2)
```

**物理 / 工程意义**：

控制 sigma 对 residual 方差变化的响应速度。

**为什么这样设**：

- `0.05` 约等于 20 个样本的时间常数。
- 能平滑估计 residual 噪声水平。
- 不会因为单次 spike 立刻大幅抬高 sigma。

**调大影响**：

例如 `0.08 ~ 0.1`：

- 优点：sigma 对噪声变化反应更快。
- 风险：单次异常可能把 sigma 拉大，导致后续 outlier 漏检。

**调小影响**：

例如 `0.02 ~ 0.03`：

- 优点：sigma 更稳，不容易被异常污染。
- 风险：真实噪声水平变化时响应慢。

**是否需要真实数据微调**：是。

需要看 jitter 场景下 sigma 是否被异常污染，以及 outlier 是否漏检。

---

## 6. Confidence Observer 参数

Confidence 用于表达系统当前对 corrected_time_us 的信任程度。

范围：

```text
0.01 <= confidence <= 0.99
```

---

### 6.1 conf_normal_base

**当前值**：`0.90`

**物理 / 工程意义**：

NORMAL 状态下 confidence 的基础值。

**为什么这样设**：

- NORMAL 表示 PPS 正常且状态机认为系统处于稳定状态。
- 因此基础可信度应较高。
- 但不能直接等于 1，因为 offset / drift 仍有不确定性。

**调大影响**：

- 优点：正常状态下更快显示高可信。
- 风险：刚进入 NORMAL 时可能过度自信。

**调小影响**：

- 优点：更保守。
- 风险：正常系统也长时间显示 confidence 偏低。

**是否需要真实数据微调**：是。

应结合真实 normal 场景下 offset / drift 稳定度确认。

---

### 6.2 conf_normal_increment

**当前值**：`0.01`

**物理 / 工程意义**：

每收到一个 valid PPS，NORMAL 状态下 confidence 增加的量。

**为什么这样设**：

- 连续 valid PPS 是系统稳定的证据。
- 每个有效 PPS 小幅增加 confidence，避免瞬间跳满。
- 上限由 `0.99` 限制。

**调大影响**：

- 优点：confidence 上升快。
- 风险：短时间内过早达到高可信。

**调小影响**：

- 优点：更保守。
- 风险：normal 场景下 confidence 可能达不到验收阈值。

**是否需要真实数据微调**：是。

需要结合 time_to_lock 和 confidence 曲线确认。

---

### 6.3 conf_recovery_base

**当前值**：`0.70`

**物理 / 工程意义**：

RECOVERY 状态下 confidence 的基础值。

**为什么这样设**：

- PPS 刚恢复时，不能立即认为完全可信。
- `0.70` 表示系统正在恢复，有一定信任，但低于 NORMAL。
- 防止 HOLDOVER 后直接高 confidence。

**调大影响**：

- 优点：恢复时 confidence 更快接近正常。
- 风险：PPS 刚恢复但未稳定时过度乐观。

**调小影响**：

- 优点：更保守。
- 风险：恢复后 confidence 长时间偏低。

**是否需要真实数据微调**：是。

需要真实 PPS recovery 数据确认。

---

### 6.4 conf_recovery_increment

**当前值**：`0.05`

**物理 / 工程意义**：

RECOVERY 状态下每个 stable PPS 对 confidence 的增加量。

**为什么这样设**：

- RECOVERY 需要比 NORMAL 更快恢复信任。
- 但 confidence 上限限制为 `0.90`，不会直接达到 NORMAL 最高值。
- 连续稳定 PPS 才能让系统逐步重建信任。

**调大影响**：

- 优点：恢复更快。
- 风险：PPS 尚未完全稳定时 confidence 上升过快。

**调小影响**：

- 优点：恢复更保守。
- 风险：恢复时间过长。

**是否需要真实数据微调**：是。

---

### 6.5 conf_holdover_decay

**当前值**：`0.95`

**物理 / 工程意义**：

HOLDOVER 期间 confidence 的衰减因子。

**为什么这样设**：

- PPS 丢失后，系统只能依赖 last offset + drift 预测时间。
- 时间越久，误差越可能累积。
- `0.95` 表示每次更新 confidence 下降约 5%，避免 PPS 丢失后假稳定。

**调大影响**：

例如 `0.97`：

- 优点：confidence 下降更慢，适合硬件时钟稳定、允许短暂 PPS 丢失的系统。
- 风险：PPS 丢失后仍长时间显示较高 confidence。

**调小影响**：

例如 `0.90 ~ 0.93`：

- 优点：PPS 丢失后更快降级。
- 风险：短暂 PPS 抖动也可能导致 confidence 过低。

**是否需要真实数据微调**：是。

必须根据真实 holdover 误差增长曲线确认。

---

### 6.6 confidence_bounds

**当前值**：`[0.01, 0.99]`

**物理 / 工程意义**：

限制 confidence 不出现完全 0 或完全 1 的极端值。

**为什么这样设**：

- `0.99` 表示高可信，但不宣称绝对正确。
- `0.01` 表示极低可信，但系统仍可能保持 monotonic time。
- 避免下游误解成“绝对可信”或“完全无输出”。

**调大 / 调小影响**：

该参数当前建议固定，不作为普通 tuning 项。

**是否需要真实数据微调**：暂不需要。

---

## 7. State Machine 参数

状态机参数不属于普通算法自由度，属于行为契约的一部分。原则上只在 spec 更新后调整。

---

### 7.1 pps_loss_threshold_s / holdover_timeout_us

**当前值**：

```text
pps_loss_threshold_s = 1.5
holdover_timeout_us = 1_500_000
```

**物理 / 工程意义**：

超过 1.5 秒没有有效 PPS，则认为 PPS 丢失。

**为什么这样设**：

- PPS 通常 1Hz 到达，即 1 秒一个边沿。
- 设置为 1.5 秒可以容忍一定调度延迟或事件传输延迟。
- 同时能在 PPS 真丢失时较快进入 HOLDOVER。

**调大影响**：

- 优点：减少误判 PPS lost。
- 风险：PPS 真丢失后状态切换变慢，confidence 可能假稳定。

**调小影响**：

- 优点：PPS 丢失后更快进入 HOLDOVER。
- 风险：正常 PPS 延迟也可能被误判为丢失。

**是否需要真实数据微调**：是。

需要真实 PPS event 间隔统计确认。

---

### 7.2 relock_required_pps / recovery_lock_condition

**当前值**：`3 consecutive valid PPS`

**物理 / 工程意义**：

HOLDOVER 后，需要连续 3 个 valid PPS 才能进入 RECOVERY。

**为什么这样设**：

- 单个 PPS 恢复不能证明系统稳定。
- 连续 3 个 valid PPS 可以避免瞬时恢复导致状态抖动。
- 3 个 PPS 在 1Hz 下约为 3 秒验证窗口，工程上可接受。

**调大影响**：

- 优点：恢复更稳。
- 风险：回到 RECOVERY / NORMAL 更慢。

**调小影响**：

- 优点：恢复更快。
- 风险：瞬时 PPS 恢复可能导致状态抖动。

**是否需要真实数据微调**：后续可根据实机恢复数据确认。

---

### 7.3 stable_required_pps

**当前值**：`3 consecutive stable PPS`

**物理 / 工程意义**：

RECOVERY 后，需要连续 3 个 stable PPS 才能回到 NORMAL。

stable 条件：

```text
residual < jitter_threshold_us
```

当前即：

```text
abs(residual) < 100us
```

**为什么这样设**：

- RECOVERY 只是恢复阶段，不代表已经可信。
- 连续 3 个 stable PPS 可以确认 PPS 已经重新稳定。
- 防止 HOLDOVER 后直接跳 NORMAL。

**调大影响**：

- 优点：更严格，状态更稳。
- 风险：恢复时间更长。

**调小影响**：

- 优点：恢复更快。
- 风险：更容易状态抖动或过早信任。

**是否需要真实数据微调**：后续可根据实机恢复数据确认。

---

## 8. 当前验证结论

### 8.1 sample_event.csv interface alignment 结果

当前运行：

```bash
python3 ./dca_event_csv_loader.py
```

结果摘要：

```text
total_rows = 615
PPS_EDGE = 5
PPS_LOST = 1
PPS_RECOVERY = 1
IMU_SAMPLE = 601
GNSS_STATUS = 7
seq_gap_marked_count = 1
loss_detected_count = 1
engine_update_count = 7
final_state = NORMAL
final_offset_us = 0.0
final_drift_ppm = 0.0
final_confidence = 0.93
holdover_seen = false
recovery_seen = false
```

结论：

```text
sample_event.csv 可作为 interface alignment smoke test PASS。
```

已验证：

- CSV 能稳定读取
- 事件类型能识别
- seq_gap / loss_detected 能进入 metrics
- interface output CSV / JSON 能生成

未验证：

- HOLDOVER 状态覆盖
- RECOVERY 状态覆盖
- drift 收敛
- jitter outlier rejection
- confidence holdover 衰减曲线
- 参数最终锁版

因此：

```text
sample_event.csv 不能作为参数调优最终 PASS 依据。
```

---

### 8.2 Fake Canary 验证结论

本次使用 `fake_scenario.csv` 进行金丝雀验证，包含三类典型场景：

1. 正常段：`0s ~ 20s`
2. 漂移段：`20s ~ 30s`
3. 电压跌落 + PPS 丢失段：`45s ~ 46s`

验证结果：

- 正常段输出 `PASS`，说明基础 offset 观测和 confidence 上升行为正常。
- 漂移段输出 `FAIL_DRIFT`，说明 checker 能识别 offset 逐渐增大的异常趋势。
- 电压跌落 + PPS 丢失段输出 `FAIL_HOLDOVER`，说明 checker 能识别电源异常和 PPS 丢失风险。
- 当前 fake data 中 PPS 丢失时间约 1s，小于 `pps_loss_threshold_s = 1.5s`，因此 DCAEngine 内部状态仍可能保持 `NORMAL`，这是符合当前状态机规则的。

结论：

```text
fake canary 可作为 smoke test，不作为最终实机锁版依据。
```

---

## 9. 调参过程记录

### 9.1 当前已尝试参数

| 日期 | 参数 | 结果 | 结论 |
|------|------|------|------|
| 当前 baseline | `drift_alpha_NORMAL = 0.05` | drift 收敛偏保守 | 可作为保守参考 |
| 当前 mock tuning | `drift_alpha_NORMAL = 0.08` | 提高 drift 场景响应速度 | 需要 golden_checker 验证是否破坏 jitter / holdover |

---

### 9.2 最终参数汇总表

| 参数 | 当前值 | 主要验证场景 | 当前建议 |
|------|--------|--------------|----------|
| `alpha_NORMAL` | `0.1` | normal | 暂时保留 |
| `alpha_RECOVERY` | `0.5` | pps_recovery | 暂时保留 |
| `alpha_HOLDOVER` | `0.01` | holdover | 暂时保留 |
| `drift_alpha_NORMAL` | `0.08` | drift / jitter / holdover | 需要 golden_checker 验证 |
| `drift_alpha_RECOVERY` | `0.1` | recovery | 暂时保留 |
| `drift_alpha_HOLDOVER` | `0.001` | holdover | 暂时保留 |
| `drift_ppm_limit` | `±50` | drift | 需要结合晶振规格确认 |
| `jitter_threshold_us` | `100` | jitter / recovery | 需要真实数据确认 |
| `static_threshold_us` | `300` | jitter | 需要真实数据确认 |
| `sigma_multiplier` | `3` | jitter | 需要真实数据确认 |
| `sigma_ema_alpha` | `0.05` | jitter | 需要真实数据确认 |
| `conf_normal_base` | `0.90` | normal | 暂时保留 |
| `conf_normal_increment` | `0.01` | normal | 暂时保留 |
| `conf_recovery_base` | `0.70` | recovery | 暂时保留 |
| `conf_recovery_increment` | `0.05` | recovery | 暂时保留 |
| `conf_holdover_decay` | `0.95` | holdover | 需要真实 holdover 数据确认 |
| `pps_loss_threshold_s` | `1.5` | holdover | 需要真实 PPS 丢失数据确认 |
| `relock_required_pps` | `3` | recovery | 暂时固定 |
| `stable_required_pps` | `3` | recovery | 暂时固定 |

---

## 10. 需要真实数据进一步微调的参数

以下参数不能只靠 fake data 最终锁定：

| 参数 | 为什么需要实机数据 |
|------|-------------------|
| `static_threshold_us` | 真实 PPS jitter / timestamp 抖动可能和 fake data 不同 |
| `sigma_multiplier` | 真实噪声可能不是正态分布，可能有长尾 |
| `sigma_ema_alpha` | 需要确认 sigma 是否被真实异常污染 |
| `jitter_threshold_us` | 决定 stable PPS，需要真实 residual 分布 |
| `drift_alpha_NORMAL` | 需要验证真实 drift 收敛和 jitter 抗扰 |
| `drift_ppm_limit` | 需要结合晶振规格和温漂 |
| `conf_holdover_decay` | 需要真实 holdover 误差增长曲线 |
| `pps_loss_threshold_s` | 需要真实 PPS 间隔和调度延迟统计 |
| `relock_required_pps` | 需要真实 PPS recovery 稳定性 |
| `stable_required_pps` | 需要真实 recovery residual 分布 |

---

## 11. 后续建议增加的测试

建议新增以下 fake scenario 或实机日志：

1. PPS 丢失 3s：验证是否真正进入 HOLDOVER
2. PPS 丢失 5s：验证 `max_holdover_drift < 500us`
3. PPS 恢复后连续 3 个 valid PPS：验证 `HOLDOVER -> RECOVERY`
4. RECOVERY 后连续 3 个 stable PPS：验证 `RECOVERY -> NORMAL`
5. 大 outlier 注入：验证 offset / drift 不被污染
6. jitter spike：验证 state 不乱跳
7. 长时间 drift：验证 drift_ppm 是否稳定收敛
8. seq gap：验证 metrics / confidence / state 是否按 spec 降级

---

## 12. Golden Checker 验证要求

最终参数锁版前必须运行：

```bash
python golden_checker.py --all
```

期望输出：

```text
NORMAL: PASS
HOLDOVER: PASS
JITTER: PASS
DRIFT: PASS
```

并且连续运行 3 次 PASS。

### 锁版条件

必须全部满足：

```text
4 个场景全部 PASS
连续运行 3 次 PASS
无时间回退
confidence 行为合理
HOLDOVER 不爆炸
参数理由已记录
```

满足后才能标记：

```text
DCA Engine V1.0 FINAL
```

---

## 13. 本阶段结论

当前参数可以作为 baseline 继续推进，但不能宣称最终锁版。

当前已经具备：

```text
interface alignment 基础验证
fake canary smoke test
参数解释 baseline
```

尚未完成：

```text
golden_checker --all 全场景 PASS
真实 PPS / jitter / drift / holdover 数据验证
连续 3 次 replay determinism 验证
```

本阶段建议：

```text
不继续盲目调参
先补齐 normal / holdover / jitter / drift 场景验证
用 golden_checker 判断 drift_alpha_NORMAL = 0.08 是否可保留
再基于真实数据微调 threshold / sigma / confidence decay
```
