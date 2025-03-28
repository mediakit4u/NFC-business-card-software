from fastapi import FastAPI, Form, UploadFile, File, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import os
import uuid
from pathlib import Path
import qrcode
from typing import Optional
import logging
import asyncio
import time
import tempfile

# Initialize app
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Enhanced logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configuration
BASE_DIR = Path(__file__).parent
UPLOADS_DIR = Path(tempfile.mkdtemp(prefix="uploads_"))
QR_CODES_DIR = Path(tempfile.mkdtemp(prefix="qr_"))
INSTANCE_DIR = Path(tempfile.mkdtemp(prefix="instance_"))
DB_PATH = str(INSTANCE_DIR / "business_cards.db")
# Create directories if they don't exist
os.makedirs("static", exist_ok=True)  # For default.png
os.makedirs("templates", exist_ok=True)  # For card.html
os.makedirs(str(UPLOADS_DIR), exist_ok=True)  # For uploaded profile images
os.makedirs(str(QR_CODES_DIR), exist_ok=True)  # For generated QR codes


# Database connection with retry logic
def get_db_connection():
    retries = 3
    delay = 1
    for i in range(retries):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=10)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.row_factory = sqlite3.Row
            return conn
        except sqlite3.Error as e:
            if i == retries - 1:
                logger.error(f"Database connection failed: {str(e)}")
                raise
            time.sleep(delay)
            delay *= 2

# Initialize database
def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cards (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                phone TEXT NOT NULL,
                email TEXT NOT NULL,
                website TEXT,
                linkedin TEXT,
                twitter TEXT,
                profile_image TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"DB init failed: {str(e)}")
        raise

@app.on_event("startup")
async def startup_event():
    logger.info("Starting application...")
    init_db()


# Add this before your mount points to serve default.png
app.mount("/static", StaticFiles(directory="static"), name="static")
# Mount static files
app.mount("/static/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/static/qr_codes", StaticFiles(directory=str(QR_CODES_DIR)), name="qr_codes")

@app.post("/api/card")
async def create_card(
    request: Request,
    name: str = Form(...),
    title: str = Form(...),
    company: str = Form(...),
    phone: str = Form(...),
    email: str = Form(...),
    website: Optional[str] = Form(None),
    linkedin: Optional[str] = Form(None),
    twitter: Optional[str] = Form(None),
    profile_img: Optional[UploadFile] = File(None)
):
    try:
        card_id = str(uuid.uuid4())
        profile_url = "/static/default.png"

        if profile_img and profile_img.filename:
            file_ext = os.path.splitext(profile_img.filename)[1].lower()
            if file_ext not in ['.jpg', '.jpeg', '.png']:
                raise HTTPException(400, detail="Only JPG/PNG images allowed")
            
            profile_filename = f"{card_id}{file_ext}"
            profile_path = UPLOADS_DIR / profile_filename
            
            contents = await profile_img.read()
            if len(contents) > 2 * 1024 * 1024:
                raise HTTPException(400, detail="Image too large (max 2MB)")
            
            with open(profile_path, "wb") as f:
                f.write(contents)
            profile_url = f"/static/uploads/{profile_filename}"

        with get_db_connection() as conn:
            conn.execute(
                """INSERT INTO cards 
                (id, name, title, company, phone, email, 
                 website, linkedin, twitter, profile_image)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (card_id, name, title, company, phone, email,
                 website, linkedin, twitter, profile_url)
            )

        card_url = f"{request.base_url}cards/{card_id}"
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(card_url)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_img.save(QR_CODES_DIR / f"{card_id}.png")

        return JSONResponse({
            "id": card_id,
            "view_url": f"/cards/{card_id}",
            "qr_url": f"/static/qr_codes/{card_id}.png",
            "profile_url": profile_url
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(500, detail="Internal server error")
        
@app.get("/card/{card_id}", response_class=HTMLResponse)
async def get_card(card_id: str, request: Request):
    try:
        # Database fetch
        with get_db_connection() as conn:
            card = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        
        if not card:
            raise HTTPException(404, detail="Card not found")
            
        # Process image URL
        profile_image = card["profile_image"]
        if not profile_image.startswith(("http://", "https://")):
            profile_image = f"{request.base_url}{profile_image.lstrip('/')}"
        
        # Render template
        return templates.TemplateResponse(
            "card.html",
            {
                "request": request,
                **dict(card),  # Unpacks all card fields automatically
                "profile_image": profile_image
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Card render failed: {str(e)}", exc_info=True)
        raise HTTPException(500, detail="Card display error")
    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
