"""E2B SDK compatibility layer.

Provides a partial E2B-compatible subset of ``e2b.Sandbox``::

    from easy_sandbox.compat import Sandbox

The main :class:`~easy_sandbox.api.sandbox.Sandbox` class is already
designed to be API-compatible with the E2B Python SDK.  This module re-exports
it for convenience and documents the mapping:

=================================  ====================================
E2B SDK                            easy_sandbox
=================================  ====================================
``Sandbox.create()``               ``Sandbox.create()``
``Sandbox.connect(id)``            ``Sandbox.connect(id)``
``Sandbox.list()``                 ``Sandbox.list()``
``sandbox.kill()``                 ``sandbox.kill()``
``Sandbox.kill(id)``               ``Sandbox.kill_by_id(id)``
``sandbox.is_running()``           ``sandbox.is_running()``
``sandbox.pause()``                ``sandbox.pause()``
``sandbox.set_timeout(t)``         ``sandbox.set_timeout(t)``
``sandbox.commands.run(cmd)``      ``sandbox.commands.run(cmd)``
``sandbox.files.read(path)``       ``sandbox.files.read(path)``
``sandbox.files.write(path, d)``   ``sandbox.files.write(path, d)``
``sandbox.run_code(code)``         ``sandbox.run_code(code)``
``sandbox.get_host(port)``         ``sandbox.network.get_host(port)``  [1]_
``sandbox.get_upload_url(path)``   ``sandbox.get_upload_url(path)``    [2]_
``sandbox.get_download_url(path)`` ``sandbox.get_download_url(path)``  [2]_
=================================  ====================================

.. [2] ``get_upload_url()`` and ``get_download_url()`` raise
   ``NotImplementedError`` — they are stub placeholders for future
   implementation.  Use ``files.write()`` / ``files.read()`` instead.

.. [1] ``network.get_host()`` / ``get_url()`` / ``get_access_headers()``
   require the template to declare the ``ports`` capability.  When it is
   absent they raise ``CapabilityNotSupportedError`` (E3004) rather than
   silently returning a URL that cannot be reached.  Declare ``ports`` in
   the template's ``capabilities`` list (template.yaml), or use a
   template that already does (e.g. ``node-web``).

Note: Not all E2B SDK features have been implemented yet.  Methods that
depend on undocumented RPC paths are marked with逆向推断 warnings in their
docstrings.
"""
from __future__ import annotations

from easy_sandbox.api.sandbox import Sandbox

# Alias for E2B SDK compatibility
E2BSandbox = Sandbox

__all__ = ["Sandbox", "E2BSandbox"]
