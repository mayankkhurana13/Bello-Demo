# Bello Foyer – Studio Edition (Soft Pastel Theme, Mobile-Fixed)
# Furniture-Only Restyle / Uplift Enhancements + Iterative Refinement
# Deps: streamlit, openai (v1.x), pillow, numpy, opencv-python-headless, requests

import os
import io
import json
import base64
from typing import List, Dict, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops
import streamlit as st

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False

from openai import OpenAI

# ---------------- Streamlit Page Config ----------------
st.set_page_config(page_title="Bello Foyer – Studio Edition", page_icon="🏡", layout="centered")

# ---------------- Load API Key ----------------
api_key: Optional[str] = None
try:
    api_key = st.secrets.get("OPENAI_API_KEY")
except Exception:
    api_key = None
if not api_key:
    api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    st.error("OpenAI API key missing. Set OPENAI_API_KEY in env or .streamlit/secrets.toml.")
    st.stop()

client = OpenAI(api_key=api_key)

# ---------------- Helpers ----------------
def b64_image(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")

def pad_to_square(image: Image.Image) -> Image.Image:
    w, h = image.size
    side = max(w, h)
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(image, ((side - w)//2, (side - h)//2))
    return canvas

def resize_1024(image: Image.Image) -> Image.Image:
    return image.resize((1024, 1024), Image.LANCZOS)

# ---------------- Vision: Movable Boxes ----------------
def detect_movable_boxes(image_bytes: bytes) -> List[Dict]:
    prompt = (
        "Detect MOVABLE furniture and decor in this interior room photo. "
        "Return JSON with key 'boxes' containing list of objects: {label, x, y, w, h}, normalized between 0 and 1. "
        "Include items like sofa, chair, bed, crib, rug, table, lamp, shelf, plant, art, cushions, decor. "
        "Do NOT include walls, floor, ceiling, windows, doors, curtains/blinds, fixed lighting, built-ins."
    )
    try:
        b64 = b64_image(image_bytes)
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]
            }],
            response_format={"type": "json_object"},
            max_tokens=600
        )
        data = json.loads(resp.choices[0].message.content)
        boxes = data.get("boxes", [])
        clean = []
        for b in boxes if isinstance(boxes, list) else []:
            try:
                x = float(b["x"]); y = float(b["y"]); w = float(b["w"]); h = float(b["h"])
                if 0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1:
                    clean.append({"x": x, "y": y, "w": w, "h": h})
            except Exception:
                continue
        return clean
    except Exception as e:
        print("detect_movable_boxes error:", e)
        return []

# ---------------- Edge Lock Mask ----------------
def edge_lock_mask(img: Image.Image, thickness_px: int = 6, canny1: int = 80, canny2: int = 160) -> Image.Image:
    w, h = img.size
    if not HAS_CV2:
        return Image.new("RGBA", (w, h), (0, 0, 0, 0))
    arr = np.array(img.convert("RGB"))[:, :, ::-1]  # BGR
    gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, threshold1=canny1, threshold2=canny2)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (thickness_px, thickness_px))
    band = cv2.dilate(edges, kernel, iterations=1)
    L = Image.fromarray(band).convert("L").filter(ImageFilter.GaussianBlur(2))
    return Image.merge("RGBA", (L, L, L, L))

# ---------------- Box Mask for Furniture ----------------
def boxes_mask(img: Image.Image, boxes: List[Dict], pad_px: int = 12, blur_px: int = 6) -> Image.Image:
    w, h = img.size
    base = Image.new("L", (w, h), 255)  # opaque/locked
    draw = ImageDraw.Draw(base)
    for b in boxes:
        x0 = max(0, int(b["x"] * w) - pad_px)
        y0 = max(0, int(b["y"] * h) - pad_px)
        x1 = min(w, int((b["x"] + b["w"]) * w) + pad_px)
        y1 = min(h, int((b["y"] + b["h"]) * h) + pad_px)
        draw.rectangle([x0, y0, x1, y1], fill=0)  # transparent/editable
    base = base.filter(ImageFilter.GaussianBlur(blur_px))
    return Image.merge("RGBA", (base, base, base, base))

