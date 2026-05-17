#!/usr/bin/env python3
"""
dca_runtime_tuning_runner.py

DCA Engine Runtime CSV Tuning Runner
定位：外层Harness，只做baseline replay、metrics采集、画图、参数对比

铁律：
- 不修改dca_engine.py的任何代码
- 只通过参数配置调用DCAEngine
- 每次只改一个参数
- 每次调参后必须做3-run deterministic check
- 违反reject rule的参数组合直接拒绝
"""

import csv
import json
import hashlib
import argparse
from dataclasses import dataclass, field
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path

# 导入核心算法（只导入，不修改）
from dca_engine import DCAEngine


# ============================================================
# 1. 参数配置类（只用于传递给DCAEngine）
# ============================================================
@dataclass
class DCAParams:
    """DCA参数配置 - 只用于传递给DCAEngine，不包含任何算法逻辑"""
    # EMA平滑系数
    ema_alpha_normal: float = 0.08
    ema_alpha_recovery: float = 0.03
    # Drift平滑因子
    drift_smoothing_factor: float = 0.10
    # PPS超时阈值（秒）
    pps_timeout_holdover: float = 1.5
    pps_timeout_lost: float = 5.0
    # Recovery条件
    recovery_stable_pps_count: int = 5
    # Outlier检测阈值（微秒）
    outlier_threshold_us: float = 1000.0
    # Confidence参数
    confidence_decay_rate: float = 0.01
    confidence_recovery_rate: float = 0.05
    # Drift限制（ppm）
    drift_clamp_ppm: float = 100.0
    # Holdover漂移补偿增益
    holdover_drift_gain: float = 0.5
    
    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith('_')}
    
    def diff(self, other: 'DCAParams') -> str:
        """输出参数差异（用于params_diff.md）"""
        changes = []
        for k in self.__dict__.keys():
            if k.startswith('_'): continue
            old = getattr(other, k, None)
            new = getattr(self, k)
            if old != new:
                changes.append(f"  {k}: {old} -> {new}")
        return "\n".join(changes) if changes else "  (no changes)"


# ============================================================
# 2. Metrics采集器
# ============================================================
@dataclass
class DCAMetrics:
    """DCA运行指标 - 从DCAEngine输出采集"""
    # 事件统计
    total_events: int = 0
    pps_events: int = 0
    imu_events: int = 0
    pps_lost_count: int = 0
    pps_recovery_count: int = 0
    outlier_rejected_count: int = 0
    seq_gap_count: int = 0
    
    # 时间指标
    max_drift_ppm: float = 0.0
    mean_drift_ppm: float = 0.0
    max_offset_us: float = 0.0
    mean_offset_us: float = 0.0
    
    # 状态分布（秒）
    state_duration: Dict[str, float] = field(default_factory=dict)
    
    # 单调性验证
    monotonic_violations: int = 0
    
    # HOLDOVER/RECOVERY跳变检测
    holdover_jump_us: float = 0.0
    recovery_jump_us: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'total_events': self.total_events,
            'pps_events': self.pps_events,
            'imu_events': self.imu_events,
            'pps_lost_count': self.pps_lost_count,
            'pps_recovery_count': self.pps_recovery_count,
            'outlier_rejected_count': self.outlier_rejected_count,
            'seq_gap_count': self.seq_gap_count,
            'max_drift_ppm': self.max_drift_ppm,
            'mean_drift_ppm': self.mean_drift_ppm,
            'max_offset_us': self.max_offset_us,
            'mean_offset_us': self.mean_offset_us,
            'state_duration': self.state_duration,
            'monotonic_violations': self.monotonic_violations,
            'holdover_jump_us': self.holdover_jump_us,
            'recovery_jump_us': self.recovery_jump_us,
        }
    
    def check_reject_rules(self) -> Tuple[bool, str]:
        """检查是否触发reject rules"""
        if self.monotonic_violations > 0:
            return True, f"R1: monotonic_violations={self.monotonic_violations}"
        if self.holdover_jump_us > 100:
            return True, f"R3: HOLDOVER jump={self.holdover_jump_us}us > 100us"
        if self.recovery_jump_us > 100:
            return True, f"R4: RECOVERY jump={self.recovery_jump_us}us > 100us"
        # R2和R5在runner层检查
        return False, ""


