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
|------|--------|------|
| alpha_NORMAL | ? | normal |
| alpha_RECOVERY | ? | recovery |
| ... | ... | ... |

---

## 7. 验证结果

运行 `python golden_checker.py --all` 输出：
