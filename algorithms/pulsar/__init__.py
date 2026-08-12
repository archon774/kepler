"""Python pulsar time-series ingest and sonification.

This package is a **language port**, not an extraction. Every other Python
folder under ``algorithms/`` is byte-preserved from Skynet; this one carries
Astromancer TypeScript logic into Python because the upstream sonifier cannot
be run headless -- see ``docs/extraction.md``, "Pulsar (sonification)".

Port markers use ``# PORTED:`` rather than the ``# EXTRACTED:`` marker the
byte-preserving folders use, so the extraction index stays meaningful.

Two modules:

* :mod:`algorithms.pulsar.ingest` -- Green Bank / Skynet pulsar file parsing
  and the running-median background subtraction.
* :mod:`algorithms.pulsar.sonification` -- amplitude-modulated-noise audio
  synthesis and 16-bit PCM WAV encoding.

Neither imports the other's caller: ``ingest`` knows nothing about audio, and
``sonification`` takes plain float arrays.
"""

from __future__ import annotations

__all__: list[str] = []