# ---------------- Uplift Placement Boxes ----------------
def detect_placement_boxes(image_bytes: bytes) -> List[Dict]:
    prompt = (
        "Identify 2-3 empty/open areas in this room photo where small additions (accent chair, planter, wall art, floor lamp) "
        "could be placed without removing existing furniture. "
        "Return JSON with key 'boxes' = list of {label, x, y, w, h}, normalized to 0-1. "
        "Label examples: 'accent_chair_zone', 'planter_zone', 'wall_art_zone'. "
        "Do NOT include areas currently occupied by large furniture."
    )
    try:
        b64 = b64_image(image_bytes)
        resp = client.chat.completions.create(  # fallback if preferred; but keep primary call below
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]
            }],
            response_format={"type": "json_object"},
            max_tokens=600
        )
        # If above doesn't exist in your SDK, use the standard call below:
    except Exception:
        resp = None

    if not resp:
        try:
            resp = client.chat.completions.create(
                model="gpt-4o",
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64_image(image_bytes)}"}}
                    ]
                }],
                response_format={"type": "json_object"},
                max_tokens=600
            )
        except Exception as e:
            print("detect_placement_boxes error:", e)
            return []

    try:
        data = json.loads(resp.choices[0].message.content)
        boxes = data.get("boxes", [])
        clean = []
        for b in boxes if isinstance(boxes, list) else []:
            try:
                x = float(b["x"]); y = float(b["y"]); w = float(b["w"]); h = float(b["h"])
                if 0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1:
                    clean.append({"x": x, "y": y, "w": w, "h": h})
            except Exception:
                continue
        return clean
    except Exception as e:
        print("detect_placement_boxes parse error:", e)
        return []

# ---------------- Analyze Architecture ----------------
def analyze_architecture(img_bytes: bytes) -> str:
    try:
        b64 = b64_image(img_bytes)
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text":
                        "Describe only the FIXED architecture: walls, windows, doors, ceiling, lighting fixtures, flooring. "
                        "Avoid describing furniture or decor."
                    },
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]
            }],
            max_tokens=200
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print("analyze_architecture error:", e)
        return "Architecture unchanged: walls, windows, floor, ceiling and fixed lighting remain the same."

# ---------------- Edit Briefs ----------------
def make_edit_brief(style_goal: str, scene_report: str) -> str:
    return f"""
A photorealistic image of the same room, from the identical camera view, under the same lighting and time of day.
Do not change walls, windows, floor, ceiling, or any fixed architecture.
Restyle ONLY the movable furniture and decor (sofa, chairs, tables, rugs, lamps, plants, accessories) to match this style: {style_goal}.
Fit scale and perspective exactly. Keep wall colors, floor material, window size/placement UNCHANGED.
Reference architecture: {scene_report}
"""

def make_uplift_brief(style_goal: str, scene_report: str) -> str:
    return f"""
A photorealistic image of the same room, preserving all existing furniture, colors, lighting, and layout exactly as in the source photo.
Only ADD tasteful enhancements — e.g., a small accent chair, wall art, a planter, a floor lamp, table decor — placed realistically into open spaces.
Do NOT remove or replace any furniture, and do NOT change wall/floor/ceiling finishes.
Fit scale/perspective exactly; avoid altering brightness or time-of-day lighting.
Style goal: {style_goal}
Reference architecture: {scene_report}
"""

# ---------------- Image Edit Function ----------------
def edit_with_mask(original_bytes: bytes, brief: str,
                   box_pad: int = 12, mask_blur: int = 6,
                   edge_px: int = 6, c1: int = 80, c2: int = 160,
                   mode: str = "revamp") -> str:
    img = Image.open(io.BytesIO(original_bytes)).convert("RGBA")

    if mode == "uplift":
        # Fully locked except small placement zones
        placement = detect_placement_boxes(original_bytes)
        w, h = img.size
        base = Image.new("L", (w, h), 255)  # locked
        draw = ImageDraw.Draw(base)
        for b in placement:
            x0 = max(0, int(b["x"] * w) - box_pad)
            y0 = max(0, int(b["y"] * h) - box_pad)
            x1 = min(w, int((b["x"] + b["w"]) * w) + box_pad)
            y1 = min(h, int((b["y"] + b["h"]) * h) + box_pad)
            draw.rectangle([x0, y0, x1, y1], fill=0)
        base = base.filter(ImageFilter.GaussianBlur(mask_blur))
        placement_mask = Image.merge("RGBA", (base, base, base, base))
        edge_mask = edge_lock_mask(img, edge_px, c1, c2)
        L_final = ImageChops.lighter(placement_mask.split()[0], edge_mask.split()[0])
        final_mask = Image.merge("RGBA", (L_final, L_final, L_final, L_final))
    else:
        # Revamp movable furniture regions + edge lock
        boxes = detect_movable_boxes(original_bytes)
        furn_mask = boxes_mask(img, boxes, pad_px=box_pad, blur_px=mask_blur)
        edge_mask = edge_lock_mask(img, edge_px, c1, c2)
        L_final = ImageChops.lighter(furn_mask.split()[0], edge_mask.split()[0])
        final_mask = Image.merge("RGBA", (L_final, L_final, L_final, L_final))

    padded_img = resize_1024(pad_to_square(img))
    padded_mask = resize_1024(pad_to_square(final_mask))
    img_io = io.BytesIO(); mask_io = io.BytesIO()
    padded_img.save(img_io, format="PNG"); padded_mask.save(mask_io, format="PNG")
    img_io.seek(0); mask_io.seek(0)
    img_io.name = "image.png"; mask_io.name = "mask.png"

    edit = client.images.edit(
        model="gpt-image-1",
        image=img_io,
        mask=mask_io,
        prompt=brief,
        size="1024x1024",
        n=1
    )
    data = edit.data[0]
    if getattr(data, "b64_json", None):
        return "data:image/png;base64," + data.b64_json
    if getattr(data, "url", None):
        return data.url
    raise RuntimeError("Image API returned no usable data.")

