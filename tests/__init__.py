"""Offline test suite."""
import atexit
import os
import shutil
import tempfile

from sportscli import checks

# Each App gets its own empty check cache so tests never read or write the user's file
# and results from one test never reorder another test's sources.
_root = tempfile.mkdtemp(prefix='sports-cli-tests-')
atexit.register(shutil.rmtree, _root, True)
checks.default_path = lambda: os.path.join(tempfile.mkdtemp(dir=_root), 'checks.json')
