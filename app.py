# Bello Foyer – Final Flow (Pastel Theme, Edge Lock + Movable Mask, Refinement)

import os
import io
import json
import base64
from typing import List, Dict, Optional, Tuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageChops
import streamlit as st

# Optional: OpenCV for edge detection (edge lock)
try:
    import cv2
    HAS_CV2 = True
except Exception:
    HAS_CV2 = False

from openai import OpenAI

# ---------------- Streamlit Config ----------------
st.set_page_config(page_title="Bello Foyer – AI Room Restyle", page_icon="🏡", layout="centered")

# ---- Pastel Bello Foyer Theme (mobile-safe light mode) ----
def inject_bello_theme():
    st.markdown(
        """
<style>
/* Force light pastel BG across desktop & mobile (iOS dark-mode safe) */
html, body, [data-testid="stAppViewContainer"] {
    background-color: #fff8f9 !important;
    color-scheme: light !important;
}

/* Center the main content a bit tighter */
.block-container {
    padding-top: 1.2rem !important;
    max-width: 900px !important;
}

/* Inputs + buttons */
input, select, textarea, .stFileUploader, .stButton>button {
    background-color: #ffffff !important;
    color: #2d3436 !important;
    border-radius: 10px !important;
    border: 1px solid #e6e6e6 !important;
}

/* Primary Bello button */
.stButton > button {
    background-color: #2d6a4f !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    border: none !important;
    padding: 0.65rem 1.1rem !important;
    border-radius: 10px !important;
    transition: background-color 0.2s ease-in-out !important;
}
.stButton > button:hover {
    background-color: #1e4934 !important;
}

/* File uploader box */
[data-testid="stFileUploader"] {
    background-color: #ffffff !important;
    border-radius: 12px !important;
    border: 1px solid #eaeaea !important;
    padding: 0.8rem !important;
}

/* Light mode override even if device prefers dark */
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

# ---------------- API Key ----------------
api_key = None
try:
    api_key = st.secrets.get("OPENAI_API_KEY")
except Exception:
    api_key = None
if not api_key:
    api_key = os.getenv("OPENAI_API_KEY")
if not api_key:
    st.error("OpenAI API key missing. Please set OPENAI_API_KEY.")
    st.stop()

client = OpenAI(api_key=api_key)

# ---------------- Utility ----------------
def data_url(path: str) -> Optional[str]:
    if not os.path.exists(path):
        return None
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    # best-effort mime
    ext = (os.path.splitext(path)[1] or "").lower()
    mime = "image/png" if ext == ".png" else ("video/mp4" if ext == ".mp4" else "image/jpeg")
    return f"data:{mime};base64,{b64}"

def display_video_autoplay(path: str):
    vid = data_url(path)
    if not vid:
        return
    st.markdown(
        f"""
        <video width="100%" autoplay muted playsinline loop style="border-radius:16px; object-fit:cover; max-height: 380px;">
          <source src="{vid}" type="video/mp4" />
        </video>
        """,
        unsafe_allow_html=True,
    )

def b64_image(image_bytes: bytes) -> str:
    return base64.b64encode(image_bytes).decode("utf-8")

def pad_to_square(image: Image.Image) -> Image.Image:
    w, h = image.size
    side = max(w, h)
    bg = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    bg.paste(image, ((side - w)//2, (side - h)//2))
    return bg

def resize_1024(img: Image.Image) -> Image.Image:
    return img.resize((1024, 1024), Image.LANCZOS)

# ---------------- Vision: Movable Furniture Boxes ----------------
def detect_movable_boxes(image_bytes: bytes) -> List[Dict]:
    """
    Ask GPT-4o to return JSON: {"boxes":[{"label":"sofa","x":0.1,"y":0.2,"w":0.6,"h":0.3}, ...]}
    Normalized coords in [0..1]. Only MOVABLE items.
    """
    prompt = (
        "Detect MOVABLE furniture/decor in this room photo. "
        "Return ONLY a compact JSON object of the form: "
        "{\"boxes\":[{\"label\":\"sofa\",\"x\":0.1,\"y\":0.2,\"w\":0.6,\"h\":0.3}, ...]} "
        "All values normalized to 0..1. Include sofa, chair, rug, table, bed, lamp, shelf, decor. "
        "Exclude walls, windows, doors, ceiling, floor. No extra text."
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
            max_tokens=400
        )
        raw = resp.choices[0].message.content.strip()
        # best effort extract JSON
        start = raw.find("{")
        end = raw.rfind("}")
        j = raw[start:end+1] if start != -1 and end != -1 else "{}"
        data = json.loads(j)
        boxes = data.get("boxes", [])
        clean = []
        for b in boxes:
            try:
                x, y, w, h = float(b["x"]), float(b["y"]), float(b["w"]), float(b["h"])
                if 0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1:
                    clean.append({"x": x, "y": y, "w": w, "h": h})
            except Exception:
                continue
        return clean
    except Exception as e:
        print("detect_movable_boxes error:", e)
        return []

# ---------------- Edge Lock ----------------
def edge_lock_mask(img: Image.Image, thickness_px=6, canny1=80, canny2=160) -> Image.Image:
    """
    Returns RGBA mask where WHITE (opaque) == protected (no edit),
    BLACK/transparent == editable (we will combine with boxes mask using LIGHTER to preserve edges).
    """
    w, h = img.size
    if not HAS_CV2:
        # No edges protected if cv2 missing
        return Image.new("RGBA", (w, h), (0, 0, 0, 0))
    arr = np.array(img.convert("RGB"))[:, :, ::-1]
    gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, canny1, canny2)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (thickness_px, thickness_px))
    band = cv2.dilate(edges, kernel, iterations=1)
    L = Image.fromarray(band).convert("L").filter(ImageFilter.GaussianBlur(2))
    return Image.merge("RGBA", (L, L, L, L))

# ---------------- Boxes Mask (Revamp mode) ----------------
def boxes_mask(img: Image.Image, boxes: List[Dict], pad_px=12, blur_px=6) -> Image.Image:
    """
    Start with WHITE (opaque/protected). Draw furniture boxes as BLACK (transparent/editable).
    Feather for natural blend. Transparent = editable for OpenAI Images API.
    """
    w, h = img.size
    base_L = Image.new("L", (w, h), 255)  # opaque everywhere
    draw = ImageDraw.Draw(base_L)
    for b in boxes:
        x0 = max(0, int(b["x"] * w) - pad_px)
        y0 = max(0, int(b["y"] * h) - pad_px)
        x1 = min(w, int((b["x"] + b["w"]) * w) + pad_px)
        y1 = min(h, int((b["y"] + b["h"]) * h) + pad_px)
        draw.rectangle([x0, y0, x1, y1], fill=0)  # editable region
    base_L = base_L.filter(ImageFilter.GaussianBlur(blur_px))
    return Image.merge("RGBA", (base_L, base_L, base_L, base_L))

# ---------------- Uplift Mask (add-only, small safe zones) ----------------
def uplift_mask(img: Image.Image) -> Image.Image:
    """
    Allow tiny zones near floor/walls for small decor adds.
    WHITE = protected; BLACK = small editable spots.
    """
    w, h = img.size
    L = Image.new("L", (w, h), 255)
    d = ImageDraw.Draw(L)
    band_top = int(h * 0.78)
    band_h = int(h * 0.12)
    spot_w = int(w * 0.18)
    gap = int(w * 0.05)
    # three spots: left, center, right
    x_positions = [gap, (w - spot_w)//2, w - spot_w - gap]
    for x in x_positions:
        d.rounded_rectangle([x, band_top, x+spot_w, band_top+band_h], radius=14, fill=0)
    L = L.filter(ImageFilter.GaussianBlur(6))
    return Image.merge("RGBA", (L, L, L, L))

# ---------------- Architecture Analysis ----------------
def analyze_architecture(img_bytes: bytes) -> str:
    try:
        b64 = b64_image(img_bytes)
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe only the FIXED architecture: walls, windows, ceiling, floor, built-in lighting. Ignore furniture."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]
            }],
            max_tokens=200
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        return "Fixed architecture unchanged (walls, floor, ceiling, windows, lighting remain identical)."

# ---------------- Briefs ----------------
def make_brief_revamp(style_goal: str, scene_report: str) -> str:
    return f"""
A photorealistic professional photograph of the **same room**, identical camera angle, geometry, and overall light direction.
Do not change walls, windows, curtains, blinds, floor, ceiling, doors, built-in lighting, or their color/material.
Replace or rearrange **movable furniture & decor only** to match this style:
{style_goal}
Architecture reference (unchanged): {scene_report}
Keep perspective and scale exactly consistent with the photo; fit new items naturally.
"""

def make_brief_uplift(style_goal: str, scene_report: str) -> str:
    return f"""
A photorealistic professional photograph of the **same room**, identical camera angle, geometry, and lighting.
Absolutely **do not** remove or alter existing furniture, walls, windows, floor, or ceiling.
**Add up to three small accessories only** (e.g., a plant, small lamp, framed art, decorative objects) that complement this style:
{style_goal}
Place additions subtly in available floor/wall spots; respect perspective and scale.
Architecture reference (unchanged): {scene_report}
"""

def make_refine_brief(base_style: str, user_feedback: str, scene_report: str, mode: str) -> str:
    if mode == "Uplift":
        extra = "Do not remove existing items; only add small accessories per the request."
    else:
        extra = "Change only movable items; keep architecture identical."
    return f"""
A photorealistic professional photograph of the same room, identical camera, geometry and lighting.
User requested refinement: {user_feedback}
Style baseline: {base_style}
{extra}
Architecture reference (unchanged): {scene_report}
Keep perspective & scale consistent.
"""

# ---------------- Edit Function ----------------
def build_mask_for_mode(img: Image.Image, img_bytes: bytes, mode: str,
                        pad_px: int, blur_px: int, edge_px: int, c1: int, c2: int) -> Image.Image:
    if mode == "Uplift":
        m_main = uplift_mask(img)
    else:
        boxes = detect_movable_boxes(img_bytes)
        m_main = boxes_mask(img, boxes, pad_px=pad_px, blur_px=blur_px)
    m_edge = edge_lock_mask(img, thickness_px=edge_px, canny1=c1, canny2=c2)
    # LIGHTER = max() → keeps white where edges are (protected), black in editable zones
    L_final = ImageChops.lighter(m_main.split()[0], m_edge.split()[0])
    return Image.merge("RGBA", (L_final, L_final, L_final, L_final))

def edit_with_mask(img_bytes: bytes, brief: str, mode: str,
                   pad_px=12, blur_px=6, edge_px=6, c1=80, c2=160) -> str:
    """
    Returns a displayable data URL (b64) or a URL from the API.
    """
    # Prepare image & mask
    base_img = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    mask_rgba = build_mask_for_mode(base_img, img_bytes, mode, pad_px, blur_px, edge_px, c1, c2)
    img_sq = resize_1024(pad_to_square(base_img))
    mask_sq = resize_1024(pad_to_square(mask_rgba))

    img_io, mask_io = io.BytesIO(), io.BytesIO()
    img_sq.save(img_io, "PNG")
    mask_sq.save(mask_io, "PNG")
    img_io.seek(0)
    mask_io.seek(0)
    img_io.name = "image.png"
    mask_io.name = "mask.png"

    # Call Images Edit
    edit = client.images.edit(
        model="gpt-image-1",
        image=img_io,
        mask=mask_io,
        prompt=brief,
        size="1024x1024",
        n=1
    )
    d = edit.data[0]
    # Prefer b64 if present
    b64 = getattr(d, "b64_json", None)
    if b64:
        return "data:image/png;base64," + b64
    url = getattr(d, "url", None)
    if url:
        return url
    raise RuntimeError("Image API returned no usable data.")

# ---------------- Session State ----------------
ss = st.session_state
if "step" not in ss:
    ss.step = 1
    ss.upload = None
    ss.result = None
    ss.history: List[Tuple[str, str]] = []  # [(desc/prompt, image_url)]
    ss.style_choice = "Minimal"
    ss.mode = "Revamp"
    ss.error = None
    # mask controls
    ss.box_pad = 12
    ss.mask_blur = 6
    ss.edge_thick = 6
    ss.canny1 = 80
    ss.canny2 = 160

# ---------------- Step 1 — Welcome Screen ----------------
if ss.step == 1:
    # Logo
    logo_path = "assets/bello_logo.png"
    if os.path.exists(logo_path):
        st.image(logo_path, width=140, use_container_width=False)
    st.markdown("<h2 style='text-align:center;'>Welcome to <b>Bello Foyer</b></h2>", unsafe_allow_html=True)

    # Intro video
    display_video_autoplay("assets/intro.mp4")

    st.write("")
    if st.button("Get Started", type="primary", use_container_width=True):
        ss.step = 2
        st.rerun()

# ---------------- Step 2 — Design Studio ----------------
elif ss.step == 2:
    st.header("🎨 Design Studio")

    # Style dropdown
    styles = ["Minimal", "Modern", "Boho", "Scandi", "Industrial", "Classic", "Contemporary Luxe"]
    ss.style_choice = st.selectbox("Choose your style", styles, index=0)

    # Mode radio
    mode_label = st.radio(
        "Mode",
        options=["🧱 Revamp Full Room", "🌿 Suggest Uplift Enhancements"],
        index=0,
        horizontal=False
    )
    ss.mode = "Revamp" if mode_label.startswith("🧱") else "Uplift"

    # Upload
    ss.upload = st.file_uploader("Upload your room photo", type=["jpg", "jpeg", "png", "webp"])
    if ss.upload:
        st.image(ss.upload, caption="Your room", use_container_width=True)

    with st.expander("Advanced mask controls"):
        ss.box_pad = st.slider("Furniture padding (px)", 4, 30, ss.box_pad, 2)
        ss.mask_blur = st.slider("Mask feather (px)", 2, 16, ss.mask_blur, 1)
        ss.edge_thick = st.slider("Edge lock thickness (px)", 2, 18, ss.edge_thick, 1)
        ss.canny1 = st.slider("Canny threshold 1", 20, 200, ss.canny1, 10)
        ss.canny2 = st.slider("Canny threshold 2", 40, 300, ss.canny2, 10)

    col_run = st.columns(1)[0]
    with col_run:
        if st.button("Generate Design", type="primary", use_container_width=True, disabled=not ss.upload):
            if not ss.upload:
                st.warning("Please upload a photo first.")
            else:
                # Process
                img_bytes = ss.upload.getvalue()
                with st.spinner("Analyzing architecture..."):
                    scene = analyze_architecture(img_bytes)

                # Brief per mode
                style_goal_text = {
                    "Minimal": "Minimal, calm, airy, neutral palette, clean lines.",
                    "Modern": "Modern, sleek, neutral with occasional bold accents.",
                    "Boho": "Boho, layered textures, natural materials, relaxed & warm.",
                    "Scandi": "Scandinavian, light wood, white walls, cozy minimalism.",
                    "Industrial": "Industrial with warm accents; metal + wood, neutral fabric.",
                    "Classic": "Classic, timeless, balanced forms, subtle patterns.",
                    "Contemporary Luxe": "Contemporary luxe, soft neutrals, brass accents, plush textures."
                }.get(ss.style_choice, ss.style_choice)

                if ss.mode == "Uplift":
                    brief = make_brief_uplift(style_goal_text, scene)
                else:
                    brief = make_brief_revamp(style_goal_text, scene)

                with st.spinner("Generating your design (this can take ~30–60s)..."):
                    try:
                        ss.result = edit_with_mask(
                            img_bytes, brief, ss.mode,
                            pad_px=ss.box_pad, blur_px=ss.mask_blur,
                            edge_px=ss.edge_thick, c1=ss.canny1, c2=ss.canny2
                        )
                        ss.history = [("Initial", ss.result)]
                        ss.error = None
                        ss.step = 3
                        st.rerun()
                    except Exception as e:
                        ss.error = str(e)
                        ss.result = None
                        ss.step = 3
                        st.rerun()

    st.write("")
    if st.button("Back", use_container_width=True):
        ss.step = 1
        st.rerun()

# ---------------- Step 3 — Refine My Design ----------------
elif ss.step == 3:
    st.header("🛠️ Refine My Design")

    cols = st.columns(2)
    with cols[0]:
        st.markdown("#### Original")
        if ss.upload:
            st.image(ss.upload, use_container_width=True)
    with cols[1]:
        st.markdown("#### AI-Styled")
        if ss.result:
            st.image(ss.result, use_container_width=True)
        else:
            st.error("❌ Failed to generate.")
            if ss.error:
                st.exception(RuntimeError(ss.error))

    st.markdown("---")
    st.subheader("💬 Refinement")
    refine = st.text_input(
        "Suggest adjustments",
        placeholder="e.g., Add a floor lamp near the window; make the rug blue; add two pillows",
        label_visibility="collapsed"
    )

    c1, c2, c3 = st.columns(3)
    with c1:
        if st.button("Apply Refinement", type="primary", use_container_width=True, disabled=not (refine and ss.result)):
            try:
                # Use the last generated image as input
                if ss.result.startswith("data:image"):
                    img_bytes = base64.b64decode(ss.result.split(",")[1])
                else:
                    import requests
                    img_bytes = requests.get(ss.result, timeout=30).content

                # Keep same architecture description for consistency
                scene = analyze_architecture(img_bytes)
                brief = make_refine_brief(
                    base_style=ss.style_choice,
                    user_feedback=refine,
                    scene_report=scene,
                    mode=ss.mode
                )
                with st.spinner("Applying refinement..."):
                    new_img = edit_with_mask(
                        img_bytes, brief, ss.mode,
                        pad_px=ss.box_pad, blur_px=ss.mask_blur,
                        edge_px=ss.edge_thick, c1=ss.canny1, c2=ss.canny2
                    )
                ss.history.append((refine, new_img))
                ss.result = new_img
                st.success("Refinement applied!")
                st.rerun()
            except Exception as e:
                st.error(f"Refinement failed: {e}")

    with c2:
        if st.button("Undo Last Change", use_container_width=True, disabled=len(ss.history) <= 1):
            if len(ss.history) > 1:
                ss.history.pop()
                ss.result = ss.history[-1][1]
                st.success("Reverted to previous version.")
                st.rerun()

    with c3:
        if st.button("Start Over", use_container_width=True):
            for k in list(ss.keys()):
                del ss[k]
            st.rerun()

    if len(ss.history) > 1:
        st.markdown("---")
        st.subheader("🕓 Refinement History")
        for i, (desc, img_url) in enumerate(ss.history):
            st.markdown(f"**Step {i+1}:** {desc}")
            st.image(img_url, use_container_width=True)