# ---------------- Session State ----------------
ss = st.session_state
if "step" not in ss:
    ss.step = 0
    ss.upload = None
    ss.style_goal = "Modern"
    ss.design_mode = "Revamp Full Room"
    ss.result = None
    ss.history = []  # list of (description, image_url)
    ss.error = None
    # Advanced mask defaults
    ss.mask_blur = 6
    ss.edge_thick = 6
    ss.canny1 = 80
    ss.canny2 = 160
    ss.box_pad = 12

# ---------------- Pastel Theme CSS (Mobile-fixed) ----------------
# ---- Bello Foyer pastel light theme (mobile safe) ----
def inject_bello_theme():
    st.markdown(
        """
<style>
/* Force light, pastel background across desktop & mobile */
html, body, [data-testid="stAppViewContainer"] {
    background-color: #fff8f9 !important;
    color-scheme: light !important;
}

/* Inputs + buttons */
input, select, textarea, .stFileUploader, .stButton>button {
    background-color: #ffffff !important;
    color: #2d3436 !important;
    border-radius: 8px !important;
    border: 1px solid #dcdcdc !important;
}

/* Primary buttons */
.stButton > button {
    background-color: #9dbfa5 !important; /* <<< CHANGED from dark green to soft sage */
    color: #ffffff !important;
    font-weight: 600 !important;
    border: none !important;
    padding: 0.6rem 1rem !important;
    border-radius: 8px !important;
    transition: background-color 0.2s ease-in-out !important;
}
.stButton > button:hover {
    background-color: #8aa891 !important; /* <<< CHANGED from dark green to darker soft sage */
}

/* File uploader card */
[data-testid="stFileUploader"] {
    background-color: #ffffff !important;
    border-radius: 10px !important;
    border: 1px solid #e0e0e0 !important;
    padding: 1rem !important;
}

/* Enforce light mode even if device prefers dark */
@media (prefers-color-scheme: dark) {
  html, body {
    background-color: #fff8f9 !important;
    color: #2d3436 !important;
  }
}
</style>
        """,
        unsafe_allow_html=True,
    )

inject_bello_theme()

# ---------------- Step 0: Welcome ----------------
if ss.step == 0:
    logo_path = "assets/bello_logo.png"
    if os.path.exists(logo_path):
        st.image(logo_path, width=180)
    else:
        st.markdown("<h1 style='color:#9dbfa5;'>Bello Foyer</h1>", unsafe_allow_html=True) # <<< CHANGED from dark green

    intro_video = "assets/intro.mp4"
    if os.path.exists(intro_video):
        with open(intro_video, "rb") as f:
            video_b64 = base64.b64encode(f.read()).decode("utf-8")
        st.markdown(
            f"""
            <video autoplay muted playsinline loop>
              <source src="data:video/mp4;base64,{video_b64}" type="video/mp4" />
            </video>
            """,
            unsafe_allow_html=True
        )

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("Get Started", type="primary", use_container_width=True):
        ss.step = 1
        st.rerun()

