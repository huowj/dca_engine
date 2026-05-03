from enum import Enum


class SyncState(Enum):
    NORMAL = 0
    HOLDOVER = 1
    RECOVERY = 2


class DCAStateMachine:
    def __init__(self):
        self.state = SyncState.NORMAL

        self.last_valid_pps_time = None
        self.last_event_time = None

        self.valid_pps_counter = 0
        self.stable_pps_counter = 0
        self.outlier_counter = 0

    def is_valid_pps(self, is_pps, is_outlier):
        return is_pps and (not is_outlier)

    def is_stable_pps(self, is_valid_pps, residual_us):
        return is_valid_pps and abs(residual_us) < 100

    def update(self, now_us, is_pps, is_outlier, residual_us):
        """
        now_us: current board_time_us
        is_pps: bool
        is_outlier: bool
        residual_us: float
        """

        # --- VALIDATION ---
        valid_pps = self.is_valid_pps(is_pps, is_outlier)
        stable_pps = self.is_stable_pps(valid_pps, residual_us)

        if valid_pps:
            self.last_valid_pps_time = now_us
            self.valid_pps_counter += 1
        else:
            self.valid_pps_counter = 0

        if stable_pps:
            self.stable_pps_counter += 1
        else:
            self.stable_pps_counter = 0

        if is_outlier:
            self.outlier_counter += 1

        # --- PPS LOSS CHECK ---
        pps_lost = False
        if self.last_valid_pps_time is not None:
            if now_us - self.last_valid_pps_time > 1_500_000:
                pps_lost = True

        # --- STATE MACHINE ---
        if self.state == SyncState.NORMAL:
            if pps_lost:
                self.state = SyncState.HOLDOVER

        elif self.state == SyncState.HOLDOVER:
            if self.valid_pps_counter >= 3:
                self.state = SyncState.RECOVERY

        elif self.state == SyncState.RECOVERY:
            if pps_lost or self.outlier_counter > 5:
                self.state = SyncState.HOLDOVER
            elif self.stable_pps_counter >= 3:
                self.state = SyncState.NORMAL

        return self.state
