from fastapi import FastAPI, Form, UploadFile, File, Request, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader
from pydantic import BaseSettings
import sqlite3
import os
import uuid
from pathlib import Path
import qrcode
from PIL import Image
from typing import Optional
import logging
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware

# --- Configuration ---
class Settings(BaseSettings):
    database_url: str = "sqlite:///instance/business_cards.db"
    allow_origins: str = "*"  # Change to your frontend URL in production
    api_key: str = "your-secure-api-key"  # Generate a real one for production
    debug: bool = False

    class Config:
        env_file = ".env"

settings = Settings()

# --- App Initialization ---
app = FastAPI(debug=settings.debug)
limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

# --- Security ---
api_key_header = APIKeyHeader(name="X-API-Key")

async def validate_api_key(api_key: str = Depends(api_key_header)):
    if api_key != settings.api_key:
        raise HTTPException(status_code=403, detail="Invalid API Key")
    return api_key

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allow_origins.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# --- Directory Setup ---
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
UPLOADS_DIR = STATIC_DIR / "uploads"
QR_CODES_DIR = STATIC_DIR / "qr_codes"
TEMPLATES_DIR = BASE_DIR / "templates"
INSTANCE_DIR = BASE_DIR / "instance"
DB_PATH = INSTANCE_DIR / "business_cards.db"

def init_directories():
    required_dirs = [STATIC_DIR, UPLOADS_DIR, QR_CODES_DIR, TEMPLATES_DIR, INSTANCE_DIR]
    for directory in required_dirs:
        directory.mkdir(parents=True, exist_ok=True)

init_directories()

# --- Static Files ---
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# --- Database ---
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
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

@app.on_event("startup")
async def startup():
    init_db()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

# --- Routes ---
@app.post("/api/cards")
@limiter.limit("10/minute")
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
    profile_img: Optional[UploadFile] = File(None),
    db: sqlite3.Connection = Depends(get_db)
):
    try:
        card_id = str(uuid.uuid4())
        profile_path = "static/default.png"

        # File upload handling
        if profile_img and profile_img.filename:
            file_ext = os.path.splitext(profile_img.filename)[1].lower()
            if file_ext not in ['.jpg', '.jpeg', '.png']:
                raise HTTPException(400, detail="Only JPG/PNG images allowed")
            
            profile_filename = f"{card_id}{file_ext}"
            profile_path = f"static/uploads/{profile_filename}"
            
            with open(UPLOADS_DIR / profile_filename, "wb") as buffer:
                buffer.write(await profile_img.read())

        # Database operation
        db.execute(
            """INSERT INTO cards 
            (id, name, title, company, phone, email, website, linkedin, twitter, profile_image)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (card_id, name, title, company, phone, email, 
             website, linkedin, twitter, profile_path)
        )
        db.commit()

        # QR Code Generation
        card_url = f"{request.base_url}cards/{card_id}"
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )
        qr.add_data(card_url)
        qr.make(fit=True)
        
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_filename = f"{card_id}.png"
        qr_img.save(QR_CODES_DIR / qr_filename)

        return JSONResponse({
            "id": card_id,
            "view_url": f"/cards/{card_id}",
            "qr_url": f"/static/qr_codes/{qr_filename}"
        })

    except sqlite3.Error as e:
        logging.error(f"Database error: {str(e)}")
        raise HTTPException(500, detail="Database operation failed")
    except IOError as e:
        logging.error(f"Filesystem error: {str(e)}")
        raise HTTPException(500, detail="File storage failed")
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        raise HTTPException(500, detail="Internal server error")

@app.get("/cards/{card_id}", response_class=HTMLResponse)
async def view_card(card_id: str, request: Request, db: sqlite3.Connection = Depends(get_db)):
    try:
        card = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not card:
            raise HTTPException(404, detail="Card not found")
        
        return templates.TemplateResponse(
            "card.html",
            {"request": request, "card": dict(card)}
        )
    except Exception as e:
        logging.error(f"Card view error: {str(e)}")
        raise HTTPException(500, detail="Internal server error")

@app.get("/api/cards/{card_id}")
async def get_card_data(card_id: str, db: sqlite3.Connection = Depends(get_db)):
    try:
        card = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if not card:
            raise HTTPException(404, detail="Card not found")
        return JSONResponse(dict(card))
    except Exception as e:
        logging.error(f"Card data error: {str(e)}")
        raise HTTPException(500, detail="Internal server error")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "NFC Business Cards API"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
