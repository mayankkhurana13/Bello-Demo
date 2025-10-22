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
@st.cache_data(show_spinner="Generating profile...") # Add spinner text
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
            max_tokens=100, # Reduced max_tokens for shorter output
        )
        # Safely access message content
        message = resp.choices[0].message
        return message.content.strip() if message and message.content else "Could not generate profile content."
    except Exception as e:
        st.error(f"Profile Generation Error: {e}") # Show specific error
        return "Your design profile suggests a love for calm, modern spaces. (Default due to error)"

@st.cache_data(show_spinner="Analyzing room...") # Add spinner text
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
                        "Do NOT describe movable furniture or decor. Keep it concise (2-3 sentences max)."}, # Added conciseness instruction
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}
                ]
            }],
            max_tokens=150, # Reduced max_tokens
        )
        message = resp.choices[0].message
        return message.content.strip() if message and message.content else "Could not analyze room features."
    except Exception as e:
        st.error(f"Room Analysis Error: {e}") # Show specific error
        return "Analysis unavailable. Assuming a standard living room with windows and neutral walls."

@st.cache_data(show_spinner="Creating design brief...") # Add spinner text
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
        st.error(f"Design Brief Error: {e}") # Show specific error
        return (
            "A photorealistic professional photograph of a modern, calm living room with soft natural light, "
            "matching the user's taste. Ensure architecture remains identical." # Simplified fallback
        )

# Use spinner text for the main generation function too
@st.cache_data(show_spinner="Generating redesigned image...")
def edit_room_image_with_brief(processed_png_bytes: bytes, brief: str) -> str:
    """
    Use the *masked edit* endpoint. OPAQUE mask = preserved pixels, TRANSPARENT = editable.
    Returns a data URL (base64) you can show with st.image.
    """
    # 1) Make file-like objects with names (required for multipart upload)
    img_io = io.BytesIO(processed_png_bytes)
    img_io.name = "input.png"

    mask_bytes = make_architecture_preserving_mask((1024, 1024))
    mask_io = io.BytesIO(mask_bytes)
    mask_io.name = "mask.png"

    # 2) Call the *correct* endpoint: images.edit (singular!)
    try:
        edit = client.images.edit(
            model="gpt-image-1",
            image=img_io,
            mask=mask_io,
            prompt=brief,
            size="1024x1024",
            n=1,
            # Removed response_format as it's not supported here
        )
        # Default is URL, which is fine for Streamlit
        url = getattr(edit.data[0], "url", None)
        if url:
             return url
        # Fallback to check b64 if URL is missing (less common now)
        b64 = getattr(edit.data[0], "b64_json", None)
        if b64:
             return "data:image/png;base64," + b64

        raise RuntimeError("Image API returned neither URL nor b64_json (edit).")

    except Exception as e:
        # Log the error for debugging
        st.error(f"Image Edit Error: {e}")
        # Consider a simpler fallback or just raise
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
            img = img.resize((1024, 1024), Image.Resampling.LANCZOS) # Updated resampling method
        out = io.BytesIO()
        img.save(out, format="PNG")
        return out.getvalue()
    except Exception as e:
        st.error(f"Image preprocessing failed: {e}")
        raise

@st.cache_data(show_spinner="Describing image...")
def describe_image_content(image_url: str) -> str:
    """Uses AI to provide a concise 2-3 line description of the image content."""
    if not image_url:
        return "No image to describe."

    try:
        if image_url.startswith("data:image"):
             image_input = {"url": image_url}
        else:
             image_input = {"url": image_url}

        prompt = "Describe the interior design in this image in 2-3 concise sentences. Focus on furniture, decor, and overall style."

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": image_input}
                ]
            }],
            max_tokens=100 # Keep response short
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        st.error(f"Image description failed: {e}")
        return "A beautiful AI-styled room with a modern touch."


