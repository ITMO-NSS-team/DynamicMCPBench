"""Put dmcp-studio/ on sys.path so `backend` imports as a package.

The directory is hyphenated (not itself importable), so we expose its children
(`backend`) by adding this dir to the path for any test collected beneath it.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
