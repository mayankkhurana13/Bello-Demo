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
# Use wide layout initially, but control width with containers
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
        print(f"Warning: Asset not found at {path}")
        return None
    mime, _ = mimetypes.guess_type(path)
    mime = mime or "image/jpeg" # Default mime type
    try:
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"data:{mime};base64,{b64}"
    except Exception as e:
        print(f"Error reading or encoding file {path}: {e}")
        return None


def display_video_autoplay(path: str):
    video_data = data_url(path) # Use data_url to get base64
    if video_data:
        st.markdown(
            f"""
            <video width="100%" autoplay muted playsinline loop style="border-radius:16px; object-fit: cover; height: 100%; max-height: 400px;">
              <source src="{video_data}" type="video/mp4" />
              Your browser does not support the video tag.
            </video>
            """,
            unsafe_allow_html=True,
        )
    # else: st.warning("Intro video asset missing.") # Optional: uncomment for debugging

def make_architecture_preserving_mask(size: tuple[int, int]) -> bytes:
    """
    Locks walls, windows, floor, ceiling by default.
    Only a lower-central band is transparent (editable).
    """
    w, h = size
    mask = Image.new("RGBA", (w, h), (0, 0, 0, 255))  # OPAQUE = protected
    draw = ImageDraw.Draw(mask)
    left = int(w * 0.15); right = int(w * 0.85)
    top = int(h * 0.55); bottom = int(h * 0.95)
    draw.rectangle([left, top, right, bottom], fill=(0, 0, 0, 0))  # TRANSPARENT = editable
    buf = io.BytesIO(); mask.save(buf, format="PNG"); return buf.getvalue()


# --------------------- AI Calls ---------------------
# Removed show_spinner from decorators as calls are wrapped in spinners in Step 5.5
@st.cache_data
def generate_customer_profile(style_tags: List[str]) -> str:
    tags_string = ", ".join(sorted(set(style_tags))) if style_tags else "modern, neutral, balanced"
    prompt = f"Write a very concise summary (2-3 lines max) of a user's interior design style based on these tags: {tags_string}. Start with 'Your design profile suggests...'"
    try:
        resp = client.chat.completions.create( model="gpt-4o", messages=[ {"role": "system", "content": "You are a helpful interior design assistant skilled at brevity."}, {"role": "user", "content": prompt}, ], max_tokens=100)
        message = resp.choices[0].message
        return message.content.strip() if message and message.content else "Could not generate profile content."
    except Exception as e: print(f"Profile Generation Error: {e}"); return "Your design profile suggests a love for calm, modern spaces. (Default due to error)"

@st.cache_data
def analyze_room_architecture(image_bytes: bytes) -> str:
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    try:
        resp = client.chat.completions.create( model="gpt-4o", messages=[{"role": "user", "content": [ {"type": "text", "text": "Analyze permanent architectural features (layout, floor, windows, doors, lights). Ignore furniture/decor. Be concise (2-3 sentences max)."}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}} ]}], max_tokens=150)
        message = resp.choices[0].message
        return message.content.strip() if message and message.content else "Could not analyze room features."
    except Exception as e: print(f"Room Analysis Error: {e}"); return "Analysis unavailable."

@st.cache_data
def create_design_brief(profile: str, scene_report: str) -> str:
    try:
        resp = client.chat.completions.create( model="gpt-4o", messages=[ {"role": "system", "content": "You are a world-class interior designer. Produce a single-paragraph brief."}, {"role": "user", "content": f"Create a photorealistic brief starting with 'A photorealistic professional photograph of...'. Keep ALL architecture (walls, floor, ceiling, windows, doors, layout, fixed lights) EXACTLY the same. Only change MOVABLE items (furniture, rugs, decor, art, plants). Make no structural changes. \n\nUser Style Preference: {profile}\n\nScene Report (Unchangeable Structure): {scene_report}" }], max_tokens=700)
        brief = resp.choices[0].message.content.strip()
        brief += "\n\nIMPORTANT: Fit scale/perspective exactly. Place items only in transparent mask area. Do not change architecture."
        return brief
    except Exception as e: print(f"Design Brief Error: {e}"); return f"A photorealistic professional photograph of a room matching the user's taste: {profile}. Architecture must remain identical."