# ---- AI Product Recognition for Shop the Look ----
@st.cache_data(show_spinner="Identifying products...")
def recognize_products_in_image(image_url: str) -> List[Dict[str, Any]]:
    """Uses AI to identify products in the generated image."""
    if not image_url:
        return []

    try:
        # Ensure the image URL is accessible (data URLs need to be handled if used)
        if image_url.startswith("data:image"):
             image_input = {"url": image_url} # GPT-4o can handle data URLs directly
        else:
             image_input = {"url": image_url} # Assume it's a standard URL

        prompt = """
        Analyze the provided interior design image. Identify the main furniture and decor items visible.
        For each item, provide a short descriptive name (e.g., 'Mid-Century Modern Armchair', 'Abstract Canvas Art')
        and estimate a plausible price in Indian Rupees (INR), formatted as just the number (e.g., 45000).
        Return the results as a JSON list of objects, where each object has 'name' and 'price' keys.
        Example: [{"name": "Velvet Cushion", "price": 1500}, {"name": "Oak Coffee Table", "price": 25000}]
        Only include items clearly visible and identifiable. Limit to 5-7 main items.
        """

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": image_input}
                ]
            }],
            response_format={"type": "json_object"}, # Request JSON output
            max_tokens=1000
        )
        content = response.choices[0].message.content
        # Assuming the response is a JSON string containing a list under a key, e.g., {"products": [...]}
        # Adjust parsing based on the actual model response structure.
        # If the model directly returns the list string `[...]`, use json.loads(content)
        try:
            # Attempt to parse assuming the model returns {"products": [...]}
            result_data = json.loads(content)
            # Find the key containing the list (could be 'products', 'items', etc.)
            product_list_key = next((key for key in result_data if isinstance(result_data[key], list)), None)
            if product_list_key:
                products = result_data[product_list_key]
            else: # If the JSON is directly the list `[...]`
                 products = result_data if isinstance(result_data, list) else []

        except json.JSONDecodeError:
             st.warning("AI product recognition returned invalid format. Using placeholders.")
             products = [] # Fallback
        except Exception as parse_e:
             st.warning(f"Error parsing AI product response: {parse_e}. Using placeholders.")
             products = []

        # Add unique IDs and ensure price is integer
        final_products = []
        for i, p in enumerate(products):
            if isinstance(p, dict) and 'name' in p and 'price' in p:
                try:
                    price = int(p['price'])
                    final_products.append({"id": i + 1, "name": str(p['name']), "price": price})
                except (ValueError, TypeError):
                    continue # Skip items with invalid prices
        return final_products

    except Exception as e:
        st.error(f"AI Product Recognition Failed: {e}")
        # Fallback simulation if AI fails
        return [
            {"id": 1, "name": "Modern Sectional Sofa", "price": random.randint(35000, 85000)},
            {"id": 2, "name": "Textured Area Rug", "price": random.randint(7000, 22000)},
            {"id": 3, "name": "Floor Lamp with Metal Shade", "price": random.randint(3000, 9000)},
            {"id": 4, "name": "Wooden Bookshelf", "price": random.randint(12000, 30000)},
            {"id": 5, "name": "Decorative Planter", "price": random.randint(800, 2500)},
            {"id": 6, "name": "Coffee Table", "price": random.randint(6000, 18000)},
        ]


# --------------------- Session ---------------------
ss = st.session_state
if "step" not in ss:
    # Start at step 0 for the splash screen
    ss.step = 0
    ss.quiz_choices = {2: None, 3: None, 4: None}
    ss.customer_profile = None
    ss.uploaded_file = None # Will store the file object from uploader or camera
    ss.styled_image_url = None
    ss.last_error = None
    ss.shop_items = [] # Initialize shopping cart
    ss.buy_now_clicked = False # Track if buy now was clicked
    ss.image_description = None # New: Store image description


# --------------------- Main App Container ---------------------
# Use a main container to control max-width for centered content on larger screens
# Only apply max-width after splash screen
st.markdown(f'<div class="main-container {"splash" if ss.step == 0 else ""}">', unsafe_allow_html=True)


# --------------------- UI ---------------------

