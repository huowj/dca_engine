# DCA Engine Failure Modes 说明

> 本文档用于定义 DCA Engine 必须识别的 warning / failure mode。  
> 重点是明确：
>
> - 什么情况下系统不能继续认为时间完全可信
> - 哪些异常必须进入 metrics / report
> - 哪些异常必须触发 DEGRADED
> - 哪些异常必须阻止 LOCKED 或进入 HOLDOVER
>
> 本文档用于支撑 replay evidence、Trust Check、OEM evidence 和后续验收签字。

---

## 1. Failure Mode 设计目标

DCA Engine 不能只输出 corrected time，还必须说明：

```text
这个 corrected time 当前是否可信
为什么可信
为什么不可信
如果不可信，是哪一种异常导致的
```

因此 failure mode 的目标是定义：

> 系统在什么情况下必须 WARN、DEGRADE 或 FAIL。

---

## 2. 严重级别定义

| 级别 | 含义 | Engine 响应 |
|------|------|-------------|
| `INFO` | 正常信息 | 继续正常运行 |
| `WARN` | 发现异常，但系统尚可继续输出时间 | 降低 confidence，进入或保持 DEGRADED |
| `FAIL` | 超过可信边界，不能继续认为时间可信 | 进入 HOLDOVER，阻止 LOCKED，或标记输出不可信 |

---

## 3. 必须支持的 Failure / Warning Mode

本阶段至少必须支持以下 4 类：

| Mode | 级别 | 一句话定义 |
|------|------|------------|
| `WARN_JITTER` | WARN | PPS residual 抖动超过阈值 |
| `WARN_SEQ_GAP` | WARN | 输入事件序列出现 gap |
| `FAIL_DRIFT` | FAIL | drift 超出可信边界 |
| `FAIL_HOLDOVER` | FAIL | HOLDOVER 时间过长或 confidence 过低 |

可选扩展：

| Mode | 级别 | 一句话定义 |
|------|------|------------|
| `WARN_DRIFT` | WARN | drift 接近异常但未超过失败阈值 |
| `WARN_OUTLIER` | WARN | outlier 数量过多 |
| `FAIL_PPS_LOST` | FAIL | PPS 丢失导致系统失去外部时间源 |

---

## 4. WARN_JITTER

### 4.1 定义

`WARN_JITTER` 表示 PPS residual 或 jitter 估计值超过允许阈值。

### 4.2 触发条件

满足以下任一条件触发：

```text
abs(residual_us) > jitter_threshold_us
```

或：

```text
jitter_us > jitter_threshold_us
```

或：

```text
短时间内 outlier 数量超过 outlier_warn_count
```

### 4.3 对系统的影响

jitter spike 可能导致：

- offset observer 被异常点拉偏
- drift observer 估计错误
- corrected time 短时抖动
- confidence 被高估

因此 jitter spike 不能被静默忽略。

### 4.4 DCA Engine 响应

触发 `WARN_JITTER` 后，Engine 必须：

1. 在输出中加入 `WARN_JITTER`
2. 在 metrics 中累计 `warn_jitter_count`
3. 降低 confidence
4. 进入或保持 `DEGRADED`
5. 不允许单个 jitter spike 直接污染 offset / drift
6. 保持 `corrected_time_us` 单调递增

推荐响应：

```text
warnings += ["WARN_JITTER"]
confidence *= jitter_confidence_penalty
state = DEGRADED
```

### 4.5 退出条件

只有连续稳定样本达到要求后才能清除：

```text
jitter_us <= jitter_threshold_us
stable_pps_counter >= stable_required_pps
```

---

## 5. WARN_SEQ_GAP

### 5.1 定义

`WARN_SEQ_GAP` 表示输入事件流出现 sequence gap，DCA Engine 无法证明事件连续性。

### 5.2 触发条件

满足以下任一条件触发：

```text
seq_gap_detected == true
```

或：

```text
seq_gap 字段非空
```

或：

```text
current_seq_num != previous_seq_num + 1
```

其中是否使用 `seq_num` 自动判断，可根据 interface spec 决定。

### 5.3 对系统的影响

seq gap 表示：

- 中间事件可能丢失
- replay evidence 不完整
- 状态连续性无法完全证明
- confidence 不能保持高可信

即使 PPS 当前存在，seq gap 仍然必须进入 metrics。

### 5.4 DCA Engine 响应

触发 `WARN_SEQ_GAP` 后，Engine 必须：

1. 在输出中加入 `WARN_SEQ_GAP`
2. 在 metrics 中累计 `warn_seq_gap_count`
3. 降低 confidence
4. 推荐进入或保持 `DEGRADED`
5. 保留 corrected time monotonic guarantee

推荐响应：

```text
warnings += ["WARN_SEQ_GAP"]
confidence *= seq_gap_confidence_penalty
state = DEGRADED
```

