"""Root entry point to run the SentinelFleet & OmniLedger Server."""

import uvicorn
from sentinel_fleet.core.config import settings
from sentinel_fleet.web.server import app

if __name__ == "__main__":
    print(f"[*] Starting SentinelFleet Control Center on http://{settings.host}:{settings.port}")
    uvicorn.run(app, host=settings.host, port=settings.port)