# Step 0 — Splash Screen
if ss.step == 0:
    splash_bg_path = "assets/splash_background.jpg" # Make sure this image exists
    splash_bg_data_url = data_url(splash_bg_path)
    logo_data_url = data_url("assets/bello_logo.png")

    # Inject CSS for splash screen
    st.markdown(f"""
    <style>
        /* Hide default Streamlit elements during splash */
        .block-container {{ padding: 0 !important; }}
        header[data-testid="stHeader"] {{ display: none !important; }} /* More robust header hiding */
        .main-container.splash {{ max-width: none !important; margin: 0 !important; padding: 0 !important; }}

        .splash-screen {{
            position: fixed;
            top: 0;
            left: 0;
            width: 100vw;
            height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            background-image: url('{splash_bg_data_url if splash_bg_data_url else ""}');
            background-size: cover;
            background-position: center;
            z-index: 9999;
        }}
        .splash-logo {{
            max-width: 250px; /* Adjust size as needed */
            animation: fadeIn 1.5s ease-in-out;
        }}
        @keyframes fadeIn {{
            from {{ opacity: 0; transform: scale(0.9); }} /* Slight scale effect */
            to {{ opacity: 1; transform: scale(1); }}
        }}
    </style>
    """, unsafe_allow_html=True)

    # Display splash content
    if logo_data_url:
        st.markdown(f"""
        <div class="splash-screen">
            <img src="{logo_data_url}" class="splash-logo">
        </div>
        """, unsafe_allow_html=True)
    else:
        # Fallback text if logo is missing
        st.markdown("<div class='splash-screen'><h1 style='color: white; animation: fadeIn 1.5s ease-in-out;'>Bello Foyer</h1></div>", unsafe_allow_html=True)

    # Simulate loading and transition
    time.sleep(2) # Display splash for 2 seconds
    ss.step = 1
    st.rerun()


