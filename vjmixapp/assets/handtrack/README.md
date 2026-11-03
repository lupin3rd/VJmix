# Hand-tracking models (e87)

Two ONNX models converted from the MediaPipe Hands model bundle
(TFLite -> ONNX, then simplified) and published by the OpenCV Zoo project.

| File | Input | Outputs | Size |
|---|---|---|---|
| `palm_detection_mediapipe_2023feb.onnx` | NHWC 1x192x192x3 float32, RGB, /255 | 1x2016x18 (box deltas + 7 palm keypoints), 1x2016x1 (logit) | 3.9 MB |
| `handpose_estimation_mediapipe_2023feb.onnx` | NHWC 1x224x224x3 float32, RGB, /255 | 1x63 landmarks, 1x1 presence, 1x1 handedness, 1x63 world landmarks | 4.1 MB |

Both are Apache-2.0 (Copyright 2023 OpenCV; converted from the MediaPipe Hands
model bundle, Apache-2.0) — the notice Apache-2.0 §4 requires is in
`NOTICE.md` beside them, and the full licence text ships in
`licenses/Apache-2.0.txt` at the repository root (the AppImage carries
`opt/vjmix/licenses/`). They are bundled so the app never needs the network and
never needs the MediaPipe runtime (which would add 250-350 MB and
`opencv-contrib-python`).

Sources:
- https://huggingface.co/opencv/palm_detection_mediapipe
- https://huggingface.co/opencv/handpose_estimation_mediapipe
- https://github.com/opencv/opencv_zoo/tree/main/models/palm_detection_mediapipe
- https://github.com/opencv/opencv_zoo/tree/main/models/handpose_estimation_mediapipe

The preprocessing/postprocessing in `vjmixapp/handio.py` is a port of those
demos' logic to numpy + Pillow (no OpenCV). The 2016-anchor table is generated
from the MediaPipe grid and asserted against the reference values in the tests.
