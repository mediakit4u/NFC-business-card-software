from fastapi import FastAPI, Form, UploadFile, File, Request, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import sqlite3
print("SQLite version:", sqlite3.sqlite_version)
import os
import uuid
from pathlib import Path
import qrcode

app = FastAPI()

# Setup directories
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
QR_DIR = BASE_DIR / "static" / "qr_codes"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(QR_DIR, exist_ok=True)

# Mount static files and templates
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# Database setup
def init_db():
    with sqlite3.connect("business_cards.db") as conn:
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

@app.on_event("startup")
def startup():
    init_db()

@app.post("/api/cards")
async def create_card(
    request: Request,
    name: str = Form(...),
    title: str = Form(...),
    company: str = Form(...),
    phone: str = Form(...),
    email: str = Form(...),
    website: str = Form(""),
    linkedin: str = Form(""),
    twitter: str = Form(""),
    profile_image: UploadFile = File(None)
):
    try:
        card_id = str(uuid.uuid4())
        profile_path = "static/default.png"
        
        if profile_image:
            profile_path = f"uploads/{card_id}_{profile_image.filename}"
            with open(BASE_DIR / profile_path, "wb") as f:
                f.write(await profile_image.read())
        
        with sqlite3.connect("business_cards.db") as conn:
            conn.execute(
                "INSERT INTO cards VALUES (?,?,?,?,?,?,?,?,?,?,datetime('now'))",
                (card_id, name, title, company, phone, email, 
                 website, linkedin, twitter, profile_path)
            )
        
        # Generate QR code
        qr = qrcode.QRCode(version=1, box_size=10, border=4)
        qr.add_data(f"{request.base_url}cards/{card_id}")
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        qr_img.save(QR_DIR / f"{card_id}.png")
        
        return {
            "id": card_id,
            "view_url": f"/cards/{card_id}",
            "qr_url": f"/static/qr_codes/{card_id}.png"
        }
    
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@app.get("/cards/{card_id}", response_class=HTMLResponse)
async def view_card(card_id: str, request: Request):
    with sqlite3.connect("business_cards.db") as conn:
        conn.row_factory = sqlite3.Row
        card = conn.execute(
            "SELECT * FROM cards WHERE id = ?", (card_id,)
        ).fetchone()
    
    if not card:
        raise HTTPException(404, detail="Card not found")
    
    return templates.TemplateResponse(
        "card.html",
        {"request": request, "card": dict(card)}
    )

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
