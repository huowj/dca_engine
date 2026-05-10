# DCA Failure Modes

## 1. Purpose

This document defines DCA Engine warning and failure modes.

The goal is to clearly answer:

> Under what conditions should the corrected time output be considered degraded or untrusted?

Failure modes are part of the engineering contract. They must be visible in metrics, replay output, and reports.

---

## 2. Severity Levels

| Level | Meaning | Engine Response |
|---|---|---|
| `INFO` | Normal operating information. | Continue normal operation. |
| `WARN` | Abnormal condition detected, but time output may continue. | Reduce confidence and enter or remain in `DEGRADED`. |
| `FAIL` | Trust boundary exceeded. | Enter `HOLDOVER`, block LOCKED, or mark output as not trusted. |

---

## 3. Required Warning / Failure Modes

| Mode | Severity | Description |
|---|---|---|
| `WARN_JITTER` | WARN | PPS residual jitter exceeds threshold. |
| `WARN_SEQ_GAP` | WARN | Input event sequence gap is detected. |
| `FAIL_DRIFT` | FAIL | Drift estimate exceeds allowed trust boundary. |
| `FAIL_HOLDOVER` | FAIL | HOLDOVER duration or confidence crosses the allowed trust boundary. |

---

## 4. `WARN_JITTER`

### Trigger Condition

Triggered when:

```text
abs(residual_us) > jitter_threshold_us
```

or when estimated jitter exceeds the allowed threshold:

```text
jitter_us > jitter_threshold_us
```

### System Impact

- PPS is present but not stable.
- Offset updates may become noisy.
- Drift estimation may be corrupted if raw residual changes are used directly.
- Corrected time may still be monotonic but should not be treated as fully trusted.

### DCA Engine Response

The engine must:

1. Emit `WARN_JITTER`.
2. Reduce `confidence`.
3. Enter or remain in `DEGRADED` unless already in `HOLDOVER`.
4. Avoid allowing a single jitter spike to over-correct offset or drift.
5. Keep replay deterministic.

Recommended response:

```text
state = DEGRADED
confidence *= confidence_degraded_decay
warnings += ["WARN_JITTER"]
```

### Exit Condition

Clear `WARN_JITTER` only after:

```text
jitter_us <= jitter_threshold_us
for degraded_clear_count consecutive valid PPS samples
```

---

## 5. `WARN_SEQ_GAP`

### Trigger Condition

Triggered when the input interface marks a sequence gap:

```text
seq_gap == true
```

or when event sequence numbers are non-contiguous:

```text
current_seq_num != previous_seq_num + 1
```

when sequence tracking is enabled.

### System Impact

- The event stream is incomplete.
- The state history may be missing important timing evidence.
- Confidence must decrease because the engine cannot prove continuity.
- Even if PPS is present, the trust model must reflect missing data.

### DCA Engine Response

The engine must:

1. Emit `WARN_SEQ_GAP`.
2. Record the event in metrics.
3. Reduce `confidence`.
4. Enter or remain in `DEGRADED`, unless the system is already in `HOLDOVER`.
5. Preserve monotonic corrected time.

Recommended response:

```text
warnings += ["WARN_SEQ_GAP"]
confidence *= seq_gap_confidence_penalty
state = DEGRADED if PPS is still present
```

### Exit Condition

Clear `WARN_SEQ_GAP` only after:

```text
no seq gap for degraded_clear_count consecutive events
```

or after replay segment boundary reset, if explicitly defined by test spec.

---

## 6. `FAIL_DRIFT`

### Trigger Condition

Triggered when drift exceeds the hard trust boundary:

```text
abs(drift_ppm) > drift_ppm_limit
```

or when drift remains above warning threshold for too long:

```text
abs(drift_ppm) > drift_ppm_warn_threshold
for drift_fail_count consecutive updates
```

### System Impact

