import os
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

# Storage Imports
from supabase import create_client, Client
import cloudinary
import cloudinary.uploader

# DB Imports
from data import get_db, User, Category, Post, AppConfig, Plugin

# ---------- Configs ----------
SECRET_KEY = os.getenv("SECRET_KEY", "your-secret-key-change-in-production")
ALGORITHM = "HS256"

# Supabase Auth (Aapki di hui keys yahan default set hain)
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://bvulvlcwjuligeaaligq.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJ2dWx2bGN3anVsaWdlYWFsaWdxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIxNTgwNjMsImV4cCI6MjA4NzczNDA2M30.6LINOcy7O66yO-m9_-DwnNQ0hrIgo8e0CB6Qc-wPggU")
SUPABASE_BUCKET = "Raaz" # Aapka custom bucket

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Cloudinary Auth (Render Dashboard me Environment Variables me CLOUDINARY_URL add karein)
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL")
if CLOUDINARY_URL:
    cloudinary.config(url=CLOUDINARY_URL)

# ---------- Security ----------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

def verify_password(plain, hashed): return pwd_context.verify(plain, hashed)
def get_password_hash(password): return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=1440) # 24 Hours login
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None: raise HTTPException(401)
    except JWTError:
        raise HTTPException(401)
    user = db.query(User).filter(User.username == username).first()
    if user is None: raise HTTPException(401)
    return user

# ---------- App Setup ----------
app = FastAPI(title="Mera Pro Backend App")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ---------- 1. Authentication ----------
@app.post("/auth/register")
def register(username: str, password: str, db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == username).first():
        raise HTTPException(400, "Username already exists")
    new_user = User(username=username, password_hash=get_password_hash(password))
    db.add(new_user)
    db.commit()
    return {"message": "User registered successfully!"}

@app.post("/auth/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(401, "Wrong credentials")
    return {"access_token": create_access_token({"sub": user.username}), "token_type": "bearer"}

# ---------- 2. Storage APIs (Supabase 'Raaz' & Cloudinary) ----------
@app.post("/upload/supabase")
async def upload_supabase(file: UploadFile = File(...), user=Depends(get_current_user)):
    try:
        content = await file.read()
        # Uploading to 'Raaz' bucket
        supabase.storage.from_(SUPABASE_BUCKET).upload(file.filename, content)
        url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(file.filename)
        return {"url": url, "bucket": SUPABASE_BUCKET}
    except Exception as e:
        raise HTTPException(500, f"Supabase Error: {str(e)}. Make sure 'Raaz' bucket exists and is public.")

@app.post("/upload/cloudinary")
async def upload_cloudinary(file: UploadFile = File(...), user=Depends(get_current_user)):
    if not CLOUDINARY_URL: raise HTTPException(500, "Cloudinary URL is missing in server environment variables.")
    try:
        result = cloudinary.uploader.upload(file.file)
        return {"url": result.get("secure_url")}
    except Exception as e:
        raise HTTPException(500, f"Cloudinary Error: {str(e)}")

# ---------- 3. App Features (Posts & Categories) ----------
@app.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    return db.query(Category).all()

@app.post("/categories")
def create_category(name: str, description: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    # Sirf 'Raaz' account hi category bana sakta hai (Admin check)
    if user.username.lower() != "raaz": raise HTTPException(403, "Only Admin Raaz can create categories")
    cat = Category(name=name, description=description)
    db.add(cat)
    db.commit()
    return cat

@app.get("/posts")
def get_posts(db: Session = Depends(get_db)):
    return db.query(Post).all()

@app.post("/posts")
def create_post(title: str = Form(...), description: str = Form(...), image_url: str = Form(None), category_id: int = Form(None), db: Session = Depends(get_db), user=Depends(get_current_user)):
    # User ko register aur login hona zaroori hai (Token required)
    post = Post(title=title, description=description, image_url=image_url, category_id=category_id, owner_id=user.id)
    db.add(post)
    db.commit()
    return {"message": "Post Created Successfully", "post_id": post.id}

# ---------- 4. App System (Maintenance & Plugins) ----------
@app.get("/app/config")
def get_app_config(db: Session = Depends(get_db)):
    config = db.query(AppConfig).first()
    if not config:
        config = AppConfig(maintenance_mode=False, latest_version="1.0.0")
        db.add(config)
        db.commit()
    return {"maintenance": config.maintenance_mode, "version": config.latest_version, "update_url": config.update_url}

@app.get("/app/plugins")
def get_plugins(db: Session = Depends(get_db)):
    return db.query(Plugin).all()

# ---------- 5. DARK MODE ADMIN DASHBOARD ----------
@app.get("/admin", response_class=HTMLResponse)
def admin_panel():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>Raaz - Admin Panel</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { background-color: #0d1117; color: #58a6ff; font-family: 'Courier New', Courier, monospace; padding: 20px; text-align: center; }
            .container { max-width: 400px; margin: auto; background: #161b22; padding: 30px; border-radius: 10px; box-shadow: 0px 0px 15px rgba(88, 166, 255, 0.2); border: 1px solid #30363d; }
            h2 { color: #c9d1d9; }
            input, button { width: 90%; padding: 12px; margin: 10px 0; border-radius: 5px; border: 1px solid #30363d; background: #0d1117; color: #c9d1d9; }
            button { background: #238636; color: white; font-weight: bold; cursor: pointer; border: none; }
            button:hover { background: #2ea043; }
            .danger-btn { background: #da3633; }
            .danger-btn:hover { background: #f85149; }
            #dashboard { display: none; }
        </style>
    </head>
    <body>
        <div class="container" id="loginBox">
            <h2>🛡️ RAAZ ADMIN</h2>
            <input type="text" id="adminUser" placeholder="Username (Raaz)">
            <input type="password" id="adminPass" placeholder="Password">
            <button onclick="adminLogin()">SECURE LOGIN</button>
            <p id="msg" style="color:#ff7b72;"></p>
        </div>

        <div class="container" id="dashboard">
            <h2>Welcome, Master Raaz 👑</h2>
            <p style="color: #8b949e; font-size: 14px;">Server API & Database Management</p>
            <button onclick="window.location.href='/docs'">Open API Manager (Swagger)</button>
            <button class="danger-btn" onclick="location.reload()">Logout System</button>
        </div>

        <script>
            async function adminLogin() {
                let u = document.getElementById("adminUser").value;
                let p = document.getElementById("adminPass").value;
                
                let formData = new URLSearchParams();
                formData.append("username", u);
                formData.append("password", p);

                let res = await fetch("/auth/token", { method: "POST", body: formData });
                if(res.ok) {
                    if (u.toLowerCase() === "raaz") {
                        document.getElementById("loginBox").style.display = "none";
                        document.getElementById("dashboard").style.display = "block";
                    } else {
                        document.getElementById("msg").innerText = "Access Denied: You are not Admin!";
                    }
                } else {
                    document.getElementById("msg").innerText = "Invalid Credentials!";
                }
            }
        </script>
    </body>
    </html>
    """

# ---------- Run ----------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
