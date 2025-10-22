# Bello Foyer — Final Streamlit App (fixed OpenAI client + image edit)
import os
import io
import base64
import mimetypes
import time # Added for splash screen delay
from typing import Optional, List, Dict, Any # Added Dict, Any
from PIL import Image, ImageDraw
import random # Added for simulating prices
import json # Added for parsing AI product recognition

import streamlit as st

# ===== OpenAI (modern 1.x client) =====
from openai import OpenAI

# --------------------- Page Config ---------------------
# Use wide layout to better control centering with CSS
st.set_page_config(page_title="Bello Foyer – AI Styling Demo", page_icon="🏡", layout="wide")

# --------------------- Load API Key ---------------------
api_key = None
try:
    # Use st.secrets.get for safer access
    api_key = st.secrets.get("OPENAI_API_KEY")
except Exception: # Broad exception for cases where secrets might not be configured
    api_key = None

if not api_key:
    api_key = os.getenv("OPENAI_API_KEY")

if not api_key:
    # Display error and stop if key is missing
    st.error("OpenAI API key not found. Please configure it in your Streamlit secrets or as an environment variable (`OPENAI_API_KEY`).")
    st.stop()

# Initialize OpenAI client
client = OpenAI(api_key=api_key)

# --------------------- Helpers ---------------------
def data_url(path: str) -> Optional[str]:
    """Return data:image/...;base64,... for a local file, or None if missing."""
    if not os.path.exists(path):
        st.warning(f"Asset not found: {path}") # Add warning for missing assets
        return None
    mime, _ = mimetypes.guess_type(path)
    mime = mime or "image/jpeg" # Default mime type
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    return f"data:{mime};base64,{b64}"

def display_video_autoplay(path: str):
    video_data = data_url(path) # Use data_url to get base64
    if video_data:
        st.markdown(
            f"""
            <video width="100%" autoplay muted playsinline loop style="border-radius:16px; object-fit: cover; height: 100%;">
              <source src="{video_data}" type="video/mp4" />
            </video>
            """,
            unsafe_allow_html=True,
        )

def make_architecture_preserving_mask(size: tuple[int, int]) -> bytes:
    """
    Locks walls, windows, floor, ceiling by default.
    Only a lower-central band is transparent (editable).
    """
    w, h = size
    mask = Image.new("RGBA", (w, h), (0, 0, 0, 255))  # OPAQUE = protected
    draw = ImageDraw.Draw(mask)

    # Define editable zone (transparent)
    left = int(w * 0.15)
    right = int(w * 0.85)
    top = int(h * 0.55)
    bottom = int(h * 0.95)

    draw.rectangle([left, top, right, bottom], fill=(0, 0, 0, 0))  # TRANSPARENT = editable

    buf = io.BytesIO()
    mask.save(buf, format="PNG")
    return buf.getvalue()


# --------------------- AI Calls ---------------------
# Removed show_spinner from decorators as calls are wrapped in spinners in Step 5.5
@st.cache_data
def generate_customer_profile(style_tags: List[str]) -> str:
    """Small prompt that turns chosen tags into a concise style profile paragraph."""
    tags_string = ", ".join(sorted(set(style_tags))) if style_tags else "modern, neutral, balanced"
    prompt = (
        "Based on these interior design style tags, write a very concise summary (2-3 lines maximum) "
        "of the user's style profile. Start the summary with 'Your design profile suggests a love for...'. "
        "This summary will guide an AI image generator.\n\n"
        f"Selected Style Tags: {tags_string}"
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful interior design assistant skilled at brevity."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=100,
        )
        message = resp.choices[0].message
        return message.content.strip() if message and message.content else "Could not generate profile content."
    except Exception as e:
        # Avoid showing Streamlit error directly in cached function
        # Log error instead (e.g., import logging; logging.error(...))
        print(f"Profile Generation Error: {e}")
        return "Your design profile suggests a love for calm, modern spaces. (Default due to error)"