# ---------------- Step 1: Design Studio ----------------
elif ss.step == 1:
    st.subheader("🎨 Select Your Design Style")
    style_options = ["Minimal", "Modern", "Boho", "Scandi", "Industrial", "Classic", "Contemporary Luxe"]
    ss.style_goal = st.selectbox(
        "Choose style", style_options,
        index=style_options.index(ss.style_goal if ss.style_goal in style_options else "Modern")
    )

    st.subheader("🔧 Select Mode")
    ss.design_mode = st.radio("Design Mode", ["Revamp Full Room", "Suggest Uplift Enhancements"], index=0)

    st.subheader("📤 Upload a room photo")
    upload = st.file_uploader("Upload JPG/PNG/WebP", type=["jpg", "jpeg", "png", "webp"])
    if upload:
        ss.upload = upload
        st.image(upload, use_container_width=True, caption="Your room photo")

    with st.expander("Advanced mask controls (optional)", expanded=False):
        ss.box_pad = st.slider("Furniture padding (px)", 4, 30, ss.box_pad, step=2)
        ss.mask_blur = st.slider("Mask feather (px)", 2, 16, ss.mask_blur, step=1)
        ss.edge_thick = st.slider("Edge lock thickness (px)", 2, 18, ss.edge_thick, step=1)
        ss.canny1 = st.slider("Canny threshold 1", 20, 200, ss.canny1, step=10)
        ss.canny2 = st.slider("Canny threshold 2", 40, 300, ss.canny2, step=10)

    if ss.upload and st.button("Generate Design", type="primary", use_container_width=True):
        ss.step = 2
        st.rerun()

# ---------------- Step 2: Processing ----------------
elif ss.step == 2:
    if not ss.upload:
        st.warning("Please upload a room photo to proceed.")
    else:
        img_bytes = ss.upload.getvalue()
        st.info("Working on your design… this may take ~30–60 seconds.")
        try:
            scene = analyze_architecture(img_bytes)
            if ss.design_mode == "Suggest Uplift Enhancements":
                brief = make_uplift_brief(ss.style_goal, scene)
                mode_flag = "uplift"
            else:
                brief = make_edit_brief(ss.style_goal, scene)
                mode_flag = "revamp"

            ss.result = edit_with_mask(
                img_bytes, brief,
                box_pad=ss.box_pad, mask_blur=ss.mask_blur,
                edge_px=ss.edge_thick, c1=ss.canny1, c2=ss.canny2,
                mode=mode_flag
            )
            ss.history = [("Initial", ss.result)]
            ss.step = 3
            st.rerun()
        except Exception as e:
            ss.error = str(e)
            ss.step = 3
            st.rerun()

# ---------------- Step 3: Refine My Design ----------------
elif ss.step == 3:
    st.markdown("### ✨ Your AI-Styled Room")
    cols = st.columns(2)
    with cols[0]:
        st.markdown("#### Original")
        if ss.upload:
            st.image(ss.upload, use_container_width=True)
    with cols[1]:
        st.markdown("#### Restyled")
        if ss.result:
            st.image(ss.result, use_container_width=True)
        else:
            st.error("❌ Generation failed.")
            if ss.error:
                st.exception(RuntimeError(ss.error))

    st.markdown("---")
    st.subheader("🔁 Refinement")
    feedback = st.text_input(
        "Describe further changes (e.g., 'Make rug blue, add floor lamp near window')",
        key="refine_prompt"
    )

    col_r1, col_r2, col_r3 = st.columns(3)
    with col_r1:
        if st.button("Apply Refinement", type="primary", disabled=not (feedback and ss.result)):
            try:
                # Pull bytes from last result (data URL or remote)
                if ss.result.startswith("data:image"):
                    b64_part = ss.result.split(",")[1]
                    img_bytes2 = base64.b64decode(b64_part)
                else:
                    import requests
                    img_bytes2 = requests.get(ss.result, timeout=30).content

                scene2 = analyze_architecture(img_bytes2)
                if ss.design_mode == "Suggest Uplift Enhancements":
                    brief2 = make_uplift_brief(f"{ss.style_goal}. User requested: {feedback}", scene2)
                    mode2 = "uplift"
                else:
                    brief2 = make_edit_brief(f"{ss.style_goal}. User requested: {feedback}", scene2)
                    mode2 = "revamp"

                new_result = edit_with_mask(
                    img_bytes2, brief2,
                    box_pad=ss.box_pad, mask_blur=ss.mask_blur,
                    edge_px=ss.edge_thick, c1=ss.canny1, c2=ss.canny2,
                    mode=mode2
                )
                ss.history.append((feedback, new_result))
                ss.result = new_result
                st.success("Refinement applied!")
                st.rerun()
            except Exception as e:
                st.error(f"Refinement failed: {e}")

    with col_r2:
        if st.button("Undo", disabled=len(ss.history) <= 1):
            if len(ss.history) > 1:
                ss.history.pop()
                ss.result = ss.history[-1][1]
                st.success("Reverted.")
                st.rerun()

    with col_r3:
        if st.button("Start Over"):
            for k in list(ss.keys()):
                del ss[k]
            st.rerun()

    if len(ss.history) > 1:
        st.markdown("---")
        st.subheader("🕓 Refinement History")
        for i, (desc, img_url) in enumerate(ss.history):
            st.markdown(f"**Step {i+1}:** {desc}")
            st.image(img_url, width=160, use_container_width=False)
