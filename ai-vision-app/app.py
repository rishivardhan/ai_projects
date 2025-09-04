"""
Webcam Object Detector – Streamlit + YOLOv8n (Live)
Single-file app. No cloud APIs. CPU-only. No persistence.
"""

import streamlit as st
import cv2
import numpy as np
from ultralytics import YOLO
from streamlit_webrtc import webrtc_streamer, VideoProcessorBase, RTCConfiguration
from collections import Counter
import time

# Page config
st.set_page_config(page_title="Webcam Object Detector", page_icon="📷", layout="centered")
st.title("Webcam Object Detector (Live)")
st.write("Live object detection using your webcam and a free, local AI model (YOLOv8n). No images leave your device.")

# Sidebar: model selection
model_options = ["yolov8n.pt", "yolov8s.pt"]
model_name = st.sidebar.selectbox("Model", model_options, index=0)
threshold = st.sidebar.slider("Confidence threshold", 0.1, 0.9, 0.35, 0.01)
st.sidebar.caption("Images are processed locally. No cloud APIs.")

# Model loader (cached)
@st.cache_resource(show_spinner=True)
def load_model(model_name: str) -> YOLO:
    """Load YOLOv8 model, handle errors."""
    try:
        return YOLO(model_name)
    except Exception as e:
        st.error(f"Model load failed: {e}")
        st.stop()

model = load_model(model_name)

class VideoProcessor(VideoProcessorBase):
    def __init__(self):
        self.threshold = threshold
        self.last_labels = []
    def recv(self, frame):
        img = frame.to_ndarray(format="bgr24")
        labels = []
        results = model(img)
        for result in results:
            # Use result.names to map class indices to names
            for box, score, cls_idx in zip(result.boxes.xyxy, result.boxes.conf, result.boxes.cls):
                if score >= self.threshold:
                    x1, y1, x2, y2 = map(int, box)
                    label = result.names[int(cls_idx)]
                    cv2.rectangle(img, (x1, y1), (x2, y2), (0,255,0), 2)
                    cv2.putText(img, f"{label} {score:.2f}", (x1, y1-10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0,255,0), 2)
                    labels.append(label)
        self.last_labels = labels
        return frame.from_ndarray(img, format="bgr24")

webrtc_ctx = webrtc_streamer(
    key="yolo-live",
    video_processor_factory=VideoProcessor,
    rtc_configuration=RTCConfiguration({"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}),
    media_stream_constraints={"video": True, "audio": False},
    async_processing=True,
)

status_box = st.empty()

# Poll for detected labels from the video processor
while True:
    if webrtc_ctx and webrtc_ctx.state.playing and webrtc_ctx.video_processor:
        labels = webrtc_ctx.video_processor.last_labels
        if labels:
            label_counts = Counter(labels)
            label_str = ", ".join(f"{lbl} ({cnt})" for lbl, cnt in label_counts.items())
            status_box.markdown(f"**I see:** {label_str}")
        else:
            status_box.markdown("**I see:** nothing confidently.")
    time.sleep(0.5)
    if not (webrtc_ctx and webrtc_ctx.state.playing):
        break
