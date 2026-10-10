"""BoardRunner: automatic rehosting of embedded firmware with learned device
models (VIOMapper), built on FastDyn."""

import logging

__version__ = "0.1.0.dev0"

# Library code never configures logging; the boardrunner command does.
logging.getLogger("boardrunner").addHandler(logging.NullHandler())