def edit_room_image_with_brief(processed_png_bytes: bytes, brief: str) -> str:
    img_io = io.BytesIO(processed_png_bytes); img_io.name = "input.png"
    mask_bytes = make_architecture_preserving_mask((1024, 1024)); mask_io = io.BytesIO(mask_bytes); mask_io.name = "mask.png"
    try:
        edit = client.images.edit( model="gpt-image-1", image=img_io, mask=mask_io, prompt=brief, size="1024x1024", n=1)
        url = getattr(edit.data[0], "url", None); b64 = getattr(edit.data[0], "b64_json", None)
        if url: return url
        if b64: return "data:image/png;base64," + b64
        raise RuntimeError("Image API returned neither URL nor b64_json (edit).")
    except Exception as e: raise RuntimeError(f"Image generation failed: {e}") from e

def preprocess_to_square_png(image_bytes: bytes) -> bytes:
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGBA"); w, h = img.size
        if w != h: side = min(w, h); left = (w - side) // 2; top = (h - side) // 2; img = img.crop((left, top, left + side, top + side))
        if img.size != (1024, 1024): img = img.resize((1024, 1024), Image.Resampling.LANCZOS)
        out = io.BytesIO(); img.save(out, format="PNG"); return out.getvalue()
    except Exception as e: st.error(f"Image preprocessing failed: {e}"); raise

@st.cache_data(show_spinner="Describing image...")
def describe_image_content(image_url: str) -> str:
    if not image_url: return "No image to describe."
    try:
        image_input = {"url": image_url}
        prompt = "Describe the interior design in this image in 2-3 concise sentences (focus on style, furniture, decor)."
        response = client.chat.completions.create( model="gpt-4o", messages=[{"role": "user", "content": [ {"type": "text", "text": prompt}, {"type": "image_url", "image_url": image_input} ]}], max_tokens=100)
        return response.choices[0].message.content.strip()
    except Exception as e: print(f"Image description failed: {e}"); return "A beautiful AI-styled room."

@st.cache_data(show_spinner="Identifying products...")
def recognize_products_in_image(image_url: str) -> List[Dict[str, Any]]:
    if not image_url: return []
    try:
        image_input = {"url": image_url}
        prompt = "Analyze the interior design image. Identify main furniture/decor. Provide name and estimated INR price (number only) for each as JSON list: [{'name': 'X', 'price': N}, ...]. Limit 5-7 items."
        response = client.chat.completions.create( model="gpt-4o", messages=[{"role": "user", "content": [ {"type": "text", "text": prompt}, {"type": "image_url", "image_url": image_input} ]}], response_format={"type": "json_object"}, max_tokens=1000)
        content = response.choices[0].message.content
        try:
            result_data = json.loads(content)
            product_list_key = next((key for key in result_data if isinstance(result_data.get(key), list)), None)
            products = result_data[product_list_key] if product_list_key else (result_data if isinstance(result_data, list) else [])
        except (json.JSONDecodeError, Exception) as parse_e: st.warning(f"Error parsing products: {parse_e}. Placeholders used."); products = []
        final_products = []
        for i, p in enumerate(products):
            if isinstance(p, dict) and 'name' in p and 'price' in p:
                try: final_products.append({"id": i + 1, "name": str(p['name']), "price": int(p['price'])})
                except (ValueError, TypeError): continue
        if not final_products: raise ValueError("No valid products parsed.") # Trigger fallback if parsing fails badly
        return final_products
    except Exception as e:
        print(f"AI Product Recognition Failed: {e}")
        return [ {"id": 1, "name": "Sofa", "price": random.randint(35000, 85000)}, {"id": 2, "name": "Rug", "price": random.randint(7000, 22000)}, {"id": 3, "name": "Lamp", "price": random.randint(3000, 9000)}]

