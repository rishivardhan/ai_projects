This README is written as explicit instructions for GitHub Copilot to generate a single-file Streamlit app in Python that:

Opens the webcam in the browser

Runs a free, local AI model (YOLOv8n) on CPU

Identifies objects in the captured image

Stays simple, reliable, and well-commented

1) Project Goal (for Copilot)

Build a one-file Python app app.py using Streamlit and Ultralytics YOLOv8 that captures an image from the webcam and returns object labels with confidence, plus an annotated image with bounding boxes. No cloud APIs. CPU-only is fine.

2) Minimal Requirements

Ask Copilot to create a requirements.txt with exactly these packages (no extras):

streamlit
ultralytics
opencv-python
pillow
numpy

3) Constraints (what Copilot must follow)

Single file app: app.py

Simple UI using st.camera_input (no webrtc streaming; snapshot only)

Local model: yolov8n.pt (downloaded automatically by ultralytics)

Cache the model with @st.cache_resource

Clear comments + type hints

Handle errors gracefully (e.g., model load failure, empty capture)

Show:

Annotated image

A small table/list of detections (label + score)

Keep code under ~200 lines, readable and modular

4) App Behavior (step-by-step for Copilot)

Page setup

st.set_page_config(title="Webcam Object Detector", page_icon="📷", layout="centered")

Header + short description

Sidebar

Confidence threshold slider (0.1–0.9; default 0.35)

Model

Cached loader load_model("yolov8n.pt") -> YOLO

If load fails: st.error(...) and st.stop()

Capture

img_file = st.camera_input("Take a photo")

If img_file is None: show helper text and return

Inference

Convert img_file to PIL (Image.open(img_file))

Run model.predict(np.array(pil_img), verbose=False)

Parse first result’s boxes: xyxy, conf, cls, map cls → names

Filter by confidence threshold

Draw

Use PIL ImageDraw to draw rectangles + label text

Use simple deterministic color (e.g., per label hash)

Display

Two columns: annotated image left, detections right (label, confidence as percentage)

If no detections above threshold: say “No objects detected”

Performance

Optionally time the inference and show milliseconds (simple)

Privacy

Do not persist frames/files

5) Copilot Prompts (paste these as you code)
Prompt A — Scaffold app.py

Create a single-file Streamlit app app.py with page config, a title, and a sidebar slider for confidence threshold (0.1–0.9, default 0.35). Add st.camera_input("Take a photo") and a note that the image is only processed locally.

Prompt B — Add Model Loader

Add a cached function load_model(model_name: str = "yolov8n.pt") -> YOLO using @st.cache_resource. It should import YOLO from ultralytics, handle exceptions with st.error, and return the loaded model.

Prompt C — Prediction Function

Write a function predict(image: Image.Image, threshold: float) -> list[dict] that:

Converts PIL image to NumPy RGB

Calls model.predict(..., verbose=False)

Extracts detections from the first result (xyxy, conf, cls)

Filters by conf >= threshold

Returns a list of dicts like {"box": (x1,y1,x2,y2), "label": str, "score": float} using result.names to map class IDs.

Prompt D — Drawing Function

Write draw_detections(image: Image.Image, detections: list[dict]) -> Image.Image that:

Copies the image

Draws rectangles and text using ImageDraw

Uses a deterministic color per label (e.g., hash(label) % 255 triplet)

Returns the annotated PIL image

Prompt E — Wire It Up in UI

In the main app:

Load the model once via load_model()

When img_file exists: open as PIL, run predict, draw with draw_detections

Show the annotated image with st.image

In a right column, show detections in a simple table: label and score as percentage with two decimals

If empty: show st.info("No objects detected above threshold.")

Prompt F — Niceties & Error Handling

Add try/except around inference and drawing. If any error occurs, show st.error with a short hint. Also measure simple inference time with time.perf_counter() and show st.caption(f"Inference: {ms:.1f} ms").

6) Example Run Command
# (inside your virtualenv)
pip install -r requirements.txt
streamlit run app.py


Open the local URL, allow camera permissions, click “Take Photo”, and view detections.

7) Acceptance Checklist (what “done” means)

 app.py only; no extra modules

 Runs with pip install -r requirements.txt && streamlit run app.py

 Captures from webcam via st.camera_input

 Loads YOLOv8n locally (no API keys)

 Shows annotated image + detection list

 Confidence threshold works

 Clear comments + type hints

 Handles empty capture / model load errors gracefully

 ≤ ~200 lines and easy to read

8) Optional (if you want, Copilot)

A small toggle to hide boxes/labels

A selectbox to choose alternate small models if available locally

Save annotated image button (disabled by default; warn about privacy)