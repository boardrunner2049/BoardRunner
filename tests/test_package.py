"""The package installs and finds FastDyn."""

import logging

import boardrunner
import fastdyn


def test_boardrunner_and_fastdyn_import():
    assert boardrunner.__version__
    assert callable(fastdyn.run_config) and callable(fastdyn.build_models)


def test_importing_installs_no_log_handlers():
    handlers = logging.getLogger("boardrunner").handlers
    assert all(isinstance(h, logging.NullHandler) for h in handlers)