# Step 1 — Welcome
elif ss.step == 1:
    # --- Header with Logo and Hamburger Menu (Only on Welcome) ---
    st.markdown(f"""
    <div class="top-bar">
        <div class="logo-container">
            <img src="{data_url("assets/bello_logo.png")}" class="logo-img">
        </div>
        <h3 class="header-title">Bello Foyer</h3>
        <div class="menu-wrap">
            <input type="checkbox" class="toggler">
            <div class="hamburger"><div></div></div>
            <div class="menu">
                <div>
                    <div>
                        <ul>
                            <li><a href="#">Home</a></li>
                            <li><a href="#">Catalogue (Not Live)</a></li>
                            <li><a href="#">Contact Us</a></li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    # --- Main Welcome Content ---
    st.markdown("<div class='welcome-content'>", unsafe_allow_html=True)
    col1, col2 = st.columns([1, 1.1]) # Adjust column ratios if needed for desktop

    with col1:
        display_video_autoplay("assets/intro.mp4")

    with col2:
        st.markdown("<h1 class='welcome-headline'>Reimagine Your Space.<br>Instantly.</h1>", unsafe_allow_html=True)
        if st.button("Get Started", type="primary", use_container_width=True):
            ss.step = 2
            st.rerun()
        st.markdown("""
        <p class='welcome-text'>
        Welcome to Bello Foyer, where your design dreams come to life.
        Our AI-powered assistant helps you visualize new styles for your home,
        starting with just a single photo. Let's create a space you'll love.
        </p>
        """, unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

# Steps 2–4 — Visual Quiz
elif ss.step in [2, 3, 4]:
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
            fname = files[i]
            p = os.path.join("assets", fname)
            if not os.path.exists(p):
                st.error(f"Missing asset: {p}")
            else:
                st.image(p, use_column_width=True)
                if st.button("I like this one", key=f"pick_{fname}", use_container_width=True, type="primary"):
                    ss.quiz_choices[ss.step] = info["options"][fname]
                    ss.step = 5 if ss.step == 4 else ss.step + 1
                    st.rerun()

    st.markdown("---")
    if st.button("Back", use_container_width=True):
        # Go back to welcome screen if on first quiz step, else previous quiz step
        ss.step = 1 if ss.step == 2 else ss.step - 1
        st.rerun()

# Step 5 — Redesign Studio (profile + upload + run)
elif ss.step == 5:
    st.markdown("<h2 style='text-align:center;'>Your Redesign Studio</h2>", unsafe_allow_html=True)

    profile_placeholder = st.empty()
    profile_placeholder.info("Analyzing your style...")
    if "customer_profile" not in ss or not ss.customer_profile: # Check if profile needs generation
        tags: List[str] = []
        for k in sorted(ss.quiz_choices.keys()):
            if ss.quiz_choices[k]:
                tags.extend(ss.quiz_choices[k])
        ss.customer_profile = generate_customer_profile(tags or ["modern", "neutral", "balanced"])
    profile_placeholder.empty()

    with st.expander("Your AI-Generated Design Profile", expanded=True):
        st.markdown(ss.customer_profile if ss.customer_profile else "Profile generation pending...")

    st.markdown("---")
    st.markdown("<h3 style='text-align:center; margin-bottom: 1.5rem;'>Let's Transform Your Room</h3>", unsafe_allow_html=True)

    col_upload, col_cam = st.columns(2)
    with col_upload:
        uploaded_file = st.file_uploader("Upload Now", type=["jpg", "jpeg", "png", "webp"], label_visibility="visible")
    with col_cam:
        camera_file = st.camera_input("Open Camera")

    input_file = camera_file if camera_file is not None else uploaded_file
    if input_file:
        ss.uploaded_file = input_file # Update session state only if there's new input

    if ss.uploaded_file:
        st.image(ss.uploaded_file, caption="Your uploaded room", use_column_width=True)
        if st.button("Redesign My Room", type="primary", use_container_width=True, key="redesign_button"):
            ss.last_error = None
            ss.image_description = None # Clear old description
            try:
                img_bytes = ss.uploaded_file.getvalue()
                # Run AI steps sequentially
                scene = analyze_room_architecture(img_bytes)
                brief = create_design_brief(ss.customer_profile, scene)
                png_bytes = preprocess_to_square_png(img_bytes)

                # Optional Mask Preview (keep commented out for cleaner UI unless debugging)
                # mask_preview = Image.open(io.BytesIO(make_architecture_preserving_mask((1024, 1024))))
                # st.caption("Editable region preview (transparent area will change; opaque is preserved):")
                # st.image(mask_preview, use_column_width=True)

                ss.styled_image_url = edit_room_image_with_brief(png_bytes, brief)
                ss.step = 6
                st.rerun()
            except Exception as e:
                ss.last_error = str(e)
                ss.step = 6
                st.rerun()

    st.markdown("---")
    if st.button("Back"):
        ss.step = 4 # Go back to the last quiz step
        st.rerun()

# Step 6 — Results
elif ss.step == 6:
    st.markdown("<h2 style='text-align:center;'>Your AI-Styled Home</h2>", unsafe_allow_html=True)

    # Display the AI Generated Concept
    if ss.styled_image_url:
        st.image(ss.styled_image_url, use_column_width=True)
        # Generate and display description
        if "image_description" not in ss or not ss.image_description: # Check if description needs generating
            ss.image_description = describe_image_content(ss.styled_image_url)
        st.markdown(f"<p class='image-description'>{ss.image_description}</p>", unsafe_allow_html=True)
    else:
        # Display error if generation failed
        if ss.last_error:
            st.error(f"Image generation failed: {ss.last_error}")
        else:
            st.error("Image generation failed for an unknown reason.")

    st.markdown("---") # Separator

    # --- Chat Box Placeholder ---
    st.markdown("<h5 style='margin-bottom: 0.5rem;'>Suggest Changes:</h5>", unsafe_allow_html=True)
    chat_input = st.text_input( # Changed to text_input for better styling control
        "Suggest changes",
        placeholder="e.g., 'Make the rug blue' or 'Add a bookshelf'",
        label_visibility="collapsed",
        disabled=True # Keep it disabled as it's a placeholder
    )
    st.caption("_(Live editing feature coming soon!)_") # Changed info to caption
    st.markdown("---")


    # --- Buttons ---
    # Use columns for button layout
    cL, cR = st.columns(2)
    with cL:
        if st.button("Start Over", use_container_width=True, key="results_start_over"): # Add unique key
            keys_to_clear = ["step", "quiz_choices", "customer_profile", "uploaded_file", "styled_image_url", "last_error", "shop_items", "buy_now_clicked", "image_description"]
            for k in keys_to_clear:
                if k in ss: del ss[k]
            st.cache_data.clear() # Clear cache on start over too
            st.rerun()
    with cR:
        shop_disabled = not ss.styled_image_url
        if st.button("Shop the Look", type="primary", use_container_width=True, disabled=shop_disabled):
            ss.buy_now_clicked = False # Reset buy now state
            ss.shop_items = recognize_products_in_image(ss.styled_image_url) # Initialize shop items using AI recognition
            ss.step = 7
            st.rerun()

# Step 7 — Shop the Look
elif ss.step == 7:
    st.markdown("<h2 style='text-align:center;'>Shop the Look</h2>", unsafe_allow_html=True)

    if not ss.styled_image_url:
        st.warning("No styled image available to shop.")
        if st.button("Go Back"):
            ss.step = 6
            st.rerun()
        st.stop()

    st.image(ss.styled_image_url, caption="Your AI Concept", use_column_width=True)
    st.markdown("---")
    st.markdown("<h4>Items in this look:</h4>", unsafe_allow_html=True)

    if "shop_items" not in ss or not ss.shop_items:
        # If items are missing (e.g., after refresh), try recognizing again
        ss.shop_items = recognize_products_in_image(ss.styled_image_url)
    if "buy_now_clicked" not in ss:
        ss.buy_now_clicked = False

    total_price = 0

    # Display items with remove buttons using columns and markdown for better layout control
    for i, item in enumerate(list(ss.shop_items)): # Iterate over a copy
        col1, col2 = st.columns([0.85, 0.15]) # Adjust ratio: 85% for name/price, 15% for button
        with col1:
            st.markdown(f"<div class='shop-item-line'><span class='item-name'>{item['name']}</span><span class='item-price'>₹{item['price']:,}</span></div>", unsafe_allow_html=True)
        with col2:
            if st.button("X", key=f"remove_{item['id']}", help="Remove item"):
                # Filter out the item to remove from session state
                ss.shop_items = [itm for itm in ss.shop_items if itm['id'] != item['id']]
                st.rerun() # Rerun to update the displayed list and total

    # Recalculate total based on potentially updated session state list
    total_price = sum(item['price'] for item in ss.shop_items)

    st.markdown("---")
    st.markdown(f"<h4 style='text-align:right;'>Total: ₹{total_price:,}</h4>", unsafe_allow_html=True)

    # --- Buy Now Button and Confirmation ---
    buy_now_placeholder = st.empty() # Placeholder for button and message
    if ss.buy_now_clicked:
         buy_now_placeholder.success("Thank you for your interest! Our team will be in touch shortly to finalize your order.")
         # Show disabled button below success message for visual consistency
         st.button("Buy Now", type="primary", use_container_width=True, disabled=True, key="buy_now_final_disabled")
    else:
        if buy_now_placeholder.button("Buy Now", type="primary", use_container_width=True, disabled=(total_price == 0), key="buy_now_final"):
             ss.buy_now_clicked = True
             st.rerun() # Rerun to show the success message and disable button


    # --- Bottom Navigation ---
    st.markdown("---")
    col_back, col_start_over = st.columns(2)
    with col_back:
        # Disable Back button if Buy Now was clicked
        if st.button("Back to Results", use_container_width=True, disabled=ss.buy_now_clicked):
            ss.step = 6
            ss.buy_now_clicked = False # Reset buy_now state
            st.rerun()
    with col_start_over:
         # Disable Start Over button if Buy Now was clicked
         if st.button("Start Over", use_container_width=True, key="shop_start_over", disabled=ss.buy_now_clicked):
             keys_to_clear = ["step", "quiz_choices", "customer_profile", "uploaded_file", "styled_image_url", "last_error", "shop_items", "buy_now_clicked", "image_description"]
             for k in keys_to_clear:
                 if k in ss: del ss[k]
             st.cache_data.clear()
             st.rerun()


# --------------------- Custom CSS for Layout and Style ---------------------
st.markdown(f"""
<style>
    /* --- Base Body & Container --- */
    body {{ background:#fff8f9; font-family: 'Inter', sans-serif; margin: 0; }}
    .block-container {{
        padding-top: { '0' if ss.step == 0 else '1rem' };
        padding-bottom: { '0' if ss.step == 0 else '2rem' };
        padding-left: { '0' if ss.step == 0 else '1rem' };
        padding-right: { '0' if ss.step == 0 else '1rem' };
    }}
    .main-container {{ max-width: { 'none' if ss.step == 0 else '900px' }; margin: auto; padding-top: 0; }}

    /* --- Splash Screen --- */
    .splash-screen {{
        position: fixed; top: 0; left: 0; width: 100vw; height: 100vh; display: flex;
        justify-content: center; align-items: center; z-index: 9999;
        background-image: url('{data_url("assets/splash_background.jpg") if data_url("assets/splash_background.jpg") else ""}');
        background-size: cover; background-position: center;
    }}
    .splash-logo {{ max-width: 250px; animation: fadeIn 1.5s ease-in-out; }}
    @keyframes fadeIn {{ from {{ opacity: 0; transform: scale(0.9); }} to {{ opacity: 1; transform: scale(1); }} }}

    /* --- Top Bar (Logo + Title + Menu) --- */
    /* Only show top bar on welcome screen (Step 1) */
    .top-bar {{
        display: {'flex' if ss.step == 1 else 'none'};
        justify-content: space-between; align-items: center; margin-bottom: 2rem; padding: 0.5rem 0; position: relative;
    }}
    .logo-container {{ flex-shrink: 0; }}
    .logo-img {{ height: 45px; width: auto; }}
    .header-title {{ text-align: center; margin: 0 1rem; color: #2d6a4f; font-size: 1.6rem; font-weight: bold; position: absolute; left: 50%; transform: translateX(-50%); white-space: nowrap; }}
    .menu-wrap {{ flex-shrink: 0; width: 40px; height: 40px; position: relative; z-index: 100; }}

    /* --- Welcome Screen Content --- */
    .welcome-content .stButton {{ margin-bottom: 1rem; }}
    .welcome-headline {{ font-size: 2.6rem; margin-bottom: 1.5rem; line-height: 1.2; }}
    .welcome-text {{ font-size: 1rem; color: #495057; margin-top: 1.5rem; }}

    /* --- Hamburger Menu CSS --- */
    .menu-wrap .toggler {{ position: absolute; top: 0; right: 0; z-index: 101; cursor: pointer; width: 40px; height: 40px; opacity: 0; }} .menu-wrap .hamburger {{ position: absolute; top: 0; right: 0; z-index: 100; width: 40px; height: 40px; padding: 0.5rem; background: #2d6a4f; display: flex; align-items: center; justify-content: center; border-radius: 50%; }} .menu-wrap .hamburger > div {{ position: relative; width: 100%; height: 2px; background-color: white; transition: all 0.4s ease; }} .menu-wrap .hamburger > div::before, .menu-wrap .hamburger > div::after {{ content: ''; position: absolute; top: -8px; width: 100%; height: 2px; background: inherit; }} .menu-wrap .hamburger > div::after {{ top: 8px; }} .menu-wrap .toggler:checked + .hamburger > div {{ transform: rotate(135deg); }} .menu-wrap .toggler:checked + .hamburger > div:before, .menu-wrap .toggler:checked + .hamburger > div:after {{ top: 0; transform: rotate(90deg); }} .menu-wrap .toggler:checked ~ .menu {{ visibility: visible; }} .menu-wrap .toggler:checked ~ .menu > div {{ transform: scale(1); transition-duration: 0.75s; }} .menu-wrap .menu {{ position: fixed; top: 0; right: 0; width: 100%; height: 100%; visibility: hidden; overflow: hidden; display: flex; align-items: center; justify-content: center; }} .menu-wrap .menu > div {{ background: rgba(45, 106, 79, 0.95); border-radius: 0; width: 200vw; height: 200vw; display: flex; flex: none; align-items: center; justify-content: center; transform: scale(0); transition: all 0.4s ease; }} .menu-wrap .menu > div > div > ul {{ list-style: none; padding: 0; text-align: center; }} .menu-wrap .menu > div > div > ul > li {{ padding: 1rem; }} .menu-wrap .menu > div > div > ul > li > a {{ color: white; text-decoration: none; font-size: 1.5rem; font-weight: 600; }}

    /* --- Results Screen Description --- */
    .image-description {{
        text-align: center;
        font-style: italic;
        color: #555;
        margin-top: 0.5rem;
        margin-bottom: 1.5rem;
        padding: 0 1rem; /* Add padding for better spacing */
    }}

    /* --- Shop the Look Item Line --- */
    .shop-item-line {{
        display: flex;
        justify-content: space-between; /* Pushes price to the right */
        align-items: center;
        padding: 0.5rem 0; /* Add vertical padding */
        border-bottom: 1px solid #eee; /* Separator line */
    }}
    .item-name {{
        flex-grow: 1; /* Allows name to take up space */
        margin-right: 1rem; /* Space between name and price */
    }}
    .item-price {{
        font-weight: bold;
        white-space: nowrap; /* Prevent price from wrapping */
    }}

    /* --- Responsive Design for Mobile --- */
    @media (max-width: 768px) {{
        .block-container {{ padding-left: { '0' if ss.step == 0 else '1rem' }; padding-right: { '0' if ss.step == 0 else '1rem' }; }}
        .header-title {{ font-size: 1.1rem; position: static; transform: none; flex-grow: 1; margin: 0 0.5rem; }}
        .top-bar {{ padding-left: 1rem; padding-right: 1rem; }}
        .logo-img {{ height: 30px; }}
        .welcome-headline {{ font-size: 1.8rem; margin-bottom: 1rem; }}
        .welcome-content .stButton {{ width: 100%; margin-bottom: 1rem; }}
        .welcome-text {{ font-size: 0.9rem; text-align: center; margin-bottom: 1.5rem; margin-top: 0; }}
        .welcome-content > .st-emotion-cache-1b202tt {{ flex-direction: column !important; }}
        .welcome-content > .st-emotion-cache-1b202tt > div:nth-child(1) {{ order: 4; margin-top: 1.5rem; }}
        .welcome-content > .st-emotion-cache-1b202tt > div:nth-child(2) {{ order: 1; }}
        .welcome-content > .st-emotion-cache-1b202tt > div:nth-child(2) > .welcome-headline {{ order: 1; }}
        .welcome-content > .st-emotion-cache-1b202tt > div:nth-child(2) > .stButton {{ order: 2; }}
        .welcome-content > .st-emotion-cache-1b202tt > div:nth-child(2) > .welcome-text {{ order: 3; }}
        /* Style the upload section on mobile */
        [data-testid="stVerticalBlock"] > [data-testid="stFileUploader"], [data-testid="stVerticalBlock"] > [data-testid="stCameraInput"] {{ margin-bottom: 0.5rem; }}
        /* Adjust shop item columns on mobile */
        .shop-item-line {{
            flex-wrap: wrap; /* Allow wrapping if needed, though unlikely with short price */
        }}
        .item-price {{
            margin-left: auto; /* Push price to right even on mobile */
            padding-left: 1rem; /* Ensure space */
        }}
         /* Ensure remove button takes full width in its column on mobile */
         .stButton>button[key*="remove_"] {{ width: 100%; text-align: center; }}

    }}

    /* --- General Button Styles --- */
    .stButton>button {{ background:#2d6a4f; color:white; padding:0.8rem 1.2rem; border-radius:12px; border:none; font-weight: bold; transition: background-color 0.2s ease; }}
    .stButton>button:hover {{ background: #1e4934; filter: brightness(110%); }}
    .stButton>button:disabled {{ background: #adb5bd; color: #6c757d; cursor: not-allowed; opacity: 0.7; }} /* Added opacity */
    .stButton>button[kind="secondary"] {{ background:#e9ecef; color:#343a40; }}
    .stButton>button[kind="secondary"]:hover {{ background: #ced4da; }}
    /* Specific style for remove button in cart */
    .stButton>button[key*="remove_"] {{
        background: none; color: #dc3545; padding: 0.2rem 0.5rem; font-weight: bold;
        font-size: 1.1rem; border: none; box-shadow: none; line-height: 1; /* Align 'X' better */
    }}
     .stButton>button[key*="remove_"]:hover {{ background: none; color: #c82333; filter: none; }}

</style>
""", unsafe_allow_html=True)

# Close the main container div only if not on splash screen
if ss.step != 0:
    st.markdown('</div>', unsafe_allow_html=True)

