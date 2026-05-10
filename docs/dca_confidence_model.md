# DCA Engine Confidence Model 说明

> 本文档用于定义 DCA Engine 的 `confidence` 计算逻辑和工程含义。  
> 重点不是让曲线“好看”，而是让系统能诚实表达：
>
> - 当前 corrected time 是否可信
> - PPS 正常时 confidence 如何上升
> - PPS 异常时 confidence 如何下降
> - HOLDOVER 期间 confidence 为什么不能保持高值
> - seq gap / jitter / drift 对 confidence 的影响
>
> 本文档应作为后续 tuning、replay、report 和 Trust Check 的依据。

---

## 1. Confidence 设计目标

`confidence` 的目标是回答一个问题：

> 当前 DCA Engine 输出的 `corrected_time_us` 有多可信？

它不是 UI 分数，也不是为了让曲线平滑好看，而是一个工程可信度指标。

DCA Engine 必须做到：

```text
有稳定 PPS 证据时，confidence 上升
PPS 丢失时，confidence 下降
存在 jitter / drift / seq gap 时，confidence 下降
恢复过程中，confidence 逐步回升
不能在证据不足时假装稳定
```

---

## 2. Confidence 数值定义

`confidence` 范围固定为：

```text
0.0 <= confidence <= 1.0
```

推荐实现中可以使用边界：

```text
confidence_bounds = [0.01, 0.99]
```

### 数值含义

| confidence 范围 | 含义 | 工程解释 |
|-----------------|------|----------|
| `0.90 ~ 0.99` | 高可信 | PPS 稳定，系统处于 LOCKED |
| `0.70 ~ 0.90` | 中高可信 | 系统处于 RECOVERY，正在重新建立锁定 |
| `0.40 ~ 0.70` | 降级可信 | 存在 jitter / drift / seq gap 等异常 |
| `0.10 ~ 0.40` | 低可信 | HOLDOVER 或持续异常 |
| `0.01 ~ 0.10` | 基本不可信 | 只能保证时间单调，不能保证时间准确 |

注意：

```text
confidence 接近 0 不代表 corrected_time_us 可以倒退
```

即使 confidence 很低，`corrected_time_us` 仍必须满足 monotonic guarantee。

---

## 3. 各状态下的 Confidence 行为

---

## 3.1 INIT 状态

### 定义

`INIT` 表示 DCA Engine 刚启动，还没有足够 PPS 证据建立可信锁定。

### confidence 行为

INIT 阶段 confidence 不应过高。

推荐初始值：

```text
confidence_initial = 0.5
```

### 物理 / 工程意义

- 系统刚启动，还不知道 board clock 与 reference time 的稳定关系
- offset / drift 尚未充分收敛
- 不能一开始就输出高可信度

### 推荐范围

```text
0.3 <= confidence <= 0.7
```

### 退出 INIT 后

- 如果 PPS 稳定并进入 `LOCKED`，confidence 可逐步上升
- 如果 PPS 丢失并进入 `HOLDOVER`，confidence 必须下降

---

## 3.2 LOCKED 状态

### 定义

`LOCKED` 表示 PPS 正常、稳定，DCA Engine 已经建立可信锁定。

### confidence 行为

LOCKED 状态下，confidence 应随连续有效 PPS 增加而上升。

推荐公式：

```text
confidence = min(conf_normal_cap,
                 conf_normal_base + conf_normal_increment * valid_pps_counter)
```

推荐参数：

```text
conf_normal_base = 0.90
conf_normal_increment = 0.01
conf_normal_cap = 0.99
```

### 物理 / 工程意义

- 连续 PPS 正常说明外部时间源稳定
- offset 观测可信
- drift 估计可信
- 系统可以逐步提高对 corrected time 的信任

### 调大 / 调小影响

#### 调大 `conf_normal_increment`

效果：

```text
confidence 上升更快
```

风险：

```text
可能过早给出高可信度
```

#### 调小 `conf_normal_increment`

效果：

```text
confidence 上升更慢，更保守
```

风险：

```text
正常场景下较长时间保持低 confidence
```

---

## 3.3 DEGRADED 状态

### 定义

`DEGRADED` 表示 PPS 可能仍存在，但系统检测到 jitter、drift、seq gap 或 outlier 等异常。

### confidence 行为

DEGRADED 状态下 confidence 必须下降，或至少被限制在低于 LOCKED 的上限。

推荐公式：

```text
confidence = confidence * conf_degraded_decay
```

推荐参数：

```text
conf_degraded_decay = 0.90
conf_degraded_cap = 0.80
```

可以进一步叠加异常惩罚：

```text
if seq_gap:
    confidence *= seq_gap_confidence_penalty

if jitter_warning:
    confidence *= jitter_confidence_penalty

if drift_warning:
    confidence *= drift_confidence_penalty
```

### 物理 / 工程意义