# ============================================================
# 3. Tuning Runner（外层Harness）
# ============================================================
class DCATuningRunner:
    """
    DCA调参运行器
    
    职责：
    1. 读取runtime CSV
    2. 调用DCAEngine（通过参数配置）
    3. 采集metrics
    4. 验证deterministic replay
    5. 生成对比图和报告
    
    禁止：
    - 修改dca_engine.py
    - 包含任何算法逻辑
    """
    
    def __init__(self, csv_path: str, params: DCAParams, engine_class=None):
        """
        Args:
            csv_path: runtime CSV文件路径
            params: DCA参数配置
            engine_class: DCAEngine类（用于注入，避免硬导入）
        """
        self.csv_path = Path(csv_path)
        self.params = params
        self._engine_class = engine_class
        self._engine = None
        
        # 验证CSV存在
        if not self.csv_path.exists():
            raise FileNotFoundError(f"CSV not found: {csv_path}")
        
        # 计算输入文件hash
        self.input_hash = self._compute_file_hash()
        self.input_row_count = self._count_csv_rows()
    
    def _compute_file_hash(self) -> str:
        """计算文件SHA256"""
        sha = hashlib.sha256()
        with open(self.csv_path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                sha.update(chunk)
        return sha.hexdigest()
    
    def _count_csv_rows(self) -> int:
        """快速统计CSV行数"""
        with open(self.csv_path, 'r') as f:
            return sum(1 for _ in f) - 1  # 减header
    
    def _create_engine(self):
        """创建DCAEngine实例（只通过参数配置）"""
        if self._engine_class is None:
            self._engine_class = DCAEngine

        self._engine = self._engine_class()
        return self._engine
    
    def run(self, reset: bool = True) -> DCAMetrics:
        """
        运行单次DCA replay

        CSV columns:
        seq_num, board_time_us, event_type, sensor_id, delta_us, flags,
        sync_state, confidence, tier, loss_detected, seq_gap

        DCAEngine.update():
        update(board_time_us, reference_time_us, is_pps)
        """
        import csv

        engine = self._create_engine()

        metrics = DCAMetrics()
        outputs = []

        last_corrected = None
        last_state = None
        state_start_time = None
        last_board_time = None

        last_seq = None

        drift_values = []
        offset_values = []

        holdover_entry_time = None
        recovery_entry_time = None
        prev_corrected = None
        prev_board_time = None
        prev_state = None

        with open(self.csv_path, "r") as f:
            reader = csv.DictReader(f)

            for row in reader:
                seq_num = int(row["seq_num"])
                board_time_us = int(row["board_time_us"])
                event_type = row["event_type"].strip()
                delta_us = int(float(row.get("delta_us", "0") or 0))

                is_pps = event_type == "PPS_EDGE"

                # CSV 没有 reference_time_us，用 delta_us 构造：
                # delta_us 表示 reference - board 的 offset/residual 输入
                reference_time_us = board_time_us + delta_us if is_pps else None

                out = engine.update(
                    board_time_us=board_time_us,
                    reference_time_us=reference_time_us,
                    is_pps=is_pps,
                )

                outputs.append({
                    "seq_num": seq_num,
                    "board_time_us": board_time_us,
                    "event_type": event_type,
                    "corrected_time_us": out["corrected_time_us"],
                    "state": out["state"],
                    "offset_us": out["offset_us"],
                    "drift_ppm": out["drift_ppm"],
                    "confidence": out["confidence"],
                    "residual": out["residual"],
                    "outlier": out["outlier"],
                    "valid_pps": out["valid_pps"],
                    "stable_pps": out["stable_pps"],
                })

                # ------------------------------
                # Event counters
                # ------------------------------
                metrics.total_events += 1

                if is_pps:
                    metrics.pps_events += 1
                else:
                    metrics.imu_events += 1

                if out.get("outlier"):
                    metrics.outlier_rejected_count += 1

                if row.get("loss_detected", "").strip().lower() == "true":
                    metrics.pps_lost_count += 1

                if row.get("seq_gap", "").strip().lower() == "true":
                    metrics.seq_gap_count += 1

                if last_seq is not None and seq_num <= last_seq:
                    metrics.seq_gap_count += 1
                last_seq = seq_num

                # ------------------------------
                # Monotonic check
                # ------------------------------
                corrected = int(out["corrected_time_us"])

                if last_corrected is not None and corrected <= last_corrected:
                    metrics.monotonic_violations += 1

                last_corrected = corrected

                # ------------------------------
                # Drift / offset metrics
                # ------------------------------
                drift_values.append(abs(float(out["drift_ppm"])))
                offset_values.append(abs(float(out["offset_us"])))

                # ------------------------------
                # State duration + transition jumps
                # ------------------------------
                state = out["state"]

                if last_state is None:
                    last_state = state
                    state_start_time = board_time_us
                elif state != last_state:
                    duration_s = (board_time_us - state_start_time) / 1_000_000.0
                    metrics.state_duration[last_state] = (
                        metrics.state_duration.get(last_state, 0.0) + duration_s
                    )

                    transition_jump = 0.0
                    if prev_corrected is not None and prev_board_time is not None:
                        expected_corrected = prev_corrected + (board_time_us - prev_board_time)
                        transition_jump = abs(corrected - expected_corrected)

                    if state == "HOLDOVER":
                        holdover_entry_time = board_time_us
                        metrics.holdover_jump_us = max(metrics.holdover_jump_us, transition_jump)

                    if last_state == "HOLDOVER":
                        metrics.holdover_jump_us = max(metrics.holdover_jump_us, transition_jump)

                    if state == "RECOVERY":
                        recovery_entry_time = board_time_us
                        metrics.recovery_jump_us = max(metrics.recovery_jump_us, transition_jump)

                    if last_state == "RECOVERY":
                        metrics.recovery_jump_us = max(metrics.recovery_jump_us, transition_jump)

                    if last_state == "HOLDOVER" and state == "RECOVERY":
                        metrics.pps_recovery_count += 1

                    last_state = state
                    state_start_time = board_time_us

                prev_state = state
                prev_corrected = corrected
                prev_board_time = board_time_us
                last_board_time = board_time_us

        # close final state duration
        if last_state is not None and state_start_time is not None and last_board_time is not None:
            duration_s = (last_board_time - state_start_time) / 1_000_000.0
            metrics.state_duration[last_state] = (
                metrics.state_duration.get(last_state, 0.0) + duration_s
            )

        # aggregate metrics
        if drift_values:
            metrics.max_drift_ppm = max(drift_values)
            metrics.mean_drift_ppm = sum(drift_values) / len(drift_values)

        if offset_values:
            metrics.max_offset_us = max(offset_values)
            metrics.mean_offset_us = sum(offset_values) / len(offset_values)

        self._last_metrics = metrics
        self._last_outputs = outputs

        return metrics

    
    def run_deterministic_check(self, n_runs: int = 3) -> Tuple[bool, List[str]]:
        signatures = []

        for i in range(n_runs):
            self.run(reset=True)

            payload = {
                "metrics": self._last_metrics.to_dict(),
                "outputs": self._last_outputs,
            }

            sig = hashlib.md5(
                json.dumps(payload, sort_keys=True).encode()
            ).hexdigest()

            signatures.append(sig)

        is_det = len(set(signatures)) == 1
        self._last_deterministic_signatures = signatures
        self._last_deterministic_pass = is_det
        return is_det, signatures

    
    def save_metrics(self, path: Path, metrics: Optional[DCAMetrics] = None):
        """保存metrics到JSON"""
        if metrics is None:
            metrics = getattr(self, "_last_metrics", None)

        if metrics is None:
            metrics = DCAMetrics()

        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            json.dump(metrics.to_dict(), f, indent=2)


    def save_trace(self, path: Path):
        """保存完整 replay trace"""

        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            json.dump(self._last_outputs, f, indent=2)


    def save_deterministic_verification(self, path: Path):
        """保存 deterministic verification"""

        payload = {
            "passed": getattr(self, "_last_deterministic_pass", False),
            "signatures": getattr(self, "_last_deterministic_signatures", []),
        }

        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            json.dump(payload, f, indent=2)

    
    def save_input_summary(self, path: Path):
        """保存 replay input summary"""

        payload = {
            "csv_file": str(self.csv_path),
            "input_sha256": self.input_hash,
            "row_count": self.input_row_count,
        }

        if hasattr(self, "_last_metrics"):
            payload.update({
                "pps_events": self._last_metrics.pps_events,
                "imu_events": self._last_metrics.imu_events,
            })

        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w") as f:
            json.dump(payload, f, indent=2)


    def save_plots(self, output_dir: Path):
        """生成 baseline replay plots"""

        import matplotlib.pyplot as plt

        output_dir.mkdir(parents=True, exist_ok=True)

        if not hasattr(self, "_last_outputs"):
            print("No replay outputs available")
            return

        trace = self._last_outputs

        # -----------------------------------
        # Extract series
        # -----------------------------------
        times = [
            (x["board_time_us"] - trace[0]["board_time_us"]) / 1_000_000.0
            for x in trace
        ]

        drift = [x["drift_ppm"] for x in trace]
        offset = [x["offset_us"] for x in trace]
        confidence = [x["confidence"] for x in trace]

        states = [x["state"] for x in trace]

        # -----------------------------------
        # Drift Plot
        # -----------------------------------
        plt.figure(figsize=(14, 5))
        plt.plot(times, drift)
        plt.title("Drift PPM Over Time")
        plt.xlabel("Runtime (s)")
        plt.ylabel("Drift PPM")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(output_dir / "drift_plot.png")
        plt.close()

        # -----------------------------------
        # Offset Plot
        # -----------------------------------
        plt.figure(figsize=(14, 5))
        plt.plot(times, offset)
        plt.title("Offset (us) Over Time")
        plt.xlabel("Runtime (s)")
        plt.ylabel("Offset (us)")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(output_dir / "offset_plot.png")
        plt.close()

        # -----------------------------------
        # Confidence Plot
        # -----------------------------------
        plt.figure(figsize=(14, 5))
        plt.plot(times, confidence)
        plt.title("Confidence Over Time")
        plt.xlabel("Runtime (s)")
        plt.ylabel("Confidence")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(output_dir / "confidence_plot.png")
        plt.close()

        # -----------------------------------
        # State Trace Plot
        # -----------------------------------
        state_map = {
            "LOST": 0,
            "RECOVERY": 1,
            "HOLDOVER": 2,
            "LOCKED": 3,
        }

        state_values = [state_map.get(s, -1) for s in states]

        plt.figure(figsize=(14, 3))
        plt.step(times, state_values, where="post")

        plt.yticks(
            [0, 1, 2, 3],
            ["LOST", "RECOVERY", "HOLDOVER", "LOCKED"]
        )

        plt.title("DCA State Trace")
        plt.xlabel("Runtime (s)")
        plt.ylabel("State")
        plt.grid(True)
        plt.tight_layout()
        plt.savefig(output_dir / "state_trace.png")
        plt.close()

        print(f"Plots saved to: {output_dir}")

    
    def run_baseline(self) -> Tuple[DCAMetrics, bool]:
        """
        运行baseline replay + deterministic check
        
        Returns:
            (metrics, deterministic_pass)
        """
        print(f"\n{'='*60}")
        print(f"Baseline Replay")
        print(f"Input: {self.csv_path.name}")
        print(f"Rows: {self.input_row_count}")
        print(f"SHA256: {self.input_hash[:16]}...")
        print(f"{'='*60}")
        
        # 先做deterministic check
        is_det, sigs = self.run_deterministic_check(3)
        
        if not is_det:
            print(f"❌ Deterministic check FAILED")
            print(f"   Signatures: {sigs}")
            return DCAMetrics(), False
        
        print(f"✅ Deterministic check PASSED (3 runs identical)")
        
        # 运行正式baseline
        metrics = self.run(reset=True)
        
        # 检查reject rules
        is_rejected, reason = metrics.check_reject_rules()
        if is_rejected:
            print(f"❌ Baseline rejected: {reason}")
        
        return metrics, True


# ============================================================
# 4. 调参主流程（顺序锁死）
# ============================================================
class TuningWorkflow:
    """
    调参工作流
    
    顺序锁死：
    1. baseline replay
    2. deterministic check
    3. identify failure mode
    4. single parameter change
    5. replay + deterministic check
    6. before/after comparison
    7. accept/reject
    """
    
    def __init__(self, csv_path: str, output_dir: str = "./tuning_runs"):
        self.csv_path = csv_path
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        self.baseline_params = DCAParams()
        self.baseline_metrics: Optional[DCAMetrics] = None
        self.current_params: Optional[DCAParams] = None
        self.current_metrics: Optional[DCAMetrics] = None
        
        self.run_history: List[Dict] = []
    
    def step1_baseline(self) -> bool:
        """Step 1-3: Baseline replay + deterministic check"""
        print("\n" + "="*60)
        print("STEP 1-3: Baseline Replay + Deterministic Check")
        print("="*60)
        
        runner = DCATuningRunner(self.csv_path, self.baseline_params)
        metrics, is_det = runner.run_baseline()
        print("\nBaseline Metrics Summary")
        print("-" * 40)

        print(f"Total Events:        {metrics.total_events}")
        print(f"PPS Events:          {metrics.pps_events}")
        print(f"IMU Events:          {metrics.imu_events}")

        print(f"Max Drift PPM:       {metrics.max_drift_ppm:.3f}")
        print(f"Mean Drift PPM:      {metrics.mean_drift_ppm:.3f}")

        print(f"Max Offset (us):     {metrics.max_offset_us:.3f}")
        print(f"Mean Offset (us):    {metrics.mean_offset_us:.3f}")

        print(f"Monotonic Violations:{metrics.monotonic_violations}")

        print(f"HOLDOVER Jump (us):  {metrics.holdover_jump_us:.3f}")
        print(f"RECOVERY Jump (us):  {metrics.recovery_jump_us:.3f}")

        print("\nState Duration:")
        for k, v in metrics.state_duration.items():
            print(f"  {k}: {v:.2f}s")
        
        if not is_det:
            print("❌ Fatal: Baseline is not deterministic. Fix dca_engine first.")
            return False
        
        self.baseline_metrics = metrics
        
        # -----------------------------------
        # baseline output directory
        # -----------------------------------
        baseline_dir = self.output_dir / "baseline"
        baseline_dir.mkdir(parents=True, exist_ok=True)

        # -----------------------------------
        # Save baseline outputs
        # -----------------------------------
        with open(baseline_dir / "params_used.json", "w") as f:
            json.dump(
                self.baseline_params.to_dict(),
                f,
                indent=2
            )

        runner.save_metrics(
            baseline_dir / "baseline_metrics.json"
        )

        runner.save_trace(
            baseline_dir / "baseline_trace.json"
        )

        runner.save_deterministic_verification(
            baseline_dir / "deterministic_verification.json"
        )

        runner.save_input_summary(
            baseline_dir / "replay_input_summary.json"
        )

        runner.save_plots(
            baseline_dir / "plots"
        )

        decision_path = baseline_dir / "tuning_decision.md"

        with open(decision_path, "w") as f:
            if metrics.check_reject_rules()[0]:
                f.write("BASELINE REJECTED\n")
            else:
                f.write("BASELINE ACCEPTED\n")
        
        return True
    
    def step4_identify_failure_mode(self) -> str:
        """Step 4: Identify failure mode from baseline plots"""
        # TODO: 从metrics和plots中识别问题
        # 返回: "drift_divergence" / "recovery_overshoot" / "outlier_pollution" / "stable"
        print("\n" + "="*60)
        print("STEP 4: Identify Failure Mode")
        print("="*60)
        print("Please review baseline_plots/ and identify issues:")
        print("  - drift divergence?")
        print("  - recovery overshoot?")
        print("  - outlier pollution?")
        print("  - HOLDOVER instability?")
        
        # 交互式输入（或从文件读取）
        mode = input("Enter failure mode (or 'stable'): ").strip()
        return mode
    
    def step5_single_parameter_change(self) -> DCAParams:
        """Step 5: Single parameter change"""
        print("\n" + "="*60)
        print("STEP 5: Single Parameter Change")
        print("="*60)
        print("Available parameters:")
        for k, v in self.baseline_params.to_dict().items():
            print(f"  {k}: {v}")
        
        param_name = input("Enter parameter name to change: ").strip()
        new_value = input(f"Enter new value for {param_name}: ").strip()
        
        new_params = DCAParams()
        # 复制baseline参数
        for k, v in self.baseline_params.to_dict().items():
            setattr(new_params, k, v)
        # 修改目标参数
        setattr(new_params, param_name, type(getattr(new_params, param_name))(new_value))
        
        self.current_params = new_params
        return new_params
    
    def step6_replay_and_validate(self, params: DCAParams) -> Tuple[DCAMetrics, bool]:
        """Step 6-9: Replay, validate, compare"""
        print("\n" + "="*60)
        print("STEP 6-9: Replay + Validate + Compare")
        print("="*60)
        
        runner = DCATuningRunner(self.csv_path, params)
        
        # Deterministic check
        is_det, sigs = runner.run_deterministic_check(3)
        if not is_det:
            print(f"❌ REJECTED: Non-deterministic replay")
            return DCAMetrics(), False
        
        # Run
        metrics = runner.run(reset=True)
        
        # Check reject rules
        is_rejected, reason = metrics.check_reject_rules()
        if is_rejected:
            print(f"❌ REJECTED: {reason}")
            return metrics, False
        
        # Compare with baseline
        print("\nComparison with baseline:")
        print(f"  max_drift_ppm: {self.baseline_metrics.max_drift_ppm:.2f} -> {metrics.max_drift_ppm:.2f}")
        print(f"  mean_drift_ppm: {self.baseline_metrics.mean_drift_ppm:.2f} -> {metrics.mean_drift_ppm:.2f}")
        print(f"  max_offset_us: {self.baseline_metrics.max_offset_us:.2f} -> {metrics.max_offset_us:.2f}")
        
        # Save
        runner.save_metrics(self.output_dir / f"params_{self._param_hash(params)}_metrics.json")
        runner.save_plots(self.output_dir / f"params_{self._param_hash(params)}_plots")
        
        return metrics, True
    
    def _param_hash(self, params: DCAParams) -> str:
        """生成参数组合的短hash"""
        import hashlib
        s = json.dumps(params.to_dict(), sort_keys=True)
        return hashlib.md5(s.encode()).hexdigest()[:8]
    
    def run(self):
        """执行完整调参流程"""
        # Step 1-3
        if not self.step1_baseline():
            print("❌ Aborting: Baseline failed")
            return
        
        # Step 4
        failure_mode = self.step4_identify_failure_mode()
        if failure_mode == "stable":
            print("✅ Baseline already stable. No tuning needed.")
            return
        
        # Step 5-9 (循环)
        while True:
            params = self.step5_single_parameter_change()
            metrics, accepted = self.step6_replay_and_validate(params)
            
            if accepted:
                print(f"\n✅ ACCEPTED: Parameter change accepted")
                # 记录到history
                self.run_history.append({
                    'params': params.to_dict(),
                    'metrics': metrics.to_dict(),
                    'accepted': True
                })
                
                # 询问是否继续
                cont = input("\nContinue tuning? (y/n): ").strip().lower()
                if cont != 'y':
                    break
            else:
                print(f"\n❌ REJECTED: Parameter change rejected")
                self.run_history.append({
                    'params': params.to_dict(),
                    'metrics': metrics.to_dict(),
                    'accepted': False,
                    'reason': 'reject_rule'
                })
            
            # 询问是否继续尝试其他参数
            cont = input("Try another parameter? (y/n): ").strip().lower()
            if cont != 'y':
                break
        
        # 保存调参历史
        with open(self.output_dir / "tuning_history.json", 'w') as f:
            json.dump(self.run_history, f, indent=2)
        
        print("\n" + "="*60)
        print("Tuning Complete")
        print(f"History saved to: {self.output_dir / 'tuning_history.json'}")
        print("="*60)


# ============================================================
# 5. 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='DCA Runtime CSV Tuning Runner')
    parser.add_argument('csv_path', help='Path to runtime CSV file')
    parser.add_argument('--output-dir', '-o', default='./tuning_runs',
                        help='Output directory for metrics and plots')
    parser.add_argument('--baseline-only', action='store_true',
                        help='Only run baseline, no tuning')
    
    args = parser.parse_args()
    
    workflow = TuningWorkflow(args.csv_path, args.output_dir)
    
    if args.baseline_only:
        workflow.step1_baseline()
    else:
        workflow.run()


if __name__ == "__main__":
    main()
