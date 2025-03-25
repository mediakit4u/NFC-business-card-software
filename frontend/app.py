import streamlit as st
import requests
import validators

# Configuration
BACKEND_URL = "https://nfc-business-card-software.onrender.com"

def validate_urls(*urls):
    for url in urls:
        if url and not validators.url(url):
            return False
    return True

def show_success(card_data):
    st.success("🎉 Your digital business card was created successfully!")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### Your Card Details")
        st.markdown(f"""
        - **View Online:** [Open Card]({BACKEND_URL}{card_data['view_url']})
        - **Card ID:** `{card_data['id']}`
        """)
        
        if st.button("📋 Copy Card URL"):
            st.session_state.card_url = f"{BACKEND_URL}{card_data['view_url']}"
            st.experimental_rerun()
        
        if 'card_url' in st.session_state:
            st.code(st.session_state.card_url)
    
    with col2:
        st.image(f"{BACKEND_URL}{card_data['qr_url']}", 
                caption="Scan this QR code to view your card",
                width=200)
    
    st.markdown("### Next Steps:")
    st.markdown("""
    1. **Print the QR code** on your physical business cards
    2. **For NFC cards**: Program them with your card URL
    3. **Share the link** digitally in emails or messages
    """)

def main():
    st.set_page_config(
        page_title="NFC Business Card Creator",
        page_icon="📇",
        layout="centered"
    )
    
    st.title("📇 NFC Digital Business Card Creator")
    st.markdown("Create your professional digital business card with QR code and NFC capability")

    # Backend connection check
    if 'backend_checked' not in st.session_state:
        try:
            response = requests.get(f"{BACKEND_URL}/health", timeout=10)
            if response.status_code == 200:
                st.success("✅ Backend connected")
            else:
                st.warning("⚠️ Backend connection unstable")
        except Exception:
            st.warning("⚠️ Could not connect to backend")
        st.session_state.backend_checked = True

    with st.form("card_form"):
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Personal Information")
            name = st.text_input("Full Name*")
            title = st.text_input("Job Title*")
            company = st.text_input("Company*")
            phone = st.text_input("Phone*")
            email = st.text_input("Email*")
            
        with col2:
            st.subheader("Additional Details")
            website = st.text_input("Website", help="Must start with https://")
            linkedin = st.text_input("LinkedIn URL", help="Must start with https://")
            twitter = st.text_input("Twitter URL", help="Must start with https://")
            profile_img = st.file_uploader(
                "Profile Photo (max 2MB)", 
                type=["jpg", "png", "jpeg"]
            )
        
        submitted = st.form_submit_button("Save Card")
        
        if submitted:
            if not all([name, title, company, phone, email]):
                st.error("Please fill all required fields (*)")
            elif not validate_urls(website, linkedin, twitter):
                st.error("Invalid URL format (include https://)")
            else:
                with st.spinner("Creating your card (may take 20-30 seconds on first try)..."):
                    try:
                        card_data = {
                            "name": name,
                            "title": title,
                            "company": company,
                            "phone": phone,
                            "email": email,
                            "website": website or "",
                            "linkedin": linkedin or "",
                            "twitter": twitter or ""
                        }
                        
                        files = {"profile_img": profile_img} if profile_img else None
                        
                        response = requests.post(
                            f"{BACKEND_URL}/api/cards",
                            data=card_data,
                            files=files,
                            timeout=25
                        )
                        response.raise_for_status()
                        show_success(response.json())
                        
                    except requests.exceptions.Timeout:
                        st.error("Backend is starting up. Please wait 30 seconds and try again.")
                    except requests.exceptions.RequestException as e:
                        st.error(f"Network error: {str(e)}")
                    except Exception as e:
                        st.error(f"Error creating card: {str(e)}")

if __name__ == "__main__":
    main()
