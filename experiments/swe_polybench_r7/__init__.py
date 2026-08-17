"""REALBENCH_SWE_POLYBENCH_R7 — opened by R6 §6 (Endpoint B: Solar readers out of reach on SkillsBench).

Instrument audit of SWE-PolyBench Verified + a no-memory calibration pilot gated on resolved rate in
[0.10, 0.70] (a genuine measurable band — neither R3's DS-1000 ceiling nor R5/R6's SkillsBench floor). Only
after the pilot lands in-band do the M0-M4 memory arms (§7) run. No confirmatory arm before the gate passes.
"""

EXPERIMENT_ID = "REALBENCH_SWE_POLYBENCH_R7"
DYNAMIC_RANGE_BAND = (0.10, 0.70)  # no-memory resolved rate must land here to proceed
OPENED_BY = "R6 §6 viability Endpoint B"
STATUS = "R7_G1_INSTRUMENT_STOP"  # G0 PASS (freeze+smoke), G1 no-memory pilot resolved 1/40=0.025 < [0.10,0.70] floor; memory arms NOT run
