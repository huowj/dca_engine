# Validation Scope Notice

当前参数说明仅服务于 **Round 4 interface alignment / mock scenario acceptance**。

本文件解释当前 mock validation 阶段使用的参数选择依据，包括：

- EMA alpha
- jitter threshold
- PPS missing timeout
- relock stable PPS count
- confidence decay
- drift smoothing / drift clamp

当前参数验证基于 mock scenario 和 interface replay 输出，**不代表 Authority Mode PASS**，也 **不代表真实硬件证据**。

后续进入真实硬件 Authority Mode 前，必须重新基于硬件 PPS、IMU、GNSS、CAN/PHY 时间戳数据进行验证。

# DCA Engine 参数选择理由

> **霍工填写说明**：每个参数填写你选择的数值，并解释为什么选这个值（物理意义 + 实测效果）

---

## 1. Offset Observer 参数

### alpha_NORMAL = ?

**选择值**：`___`

**理由**：

- 物理意义：offset 更新速度的平滑系数
- 选择依据：（例：平衡响应速度与噪声抑制）
- 实测效果：（例：offset 标准差 <15us）

---

### alpha_RECOVERY = ?

**选择值**：`___`

**理由**：

- 物理意义：从 holdover 恢复时的更新速度
- 选择依据：（例：需要快速收敛）
- 实测效果：（例：收敛时间 <2s）

---

### alpha_HOLDOVER = ?

**选择值**：`___`

**理由**：

- 物理意义：PPS 丢失期间的更新速度
- 选择依据：（例：几乎不更新，避免漂移污染）
- 实测效果：（例：holdover 期间 offset 变化 <10us）

---

### 中值窗口大小 = 5（固定，不改）

**理由**：5 点中值能有效抑制单点 outlier，延迟可接受。

---

## 2. Drift Observer 参数

### drift_alpha_NORMAL = ?

**选择值**：`___`

**理由**：

- 物理意义：drift 估计的更新速度
- 选择依据：
- 实测效果：

---

### drift_alpha_RECOVERY = ?

**选择值**：`___`

**理由**：

- 物理意义：
- 选择依据：
- 实测效果：

---

### drift_alpha_HOLDOVER = ?

**选择值**：`___`

**理由**：

- 物理意义：
- 选择依据：
- 实测效果：

---

### drift_bounds_ppm = ±50（参考值，可调）

**选择值**：`___`

**理由**：覆盖典型晶振的 ±50ppm 范围，超出视为异常。

---

## 3. Outlier Detection 参数

### static_threshold_us = ?

**选择值**：`___`

**理由**：

- 物理意义：绝对硬阈值
- 选择依据：（例：PPS 信号 ±200us 正常，±300us 为保护带）
- 实测效果：

---

### sigma_multiplier = ?

**选择值**：`___`

**理由**：

- 物理意义：动态阈值的倍数（3σ 原则）
- 选择依据：
- 实测效果：

---

### sigma_ema_alpha = ?

**选择值**：`___`

**理由**：残差方差的 EMA 平滑系数，0.05 表示约 20 个样本的时间常数。

---

## 4. Confidence Observer 参数

### conf_normal_base = ?

**选择值**：`___`

**理由**：NORMAL 状态的基础置信度。

---

### conf_normal_increment = ?

**选择值**：`___`

**理由**：每个有效 PPS 增加的置信度，上限 0.99。

---

### conf_recovery_base = ?

**选择值**：`___`

**理由**：RECOVERY 状态的基础置信度（低于 NORMAL，表示还在验证）。

---

### conf_recovery_increment = ?

**选择值**：`___`

**理由**：每个稳定 PPS 增加的置信度。

---

### conf_holdover_decay = ?

**选择值**：`___`

**理由**：HOLDOVER 期间每秒乘的衰减因子。0.95 表示每秒衰减 5%。

---

### confidence_bounds = [0.01, 0.99]（固定）

**理由**：避免完全 0 或完全 1 的极端值。

---

## 5. State Machine 参数

### pps_loss_threshold_s = 1.5（固定）

**理由**：>1.5s 无 PPS 判定为丢失，平衡响应速度与误判风险。

---

### relock_required_pps = 3（固定）

**理由**：3 个连续有效 PPS 才退出 HOLDOVER，避免瞬时恢复导致振荡。

---

### stable_required_pps = 3（固定）

**理由**：3 个连续稳定 PPS（residual<100us）才从 RECOVERY 回到 NORMAL。

---

## 6. 调参过程记录

### 尝试过的参数组合

| 日期 | 参数 | 结果 | 结论 |
|------|------|------|------|
| Day1 | alpha=0.2 | offset 振荡 | 放弃 |
| Day2 | ... | ... | ... |

---

### 最终参数汇总表

| 参数 | 最终值 | 场景 |
| ------ | -------- | ------ |
| alpha_NORMAL | ? | normal |
| alpha_RECOVERY | ? | recovery |
| ... | ... | ... |

---

## 7. 验证结果

运行 `python golden_checker.py --all` 输出：

---

## 8. Fake Canary 验证结果与参数更新建议

### 8.1 本次假数据验证结论

本次使用 `fake_scenario.csv` 进行金丝雀验证，包含三类典型场景：

1. 正常段：0s ~ 20s  
2. 漂移段：20s ~ 30s  
3. 电压跌落 + PPS 丢失段：45s ~ 46s  

验证结果：

