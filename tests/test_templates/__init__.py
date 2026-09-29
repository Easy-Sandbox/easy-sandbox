"""Offline validation suite for the ``examples/templates/`` fixtures.

``examples/templates/`` no longer holds a publishable template collection — it
keeps only a minimal ``python-hello`` **fixture** so the install/server
pipelines stay testable without network access.  The single source of truth for
official & community templates (content, the machine-readable index, releases
and CI) is the dedicated repository ``Easy-Sandbox/awesome-templates``; its own
*test suite* lives there.  These tests are fully offline and only depend on
``pyyaml``, ``pydantic``, ``click`` and ``pytest``, so they run in any CI
without network access.
"""