# --------------------- Session ---------------------
ss = st.session_state
if "step" not in ss:
    # Initialize all session state variables used
    ss.step = 0
    ss.quiz_choices = {2: None, 3: None, 4: None}
    ss.customer_profile = None
    ss.uploaded_file = None
    ss.styled_image_url = None
    ss.last_error = None
    ss.shop_items = []
    ss.buy_now_clicked = False
    ss.image_description = None

# --------------------- Main App Container / UI Logic ---------------------

# Pre-calculate splash background URL
splash_bg_url = data_url("assets/splash_background.jpg") or ""

# Inject CSS globally first, before conditional rendering
# Escape all literal curly braces in CSS with {{ }}
st.markdown(f"""
<style>
    /* Base styles */
    body {{ background:#fff8f9; font-family: 'Inter', sans-serif; margin: 0; }}
    /* Control padding for non-splash screens */
    .block-container {{ padding: {'0' if ss.step == 0 else '1rem'} !important; margin: 0 !important; max-width: 100% !important; }}
    .main-container {{ max-width: {'none' if ss.step == 0 else '900px'}; margin: auto; padding: 0; }} /* Remove internal padding */
     /* Hide Streamlit elements */
     header[data-testid="stHeader"], footer {{ display: {'none' if ss.step == 0 else 'inherit !important'}; }}

    /* Splash Screen Specific Styles */
    /* Target the container Streamlit creates when step is 0 */
    div[data-testid="stAppViewContainer"] > section > div.block-container {{
         height: {'100vh' if ss.step == 0 else 'auto'};
         display: {'flex' if ss.step == 0 else 'block'};
         justify-content: {'center' if ss.step == 0 else 'flex-start'};
         align-items: {'center' if ss.step == 0 else 'stretch'};
         background-image: {'url("'+splash_bg_url+'")' if ss.step == 0 and splash_bg_url else 'none'};
         background-color: {'transparent' if ss.step == 0 and splash_bg_url else ('#EADEE0' if ss.step == 0 else 'transparent')}; /* Fallback color */
         background-size: cover; background-position: center;
    }}
    .splash-logo {{ max-width: 250px; animation: fadeIn 1.5s ease-in-out; }}
    @keyframes fadeIn {{ from {{ opacity: 0; transform: scale(0.9); }} to {{ opacity: 1; transform: scale(1); }} }}

    /* --- Welcome Screen Header (Step 1) --- */
    .welcome-header-simple {{ text-align: center; margin-bottom: 2rem; padding-top: 1rem; }}

    /* --- Welcome Screen Content (Step 1) --- */
    .welcome-content {{ margin-top: 1rem; }}
    .welcome-headline {{ font-size: 2.2rem; margin-bottom: 1.5rem; line-height: 1.2; text-align: left; }}
    .welcome-text {{ font-size: 1rem; color: #495057; margin-top: 1.5rem; }}
    .welcome-content .stButton {{ margin-top: 1rem; margin-bottom: 1rem; }}

    /* --- Quiz Container Padding (Steps 2-4) --- */
    .quiz-container {{ padding-top: 2rem; }}

    /* Results screen styles */
    .image-description {{ text-align: center; font-style: italic; color: #555; margin: 0.5rem 1rem 1.5rem 1rem; }}

    /* Shop the Look styles */
    .shop-item-line {{ display: flex; justify-content: space-between; align-items: center; padding: 0.5rem 0; border-bottom: 1px solid #eee; }}
    .item-name {{ flex-grow: 1; margin-right: 1rem; }} .item-price {{ font-weight: bold; white-space: nowrap; }}

    /* --- Responsive Design for Mobile --- */
    @media (max-width: 768px) {{
        .main-container {{ padding: {'0' if ss.step == 0 else '1rem 0.5rem'}; }}
        .welcome-header-simple img {{ width: 100px; }}
        .welcome-headline {{ font-size: 1.8rem; text-align: center; }}
        .welcome-text {{ font-size: 0.9rem; text-align: center; margin-bottom: 1rem; margin-top: 0; }}
         /* Mobile stacking order for Welcome Screen */
         div[data-testid="stHorizontalBlock"] {{
             flex-direction: column !important; /* Force column for all st.columns on mobile */
         }}
         /* Welcome screen columns specifically */
         .welcome-content > div[data-testid="stHorizontalBlock"] > div:nth-child(1) {{ order: 2; width: 100% !important; margin-top: 1.5rem; }} /* Text Block */
         .welcome-content > div[data-testid="stHorizontalBlock"] > div:nth-child(2) {{ order: 1; width: 100% !important; }} /* Video Block */

        .quiz-container {{ padding-top: 1rem; }}
        .shop-item-line {{ padding: 0.7rem 0; }}
        .stButton>button[key*="remove_"] {{ padding: 0.1rem 0.4rem; font-size: 1rem; }}
    }}

    /* Button Styles */
    .stButton>button {{ background:#2d6a4f; border-radius: 8px; color: white; padding: 0.7rem 1.1rem; border: none; font-weight: bold; transition: background-color 0.2s; }}
    .stButton>button:hover {{ background: #1e4934; filter: brightness(110%); }}
    .stButton>button:disabled {{ background: #adb5bd; color: #6c757d; cursor: not-allowed; opacity: 0.7; }} /* Fixed: Use 0.7 */
    .stButton>button[kind="secondary"] {{ background:#e9ecef; color:#343a40; }}
    .stButton>button[kind="secondary"]:hover {{ background: #ced4da; }}
    .stButton>button[key*="remove_"] {{ background: none; color: #dc3545; padding: 0.1rem 0.4rem; font-size: 1rem; border: none; box-shadow: none; line-height: 1; }}
    .stButton>button[key*="remove_"]:hover {{ background: none; color: #c82333; }}
    /* Remove focus outline/border */
    .stButton>button:focus, .stButton>button:active {{ outline: none !important; box-shadow: none !important; border: none !important; }}
    button:focus {{ outline: none !important; }}

</style>
""", unsafe_allow_html=True)