- 正常段输出 `PASS`，说明基础 offset 观测和 confidence 上升行为正常。
- 漂移段输出 `FAIL_DRIFT`，说明 checker 能识别 offset 逐渐增大的异常趋势。
- 电压跌落 + PPS 丢失段输出 `FAIL_HOLDOVER`，说明 checker 能识别电源异常和 PPS 丢失风险。
- 当前假数据中 PPS 丢失时间约 1s，小于状态机设定的 `pps_loss_threshold_s = 1.5s`，因此 DCAEngine 内部状态仍可能保持 `NORMAL`，这是符合当前状态机规则的。

结论：  
本次结果可作为 fake canary smoke test PASS，但不能作为最终实机锁版依据。后续需要使用真实传感器数据进一步微调阈值。

---

### 8.2 当前建议保留的参数

| 参数 | 当前值 | 建议 |
| ----- | -------- | ------ |
| alpha_NORMAL | 0.1 | 暂时保留 |
| alpha_RECOVERY | 0.5 | 暂时保留 |
| alpha_HOLDOVER | 0.01 | 暂时保留 |
| drift_alpha_NORMAL | 0.05 | 暂时保留 |
| drift_alpha_RECOVERY | 0.1 | 暂时保留 |
| drift_alpha_HOLDOVER | 0.001 | 暂时保留 |
| sigma_ema_alpha | 0.05 | 暂时保留 |
| static_threshold_us | 300 | 需要真实数据确认 |
| sigma_multiplier | 3 | 需要真实数据确认 |
| conf_holdover_decay | 0.95 | 需要真实 holdover 数据确认 |
| drift_bounds_ppm | ±50 | 需要根据晶振规格确认 |

---

### 8.3 需要实机数据进一步微调的阈值

#### 1. static_threshold_us = 300

当前 fake data 中基础 offset 为 200us，正常抖动约 ±50us，因此 300us 可以暂时区分正常波动和异常漂移。

但是实机中 PPS 抖动、传感器 timestamp 抖动、通信延迟可能更复杂。  
建议采集真实数据后统计：

- 正常运行 offset 均值
- 正常运行 offset 标准差
- 99.7% 分位 offset 范围
- 电压波动时 offset 最大跳变

后续建议：

```text
static_threshold_us ≈ 正常 offset 最大波动 + 安全裕量
```

#### 2. sigma_multiplier = 3

当前使用 3σ 原则，适合正态噪声场景。
fake data 中随机抖动是正态分布，因此 3σ 能正常工作。

但如果真实传感器噪声不是正态分布，例如有长尾、突刺、偶发通信延迟，则 3σ 可能需要调整。

建议实机验证：

- 如果误杀正常 PPS，调大到 3.5 或 4
- 如果漏检异常 outlier，调小到 2.5

---

#### 3. sigma_ema_alpha = 0.05

当前 0.05 表示 sigma 约 20 个样本的时间常数，适合平稳更新。

实机上需要观察：

sigma 是否被单次异常拉大

sigma 是否恢复太慢

jitter 场景下 outlier 是否被漏检

建议：

- 如果 sigma 反应太慢，可增大到 0.08 ~ 0.1
- 如果 sigma 被异常污染，可减小到 0.02 ~ 0.03

---

#### 4. conf_holdover_decay = 0.95

当前 HOLDOVER 每次更新乘以 0.95，表示置信度逐步下降。

但最终 decay 应该根据真实系统可接受的 holdover 时间确定：

- 如果系统允许短时间 PPS 丢失，decay 可以慢一些，例如 0.97
- 如果 PPS 丢失必须快速降级，decay 可以快一些，例如 0.90 ~ 0.93

本次 fake data 中 PPS 丢失只有 1s，小于 1.5s 状态切换阈值，因此还不足以验证真实 HOLDOVER 衰减曲线。
建议后续增加 45s ~ 48s 的 PPS 丢失数据进行验证。

---

#### 5. pps_loss_threshold_s = 1.5

当前规则是超过 1.5s 无有效 PPS 才进入 HOLDOVER。

本次 fake data 的 PPS 丢失区间为 45s ~ 46s，约 1s，因此 DCAEngine 没有进入 HOLDOVER 是正常的。

如果产品要求 1s 内快速进入 HOLDOVER，则需要把阈值从 1.5s 调小。
如果产品允许 PPS 短暂丢失不切状态，则当前 1.5s 合理。

建议先不修改，等真实 PPS 丢失数据确认。

---

### 8.4 后续建议增加的测试

建议新增以下 fake scenario 或实机日志：

1. PPS 丢失 3s：验证 DCAEngine 是否真正进入 HOLDOVER
2. PPS 恢复后连续 3 个有效 PPS：验证 HOLDOVER -> RECOVERY
3. RECOVERY 后连续 3 个 stable PPS：验证 RECOVERY -> NORMAL
4. 电压跌落但 PPS 未丢失：验证 power 异常是否单独触发 checker FAIL
5. 大 outlier 注入：验证 offset observer 是否被污染
6. 长时间 drift：验证 drift_ppm 是否稳定收敛

---

### 8.5 本阶段结论

当前参数可以作为 baseline 参数继续推进。

本阶段不建议立即改动 DCAEngine 核心参数。
原因是当前 fake canary 已能区分：

- 正常 offset：PASS
- drift 异常：FAIL_DRIFT
- 电压/PPS 异常：FAIL_HOLDOVER

下一步应使用真实传感器数据替换 fake data，再决定是否调整：

- `static_threshold_us`
- `sigma_multiplier`
- `sigma_ema_alpha`
- `conf_holdover_decay`
- `pps_loss_threshold_s`
