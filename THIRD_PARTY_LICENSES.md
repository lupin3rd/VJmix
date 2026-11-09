# Third-party libraries and licences

**VJmix itself is Copyright (C) 2026 lupin3rd and released under the GNU GPL
v3.0** — see [LICENSE](LICENSE). This document is the inventory of everything
VJmix uses or ships that is not its own work: the runtime dependencies (exact
versions pinned in `requirements.txt`), the compiled or bundled pieces that are
not pip packages, and the development-only tools (which are **not**
distributed). The licence texts themselves live in [`licenses/`](licenses/),
with the non-pip components described in [`licenses/NOTICE`](licenses/NOTICE).

> Kept in sync mechanically: `scripts/collect_licenses.py` copies the texts from
> the installed wheels, and `tests/test_licenses.py` fails if a requirement is
> missing from this table, if a referenced text does not exist, or if the
> AppImage stops shipping `licenses/`. Bump a dependency → run the script →
> update the row.

## Runtime dependencies (installed, bundled in the AppImage)

| Package | Version | Licence | Copyright | Used for | Licence text |
|---|---|---|---|---|---|
| [Dear PyGui](https://github.com/hoffstadt/DearPyGui) | 2.3.1 | MIT | © 2026 Dear PyGui, LLC (Jonathan Hoffstadt, Preston Cothren) | the whole UI | `licenses/distributions/dearpygui/LICENSE` |
| [essentia](https://essentia.upf.edu) | 2.1b6.dev1389 | **AGPL-3.0-only** | © Universitat Pompeu Fabra (MTG) | BPM, key and audio analysis | `licenses/distributions/essentia/COPYING.txt` |
| [numpy](https://numpy.org) | 2.5.x (`>=2,<3`) | BSD-3-Clause (plus bundled components) | © NumPy Developers | arrays, DSP, image/maths everywhere | `licenses/distributions/numpy/` |
| [python-osc](https://github.com/attwad/python-osc) | 1.10.2 | Unlicense (public domain) | attwad and contributors | every `/vimix/...` message | `licenses/distributions/python_osc/LICENSE.txt` |
| [sounddevice](https://python-sounddevice.readthedocs.io) | 0.5.6 | MIT (PortAudio: MIT) | © Matthias Geier | audio capture / playback (PortAudio) | `licenses/distributions/sounddevice/LICENSE` |
| [Pillow](https://python-pillow.org) | 12.3.x (`>=11,<13`) | MIT-CMU (HPND) | © the Pillow team | thumbnails, preview downscale, frame rotate | `licenses/distributions/pillow/LICENSE` |
| [PyAV](https://pyav.basswood-io.com) (`av`) | 18.1.0 | BSD-3-Clause (bundles FFmpeg: LGPL-2.1+) | © Mike Boers, WyattBlue and PyAV contributors | video decode, webcam capture | `licenses/distributions/av/LICENSE.txt` |
| [onnxruntime](https://onnxruntime.ai) | 1.31.0 | MIT (plus its third-party notices) | © Microsoft Corporation | the two hand-tracking models | `licenses/distributions/onnxruntime/` |
| [mido](https://mido.readthedocs.io) | 1.3.3 | MIT | © Ole Martin Bjørndalen | MIDI messages (controllers, clock) | `licenses/distributions/mido/LICENSE` |
| [python-rtmidi](https://github.com/SpotlightKid/python-rtmidi) | 1.5.8 | MIT (bundles RtMidi: modified MIT) | © Christopher Arndt / RtMidi © Gary P. Scavone | the MIDI I/O backend for mido | `licenses/distributions/python_rtmidi/LICENSE.md` |
| [aalink](https://github.com/artfwo/aalink) | 0.2.3 | **GPL-3.0-or-later** (bundles Ableton Link: GPL-3.0) | © Artem Popov / Ableton Link © Ableton AG | the Ableton Link beat source | `licenses/distributions/aalink/LICENSE` |

## Bundled but not a pip package

Full details and sources: [`licenses/NOTICE`](licenses/NOTICE).

| Component | Licence | Copyright | Where it ships |
|---|---|---|---|
| FFmpeg (inside the PyAV wheel) | LGPL-2.1-or-later (GPL-2.0+ only if built with `--enable-gpl`) | © the FFmpeg developers | inside `av` |
| PortAudio 19.7.0 | MIT | © 1999-2006 Ross Bencina and Phil Burk | `usr/lib/libportaudio.so.2` (built from source, ALSA only) |
| RtMidi (inside python-rtmidi) | modified MIT | © 2003-2023 Gary P. Scavone, McGill University | inside `python-rtmidi` |
| Ableton Link (inside aalink) | GPL-3.0 (proprietary licence also sold by Ableton) | © Ableton AG | inside `aalink` |
| Hand-tracking ONNX models | Apache-2.0 | © 2023 OpenCV, converted from the MediaPipe Hands bundle (© Google LLC) | `vjmixapp/assets/handtrack/` (+ `NOTICE.md` there) |
| ProggyTiny font | MIT | © 2004, 2005 Tristan Grimmer | `vjmixapp/assets/ProggyTiny.ttf` |
| Font Awesome 4.7.0 webfont | SIL OFL 1.1 (the FA code/docs, not shipped here, are MIT) | © Dave Gandy 2016 | `vjmixapp/assets/fontawesome-webfont.ttf` |
| Vimix blending icons | GPL-3.0 (same as VJmix) | © Bruno Herbelin | `vjmixapp/assets/blending_icons.png` |
| CPython 3.13 runtime | PSF-2.0 (plus CWI/CNRI/BeOpen terms, 0BSD for docs code) | © 2001-2024 Python Software Foundation | the AppImage base (`python-appimage`, manylinux_2_28) |
| manylinux_2_28 base libraries | their own licences | their respective holders | the AppImage base (glibc, libstdc++, X11/GL client libs, ALSA, …) |

## Licence compatibility (why this mix is legal here)

- **essentia (AGPL-3.0) + VJmix (GPL-3.0).** GPLv3 §13 explicitly allows
  combining a GPLv3 work with an AGPLv3 work: the GPL part stays GPL-3.0, the
  AGPL part stays AGPL-3.0, and the AGPL text is conveyed with the binary
  (`licenses/distributions/essentia/COPYING.txt`). Sources are public (gitea),
  which satisfies both licences. Essentia also sells a commercial licence for
  closed-source use — not needed by VJmix, which is open source.
- **aalink (GPL-3.0) + Ableton Link.** Same licence family as VJmix, so the
  combination is the ordinary GPL case; Ableton's proprietary option matters
  only for closed products.
- **FFmpeg (LGPL-2.1+) inside the PyAV wheel.** Dynamic linking through the
  wheel, no VJmix code modified: the LGPL conditions are met by shipping the
  text and keeping our own sources public. If the bundled build were a GPL one,
  GPL-3.0 (our licence) would cover the combination anyway.
- **Apache-2.0 (the ONNX models).** Compatible with GPL-3.0 (not with
  GPL-2.0-only): §4 obligations are the notice next to the models and the
  licence text, both shipped. The models are unmodified data files; the
  conversion and the source URLs are recorded in the model `NOTICE.md`.
- **MIT / BSD / Unlicense / OFL dependencies.** Permissive, no obligation beyond
  preserving the notices, which `licenses/distributions/` does verbatim.

## Development-only (NOT distributed)

`requirements-dev.txt` — `ruff` (MIT), `mypy` (MIT), `pytest` (MIT),
`pre-commit` (MIT), `moderngl` (MIT, dev-only shader render harness). Installed
in the developer venv, never shipped in the AppImage.

## Rig-only (local, never redistributed)

`requirements-rig.txt` — `setuptools` (MIT), `py-spy` (MIT), `PyAutoGUI`
(BSD-3-Clause), `python-xlib` (LGPL-2.1+), plus the local Leap Motion bindings
built from `~/repo-git/leapc-python-bindings` (`leapc-cffi`, `leapc-python-api`).
Local UAT tooling only: the AppImage installs `requirements.txt` alone.

## Obtaining the sources

- VJmix: <https://git.franceschini.it/lupin3rd/VJmix> (full history, this
  repository).
- Every dependency: the upstream links in the tables above, and the exact
  versions pinned in `requirements.txt`.
- The models and their conversion: <https://github.com/opencv/opencv_zoo> and
  <https://huggingface.co/opencv>.