- Board clock behavior is outside expected range.
- HOLDOVER prediction may become unreliable.
- Offset correction may not be enough to guarantee trusted time.
- Continued LOCKED operation would overstate trust.

### DCA Engine Response

The engine must:

1. Emit `FAIL_DRIFT`.
2. Prevent entry into `LOCKED`.
3. Enter `DEGRADED` if PPS is present but drift is abnormal.
4. Enter `HOLDOVER` if PPS is missing or drift makes prediction untrusted.
5. Reduce confidence aggressively.

Recommended response:

```text
failure_mode = "FAIL_DRIFT"
confidence = min(confidence, degraded_confidence_cap)
state = DEGRADED or HOLDOVER depending on PPS availability
```

### Exit Condition

Clear `FAIL_DRIFT` only after:

```text
abs(drift_ppm) <= drift_ppm_warn_threshold
for recovery_lock_count consecutive stable PPS samples
```

The engine must pass through `RECOVERY` before returning to `LOCKED`.

---

## 7. `FAIL_HOLDOVER`

### Trigger Condition

Triggered when HOLDOVER becomes too long or too uncertain:

```text
state == HOLDOVER
and holdover_duration_us > max_holdover_duration_us
```

or:

```text
state == HOLDOVER
and confidence < min_holdover_confidence
```

### System Impact

- PPS is unavailable.
- Corrected time is based only on prediction.
- Prediction uncertainty grows over time.
- The system can no longer honestly claim high trust.

### DCA Engine Response

The engine must:

1. Emit `FAIL_HOLDOVER`.
2. Keep corrected time monotonic.
3. Keep state in `HOLDOVER` until valid PPS returns.
4. Mark confidence as low.
5. Prevent immediate jump to `LOCKED` after PPS returns; require `RECOVERY`.

Recommended response:

```text
failure_mode = "FAIL_HOLDOVER"
state = HOLDOVER
confidence = max(confidence_floor, confidence * confidence_holdover_decay)
```

### Exit Condition

Clear `FAIL_HOLDOVER` only when:

```text
valid PPS returns
and state enters RECOVERY
and stable PPS count reaches recovery_lock_count
```

---

## 8. Failure Mode Interaction

Multiple warnings or failures may exist at the same time.

Recommended priority:

```text
FAIL_HOLDOVER > FAIL_DRIFT > WARN_SEQ_GAP > WARN_JITTER
```

State priority:

```text
PPS lost      -> HOLDOVER
PPS returned  -> RECOVERY
Hard failure  -> HOLDOVER or DEGRADED
Warning only  -> DEGRADED
Stable normal -> LOCKED
```

Confidence should reflect the worst active condition.

---

## 9. Metrics Requirements

Every run should report:

| Metric | Meaning |
|---|---|
| `warn_jitter_count` | Number of jitter warnings. |
| `warn_seq_gap_count` | Number of seq gap warnings. |
| `fail_drift_count` | Number of drift failures. |
| `fail_holdover_count` | Number of holdover failures. |
| `degraded_seen` | Whether DEGRADED occurred. |
| `holdover_seen` | Whether HOLDOVER occurred. |
| `recovery_seen` | Whether RECOVERY occurred. |
| `locked_seen` | Whether LOCKED occurred. |
| `min_confidence` | Lowest confidence in replay. |
| `final_confidence` | Final confidence after replay. |

---

## 10. Acceptance Checklist

| Failure Mode | Must Be Detected | Must Affect Confidence | Must Affect State |
|---|---:|---:|---:|
| `WARN_JITTER` | Yes | Yes | Yes, DEGRADED |
| `WARN_SEQ_GAP` | Yes | Yes | Yes, DEGRADED |
| `FAIL_DRIFT` | Yes | Yes | Yes, DEGRADED or HOLDOVER |
| `FAIL_HOLDOVER` | Yes | Yes | Yes, HOLDOVER |

The engine must not silently absorb these conditions.
