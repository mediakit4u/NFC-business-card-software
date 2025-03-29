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
import time

# Initialize app
app = FastAPI()

# Configuration - MUST COME FIRST
BASE_DIR = Path(__file__).parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
UPLOADS_DIR = BASE_DIR / "uploads"
QR_CODES_DIR = BASE_DIR / "qr_codes"
INSTANCE_DIR = BASE_DIR / "instance"

# Ensure directories exist
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(QR_CODES_DIR, exist_ok=True)
os.makedirs(INSTANCE_DIR, exist_ok=True)

# Initialize templates with absolute path
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

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

# Database connection with retry logic
def get_db_connection():
    retries = 3
    delay = 1
    for i in range(retries):
        try:
            conn = sqlite3.connect(str(INSTANCE_DIR / "business_cards.db"), timeout=10)
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

# Mount static files with absolute paths
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/static/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
app.mount("/static/qr_codes", StaticFiles(directory=str(QR_CODES_DIR)), name="qr_codes")

@app.post("/api/cards")
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
            if len(contents) > 2 * 1024 * 1024:  # 2MB limit
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
            "profile_url": f"{request.base_url}{profile_url}"
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(500, detail="Internal server error")
        
@app.get("/cards/{card_id}", response_class=HTMLResponse)
async def get_card(card_id: str, request: Request):
    try:
        # Verify template exists
        template_path = TEMPLATES_DIR / "card.html"
        if not template_path.exists():
            raise HTTPException(500, detail=f"Template not found at: {template_path}")
        
        # Database fetch
        with get_db_connection() as conn:
            card = conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        
        if not card:
            raise HTTPException(404, detail="Card not found")
            
        # Process image URL
        profile_image = card["profile_image"]
        if not profile_image.startswith(("http://", "https://")):
            if profile_image.startswith("static/"):
                profile_image = f"{request.base_url}{profile_image}"
            else:
                profile_image = f"{request.base_url}static/uploads/{os.path.basename(profile_image)}"
        
        # Render template
        return templates.TemplateResponse(
            "card.html",
            {
                "request": request,
                **dict(card),
                "profile_image": profile_image
            }
        )
        
    except HTTPException as http_exc:
        raise http_exc
    except Exception as e:
        logger.error(f"Card render failed: {str(e)}", exc_info=True)
        raise HTTPException(500, detail="Card display error")

@app.get("/debug")
async def debug():
    return {
        "template_path": str(TEMPLATES_DIR / "card.html"),
        "template_exists": (TEMPLATES_DIR / "card.html").exists(),
        "static_dir": str(STATIC_DIR),
        "uploads_dir": str(UPLOADS_DIR),
        "static_exists": (STATIC_DIR / "default.png").exists(),
        "uploads_dir_exists": os.path.exists(UPLOADS_DIR)
    }

    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
