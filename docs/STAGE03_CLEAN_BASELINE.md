# ITICAS Stage 03 Nigeria Clean Baseline

This package fixes the overlay/test architecture before Stage 04.

Key changes:
1. ITICAS scope is Nigeria-wide.
2. Ibadan is only the initial demonstration catalogue.
3. `monitoring_locations.name` is no longer globally unique.
4. Duplicate protection is now based on the same name + city + state.
5. Old stage-specific tests are removed automatically.
6. `pytest.ini` only discovers the current regression suite:
   `test_current_*.py`
7. Future stages should replace/update these current regression files instead
   of accumulating stage-number-specific tests.
8. FastAPI uses the documented lifespan mechanism.
9. Developer credit remains: Dr. Oyeyode A.O.

Stage 04 should not be started until this baseline passes.
