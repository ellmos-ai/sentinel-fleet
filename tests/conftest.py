"""Test-wide isolation of the persistent entity stores.

`LocalJsonStore` writes every `put()` back to `DATA_DIR` as a whole file, and the default is the
repository's own `./data`. Without this, a test run permanently adds to the store the next run
starts from - and since each write serialises the entire collection, the suite gets slower with
every run it has ever done. Measured on this repository: 5 minutes 12 seconds against the grown
`./data`, 25 seconds against an empty directory, same 255 tests.

So the isolation is not only hygiene. It is the difference between a suite that stays fast and
one that silently decays, and it keeps a test run from writing into the data a running console
is serving from.

The variable is set at import time on purpose: `core/config.py` reads the environment when its
`settings` singleton is constructed, which happens on the first `sentinel_fleet` import - and
pytest imports conftest before any test module.
"""

import os
import shutil
import tempfile

_TEST_DATA_DIR = tempfile.mkdtemp(prefix="sentinel-fleet-tests-")

# Deliberately overriding rather than defaulting: an inherited DATA_DIR from a developer's shell
# would point the suite at a real store, which is exactly what this guards against.
os.environ["DATA_DIR"] = _TEST_DATA_DIR


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_TEST_DATA_DIR, ignore_errors=True)
