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

# Initialize app
app = FastAPI()

# Setup CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Timeout middleware
@app.middleware("http")
async def timeout_middleware(request: Request, call_next):
    try:
        return await asyncio.wait_for(call_next(request), timeout=25)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Request timeout")

# Base directory setup
BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
#UPLOADS_DIR = Path("/tmp/uploads")  # Render-compatible path
#QR_CODES_DIR = Path("/tmp/qr_codes")  # Render-compatible path
UPLOADS_DIR = STATIC_DIR / "uploads"
QR_CODES_DIR = STATIC_DIR / "qr_codes"
TEMPLATES_DIR = BASE_DIR / "templates"
INSTANCE_DIR = BASE_DIR / "instance"
DB_PATH = str(INSTANCE_DIR / "business_cards.db")

# Initialize directories
def init_directories():
    required_dirs = [
        STATIC_DIR,
        UPLOADS_DIR,  # Now resolves to static/uploads
        QR_CODES_DIR,  # Now resolves to static/qr_codes
        TEMPLATES_DIR,
        INSTANCE_DIR
    ]
    # ... rest of the function remains the same ...
    for directory in required_dirs:
        try:
            # Handle file/directory conflicts
            if directory.exists() and not directory.is_dir():
                os.remove(str(directory))
            directory.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            logging.error(f"Error initializing {directory}: {str(e)}")

init_directories()

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
templates = Jinja2Templates(directory=TEMPLATES_DIR)
# Add after your existing static mount in backend/main.py
#app.mount("/static/uploads", StaticFiles(directory=UPLOADS_DIR), name="uploads")
#app.mount("/static/qr_codes", StaticFiles(directory=QR_CODES_DIR), name="qr_codes")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Database setup
def init_db():
    try:
        with sqlite3.connect(DB_PATH) as conn:  # Use context manager
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA busy_timeout=5000")
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
                    profile_img TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
    except Exception as e:
        logging.error(f"Database error: {str(e)}")

@app.on_event("startup")
async def startup():
    logging.basicConfig(level=logging.INFO)
    init_db()

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
        profile_path = "static/default.png"

        # File upload handling (using /tmp)
        if profile_img and profile_img.filename:
              profile_url = f"{request.base_url}static/uploads/{profile_filename}"  # This is new
            file_ext = os.path.splitext(profile_img.filename)[1].lower()
            if file_ext not in ['.jpg', '.jpeg', '.png']:
                raise HTTPException(400, detail="Only JPG/PNG images allowed")
            
            profile_filename = f"{card_id}{file_ext}"
           #old profile_path = f"/tmp/uploads/{profile_filename}"
           #old profile_path = f"/static/uploads/{profile_filename}"  # URL path
            profile_url = f"{request.base_url}static/uploads/{profile_filename}"

         # Database insertion
    conn.execute(
        """INSERT INTO cards 
        (id, name, title, company, phone, email, website, linkedin, twitter, profile_image)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (card_id, name, title, company, phone, email, 
         website, linkedin, twitter, profile_url)  # Changed from profile_path to profile_url
    )

   
            
            with open(UPLOADS_DIR / profile_filename, "wb") as buffer:
                content = await profile_img.read()
                if len(content) > 2 * 1024 * 1024:  # 2MB limit
                    raise HTTPException(400, detail="Image too large (max 2MB)")
                buffer.write(content)

        # Database operation (with context manager)
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """INSERT INTO cards 
                (id, name, title, company, phone, email, website, linkedin, twitter, profile_image)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (card_id, name, title, company, phone, email, 
                 website, linkedin, twitter, profile_path)
            )
            conn.commit()

        # QR Code generation (no redundant mkdir)
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

        return {
            "id": card_id,
            "view_url": f"/cards/{card_id}",
            "qr_url": f"/static/qr_codes/{qr_filename}"  # Update frontend to use /tmp paths
        }

    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Unexpected error: {str(e)}")
        raise HTTPException(500, detail="Internal server error")

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "NFC Business Cards API"}


#new code for view card error
@app.get("/cards/{card_id}", response_class=HTMLResponse)
async def get_card(request: Request, card_id: str):
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM cards WHERE id = ?", (card_id,))
            card_data = cursor.fetchone()

        if not card_data:
            raise HTTPException(status_code=404, detail="Card not found")

        # Convert SQLite row to dict
        columns = [col[0] for col in cursor.description]
        card = dict(zip(columns, card_data))

        return templates.TemplateResponse("card.html", {"request": request, "card": card})

    except sqlite3.Error as e:
        logging.error(f"Database error: {str(e)}")
        raise HTTPException(500, detail="Database error")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
