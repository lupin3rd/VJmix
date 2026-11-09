# licenses/

The licence texts VJmix must carry with it. The human-readable inventory — which
component, which version, which licence, which source — is
[`../THIRD_PARTY_LICENSES.md`](../THIRD_PARTY_LICENSES.md); this directory holds
the texts themselves.

| Path | What it is |
|---|---|
| `distributions/<name>/` | verbatim copies of the licence files shipped by each **pip** dependency in `requirements.txt` (generated — do not hand-edit) |
| `Apache-2.0.txt` | the ONNX models (OpenCV / MediaPipe) |
| `GPL-3.0.txt` | VJmix itself, Ableton Link inside `aalink`, the Vimix icons |
| `LGPL-2.1.txt` | FFmpeg inside the PyAV wheel |
| `OFL-1.1.txt` | the Font Awesome webfont |
| `ProggyTiny-MIT.txt` | the ProggyTiny font bundled in `vjmixapp/assets/` |
| `PortAudio-MIT.txt` | PortAudio, built from source and shipped in the AppImage |
| `Python-2.0.txt` | the CPython runtime bundled by the AppImage base |
| `NOTICE` | holder + licence + source for every **non-pip** component |

Regenerate the pip part after a dependency bump:

```bash
.venv/bin/python scripts/collect_licenses.py
```

`tests/test_licenses.py` fails if a requirement is missing from the inventory,
if a text referenced here does not exist, or if the AppImage stops shipping the
`licenses/` directory. The AppImage copies this directory to
`/opt/vjmix/licenses/` (see `scripts/build_appimage.sh`).
