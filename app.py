"""Run the retired static-only public archive; historical agent source is retained."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "archive" / "server.py"), run_name="__main__")
