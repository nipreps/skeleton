"""Test data files

.. autofunction:: load

.. automethod:: load.readable

.. automethod:: load.as_path

.. automethod:: load.cached
"""

import pytest
from acres import Loader

load_resource = Loader(__spec__.name, list_contents=True)


def needs_test_data(resource):
    res = load_resource(resource)
    # Empty directories are uninitialized submodules
    check = res.exists() and (not res.is_dir() or any(res.iterdir()))
    return pytest.mark.skipif(not check, reason=f'Resource {resource} is not available')