# Step 0 — Splash Screen
if ss.step == 0:
    # The CSS above handles the full screen background and logo centering
    logo_url = data_url("assets/bello_logo.png")
    if logo_url:
        st.markdown(f'<img src="{logo_url}" class="splash-logo">', unsafe_allow_html=True)
    else:
        st.markdown("<h1 style='color: #2d6a4f;'>Bello Foyer</h1>", unsafe_allow_html=True) # Fallback

    time.sleep(2)
    ss.step = 1
    st.rerun()

# --- Steps 1 onwards ---
else:
    # Wrap steps 1+ in the main container
    st.markdown('<div class="main-container">', unsafe_allow_html=True)

    if ss.step == 1:
        # --- Simple Centered Header for Welcome ---
        st.markdown("<div class='welcome-header-simple'>", unsafe_allow_html=True)
        logo_path = "assets/bello_logo.png"
        if os.path.exists(logo_path):
            st.image(logo_path, width=120) # Centered
        st.markdown("</div>", unsafe_allow_html=True)

        # --- Main Welcome Content ---
        col1, col2 = st.columns([1, 1.1]) # Content columns
        # Use CSS ordering for mobile
        with col1:
             st.markdown("<div class='welcome-text-block'>", unsafe_allow_html=True) # Mobile: Order 1
             st.markdown("<h1 class='welcome-headline'>Reimagine Your Space.<br>Instantly.</h1>", unsafe_allow_html=True)
             if st.button("Get Started", type="primary", use_container_width=True): ss.step = 2; st.rerun()
             st.markdown("<p class='welcome-text'> Welcome to Bello Foyer where design dreams come to life...</p>", unsafe_allow_html=True) # Shortened
             st.markdown("</div>", unsafe_allow_html=True)
        with col2:
             st.markdown("<div class='welcome-video-block'>", unsafe_allow_html=True) # Mobile: Order 2
             display_video_autoplay("assets/intro.mp4")
             st.markdown("</div>", unsafe_allow_html=True)

    elif ss.step in [2, 3, 4]:
        st.markdown("<div class='quiz-container'>", unsafe_allow_html=True) # Add padding container
        # Attempt to reset scroll using empty element
        scroll_reset = st.empty()
        scroll_reset.write("") # Render something temporary

        visual_quiz = {
            2: {"title": "Which look do you like better?", "options": {"quiz1_A.jpg": ["minimal"], "quiz1_B.jpg": ["modern"]}},
            3: {"title": "Which look do you like better?", "options": {"quiz2_A.jpg": ["boho"], "quiz2_B.jpg": ["scandi"]}},
            4: {"title": "Which look do you like better?", "options": {"quiz3_A.jpg": ["industrial"], "quiz3_B.jpg": ["modern"]}},
        }
        info = visual_quiz[ss.step]
        st.markdown(f"<p style='text-align:center;'>Getting to know you ({ss.step-1}/3)</p>", unsafe_allow_html=True)
        st.markdown(f"<h2 style='text-align:center;'>{info['title']}</h2>", unsafe_allow_html=True)
        files = list(info["options"].keys()); cols = st.columns(2)
        for i, col in enumerate(cols):
            with col:
                fname = files[i]; p = os.path.join("assets", fname)
                if not os.path.exists(p): st.error(f"Missing: {p}")
                else:
                    st.image(p, use_container_width=True)
                    if st.button("I like this one", key=f"pick_{fname}", use_container_width=True, type="primary"):
                        ss.quiz_choices[ss.step] = info["options"][fname]; ss.step = 5 if ss.step == 4 else ss.step + 1; st.rerun()
        st.markdown("---");
        if st.button("Back", use_container_width=True): ss.step = 1 if ss.step == 2 else ss.step - 1; st.rerun()
        st.markdown("</div>", unsafe_allow_html=True) # Close padding container
        scroll_reset.empty() # Clear the element after rendering

    elif ss.step == 5:
        st.markdown("<h2 style='text-align:center;'>Your Redesign Studio</h2>", unsafe_allow_html=True)
        profile_placeholder = st.empty();

        # Generate profile only if needed
        if "customer_profile" not in ss or not ss.customer_profile:
            with profile_placeholder, st.spinner("Analyzing your style..."):
                 tags: List[str] = []; [tags.extend(ss.quiz_choices[k]) for k in sorted(ss.quiz_choices.keys()) if ss.quiz_choices[k]]
                 ss.customer_profile = generate_customer_profile(tags or ["modern"])
        profile_placeholder.empty() # Clear placeholder regardless

        # Display profile only if successfully generated and not default
        if ss.customer_profile and "(Default due to error)" not in ss.customer_profile and "Could not generate profile" not in ss.customer_profile:
             with st.expander("Your AI-Generated Design Profile", expanded=True): st.markdown(ss.customer_profile)
        elif ss.customer_profile: # Show generated profile even if it's the fallback/error
             st.info(ss.customer_profile)
        else: # Handle complete failure
             st.warning("Could not generate design profile. Using default style: Modern."); ss.customer_profile = "Modern style."

        st.markdown("---"); st.markdown("<h3 style='text-align:center;'>Let's Transform Your Room</h3>", unsafe_allow_html=True)

        # Simplified upload - remove columns, remove explicit camera (file_uploader handles it on mobile)
        uploaded_file = st.file_uploader("Upload Now", type=["jpg", "png", "webp"], label_visibility="visible")

        # Determine which file object to work with (new upload takes precedence)
        current_file_object = uploaded_file or ss.uploaded_file

        # If we have a file object (either newly uploaded or from session state)
        if current_file_object:
            # If it's a new upload, update the session state
            if uploaded_file:
                ss.uploaded_file = uploaded_file

            # Display the image from session state
            st.image(ss.uploaded_file, caption="Your room", use_container_width=True)

            # Show the Redesign button
            if st.button("Redesign My Room", type="primary", use_container_width=True, key="redesign_button_step5"): # Unique key
                ss.last_error = None; ss.image_description = None; ss.styled_image_url = None
                ss.step = 5.5; st.rerun()

        st.markdown("---")
        if st.button("Back"): ss.step = 4; st.rerun()

    elif ss.step == 5.5:
        st.markdown("<h2 style='text-align:center;'>Creating Your Design...</h2>", unsafe_allow_html=True)
        if ss.uploaded_file: st.image(ss.uploaded_file, caption="Processing...", use_container_width=True) # Corrected parameter
        st.markdown("---")
        status_placeholder = st.empty()
        try:
            if not ss.uploaded_file: raise ValueError("No file uploaded.")
            img_bytes = ss.uploaded_file.getvalue()
            # Ensure profile exists before proceeding
            if "customer_profile" not in ss or not ss.customer_profile:
                 tags: List[str] = []; [tags.extend(ss.quiz_choices[k]) for k in sorted(ss.quiz_choices.keys()) if ss.quiz_choices[k]]
                 ss.customer_profile = generate_customer_profile(tags or ["modern"])
                 if not ss.customer_profile or "(Default due to error)" in ss.customer_profile or "Could not generate profile" in ss.customer_profile: raise ValueError("Invalid profile.")
            with status_placeholder, st.spinner("⏳ Analyzing room..."): scene = analyze_room_architecture(img_bytes)
            with status_placeholder, st.spinner("🎨 Creating brief..."): brief = create_design_brief(ss.customer_profile, scene)
            with status_placeholder, st.spinner("🖼️ Preprocessing..."): png_bytes = preprocess_to_square_png(img_bytes)
            with status_placeholder, st.spinner("✨ Generating design... (~30-60s)"): ss.styled_image_url = edit_room_image_with_brief(png_bytes, brief)
            status_placeholder.success("✅ Done!"); time.sleep(1)
            ss.last_error = None; ss.step = 6; st.rerun()
        except Exception as e: ss.last_error = str(e); ss.styled_image_url = None; ss.step = 6; st.rerun() # Go to results to show error

    elif ss.step == 6:
        st.markdown("<h2 style='text-align:center;'>Your AI-Styled Home</h2>", unsafe_allow_html=True)
        if ss.styled_image_url:
            st.image(ss.styled_image_url, use_container_width=True) # Corrected parameter
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
                # Correct way to clear session state using a loop
                keys_to_clear = list(ss.keys())
                for k in keys_to_clear:
                    del ss[k]
                st.cache_data.clear(); st.rerun()
        with cR:
            shop_disabled = not ss.styled_image_url
            if st.button("Shop the Look", type="primary", use_container_width=True, disabled=shop_disabled):
                ss.buy_now_clicked = False; ss.shop_items = recognize_products_in_image(ss.styled_image_url)
                ss.step = 7; st.rerun()

    elif ss.step == 7:
        st.markdown("<h2 style='text-align:center;'>Shop the Look</h2>", unsafe_allow_html=True)
        if not ss.styled_image_url: st.warning("No image."); st.stop()
        st.image(ss.styled_image_url, caption="AI Concept", use_container_width=True) # Corrected parameter
        st.markdown("---"); st.markdown("<h4>Items:</h4>", unsafe_allow_html=True)
        if "shop_items" not in ss or not ss.shop_items: ss.shop_items = recognize_products_in_image(ss.styled_image_url)
        if "buy_now_clicked" not in ss: ss.buy_now_clicked = False
        total_price = 0
        for item in list(ss.shop_items): # Iterate copy
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
                # Correct way to clear session state using a loop
                keys_to_clear = list(ss.keys())
                for k in keys_to_clear:
                    del ss[k]
                st.cache_data.clear(); st.rerun()

    # Close main container div
    st.markdown('</div>', unsafe_allow_html=True)