### 5.5 退出条件

推荐清除条件：

```text
连续 degraded_clear_count 个事件未再出现 seq gap
```

或：

```text
进入新的 replay segment，且 spec 明确允许重置 seq gap 状态
```

---

## 6. WARN_DRIFT

### 6.1 定义

`WARN_DRIFT` 表示 drift 已超过正常观测范围，但尚未达到 failure 边界。

### 6.2 触发条件

```text
abs(drift_ppm) > drift_ppm_warn_threshold
```

并且：

```text
abs(drift_ppm) <= drift_ppm_limit
```

### 6.3 对系统的影响

drift 异常说明：

- board clock 可能存在频偏
- holdover 预测误差会增大
- offset 修正可能需要更谨慎
- confidence 不能维持 LOCKED 高值

### 6.4 DCA Engine 响应

推荐响应：

```text
warnings += ["WARN_DRIFT"]
confidence *= drift_confidence_penalty
state = DEGRADED
```

### 6.5 退出条件

```text
abs(drift_ppm) <= drift_ppm_warn_threshold
stable_pps_counter >= stable_required_pps
```

---

## 7. FAIL_DRIFT

### 7.1 定义

`FAIL_DRIFT` 表示 drift 超过系统可信边界，不能继续按 LOCKED 状态信任 corrected time。

### 7.2 触发条件

满足以下任一条件触发：

```text
abs(drift_ppm) > drift_ppm_limit
```

或：

```text
abs(drift_ppm) > drift_ppm_warn_threshold
持续 drift_fail_count 次更新
```

### 7.3 对系统的影响

FAIL_DRIFT 表示：

- board clock 漂移超出合理范围
- holdover 预测可能不可信
- offset / drift 估计可能已经失真
- 系统不能继续保持 LOCKED

### 7.4 DCA Engine 响应

触发 `FAIL_DRIFT` 后，Engine 必须：

1. 输出 `failure_mode = "FAIL_DRIFT"`
2. 阻止进入 `LOCKED`
3. 降低 confidence
4. 如果 PPS 仍存在，进入或保持 `DEGRADED`
5. 如果 PPS 同时丢失，进入 `HOLDOVER`
6. 继续保证 corrected time 单调

推荐响应：

```text
failure_mode = "FAIL_DRIFT"
confidence = min(confidence, conf_degraded_cap)

if pps_available:
    state = DEGRADED
else:
    state = HOLDOVER
```

### 7.5 退出条件

只有 drift 回到可接受范围，并经过 RECOVERY 验证后才能清除：

```text
abs(drift_ppm) <= drift_ppm_warn_threshold
stable_pps_counter >= stable_required_pps
state == RECOVERY or LOCKED
```

注意：

```text
FAIL_DRIFT 清除后不能直接跳过 RECOVERY
```

---

## 8. FAIL_HOLDOVER

### 8.1 定义

`FAIL_HOLDOVER` 表示系统处于 HOLDOVER 太久，或 HOLDOVER 期间 confidence 已低于可接受边界。

### 8.2 触发条件

满足以下任一条件触发：

```text
state == HOLDOVER
holdover_duration_us > max_holdover_duration_us
```

或：

```text
state == HOLDOVER
confidence < min_holdover_confidence
```

或：

```text
PPS 丢失持续时间超过系统允许范围
```

### 8.3 对系统的影响

FAIL_HOLDOVER 表示：

- PPS 已不可用
- corrected time 只依赖预测
- 预测误差会随时间积累
- 下游系统不能继续按可信时间使用

### 8.4 DCA Engine 响应

触发 `FAIL_HOLDOVER` 后，Engine 必须：

1. 输出 `failure_mode = "FAIL_HOLDOVER"`
2. 保持或进入 `HOLDOVER`
3. 持续降低 confidence
4. 保证 corrected time 单调
5. PPS 恢复后必须进入 `RECOVERY`，不能直接进入 `LOCKED`

推荐响应：

```text
failure_mode = "FAIL_HOLDOVER"
state = HOLDOVER
confidence = max(confidence_floor,
                 confidence * conf_holdover_decay)
```

### 8.5 退出条件

必须满足：

```text
PPS_RECOVERY 或 valid PPS 恢复
```

然后进入：

```text
RECOVERY
```

并且连续稳定 PPS 达标后：

```text
RECOVERY -> LOCKED
```

---

## 9. FAIL_PPS_LOST（可选但建议）

### 9.1 定义

`FAIL_PPS_LOST` 表示 PPS 信号丢失，系统失去外部时间参考。

### 9.2 触发条件

```text
PPS_LOST
```

或：

```text
time_since_last_valid_pps > pps_loss_threshold_s
```

### 9.3 对系统的影响

- 系统不能继续维持 LOCKED
- offset 不能继续依赖 PPS 更新
- drift 预测成为 holdover 的主要依据
- confidence 必须下降

