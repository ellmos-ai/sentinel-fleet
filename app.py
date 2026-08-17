"""Root entry point to run the SentinelFleet & OmniLedger Server."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import uvicorn
from sentinel_fleet.core.config import settings
from sentinel_fleet.web.server import app

if __name__ == "__main__":
    print(f"[*] Starting SentinelFleet Control Center on http://{settings.host}:{settings.port}")
    uvicorn.run(app, host=settings.host, port=settings.port)
