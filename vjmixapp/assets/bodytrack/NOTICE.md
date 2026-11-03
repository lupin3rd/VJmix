# Body-tracking models — provenance and licence

| File | Source | Licence |
|---|---|---|
| `person_detection_mediapipe_2023mar.onnx` (12.0 MB) | OpenCV Zoo `models/person_detection_mediapipe`, converted from the MediaPipe BlazePose person detector | Apache-2.0 |
| `pose_estimation_mediapipe_2023mar.onnx` (5.6 MB) | OpenCV Zoo `models/pose_estimation_mediapipe`, converted from the MediaPipe BlazePose pose landmark model (33 landmarks) | Apache-2.0 |
| `anchors.npy` (2254×2) | the SSD anchor table from the OpenCV Zoo person-detector demo | Apache-2.0 |

Sources:
- <https://github.com/opencv/opencv_zoo/tree/main/models/person_detection_mediapipe>
- <https://github.com/opencv/opencv_zoo/tree/main/models/pose_estimation_mediapipe>

The models are shipped in the repository (no runtime download), loaded through
`onnxruntime` (already a dependency for the hand engine) and used only on frames
from the operator's camera. See `THIRD_PARTY_LICENSES.md`.
