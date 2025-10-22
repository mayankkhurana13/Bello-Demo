# ... (previous code remains the same up to Step 5) ...

# Step 5 — Redesign Studio
elif ss.step == 5:
    st.markdown("<h2 style='text-align:center;'>Your Redesign Studio</h2>", unsafe_allow_html=True)
    profile_placeholder = st.empty();

    # Generate profile only if needed
    if "customer_profile" not in ss or not ss.customer_profile:
        with profile_placeholder, st.spinner("Analyzing your style..."):
             tags: List[str] = []; [tags.extend(ss.quiz_choices[k]) for k in sorted(ss.quiz_choices.keys()) if ss.quiz_choices[k]]
             ss.customer_profile = generate_customer_profile(tags or ["modern"])
    profile_placeholder.empty()

    # Display profile if it exists and isn't an error message
    if ss.customer_profile and "(Default due to error)" not in ss.customer_profile and "Could not generate profile" not in ss.customer_profile:
         with st.expander("Your AI-Generated Design Profile", expanded=True): st.markdown(ss.customer_profile)
    elif ss.customer_profile:
         st.info(ss.customer_profile)
    else: # Handle complete failure
         st.warning("Could not generate design profile. Using default style: Modern."); ss.customer_profile = "Modern style."

    st.markdown("---"); st.markdown("<h3 style='text-align:center;'>Let's Transform Your Room</h3>", unsafe_allow_html=True)

    # Simplified upload section
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
        if st.button("Redesign My Room", type="primary", use_container_width=True, key="redesign_button_step5"): # Added unique key
            ss.last_error = None; ss.image_description = None; ss.styled_image_url = None
            ss.step = 5.5; st.rerun()

    st.markdown("---")
    if st.button("Back"): ss.step = 4; st.rerun()

# ... (rest of the code remains the same) ...