### 9.4 DCA Engine 响应

```text
failure_mode = "FAIL_PPS_LOST"
state = HOLDOVER
enter_holdover()
confidence *= conf_holdover_decay
```

---

## 10. 多个 Failure Mode 同时存在时的优先级

多个异常可能同时发生，例如：

```text
PPS_LOST + drift 异常
PPS_LOST + seq gap
jitter spike + drift 异常
```

推荐优先级：

```text
FAIL_HOLDOVER
> FAIL_PPS_LOST
> FAIL_DRIFT
> WARN_SEQ_GAP
> WARN_JITTER
> WARN_DRIFT
```

状态优先级：

```text
PPS 丢失      -> HOLDOVER
PPS 恢复      -> RECOVERY
硬失败        -> HOLDOVER 或 DEGRADED
普通 warning  -> DEGRADED
稳定正常      -> LOCKED
```

confidence 应按最严重异常处理，不能只按较轻异常计算。

---

## 11. Metrics 输出要求

每次 replay / mock / interface alignment 后，建议输出以下 metrics：

| 字段 | 含义 |
|------|------|
| `warn_jitter_count` | jitter warning 次数 |
| `warn_seq_gap_count` | seq gap warning 次数 |
| `warn_drift_count` | drift warning 次数 |
| `fail_drift_count` | drift failure 次数 |
| `fail_holdover_count` | holdover failure 次数 |
| `fail_pps_lost_count` | PPS lost failure 次数 |
| `degraded_seen` | 是否进入过 DEGRADED |
| `holdover_seen` | 是否进入过 HOLDOVER |
| `recovery_seen` | 是否进入过 RECOVERY |
| `locked_seen` | 是否进入过 LOCKED |
| `min_confidence` | replay 期间最低 confidence |
| `final_confidence` | 最终 confidence |
| `final_state` | 最终状态 |

---

## 12. Failure Mode 与状态机关系

| Mode | 推荐状态变化 | confidence 变化 |
|------|--------------|----------------|
| `WARN_JITTER` | `LOCKED -> DEGRADED` | 下降 |
| `WARN_SEQ_GAP` | `LOCKED -> DEGRADED` | 下降 |
| `WARN_DRIFT` | `LOCKED -> DEGRADED` | 下降 |
| `FAIL_DRIFT` | 阻止 `LOCKED`，进入 `DEGRADED` 或 `HOLDOVER` | 明显下降 |
| `FAIL_HOLDOVER` | 保持 `HOLDOVER` | 持续下降 |
| `FAIL_PPS_LOST` | 进入 `HOLDOVER` | 持续下降 |

---

## 13. 验收 Checklist

| Failure / Warning | 必须识别 | 必须进入 metrics | 必须影响 confidence | 必须影响 state | 当前结论 |
|-------------------|----------|------------------|---------------------|----------------|----------|
| `WARN_JITTER` | 是 | 是 | 是 | 是，进入 DEGRADED | `___` |
| `WARN_SEQ_GAP` | 是 | 是 | 是 | 是，进入 DEGRADED 或至少明确 metrics | `___` |
| `WARN_DRIFT` | 建议 | 是 | 是 | 是，进入 DEGRADED | `___` |
| `FAIL_DRIFT` | 是 | 是 | 是 | 是，阻止 LOCKED | `___` |
| `FAIL_HOLDOVER` | 是 | 是 | 是 | 是，保持 HOLDOVER | `___` |
| `FAIL_PPS_LOST` | 建议 | 是 | 是 | 是，进入 HOLDOVER | `___` |

---

## 14. 需要验证的场景

建议通过以下 scenario 验证 failure mode：

### 14.1 jitter_spike

验证：

```text
WARN_JITTER
confidence 下降
state -> DEGRADED
offset / drift 不被单点污染
```

### 14.2 seq_gap

验证：

```text
WARN_SEQ_GAP
seq_gap 进入 metrics
confidence 下降
state -> DEGRADED 或明确记录 metrics
```

### 14.3 drift_slow

验证：

```text
WARN_DRIFT 或 FAIL_DRIFT
confidence 下降
阻止不合理 LOCKED
```

### 14.4 pps_lost_holdover

验证：

```text
PPS_LOST
state -> HOLDOVER
confidence 持续下降
必要时 FAIL_HOLDOVER
```

### 14.5 pps_recovery

验证：

```text
HOLDOVER -> RECOVERY
RECOVERY -> LOCKED
不能 HOLDOVER 直接 LOCKED
```

---

## 15. 本阶段结论

DCA Engine 的 failure mode 设计目标是：

```text
不静默吞掉异常
不在异常时假装稳定
不在 PPS 丢失后继续高 confidence
不在证据不完整时继续 LOCKED
```

最终要证明：

> DCA Engine 不仅能输出时间，也能说明什么时候这个时间不能被完全信任。
