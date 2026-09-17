# ITICAS Stage 07 Reliability Fix 2

Version 0.7.2 corrects two packaging/test-harness defects discovered during the Windows upgrade:

1. The Stage 07.1 batch installer passed a literal caret to PowerShell around the pipeline. Stage 07.2 performs metadata preservation through a Python helper instead, eliminating shell-escaping fragility.
2. The two reliability regression tests no longer require pytest-asyncio. They execute asynchronous service calls with Python asyncio.run(), so the existing ITICAS test environment remains sufficient.

The traffic-provider retry, DNS/network failure classification, partial incident-failure handling, map tile retry controls, nationwide search and developer-credit changes from Stage 07.1 are retained.
