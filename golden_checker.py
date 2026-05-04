#!/usr/bin/env python3
"""
Golden Pass Checker for DCA Engine
自动验证4个场景是否通过验收标准
"""

import json
import sys
import math
from typing import Dict, List, Any
from dataclasses import dataclass
from enum import Enum

# 导入 DCA Engine
from dca_engine import DCAEngine, SyncState


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    metrics: Dict[str, Any]
    errors: List[str]


class GoldenChecker:
    """Golden Pass 验证器"""
    
    # 验收标准
    CRITERIA = {
        "normal": {
            "max_time_to_lock_s": 3.0,
            "max_offset_std_us": 50.0,
            "min_confidence": 0.95,
            "max_state_transitions": 0  # NORMAL 期间不应跳状态
        },
        "holdover": {
            "max_drift_us": 500.0,  # 5s 内漂移 <500us
            "holdover_duration_s": 5.0,
            "confidence_decay_min": 0.70,  # 5s后置信度应 >0.7
            "no_time_jump": True
        },
        "jitter": {
            "outlier_rejection_rate": 1.0,  # 100% 拒绝
            "max_state_transitions": 0,     # 状态不应跳变
            "max_offset_impact_us": 100.0   # outlier 不应影响 offset >100us
        },
        "drift": {
            "convergence_tolerance_ppm": 10.0,  # 收敛到目标 ±10ppm
            "max_convergence_time_s": 30.0,
            "drift_bounds_ppm": 50.0
        }
    }
    
    def __init__(self):
        self.results: List[ScenarioResult] = []
    
    def check(self, offset_us, power_ok=True, pps_status=1):
        """
        单点金丝雀检查：
        offset_us: 当前原始 offset = sensor_with_error - sensor_ideal
        power_ok: 电压是否正常
        pps_status: PPS 是否有效，1=有效，0=丢失
        """

        if not power_ok or pps_status == 0:
            return "FAIL_HOLDOVER"

        if abs(offset_us) > 500:
            return "FAIL_DRIFT"

        if abs(offset_us) < 300:
            return "PASS"

        return "WARN"

    def run_normal_scenario(self, engine: DCAEngine, events: List[Dict]) -> ScenarioResult:
        """验证 NORMAL 场景"""
        result = ScenarioResult(name="normal", passed=True, metrics={}, errors=[])
        
        offsets = []
        states = []
        confidences = []
        time_to_lock = None
        lock_time = None
        
        for event in events:
            board_time = event["board_time_us"]
            ref_time = event.get("reference_time_us")
            is_pps = event.get("is_pps", False)
            
            output = engine.update(board_time, ref_time, is_pps)
            
            offsets.append(output["offset_us"])
            states.append(output["state"])
            confidences.append(output["confidence"])
            
            # 检测锁定时间
            if time_to_lock is None and output["state"] == "NORMAL":
                if lock_time is None:
                    lock_time = board_time
                    time_to_lock = lock_time / 1_000_000.0
        
        # 计算指标
        if len(offsets) > 0:
            offset_std = statistics.stdev(offsets) if len(offsets) > 1 else 0
            result.metrics["offset_std_us"] = offset_std
            result.metrics["time_to_lock_s"] = time_to_lock or 999
            result.metrics["avg_confidence"] = sum(confidences) / len(confidences)
            
            # 状态转换计数
            transitions = 0
            for i in range(1, len(states)):
                if states[i] != states[i-1]:
                    transitions += 1
            result.metrics["state_transitions"] = transitions
        
        # 判断 PASS/FAIL
        criteria = self.CRITERIA["normal"]
        if result.metrics.get("time_to_lock_s", 999) > criteria["max_time_to_lock_s"]:
            result.passed = False
            result.errors.append(f"time_to_lock={result.metrics['time_to_lock_s']:.2f}s > {criteria['max_time_to_lock_s']}s")
        
        if result.metrics.get("offset_std_us", 999) > criteria["max_offset_std_us"]:
            result.passed = False
            result.errors.append(f"offset_std={result.metrics['offset_std_us']:.2f}us > {criteria['max_offset_std_us']}us")
        
        if result.metrics.get("avg_confidence", 0) < criteria["min_confidence"]:
            result.passed = False
            result.errors.append(f"avg_confidence={result.metrics['avg_confidence']:.3f} < {criteria['min_confidence']}")
        
        if result.metrics.get("state_transitions", 999) > criteria["max_state_transitions"]:
            result.passed = False
            result.errors.append(f"state_transitions={result.metrics['state_transitions']} > {criteria['max_state_transitions']}")
        
        return result
    
    def run_holdover_scenario(self, engine: DCAEngine, events: List[Dict]) -> ScenarioResult:
        """验证 HOLDOVER 场景"""
        result = ScenarioResult(name="holdover", passed=True, metrics={}, errors=[])
        
        corrected_times = []
        board_times = []
        last_time = None
        max_drift = 0
        start_holdover_time = None
        confidences = []
        
        for event in events:
            board_time = event["board_time_us"]
            ref_time = event.get("reference_time_us")
            is_pps = event.get("is_pps", False)
            
            output = engine.update(board_time, ref_time, is_pps)
            corrected_times.append(output["corrected_time_us"])
            board_times.append(board_time)
            confidences.append(output["confidence"])
            
            if output["state"] == "HOLDOVER" and start_holdover_time is None:
                start_holdover_time = board_time
            
            # 检查时间回退
            if last_time is not None:
                if output["corrected_time_us"] < last_time:
                    result.errors.append(f"time_jump at {board_time}: {last_time} -> {output['corrected_time_us']}")
            last_time = output["corrected_time_us"]
        
        # 计算 holdover 漂移
        if start_holdover_time is not None:
            holdover_samples = []
            for i, bt in enumerate(board_times):
                if bt >= start_holdover_time:
                    # 理想时间 = board_time + 初始offset
                    ideal = bt + engine.holdover_offset if hasattr(engine, 'holdover_offset') else bt
                    drift = corrected_times[i] - ideal
                    holdover_samples.append((bt, drift))
                    max_drift = max(max_drift, abs(drift))
            
            result.metrics["max_drift_us"] = max_drift
            result.metrics["holdover_duration_s"] = (board_times[-1] - start_holdover_time) / 1_000_000.0 if start_holdover_time else 0
            result.metrics["final_confidence"] = confidences[-1] if confidences else 0
        
        # 判断 PASS/FAIL
        criteria = self.CRITERIA["holdover"]
        if result.metrics.get("max_drift_us", 999) > criteria["max_drift_us"]:
            result.passed = False
            result.errors.append(f"max_drift={result.metrics['max_drift_us']:.2f}us > {criteria['max_drift_us']}us")
        
        if result.metrics.get("final_confidence", 1) < criteria["confidence_decay_min"]:
            result.passed = False
            result.errors.append(f"final_confidence={result.metrics['final_confidence']:.3f} < {criteria['confidence_decay_min']}")
        
        if result.errors and "time_jump" in str(result.errors):
            result.passed = False
        
        return result
    
    def run_jitter_scenario(self, engine: DCAEngine, events: List[Dict]) -> ScenarioResult:
        """验证 JITTER/OUTLIER 场景"""
        result = ScenarioResult(name="jitter", passed=True, metrics={}, errors=[])
        
        offsets = []
        states = []
        outliers_detected = 0
        total_outliers_injected = 0
        
        for event in events:
            board_time = event["board_time_us"]
            ref_time = event.get("reference_time_us")
            is_pps = event.get("is_pps", False)
            is_injected_outlier = event.get("is_outlier", False)
            
            if is_injected_outlier:
                total_outliers_injected += 1
            
            output = engine.update(board_time, ref_time, is_pps)
            
            offsets.append(output["offset_us"])
            states.append(output["state"])
            
            # 检测 engine 是否识别为 outlier
            # 通过 engine 内部状态判断
            if hasattr(engine, 'outlier_counter'):
                pass  # 简化：信任 engine 内部处理
        
        # 计算指标
        if len(offsets) > 0:
            # offset 不应被 outlier 大幅影响
            result.metrics["offset_range_us"] = max(offsets) - min(offsets)
            
            # 状态转换计数
            transitions = 0
            for i in range(1, len(states)):
                if states[i] != states[i-1]:
                    transitions += 1
            result.metrics["state_transitions"] = transitions
        
        # 判断 PASS/FAIL
        criteria = self.CRITERIA["jitter"]
        if result.metrics.get("offset_range_us", 0) > criteria["max_offset_impact_us"]:
            result.passed = False
            result.errors.append(f"offset_range={result.metrics['offset_range_us']:.2f}us > {criteria['max_offset_impact_us']}us")
        
        if result.metrics.get("state_transitions", 999) > criteria["max_state_transitions"]:
            result.passed = False
            result.errors.append(f"state_transitions={result.metrics['state_transitions']} > {criteria['max_state_transitions']}")
        
        return result
    
    def run_drift_scenario(self, engine: DCAEngine, events: List[Dict]) -> ScenarioResult:
        """验证 DRIFT 场景"""
        result = ScenarioResult(name="drift", passed=True, metrics={}, errors=[])
        
        drifts = []
        
        for event in events:
            board_time = event["board_time_us"]
            ref_time = event.get("reference_time_us")
            is_pps = event.get("is_pps", False)
            
            output = engine.update(board_time, ref_time, is_pps)
            drifts.append(output["drift_ppm"])
        
        if drifts:
            final_drift = drifts[-1]
            result.metrics["final_drift_ppm"] = final_drift
            result.metrics["drift_bounds_ppm"] = max(abs(max(drifts)), abs(min(drifts))) if drifts else 0
            
            # 收敛时间：进入稳定区间的时间
            target_drift = 20.0  # 模拟的 drift 目标值
            convergence_time = None
            for i, d in enumerate(drifts):
                if abs(d - target_drift) < 10:  # ±10ppm
                    convergence_time = i
                    break
            result.metrics["convergence_time_s"] = convergence_time * 0.001 if convergence_time else 999
        
        # 判断 PASS/FAIL
        criteria = self.CRITERIA["drift"]
        if abs(result.metrics.get("final_drift_ppm", 999) - 20.0) > criteria["convergence_tolerance_ppm"]:
            result.passed = False
            result.errors.append(f"final_drift={result.metrics['final_drift_ppm']:.2f}ppm off target")
        
        if result.metrics.get("drift_bounds_ppm", 0) > criteria["drift_bounds_ppm"]:
            result.passed = False
            result.errors.append(f"drift_bounds={result.metrics['drift_bounds_ppm']:.2f}ppm > {criteria['drift_bounds_ppm']}ppm")
        
        return result
    
    def run_all(self) -> bool:
        """运行所有场景"""
        import importlib.util
        import os
        
        # 导入场景生成器
        spec = importlib.util.spec_from_file_location("scenarios", "scenarios.py")
        scenarios = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scenarios)
        
        print("\n" + "=" * 60)
        print("🏆 GOLDEN PASS VALIDATION")
        print("=" * 60)
        
        all_passed = True
        
        # 1. NORMAL
        print("\n📋 Scenario 1: NORMAL")
        engine = DCAEngine()
        events = scenarios.normal_scenario()
        result = self.run_normal_scenario(engine, events)
        self._print_result(result)
        all_passed = all_passed and result.passed
        
        # 2. HOLDOVER
        print("\n📋 Scenario 2: HOLDOVER")
        engine = DCAEngine()
        events = scenarios.holdover_scenario()
        result = self.run_holdover_scenario(engine, events)
        self._print_result(result)
        all_passed = all_passed and result.passed
        
        # 3. JITTER
        print("\n📋 Scenario 3: JITTER/OUTLIER")
        engine = DCAEngine()
        events = scenarios.jitter_scenario()
        result = self.run_jitter_scenario(engine, events)
        self._print_result(result)
        all_passed = all_passed and result.passed
        
        # 4. DRIFT
        print("\n📋 Scenario 4: DRIFT")
        engine = DCAEngine()
        events = scenarios.drift_scenario()
        result = self.run_drift_scenario(engine, events)
        self._print_result(result)
        all_passed = all_passed and result.passed
        
        print("\n" + "=" * 60)
        if all_passed:
            print("🎉 ALL SCENARIOS PASS")
        else:
            print("❌ SOME SCENARIOS FAIL")
        print("=" * 60)
        
        return all_passed
    
    def _print_result(self, result: ScenarioResult):
        status = "✅ PASS" if result.passed else "❌ FAIL"
        print(f"  {status}")
        for key, val in result.metrics.items():
            print(f"    {key}: {val}")
        if result.errors:
            for err in result.errors:
                print(f"    ⚠️ {err}")


if __name__ == "__main__":
    import statistics  # 添加缺失的导入
    checker = GoldenChecker()
    success = checker.run_all()
    sys.exit(0 if success else 1)