- PPS 存在不等于时间完全可信
- jitter spike 可能污染 offset
- drift 异常可能影响 holdover 预测
- seq gap 说明输入事件流不连续
- 因此 confidence 不能继续保持 LOCKED 水平

### 调大 / 调小影响

#### 衰减变慢，例如 `0.95`

效果：

```text
DEGRADED 后 confidence 下降较慢
```

风险：

```text
异常时可能过度乐观
```

#### 衰减变快，例如 `0.80`

效果：

```text
DEGRADED 后 confidence 快速下降
```

风险：

```text
对短时噪声过于敏感
```

---

## 3.4 HOLDOVER 状态

### 定义

`HOLDOVER` 表示 PPS 丢失或不可用，DCA Engine 使用最后可信 offset / drift 进行时间预测。

### confidence 行为

HOLDOVER 状态下 confidence 必须持续下降。

推荐公式：

```text
confidence = confidence * conf_holdover_decay
```

推荐参数：

```text
conf_holdover_decay = 0.95
```

如果按秒更新，可解释为：

```text
每秒下降约 5%
```

### 物理 / 工程意义

- PPS 丢失后，系统失去外部时间锚点
- corrected time 只能依赖 board clock 和 drift 预测
- holdover 时间越长，误差可能越大
- 因此 confidence 不能保持稳定，更不能上升

### 调大 / 调小影响

#### 调大到 `0.97`

效果：

```text
confidence 下降更慢
```

适用情况：

```text
硬件时钟稳定，允许短时间 PPS 丢失
```

风险：

```text
PPS 丢失后仍长时间显示较高 confidence
```

#### 调小到 `0.90 ~ 0.93`

效果：

```text
confidence 下降更快
```

适用情况：

```text
系统要求 PPS 丢失后快速降级
```

风险：

```text
短时 PPS 抖动也可能导致 confidence 过低
```

---

## 3.5 RECOVERY 状态

### 定义

`RECOVERY` 表示 PPS 已恢复，但系统仍在重新验证 PPS 是否稳定。

### confidence 行为

RECOVERY 状态下 confidence 可以逐步回升，但不能直接跳回高可信。

推荐公式：

```text
confidence = min(conf_recovery_cap,
                 conf_recovery_base + conf_recovery_increment * stable_pps_counter)
```

推荐参数：

```text
conf_recovery_base = 0.70
conf_recovery_increment = 0.05
conf_recovery_cap = 0.90
```

### 物理 / 工程意义

- PPS 刚恢复并不代表系统已经完全稳定
- offset 需要重新收敛
- drift 需要重新确认
- 需要连续稳定 PPS 才能回到 LOCKED

### 调大 / 调小影响

#### 调大 `conf_recovery_increment`

效果：

```text
恢复更快
```

风险：

```text
可能过早回到高 confidence
```

#### 调小 `conf_recovery_increment`

效果：

```text
恢复更保守
```

风险：

```text
正常恢复后 confidence 长时间偏低
```

---

## 4. Confidence 与 PPS 状态的关系

| PPS 状态 | 期望状态 | confidence 行为 |
|----------|----------|----------------|
| PPS 有效且稳定 | `LOCKED` | 上升到高可信 |
| PPS 有效但 jitter 异常 | `DEGRADED` | 下降或被 cap |
| PPS 有效但 drift 异常 | `DEGRADED` / `FAIL_DRIFT` | 下降 |
| PPS 丢失 | `HOLDOVER` | 持续下降 |
| PPS 恢复 | `RECOVERY` | 逐步回升 |
| PPS 恢复且连续稳定 | `LOCKED` | 回到高可信 |

---

## 5. Confidence 与 Drift 的关系

### drift 对 confidence 的影响

drift 影响 confidence 的原因：

```text
drift 越大，board clock 与 reference time 的偏离趋势越明显
```

尤其在 HOLDOVER 中，系统依赖 drift 预测时间，因此 drift 直接影响预测可信度。

### 推荐规则

#### drift warning

```text
if abs(drift_ppm) > drift_ppm_warn_threshold:
    warnings += ["WARN_DRIFT"]
    confidence *= drift_confidence_penalty
    state = DEGRADED
```

#### drift failure

```text
if abs(drift_ppm) > drift_ppm_limit:
    failure_mode = "FAIL_DRIFT"
    confidence = min(confidence, conf_degraded_cap)
```

### 工程含义

- 小 drift：正常可接受
- 中等 drift：需要 WARN / DEGRADED
- 大 drift：不能继续认为 LOCKED 可信

---

## 6. Confidence 与 Jitter 的关系

### jitter 对 confidence 的影响

jitter 表示 PPS residual 的短时波动。

如果 jitter 很大，说明：

```text
PPS 边沿可能不稳定
timestamp 路径可能有抖动
offset 更新可能被噪声污染
drift 估计可能被误导
```

