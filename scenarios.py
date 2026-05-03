#!/usr/bin/env python3
"""
4 Scenarios Mock Data Generator
生成 normal / holdover / jitter / drift 四个场景的测试数据
"""

import random
import math


def normal_scenario(duration_s=30, pps_rate_hz=1):
    """NORMAL 场景：稳定 PPS，微小噪声"""
    events = []
    t = 0
    offset_true = 50.0  # 固定 offset 50us
    drift_true = 0.0
    
    for i in range(int(duration_s * pps_rate_hz)):
        t += int(1_000_000 / pps_rate_hz)  # 1e6 us
        
        # 微小噪声 ±10us
        noise = random.uniform(-10, 10)
        ref_time = t + offset_true + drift_true * t / 1_000_000 + noise
        
        events.append({
            "board_time_us": t,
            "reference_time_us": int(ref_time),
            "is_pps": True,
            "is_outlier": False
        })
    
    return events


def holdover_scenario(normal_duration_s=10, holdover_duration_s=5):
    """HOLDOVER 场景：正常 -> PPS丢失 -> holdover -> 恢复"""
    events = []
    t = 0
    offset_true = 50.0
    drift_true = 20.0  # 20ppm 漂移
    
    # Phase 1: NORMAL (10s)
    for i in range(int(normal_duration_s)):
        t += 1_000_000
        ref_time = t + offset_true + drift_true * t / 1_000_000
        events.append({
            "board_time_us": t,
            "reference_time_us": int(ref_time),
            "is_pps": True,
            "is_outlier": False
        })
    
    # Phase 2: HOLDOVER (5s, 无 PPS)
    holdover_start = t
    for i in range(int(holdover_duration_s)):
        t += 1_000_000
        events.append({
            "board_time_us": t,
            "reference_time_us": None,  # 无参考时间
            "is_pps": False,
            "is_outlier": False
        })
    
    # Phase 3: 恢复 (连续3个PPS)
    for i in range(3):
        t += 1_000_000
        ref_time = t + offset_true + drift_true * t / 1_000_000
        events.append({
            "board_time_us": t,
            "reference_time_us": int(ref_time),
            "is_pps": True,
            "is_outlier": False
        })
    
    return events


def jitter_scenario(duration_s=20, outlier_rate=0.2):
    """JITTER/OUTLIER 场景：周期性 outlier 注入"""
    events = []
    t = 0
    offset_true = 50.0
    drift_true = 0.0
    
    for i in range(int(duration_s)):
        t += 1_000_000
        
        is_outlier = random.random() < outlier_rate
        
        if is_outlier:
            # 注入 outlier: ±500us 跳变
            outlier_jump = random.choice([-500, -400, 400, 500])
            ref_time = t + offset_true + outlier_jump
        else:
            noise = random.uniform(-20, 20)
            ref_time = t + offset_true + noise
        
        events.append({
            "board_time_us": t,
            "reference_time_us": int(ref_time),
            "is_pps": True,
            "is_outlier": is_outlier
        })
    
    return events


def drift_scenario(duration_s=60, drift_ppm_target=20.0):
    """DRIFT 场景：模拟晶振频率漂移"""
    events = []
    t = 0
    offset_true = 50.0
    
    for i in range(int(duration_s)):
        t += 1_000_000
        
        # 随时间增加的 drift
        current_drift = drift_ppm_target * (t / (duration_s * 1_000_000))
        
        # offset 累积 drift
        offset_at_t = offset_true + (current_drift * t / 1_000_000)
        
        noise = random.uniform(-10, 10)
        ref_time = t + offset_at_t + noise
        
        events.append({
            "board_time_us": t,
            "reference_time_us": int(ref_time),
            "is_pps": True,
            "is_outlier": False
        })
    
    return events


if __name__ == "__main__":
    # 测试生成
    print("Generating scenarios...")
    print(f"Normal: {len(normal_scenario())} events")
    print(f"Holdover: {len(holdover_scenario())} events")
    print(f"Jitter: {len(jitter_scenario())} events")
    print(f"Drift: {len(drift_scenario())} events")
    print("✅ Done")
