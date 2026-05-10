# DCA Confidence Model

## 1. Purpose

This document defines the DCA Engine confidence model.

The purpose of confidence is to make the engine honest about trust.

Confidence is not a cosmetic score. It is an engineering signal that tells downstream systems whether corrected time should be trusted, treated as degraded, or considered unreliable.

---

## 2. Confidence Definition

`confidence` is a scalar value in range:

```text
0.0 <= confidence <= 1.0
```

Interpretation:

| Range | Meaning |
|---|---|
| `0.90 - 1.00` | High trust. PPS is stable and engine is LOCKED. |
| `0.70 - 0.90` | Recovering or moderately trusted. PPS is present but lock evidence is still building. |
| `0.40 - 0.70` | Degraded trust. Warnings exist or timing evidence is incomplete. |
| `0.10 - 0.40` | Low trust. HOLDOVER or persistent abnormal behavior. |
| `0.00 - 0.10` | Not trusted except for monotonic continuity. |

Confidence must be clamped:

```text
confidence = max(0.0, min(confidence, 1.0))
```

---

## 3. Confidence by State

### 3.1 `INIT`

In `INIT`, confidence should start low-to-medium:

```text
confidence_initial = 0.5
```

Behavior:

- Do not report high confidence before valid PPS evidence exists.
- Confidence may increase only after valid PPS samples arrive.

Recommended range:

```text
0.3 <= confidence <= 0.7
```

---

### 3.2 `LOCKED`

In `LOCKED`, confidence rises with valid and stable PPS samples.

Recommended rule:

```text
confidence = min(confidence_locked_cap,
                 confidence_locked_base + confidence_locked_rise * stable_pps_counter)
```

Example:

```text
confidence_locked_base = 0.90
confidence_locked_rise = 0.01
confidence_locked_cap = 0.99
```

Engineering meaning:

- Stable PPS increases trust.
- Confidence should approach but not exceed the cap.
- The cap avoids claiming perfect certainty.

Expected behavior:

```text
LOCKED -> confidence rises or remains high
```

---

### 3.3 `DEGRADED`

In `DEGRADED`, confidence must decrease.

Triggers include:

- jitter spike
- drift warning
- seq gap
- repeated outliers

Recommended rule:

```text
confidence *= confidence_degraded_decay
```

Example:

```text
confidence_degraded_decay = 0.90
```

Additional penalties may apply:

```text
if seq_gap:
    confidence *= seq_gap_confidence_penalty

if jitter_warning:
    confidence *= jitter_confidence_penalty

if drift_warning:
    confidence *= drift_confidence_penalty
```

Engineering meaning:

- PPS may still exist, but timing evidence is not clean.
- Confidence should not remain locked-level during warnings.

Expected behavior:

```text
DEGRADED -> confidence falls or remains capped below LOCKED level
```

---

### 3.4 `HOLDOVER`

In `HOLDOVER`, confidence must continuously decrease.

Recommended rule:

```text
confidence *= confidence_holdover_decay
```

Example:

```text
confidence_holdover_decay = 0.95
```

Engineering meaning:

- PPS is missing.
- Output depends on prediction using last trusted offset / drift.
- The longer the outage, the less trustworthy prediction becomes.

Expected behavior:

```text
HOLDOVER -> confidence continuously decays
```

Confidence must not increase in HOLDOVER unless PPS returns and the state changes to `RECOVERY`.

---

### 3.5 `RECOVERY`

In `RECOVERY`, confidence may recover gradually after PPS returns.

Recommended rule:

```text
confidence = min(confidence_recovery_cap,
                 confidence_recovery_base + confidence_recovery_rise * stable_pps_counter)
```

Example:

```text
confidence_recovery_base = 0.70
confidence_recovery_rise = 0.05
confidence_recovery_cap = 0.90
```

Engineering meaning:

- PPS has returned.
- The system is rebuilding trust.
- Confidence should not immediately jump back to LOCKED level.

Expected behavior:

```text
RECOVERY -> confidence rises only with stable PPS evidence
```

---

## 4. Relationship with PPS State

