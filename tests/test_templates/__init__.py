"""Offline validation suite for the ``examples/templates/`` catalog.

The template catalog is intentionally minimal: one ``README.md`` acting as the
sole index plus one folder per template.  These tests are the hard gate before
anything is published — they are fully offline and only depend on ``pyyaml``,
``pydantic``, ``click`` and ``pytest``, so the very same checks can run in the
CI of a standalone ``awesome-serverless-sandbox-templates`` repository.
"""