### 推荐规则

```text
if jitter_us > jitter_threshold_us:
    warnings += ["WARN_JITTER"]
    confidence *= jitter_confidence_penalty
    state = DEGRADED
```

### 工程含义

- 单次 jitter spike 不一定立即 FAIL
- 但必须降低 confidence
- 必须在 metrics / report 中可见

---

## 7. Confidence 与 Seq Gap 的关系

### seq gap 对 confidence 的影响

seq gap 表示输入事件序列不连续。

这意味着：

```text
DCA Engine 无法证明中间事件没有丢失
状态连续性证据不完整
replay 证据链不完整
```

因此即使 PPS 当前有效，也必须降低 confidence。

### 推荐规则

```text
if seq_gap_detected:
    warnings += ["WARN_SEQ_GAP"]
    confidence *= seq_gap_confidence_penalty
    state = DEGRADED
```

推荐参数：

```text
seq_gap_confidence_penalty = 0.85
```

### 工程含义

- seq gap 不是普通日志字段
- 它影响系统对时间连续性的信任
- 必须进入 metrics
- 推荐触发 WARN 或 DEGRADED

---

## 8. Confidence 推荐参数表

| 参数 | 推荐值 | 含义 |
|------|--------|------|
| `confidence_initial` | `0.5` | INIT 初始置信度 |
| `conf_normal_base` | `0.90` | LOCKED 基础置信度 |
| `conf_normal_increment` | `0.01` | 每个有效 PPS 增加量 |
| `conf_normal_cap` | `0.99` | LOCKED 上限 |
| `conf_recovery_base` | `0.70` | RECOVERY 基础置信度 |
| `conf_recovery_increment` | `0.05` | 每个稳定 PPS 增加量 |
| `conf_recovery_cap` | `0.90` | RECOVERY 上限 |
| `conf_degraded_decay` | `0.90` | DEGRADED 衰减因子 |
| `conf_degraded_cap` | `0.80` | DEGRADED 上限 |
| `conf_holdover_decay` | `0.95` | HOLDOVER 衰减因子 |
| `seq_gap_confidence_penalty` | `0.85` | seq gap 惩罚因子 |
| `jitter_confidence_penalty` | `0.90` | jitter 惩罚因子 |
| `drift_confidence_penalty` | `0.90` | drift 惩罚因子 |
| `confidence_bounds` | `[0.01, 0.99]` | confidence 边界 |

---

## 9. Confidence 状态上限建议

| 状态 | 建议上限 | 原因 |
|------|----------|------|
| `INIT` | `0.70` | 尚未建立锁定 |
| `LOCKED` | `0.99` | 高可信，但不宣称绝对可信 |
| `DEGRADED` | `0.80` | 存在异常，不能达到 LOCKED 水平 |
| `HOLDOVER` | 不上升，只下降 | PPS 丢失，可信度只能衰减 |
| `RECOVERY` | `0.90` | 正在恢复，但未完全锁定 |

---

## 10. Replay 一致性要求

confidence 必须满足 replay determinism：

```text
相同输入
相同参数
相同初始状态
```

必须得到：

```text
相同 confidence 序列
```

禁止 confidence 计算依赖：

- 当前系统时间
- 随机数
- 线程调度
- 外部状态
- 非确定性容器遍历顺序

---

## 11. 验收 Checklist

| 场景 | 期望 confidence 行为 | 当前结论 |
|------|----------------------|----------|
| normal | confidence 上升到 LOCKED 高可信 | `___` |
| drift_slow | drift 异常后 confidence 下降 | `___` |
| jitter_spike | jitter spike 后 confidence 下降 | `___` |
| pps_lost_holdover | HOLDOVER 期间 confidence 持续下降 | `___` |
| pps_recovery | RECOVERY 期间 confidence 逐步回升 | `___` |
| seq_gap | seq gap 后 confidence 下降 | `___` |
| replay | 同输入同 confidence 序列 | `___` |

---

## 12. 需要实机数据确认的参数

以下参数需要真实数据进一步确认：

| 参数 | 需要确认内容 |
|------|--------------|
| `conf_holdover_decay` | PPS 丢失后多长时间内仍可接受 |
| `seq_gap_confidence_penalty` | seq gap 对系统可信度影响程度 |
| `jitter_confidence_penalty` | jitter spike 对 offset / drift 的污染程度 |
| `drift_confidence_penalty` | drift 异常对 holdover 预测的影响 |
| `conf_recovery_increment` | PPS 恢复后多快可以重新建立信任 |

---

## 13. 本阶段结论

本阶段 confidence model 的核心原则是：

```text
有证据才上升
有异常就下降
PPS 丢失必须下降
恢复必须逐步回升
不能假稳定
```

最终目标是让 DCA Engine 诚实表达：

> 当前 corrected time 是否值得被下游系统信任。
