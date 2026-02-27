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
SECRET_KEY = "super-secret-key-raaz"
ALGORITHM = "HS256"

# Supabase Auth
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
supabase: Optional[Client] = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL else None

# Cloudinary Auth (Render Env Variables me daalna hoga: CLOUDINARY_URL)
# Format: cloudinary://API_KEY:API_SECRET@CLOUD_NAME
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
    expire = datetime.utcnow() + timedelta(minutes=1440) # 24 Hours
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
    return {"message": "User registered! Please login."}

@app.post("/auth/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == form_data.username).first()
    if not user or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(401, "Wrong credentials")
    return {"access_token": create_access_token({"sub": user.username}), "token_type": "bearer"}

# ---------- 2. Storage APIs (Supabase & Cloudinary) ----------
@app.post("/upload/supabase")
async def upload_supabase(file: UploadFile = File(...)):
    if not supabase: raise HTTPException(500, "Supabase not configured")
    content = await file.read()
    supabase.storage.from_("uploads").upload(file.filename, content)
    url = supabase.storage.from_("uploads").get_public_url(file.filename)
    return {"url": url}

@app.post("/upload/cloudinary")
async def upload_cloudinary(file: UploadFile = File(...)):
    if not CLOUDINARY_URL: raise HTTPException(500, "Cloudinary not configured")
    result = cloudinary.uploader.upload(file.file)
    return {"url": result.get("secure_url")}

# ---------- 3. Posts & Categories ----------
@app.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    return db.query(Category).all()

@app.post("/categories")
def create_category(name: str, description: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    # Sirf Admin ('Raaz') category bana sakta hai
    if user.username != "Raaz": raise HTTPException(403, "Only Admin can create categories")
    cat = Category(name=name, description=description)
    db.add(cat)
    db.commit()
    return cat

@app.post("/posts")
def create_post(title: str = Form(...), description: str = Form(...), image_url: str = Form(None), category_id: int = Form(None), db: Session = Depends(get_db), user=Depends(get_current_user)):
    post = Post(title=title, description=description, image_url=image_url, category_id=category_id, owner_id=user.id)
    db.add(post)
    db.commit()
    return {"message": "Post Created Successfully", "post_id": post.id}

@app.get("/posts")
def get_all_posts(db: Session = Depends(get_db)):
    return db.query(Post).all()

# ---------- 4. App Config (Maintenance & Update) ----------
@app.get("/app-status")
def get_app_status(db: Session = Depends(get_db)):
    config = db.query(AppConfig).first()
    if not config:
        config = AppConfig(maintenance_mode=False, latest_version="1.0.0", update_url="https://playstore.com")
        db.add(config)
        db.commit()
    return {"maintenance": config.maintenance_mode, "latest_version": config.latest_version, "update_url": config.update_url}

# ---------- 5. App Plugins ----------
@app.get("/plugins")
def get_plugins(db: Session = Depends(get_db)):
    return db.query(Plugin).all()

# ---------- 6. DARK MODE ADMIN DASHBOARD ----------
@app.get("/admin", response_class=HTMLResponse)
def admin_panel():
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>Admin Panel - Raaz</title>
        <style>
            body { background-color: #121212; color: #00ffcc; font-family: monospace; padding: 20px; text-align: center; }
            input, button { padding: 10px; margin: 10px; border-radius: 5px; border: 1px solid #00ffcc; background: #222; color: white; width: 80%; max-width: 300px;}
            button { background: #00ffcc; color: black; font-weight: bold; cursor: pointer; }
            button:hover { background: #00b38f; }
            .card { background: #1e1e1e; padding: 20px; margin: 20px auto; border-radius: 10px; max-width: 500px; box-shadow: 0px 0px 10px #00ffcc; }
            #dashboard { display: none; }
        </style>
    </head>
    <body>
        <h1>⚙️ PRO ADMIN PANEL</h1>
        
        <div class="card" id="loginBox">
            <h3>Admin Login</h3>
            <input type="text" id="adminUser" placeholder="Username (Raaz)"><br>
            <input type="password" id="adminPass" placeholder="Password"><br>
            <button onclick="adminLogin()">ENTER SYSTEM</button>
            <p id="msg" style="color:red;"></p>
        </div>

        <div id="dashboard">
            <h2 style="color:white;">Welcome, Master Raaz 👑</h2>
            
            <div class="card">
                <h3>System Controls</h3>
                <p>Use Swagger UI (/docs) to manage database securely using your Admin Token.</p>
                <button onclick="window.location.href='/docs'">Go to API Manager</button>
                <button onclick="logout()" style="background:red; color:white; border-color:red;">Logout</button>
            </div>
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
                    if (u === "Raaz") {
                        document.getElementById("loginBox").style.display = "none";
                        document.getElementById("dashboard").style.display = "block";
                    } else {
                        document.getElementById("msg").innerText = "You are not an Admin!";
                    }
                } else {
                    document.getElementById("msg").innerText = "Invalid Credentials!";
                }
            }
            function logout() { location.reload(); }
        </script>
    </body>
    </html>
    """
    return html_content

# ---------- Run ----------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
