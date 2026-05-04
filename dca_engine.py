from enum import Enum
import math


class SyncState(Enum):
    NORMAL = 0
    HOLDOVER = 1
    RECOVERY = 2


class DCAEngine:
    def __init__(self):
        # --- State ---
        self.state = SyncState.NORMAL

        # --- Time ---
        self.last_valid_pps_time = None
        self.last_output_time = 0

        # --- Counters ---
        self.valid_pps_counter = 0
        self.stable_pps_counter = 0
        self.outlier_counter = 0

        # --- Observers ---
        self.offset_us = 0.0
        self.drift_ppm = 0.0
        self.confidence = 0.5

        # --- Filter ---
        self.offset_buffer = []
        self.sigma = 50.0  # initial guess

        # --- Snapshot for holdover ---
        self.holdover_offset = 0.0
        self.holdover_start_time = None

    # ------------------------------
    # VALIDATION
    # ------------------------------
    def is_valid_pps(self, is_pps, is_outlier):
        return is_pps and (not is_outlier)

    def is_stable_pps(self, valid_pps, residual):
        return valid_pps and abs(residual) < 100

    def is_outlier(self, residual):
        return abs(residual) > max(300, 3 * self.sigma)

    # ------------------------------
    # UPDATE ENTRY
    # ------------------------------
    def update(self, board_time_us, reference_time_us, is_pps):
        """
        board_time_us: uint64
        reference_time_us: uint64 or None
        is_pps: bool
        """

        # ---- residual ----
        if reference_time_us is not None:
            residual = reference_time_us - (board_time_us + self.offset_us)
        else:
            residual = 0

        # ---- outlier detection ----
        outlier = self.is_outlier(residual)

        valid_pps = self.is_valid_pps(is_pps, outlier)
        stable_pps = self.is_stable_pps(valid_pps, residual)

        # ---- update counters ----
        if valid_pps:
            self.last_valid_pps_time = board_time_us
            self.valid_pps_counter += 1
        else:
            self.valid_pps_counter = 0

        if stable_pps:
            self.stable_pps_counter += 1
        else:
            self.stable_pps_counter = 0

        if outlier:
            self.outlier_counter += 1

        # ---- PPS loss ----
        pps_lost = False
        if self.last_valid_pps_time is not None:
            if board_time_us - self.last_valid_pps_time > 1_500_000:
                pps_lost = True

        # ------------------------------
        # STATE MACHINE
        # ------------------------------
        if self.state == SyncState.NORMAL:
            if pps_lost:
                self.state = SyncState.HOLDOVER
                self.enter_holdover(board_time_us)

        elif self.state == SyncState.HOLDOVER:
            if self.valid_pps_counter >= 3:
                self.state = SyncState.RECOVERY

        elif self.state == SyncState.RECOVERY:
            if pps_lost or self.outlier_counter > 5:
                self.state = SyncState.HOLDOVER
                self.enter_holdover(board_time_us)
            elif self.stable_pps_counter >= 3:
                self.state = SyncState.NORMAL

        # ------------------------------
        # OBSERVERS
        # ------------------------------
        if valid_pps:
            self.update_offset(residual)
            self.update_drift(board_time_us, residual)

        self.update_sigma(residual)
        self.update_confidence(pps_lost)

        # ------------------------------
        # TIME COMPUTATION
        # ------------------------------
        corrected_time = self.compute_time(board_time_us)

        # monotonic guard
        corrected_time = max(corrected_time, self.last_output_time + 1)
        self.last_output_time = corrected_time

        return {
            "corrected_time_us": int(corrected_time),
            "state": self.state.name,
            "offset_us": self.offset_us,
            "drift_ppm": self.drift_ppm,
            "confidence": self.confidence,
            "residual": residual
        }

    # ------------------------------
    # OFFSET OBSERVER
    # ------------------------------
    def update_offset(self, residual):
        self.offset_buffer.append(residual)
        if len(self.offset_buffer) > 5:
            self.offset_buffer.pop(0)

        median = sorted(self.offset_buffer)[len(self.offset_buffer)//2]

        if self.state == SyncState.NORMAL:
            alpha = 0.1
        elif self.state == SyncState.RECOVERY:
            alpha = 0.5
        else:
            alpha = 0.01

        self.offset_us += alpha * (median - self.offset_us)

    # ------------------------------
    # DRIFT OBSERVER
    # ------------------------------
    def update_drift(self, now_us, residual):
        if not hasattr(self, "last_residual"):
            self.last_residual = residual
            self.last_time = now_us
            return

        dt = now_us - self.last_time
        if dt == 0:
            return

        delta = residual - self.last_residual

        drift = (delta / dt) * 1e6

        if self.state == SyncState.NORMAL:
            alpha = 0.08
        elif self.state == SyncState.RECOVERY:
            alpha = 0.1
        else:
            alpha = 0.001

        self.drift_ppm += alpha * (drift - self.drift_ppm)
        self.drift_ppm = max(min(self.drift_ppm, 50), -50)

        self.last_residual = residual
        self.last_time = now_us

    # ------------------------------
    # SIGMA UPDATE
    # ------------------------------
    def update_sigma(self, residual):
        self.sigma = math.sqrt(0.95 * self.sigma**2 + 0.05 * residual**2)

    # ------------------------------
    # CONFIDENCE
    # ------------------------------
    def update_confidence(self, pps_lost):
        if self.state == SyncState.NORMAL:
            self.confidence = min(0.99, 0.9 + 0.01 * self.valid_pps_counter)

        elif self.state == SyncState.RECOVERY:
            self.confidence = min(0.9, 0.7 + 0.05 * self.stable_pps_counter)

        elif self.state == SyncState.HOLDOVER:
            if self.holdover_start_time is not None:
                decay = 0.95
                self.confidence *= decay

        self.confidence = max(0.01, min(self.confidence, 0.99))

    # ------------------------------
    # HOLDOVER
    # ------------------------------
    def enter_holdover(self, now_us):
        self.holdover_offset = self.offset_us
        self.holdover_start_time = now_us

    # ------------------------------
    # TIME COMPUTATION
    # ------------------------------
    def compute_time(self, board_time_us):
        if self.state == SyncState.HOLDOVER:
            dt = board_time_us - self.holdover_start_time
            predicted = self.holdover_offset + (self.drift_ppm * dt / 1e6)
            return board_time_us + predicted
        else:
            return board_time_us + self.offset_us