| PPS Condition | Expected State | Confidence Behavior |
|---|---|---|
| PPS valid and stable | `LOCKED` | Rise toward high confidence. |
| PPS valid but noisy | `DEGRADED` | Decrease or cap below LOCKED level. |
| PPS lost | `HOLDOVER` | Continuously decay. |
| PPS restored after loss | `RECOVERY` | Gradually rise. |
| PPS restored and stable for enough samples | `LOCKED` | Rise toward locked cap. |

---

## 5. Relationship with Drift

Drift affects confidence because high drift reduces the reliability of corrected time and holdover prediction.

Recommended rules:

```text
if abs(drift_ppm) > drift_ppm_warn_threshold:
    warnings += ["WARN_DRIFT"]
    confidence *= drift_confidence_penalty
    state = DEGRADED
```

```text
if abs(drift_ppm) > drift_ppm_limit:
    failure_mode = "FAIL_DRIFT"
    confidence = min(confidence, degraded_confidence_cap)
```

Engineering meaning:

- Moderate drift reduces trust.
- Excessive drift blocks LOCKED.
- Drift must be especially important during HOLDOVER because prediction depends on drift.

---

## 6. Relationship with Jitter

Jitter affects confidence because it indicates short-term instability in PPS residuals.

Recommended rules:

```text
if jitter_us > jitter_threshold_us:
    warnings += ["WARN_JITTER"]
    confidence *= jitter_confidence_penalty
    state = DEGRADED
```

Engineering meaning:

- Jitter spike should not necessarily cause immediate failure.
- It must reduce confidence and be visible in metrics.
- Repeated jitter may prevent LOCKED or keep the system DEGRADED.

---

## 7. Relationship with Seq Gap

Seq gap affects confidence because missing events break replay continuity.

Recommended rules:

```text
if seq_gap:
    warnings += ["WARN_SEQ_GAP"]
    confidence *= seq_gap_confidence_penalty
    state = DEGRADED
```

Engineering meaning:

- Even if PPS appears valid, the engine cannot prove continuity when samples are missing.
- Seq gap must be visible in metrics and output.
- Confidence must reflect incomplete evidence.

---

## 8. Confidence Caps

Recommended confidence caps:

| State | Suggested Cap |
|---|---:|
| `INIT` | `0.70` |
| `LOCKED` | `0.99` |
| `DEGRADED` | `0.80` |
| `HOLDOVER` | Decaying, no upward cap needed |
| `RECOVERY` | `0.90` |

These caps prevent overstating trust.

Example:

```text
if state == DEGRADED:
    confidence = min(confidence, 0.80)

if state == RECOVERY:
    confidence = min(confidence, 0.90)
```

---

## 9. Confidence Floor

Confidence may have a small floor to preserve numeric stability:

```text
confidence_floor = 0.01
```

However, this floor does not mean the system is trusted.

Interpretation:

```text
confidence near floor = monotonic output only, not trusted time
```

---

## 10. Replay Determinism

Confidence must be deterministic.

Forbidden sources:

- wall-clock time
- random numbers
- thread scheduling
- non-deterministic iteration order
- external mutable state

Required property:

```text
same input events + same parameters + same initial state
= same confidence sequence
```

---

## 11. Acceptance Checklist

| Scenario | Expected Confidence Behavior |
|---|---|
| Normal PPS | Confidence rises toward LOCKED cap. |
| Drift slow | Confidence decreases or caps if drift exceeds warning threshold. |
| Jitter spike | Confidence drops and WARN_JITTER is emitted. |
| PPS lost | Confidence decays in HOLDOVER. |
| PPS recovery | Confidence gradually rises in RECOVERY. |
| Seq gap | Confidence drops and WARN_SEQ_GAP is emitted. |

---

## 12. Guiding Principle

Confidence must answer:

> Can downstream systems trust this corrected time?

Therefore:

- It must rise only with evidence.
- It must fall when evidence is missing or abnormal.
- It must not hide PPS loss.
- It must not hide seq gap.
- It must not claim full trust during recovery.