@st.cache_data
def analyze_room_architecture(image_bytes: bytes) -> str:
    """Use vision to describe fixed architectural features only."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text":
                        "Analyze this room's permanent architectural features (layout, flooring, windows, doors, fixed lighting). "
                        "Do NOT describe movable furniture or decor. Keep it concise (2-3 sentences max)."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]
            }],
            max_tokens=150,
        )
        message = resp.choices[0].message
        return message.content.strip() if message and message.content else "Could not analyze room features."
    except Exception as e:
        print(f"Room Analysis Error: {e}")
        return "Analysis unavailable. Assuming a standard living room with windows and neutral walls."

@st.cache_data
def create_design_brief(profile: str, scene_report: str) -> str:
    """Turn style + fixed architecture into a photoreal brief that gpt-image-1 understands."""
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system",
                 "content": "You are a world-class interior designer. Produce a single-paragraph brief for an AI image generator."},
                {"role": "user",
                 "content": (
                     "Create a photorealistic brief starting with 'A photorealistic professional photograph of...'. "
                     "The resulting image must keep ALL architecture exactly the same: walls, floor, ceiling, windows, doors, fixed lighting, and layout. "
                     "Only change MOVABLE items (furniture, rugs, decor, art, curtains, plants). Do not modify wall color, floor material, window size or placement. "
                     "Obey the fixed architectural elements in the scene report; make no structural/civil changes."
                     f"\n\nUser Style Preference: {profile}\n\n"
                     f"Scene Report (Unchangeable Structure): {scene_report}"
                 )}
            ],
            max_tokens=700,
        )
        brief = resp.choices[0].message.content.strip()
        brief += (
            "\n\nIMPORTANT INSTRUCTION: When adding decor or furniture, fit the scale and perspective "
            "of the existing room exactly as in the photo. Place items only within the transparent mask area "
            "and do not change architectural surfaces (walls, floor, ceiling, windows, or lighting)."
        )
        return brief
    except Exception as e:
        print(f"Design Brief Error: {e}")
        return (
            "A photorealistic professional photograph of a modern, calm living room with soft natural light, "
            "matching the user's taste. Ensure architecture remains identical."
        )

# Removed cache and spinner from edit function
def edit_room_image_with_brief(processed_png_bytes: bytes, brief: str) -> str:
    """
    Use the *masked edit* endpoint. OPAQUE mask = preserved pixels, TRANSPARENT = editable.
    Returns a URL that Streamlit can display.
    """
    img_io = io.BytesIO(processed_png_bytes)
    img_io.name = "input.png"
    mask_bytes = make_architecture_preserving_mask((1024, 1024))
    mask_io = io.BytesIO(mask_bytes)
    mask_io.name = "mask.png"

    try:
        edit = client.images.edit(
            model="gpt-image-1",
            image=img_io,
            mask=mask_io,
            prompt=brief,
            size="1024x1024",
            n=1,
        )
        url = getattr(edit.data[0], "url", None)
        if url:
             return url
        b64 = getattr(edit.data[0], "b64_json", None)
        if b64:
             return "data:image/png;base64," + b64
        raise RuntimeError("Image API returned neither URL nor b64_json (edit).")
    except Exception as e:
        # Raise the specific error for handling in the calling step
        raise RuntimeError(f"Image generation failed: {e}") from e

def preprocess_to_square_png(image_bytes: bytes) -> bytes:
    """Center-crop to square and resize to 1024x1024 PNG."""
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA")
        w, h = img.size
        if w != h:
            side = min(w, h)
            left = (w - side) // 2
            top = (h - side) // 2
            img = img.crop((left, top, left + side, top + side))
        if img.size != (1024, 1024):
            img = img.resize((1024, 1024), Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    except Exception as e:
        st.error(f"Image preprocessing failed: {e}")
        raise

@st.cache_data(show_spinner="Describing image...")
def describe_image_content(image_url: str) -> str:
    """Uses AI to provide a concise 2-3 line description of the image content."""
    if not image_url: return "No image to describe."
    try:
        image_input = {"url": image_url} # Works for both data and regular URLs with GPT-4o
        prompt = "Describe the interior design in this image in 2-3 concise sentences. Focus on furniture, decor, and overall style."
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": [ {"type": "text", "text": prompt}, {"type": "image_url", "image_url": image_input} ]}],
            max_tokens=100
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"Image description failed: {e}")
        return "A beautiful AI-styled room with a modern touch."

@st.cache_data(show_spinner="Identifying products...")
def recognize_products_in_image(image_url: str) -> List[Dict[str, Any]]:
    """Uses AI to identify products in the generated image."""
    if not image_url: return []
    try:
        image_input = {"url": image_url}
        prompt = """
        Analyze the provided interior design image. Identify the main furniture and decor items visible.
        For each item, provide a short descriptive name (e.g., 'Mid-Century Modern Armchair')
        and estimate a plausible price in Indian Rupees (INR), formatted as just the number (e.g., 45000).
        Return results as a JSON list of objects, each with 'name' and 'price' keys.
        Example: [{"name": "Velvet Cushion", "price": 1500}, {"name": "Oak Coffee Table", "price": 25000}]
        Limit to 5-7 main items.
        """
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": [ {"type": "text", "text": prompt}, {"type": "image_url", "image_url": image_input} ]}],
            response_format={"type": "json_object"},
            max_tokens=1000
        )
        content = response.choices[0].message.content
        try:
            result_data = json.loads(content)
            product_list_key = next((key for key in result_data if isinstance(result_data.get(key), list)), None)
            products = result_data[product_list_key] if product_list_key else (result_data if isinstance(result_data, list) else [])
        except (json.JSONDecodeError, Exception) as parse_e:
            st.warning(f"Error parsing AI product response: {parse_e}. Using placeholders.")
            products = []
        final_products = []
        for i, p in enumerate(products):
            if isinstance(p, dict) and 'name' in p and 'price' in p:
                try: final_products.append({"id": i + 1, "name": str(p['name']), "price": int(p['price'])})
                except (ValueError, TypeError): continue
        return final_products
    except Exception as e:
        print(f"AI Product Recognition Failed: {e}")
        return [ {"id": 1, "name": "Modern Sectional Sofa", "price": random.randint(35000, 85000)}, {"id": 2, "name": "Textured Area Rug", "price": random.randint(7000, 22000)}, {"id": 3, "name": "Floor Lamp", "price": random.randint(3000, 9000)}]

# --------------------- Session ---------------------
ss = st.session_state
if "step" not in ss:
    ss.step = 0
    ss.quiz_choices = {2: None, 3: None, 4: None}
    ss.customer_profile = None
    ss.uploaded_file = None
    ss.styled_image_url = None
    ss.last_error = None
    ss.shop_items = []
    ss.buy_now_clicked = False
    ss.image_description = None

# --------------------- Main App Container ---------------------
# Apply container only after splash
if ss.step != 0:
    st.markdown('<div class="main-container">', unsafe_allow_html=True)

# --------------------- UI ---------------------

# Step 0 — Splash Screen
if ss.step == 0:
    splash_bg_path = "assets/splash_background.jpg"
    splash_bg_data_url = data_url(splash_bg_path)
    logo_data_url = data_url("assets/bello_logo.png")
    st.markdown(f""" <style> /* Hide default Streamlit elements during splash */ .block-container {{ padding: 0 !important; margin: 0 !important; max-width: none !important; }} header[data-testid="stHeader"], footer {{ display: none !important; }} .main-container {{ max-width: none !important; margin: 0 !important; padding: 0 !important; }} .splash-screen {{ position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; display: flex; justify-content: center; align-items: center; background-image: url('{splash_bg_data_url if splash_bg_data_url else ""}'); background-size: cover; background-position: center; z-index: 9999; }} .splash-logo {{ max-width: 250px; animation: fadeIn 1.5s ease-in-out; }} @keyframes fadeIn {{ from {{ opacity: 0; transform: scale(0.9); }} to {{ opacity: 1; transform: scale(1); }} }} </style> """, unsafe_allow_html=True)
    if logo_data_url: st.markdown(f""" <div class="splash-screen"> <img src="{logo_data_url}" class="splash-logo"> </div> """, unsafe_allow_html=True)
    else: st.markdown("<div class='splash-screen'><h1 style='color: white;'>Bello Foyer</h1></div>", unsafe_allow_html=True)
    time.sleep(2); ss.step = 1; st.rerun()

# Step 1 — Welcome
elif ss.step == 1:
    st.markdown(f""" <div class="top-bar"> <div class="logo-container"> <img src="{data_url("assets/bello_logo.png")}" class="logo-img"> </div> <h3 class="header-title">Bello Foyer</h3> <div class="menu-wrap"> <input type="checkbox" class="toggler"> <div class="hamburger"><div></div></div> <div class="menu"> <div> <div> <ul> <li><a href="#">Home</a></li> <li><a href="#">Catalogue (Not Live)</a></li> <li><a href="#">Contact Us</a></li> </ul> </div> </div> </div> </div> </div> """, unsafe_allow_html=True)
    st.markdown("<div class='welcome-content'>", unsafe_allow_html=True)
    col1, col2 = st.columns([1, 1.1])
    with col1: display_video_autoplay("assets/intro.mp4")
    with col2:
        st.markdown("<h1 class='welcome-headline'>Reimagine Your Space.<br>Instantly.</h1>", unsafe_allow_html=True)
        if st.button("Get Started", type="primary", use_container_width=True): ss.step = 2; st.rerun()
        st.markdown(""" <p class='welcome-text'> Welcome to Bello Foyer... </p> """, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

# Steps 2–4 — Visual Quiz
elif ss.step in [2, 3, 4]:
    st.markdown("<div class='quiz-container'>", unsafe_allow_html=True) # Add container for padding
    visual_quiz = {
        2: {"title": "Which look do you like better?", "options": {"quiz1_A.jpg": ["minimal", "natural_light"], "quiz1_B.jpg": ["modern", "clean_lines"]}},
        3: {"title": "Which look do you like better?", "options": {"quiz2_A.jpg": ["boho", "textured"], "quiz2_B.jpg": ["scandi", "light_wood"]}},
        4: {"title": "Which look do you like better?", "options": {"quiz3_A.jpg": ["industrial", "metal_wood"], "quiz3_B.jpg": ["modern"]}},
    }
    info = visual_quiz[ss.step]
    st.markdown(f"<p style='text-align:center;'>Getting to know you ({ss.step-1}/3)</p>", unsafe_allow_html=True)
    st.markdown(f"<h2 style='text-align:center;'>{info['title']}</h2>", unsafe_allow_html=True)
    files = list(info["options"].keys())
    cols = st.columns(2)
    for i, col in enumerate(cols):
        with col:
            fname = files[i]; p = os.path.join("assets", fname)
            if not os.path.exists(p): st.error(f"Missing: {p}")
            else:
                st.image(p, use_container_width=True)
                if st.button("I like this one", key=f"pick_{fname}", use_container_width=True, type="primary"):
                    ss.quiz_choices[ss.step] = info["options"][fname]; ss.step = 5 if ss.step == 4 else ss.step + 1; st.rerun()
    st.markdown("---")
    if st.button("Back", use_container_width=True): ss.step = 1 if ss.step == 2 else ss.step - 1; st.rerun()
    st.markdown("</div>", unsafe_allow_html=True) # Close quiz container

# Step 5 — Redesign Studio
elif ss.step == 5:
    st.markdown("<h2 style='text-align:center;'>Your Redesign Studio</h2>", unsafe_allow_html=True)
    profile_placeholder = st.empty(); profile_placeholder.info("Analyzing style...")
    if "customer_profile" not in ss or not ss.customer_profile:
        tags: List[str] = []; [tags.extend(ss.quiz_choices[k]) for k in sorted(ss.quiz_choices.keys()) if ss.quiz_choices[k]]
        ss.customer_profile = generate_customer_profile(tags or ["modern"])
    profile_placeholder.empty()
    # Check if profile is not None before displaying
    if ss.customer_profile:
        with st.expander("Your AI-Generated Design Profile", expanded=True): st.markdown(ss.customer_profile)
    else:
        st.warning("Could not generate design profile. Using default settings.")
        ss.customer_profile = "A beautiful modern style." # Provide a default if generation failed

    st.markdown("---"); st.markdown("<h3 style='text-align:center;'>Let's Transform Your Room</h3>", unsafe_allow_html=True)
    col_upload, col_cam = st.columns(2)
    with col_upload: uploaded_file = st.file_uploader("Upload Now", type=["jpg", "png", "webp"])
    with col_cam: camera_file = st.camera_input("Open Camera")
    input_file = camera_file if camera_file is not None else uploaded_file
    if input_file: ss.uploaded_file = input_file
    if ss.uploaded_file:
        st.image(ss.uploaded_file, caption="Your room", use_container_width=True)
        if st.button("Redesign My Room", type="primary", use_container_width=True):
            ss.last_error = None; ss.image_description = None; ss.styled_image_url = None
            ss.step = 5.5; st.rerun()
    st.markdown("---")
    if st.button("Back"): ss.step = 4; st.rerun()

# Step 5.5 - Processing Screen
elif ss.step == 5.5:
    st.markdown("<h2 style='text-align:center;'>Creating Your Design...</h2>", unsafe_allow_html=True)
    if ss.uploaded_file: st.image(ss.uploaded_file, caption="Processing...", use_container_width=True)
    st.markdown("---")
    status_placeholder = st.empty()
    try:
        if not ss.uploaded_file: raise ValueError("No file uploaded.")
        img_bytes = ss.uploaded_file.getvalue()
        status_placeholder.info("⏳ Analyzing room..."); scene = analyze_room_architecture(img_bytes)
        status_placeholder.info("🎨 Creating brief...");
        if not ss.customer_profile: # Regenerate profile if somehow missing
             tags: List[str] = []; [tags.extend(ss.quiz_choices[k]) for k in sorted(ss.quiz_choices.keys()) if ss.quiz_choices[k]]
             ss.customer_profile = generate_customer_profile(tags or ["modern"])
        brief = create_design_brief(ss.customer_profile, scene)
        status_placeholder.info("🖼️ Preprocessing..."); png_bytes = preprocess_to_square_png(img_bytes)
        status_placeholder.info("✨ Generating design..."); ss.styled_image_url = edit_room_image_with_brief(png_bytes, brief)
        status_placeholder.success("✅ Done!"); time.sleep(1)
        ss.last_error = None; ss.step = 6; st.rerun()
    except Exception as e:
        ss.last_error = str(e); ss.styled_image_url = None; ss.step = 6; st.rerun()

# Step 6 — Results
elif ss.step == 6:
    st.markdown("<h2 style='text-align:center;'>Your AI-Styled Home</h2>", unsafe_allow_html=True)
    if ss.styled_image_url:
        st.image(ss.styled_image_url, use_container_width=True)
        if "image_description" not in ss or not ss.image_description: ss.image_description = describe_image_content(ss.styled_image_url)
        st.markdown(f"<p class='image-description'>{ss.image_description}</p>", unsafe_allow_html=True)
    else: st.error(f"Failed: {ss.last_error or 'Unknown'}")
    st.markdown("---")
    st.markdown("<h5>Suggest Changes:</h5>", unsafe_allow_html=True)
    st.text_input("Suggest changes", placeholder="e.g., 'Make rug blue'", label_visibility="collapsed", disabled=True)
    st.caption("_(Live editing coming soon!)_")
    st.markdown("---")
    cL, cR = st.columns(2)
    with cL:
        if st.button("Start Over", use_container_width=True):
            keys = ["step", "quiz_choices", "customer_profile", "uploaded_file", "styled_image_url", "last_error", "shop_items", "buy_now_clicked", "image_description"]
            for k in keys:
                 if k in ss: del ss[k]
            st.cache_data.clear(); st.rerun()
    with cR:
        shop_disabled = not ss.styled_image_url
        if st.button("Shop the Look", type="primary", use_container_width=True, disabled=shop_disabled):
            ss.buy_now_clicked = False; ss.shop_items = recognize_products_in_image(ss.styled_image_url)
            ss.step = 7; st.rerun()

# Step 7 — Shop the Look
elif ss.step == 7:
    # (Shop the Look code remains largely the same)
    st.markdown("<h2 style='text-align:center;'>Shop the Look</h2>", unsafe_allow_html=True)
    if not ss.styled_image_url: st.warning("No image."); st.stop()
    st.image(ss.styled_image_url, caption="AI Concept", use_container_width=True)
    st.markdown("---"); st.markdown("<h4>Items:</h4>", unsafe_allow_html=True)
    if "shop_items" not in ss or not ss.shop_items: ss.shop_items = recognize_products_in_image(ss.styled_image_url)
    if "buy_now_clicked" not in ss: ss.buy_now_clicked = False
    total_price = 0
    for item in list(ss.shop_items):
        col1, col2 = st.columns([0.85, 0.15])
        with col1: st.markdown(f"<div class='shop-item-line'><span>{item['name']}</span><span>₹{item['price']:,}</span></div>", unsafe_allow_html=True)
        with col2:
            if st.button("X", key=f"remove_{item['id']}", help="Remove"):
                ss.shop_items = [i for i in ss.shop_items if i['id'] != item['id']]; st.rerun()
    total_price = sum(item['price'] for item in ss.shop_items)
    st.markdown("---"); st.markdown(f"<h4 style='text-align:right;'>Total: ₹{total_price:,}</h4>", unsafe_allow_html=True)
    buy_now_placeholder = st.empty()
    if ss.buy_now_clicked:
        buy_now_placeholder.success("Thank you! Team will contact you.")
        st.button("Buy Now", type="primary", use_container_width=True, disabled=True, key="buy_now_dis")
    else:
        if buy_now_placeholder.button("Buy Now", type="primary", use_container_width=True, disabled=(total_price == 0), key="buy_now_act"):
            ss.buy_now_clicked = True; st.rerun()
    st.markdown("---")
    col_back, col_start_over = st.columns(2)
    with col_back:
        if st.button("Back to Results", use_container_width=True, disabled=ss.buy_now_clicked):
            ss.step = 6; ss.buy_now_clicked = False; st.rerun()
    with col_start_over:
        if st.button("Start Over", use_container_width=True, key="shop_start_over", disabled=ss.buy_now_clicked):
            keys = ["step", "quiz_choices", "customer_profile", "uploaded_file", "styled_image_url", "last_error", "shop_items", "buy_now_clicked", "image_description"]
            for k in keys:
                 if k in ss: del ss[k]
            st.cache_data.clear(); st.rerun()

# --------------------- Custom CSS for Layout and Style ---------------------
st.markdown(f"""
<style>
    /* Base styles */
    body {{ background:#fff8f9; font-family: 'Inter', sans-serif; margin: 0; }}
    /* Give content breathing room, except splash */
    .block-container {{ padding: {'0' if ss.step == 0 else '2rem 1rem'}; }}
    .main-container {{ max-width: {'none' if ss.step == 0 else '900px'}; margin: auto; }}
    /* Ensure Streamlit headers/footers are hidden when appropriate */
     header[data-testid="stHeader"], footer {{ display: {'none' if ss.step == 0 else 'block !important'}; }}

    /* Splash screen styles */
    .splash-screen {{ position: fixed; ... }} .splash-logo {{ ... }} @keyframes fadeIn {{ ... }}

    /* Top bar styles */
    .top-bar {{ display: {'flex' if ss.step == 1 else 'none'}; ... }}
    .logo-img {{ height: 40px; ... }} .header-title {{ font-size: 1.5rem; ... }} .menu-wrap {{ ... }}

    /* Welcome screen styles */
    .welcome-content {{ ... }} .welcome-headline {{ font-size: 2.5rem; ... }} .welcome-text {{ ... }}

    /* Quiz container padding */
    .quiz-container {{ padding-top: 2rem; }}

    /* Hamburger menu styles */
    .menu-wrap .toggler {{ ... }} .menu-wrap .hamburger {{ ... }} .menu-wrap .menu {{ ... }}

    /* Results screen styles */
    .image-description {{ text-align: center; ... }}

    /* Shop the Look styles */
    .shop-item-line {{ display: flex; ... }}
    .item-name {{ ... }} .item-price {{ ... }}

    /* Responsive styles */
    @media (max-width: 768px) {{
        .block-container {{ padding: {'0' if ss.step == 0 else '1rem'}; }}
        .header-title {{ font-size: 1.1rem; ... }} .logo-img {{ height: 30px; ... }}
        .welcome-headline {{ font-size: 1.8rem; ... }} .welcome-text {{ font-size: 0.9rem; ... }}
        .welcome-content > .st-emotion-cache-1b202tt {{ flex-direction: column !important; }}
        /* Mobile stacking order fixes */
        .welcome-content > .st-emotion-cache-1b202tt > div:nth-child(1) {{ order: 2; margin-top: 1.5rem; }} /* Video */
        .welcome-content > .st-emotion-cache-1b202tt > div:nth-child(2) {{ order: 1; }} /* Text block */
        .welcome-content > .st-emotion-cache-1b202tt > div:nth-child(2) > .welcome-headline {{ order: 1; }}
        .welcome-content > .st-emotion-cache-1b202tt > div:nth-child(2) > .stButton {{ order: 2; }}
        .welcome-content > .st-emotion-cache-1b202tt > div:nth-child(2) > .welcome-text {{ order: 3; }}
        .quiz-container {{ padding-top: 1rem; }}
         /* Shop item mobile layout */
        .shop-item-line {{ padding: 0.7rem 0; }} /* More space */
        .stButton>button[key*="remove_"] {{ padding: 0.1rem 0.4rem; font-size: 1rem; }} /* Smaller remove button */
    }}

    /* Button Styles */
    .stButton>button {{ background:#2d6a4f; border-radius: 8px; ... }} /* Slightly smaller radius */
    .stButton>button:hover {{ background: #1e4934; ... }} .stButton>button:disabled {{ background: #adb5bd; ... }}
    .stButton>button[kind="secondary"] {{ background:#e9ecef; ... }}
    .stButton>button[key*="remove_"] {{ background: none; color: #dc3545; ... }}
    /* Remove focus outline/border */
    .stButton>button:focus {{ outline: none !important; box-shadow: none !important; border: none !important; }}

</style>
""", unsafe_allow_html=True)

# Close main container
if ss.step != 0: st.markdown('</div>', unsafe_allow_html=True)

