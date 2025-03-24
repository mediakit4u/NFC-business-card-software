import streamlit as st
import requests
import qrcode
from io import BytesIO
from PIL import Image
import os
import validators

# Configuration
BACKEND_URL = "https://nfc-business-card-software.onrender.com" # your render url


def test_connection():
    try:
        response = requests.get(f"{BACKEND_URL}/", timeout=5)
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# Test connection on app load
connection_status = test_connection()
st.write("Backend status:", connection_status)
    
response = requests.post(
    f"{BACKEND_URL}/api/cards",
    data={...},  # Your form data
    files={...},  # Your uploaded file
    timeout=10
)

def main():
    st.set_page_config(
        page_title="NFC Business Card Creator",
        page_icon="📇",
        layout="centered"
    )
    
    st.title("📇 NFC Digital Business Card Creator")
    st.markdown("Create your professional digital business card with QR code and NFC capability")
    
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
            website = st.text_input("Website")
            linkedin = st.text_input("LinkedIn URL")
            twitter = st.text_input("Twitter URL")
            profile_img = st.file_uploader("Profile Photo", type=["jpg", "png", "jpeg"])
        
        submitted = st.form_submit_button("Create Digital Card")
        
        if submitted:
            if not all([name, title, company, phone, email]):
                st.error("Please fill all required fields (*)")
            elif not validate_urls(website, linkedin, twitter):
                st.error("Please enter valid URLs (start with http:// or https://)")
            else:
                create_card(
                    name, title, company, phone, email,
                    website, linkedin, twitter, profile_img
                )

def validate_urls(website, linkedin, twitter):
    urls = [u for u in [website, linkedin, twitter] if u]
    return all(validators.url(url) for url in urls)

def create_card(name, title, company, phone, email, website, linkedin, twitter, profile_img):
    with st.spinner("Creating your digital card..."):
        try:
            files = {}
            if profile_img:
                files = {"profile_image": profile_img}
            
            response = requests.post(
                f"{BACKEND_URL}/api/cards",
                data={
                    "name": name,
                    "title": title,
                    "company": company,
                    "phone": phone,
                    "email": email,
                    "website": website or "",
                    "linkedin": linkedin or "",
                    "twitter": twitter or ""
                },
                files=files
            )
            
            if response.status_code == 200:
                show_success(response.json())
            else:
                st.error(f"Error creating card: {response.text}")
                
        except requests.exceptions.ConnectionError:
            st.error("Could not connect to the server. Is the backend running?")
        except Exception as e:
            st.error(f"An unexpected error occurred: {str(e)}")

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

if __name__ == "__main__":
    main()
