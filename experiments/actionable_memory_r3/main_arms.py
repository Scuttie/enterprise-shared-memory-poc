"""REALBENCH-R3 §16/§17 — confirmatory arm constants (pure; no service deps). Kept separate so the light
combine/analysis (r3_main_combine, r3_calibration_combine) can import them without pulling enterprise_memory."""
MAIN_ARMS = ["M0", "M1", "M2", "M3", "M4", "M5", "M6"]
CALIB_ARMS = ["C0", "C1", "C2", "C3", "C4", "C5"]
# calibration arm -> the main arm whose injection it mirrors
CALIB_EQUIV = {"C0": "M0", "C1": "M2", "C2": "M3", "C3": "M4", "C4": "M1", "C5": "M6"}
