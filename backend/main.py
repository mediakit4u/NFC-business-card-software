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

# Initialize directories with error handling
def init_directories():
    required_dirs = [UPLOADS_DIR, QR_CODES_DIR, INSTANCE_DIR]
    for directory in required_dirs:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            # Ensure writable permissions
            os.chmod(directory, 0o777)
            logger.info(f"Directory ready: {directory}")
        except Exception as e:
            logger.error(f"Directory init failed for {directory}: {str(e)}")
            raise

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

# Initialize database with retries
def init_db():
    max_retries = 5
    for attempt in range(max_retries):
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
            return
        except Exception as e:
            logger.error(f"DB init attempt {attempt + 1} failed: {str(e)}")
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)

@app.on_event("startup")
async def startup_event():
    logger.info("Starting application...")
    try:
        init_directories()
        init_db()
    except Exception as e:
        logger.critical(f"Startup failed: {str(e)}")
        raise

# Mount static files
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
        profile_url = "static/default.png"

        # File upload handling
        if profile_img and profile_img.filename:
            file_ext = os.path.splitext(profile_img.filename)[1].lower()
            if file_ext not in ['.jpg', '.jpeg', '.png']:
                raise HTTPException(400, detail="Only JPG/PNG images allowed")
            
            profile_filename = f"{card_id}{file_ext}"
            profile_path = UPLOADS_DIR / profile_filename
            
            try:
                contents = await profile_img.read()
                if len(contents) > 2 * 1024 * 1024:
                    raise HTTPException(400, detail="Image too large (max 2MB)")
                
                with open(profile_path, "wb") as f:
                    f.write(contents)
                
                profile_url = f"/static/uploads/{profile_filename}"
            except Exception as e:
                logger.error(f"File upload failed: {str(e)}")
                raise HTTPException(500, detail="File upload failed")

        # Database operation
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                """INSERT INTO cards 
                (id, name, title, company, phone, email, 
                 website, linkedin, twitter, profile_image)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (card_id, name, title, company, phone, email,
                 website, linkedin, twitter, profile_url)
            )
            conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Database error: {str(e)}")
            raise HTTPException(500, detail="Database operation failed")
        finally:
            conn.close()

        # QR Code generation
        try:
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
            qr_path = QR_CODES_DIR / qr_filename
            qr_img.save(qr_path)
            
            qr_url = f"/static/qr_codes/{qr_filename}"
        except Exception as e:
            logger.error(f"QR generation failed: {str(e)}")
            qr_url = None

        return JSONResponse({
            "id": card_id,
            "view_url": f"/cards/{card_id}",
            "qr_url": qr_url,
            "profile_url": profile_url
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(500, detail="Internal server error")

@app.get("/health")
async def health_check():
    try:
        # Test database connection
        conn = get_db_connection()
        conn.close()
        
        # Test directory access
        test_file = UPLOADS_DIR / "test.txt"
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        
        return {"status": "healthy", "database": "ok", "storage": "ok"}
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, timeout_keep_alive=30)
