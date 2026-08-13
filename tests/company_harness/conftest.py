"""P5.1 §10 company-harness tests run fully credential-free against a local fake harness HTTP server."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
