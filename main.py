import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from passlib.context import CryptContext

# Cloud Storage Libraries
from supabase import create_client, Client
import cloudinary
import cloudinary.uploader

# 🔥 Firebase Admin SDK 🔥
import firebase_admin
from firebase_admin import credentials, firestore

# ---------- Firebase Setup ----------
# Render par hum ek 'Secret File' banayenge jiska naam firebase.json hoga
try:
    cred = credentials.Certificate("firebase.json")
    firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"Firebase Error: {e}. Make sure firebase.json exists!")

db = firestore.client()

# ---------- Configs ----------
SECRET_KEY = os.getenv("SECRET_KEY", "Raaz-Super-Secret-Key-2026")
ALGORITHM = "HS256"

# Supabase Auth
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://bvulvlcwjuligeaaligq.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImJ2dWx2bGN3anVsaWdlYWFsaWdxIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIxNTgwNjMsImV4cCI6MjA4NzczNDA2M30.6LINOcy7O66yO-m9_-DwnNQ0hrIgo8e0CB6Qc-wPggU")
SUPABASE_BUCKET = "Raaz"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Cloudinary Auth
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

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None: raise HTTPException(401)
    except JWTError:
        raise HTTPException(401)
    
    # Check in Firebase
    users_ref = db.collection("users").where("username", "==", username).stream()
    user_list = list(users_ref)
    if not user_list: raise HTTPException(401, "User not found")
    
    user_data = user_list[0].to_dict()
    user_data['id'] = user_list[0].id
    return user_data

# ---------- App Setup ----------
app = FastAPI(title="Pro Firebase API Server")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# ---------- 1. Authentication (Firebase) ----------
@app.post("/auth/register")
def register(username: str, password: str):
    users_ref = db.collection("users")
    # Check if exists
    existing_users = list(users_ref.where("username", "==", username).stream())
    if len(existing_users) > 0:
        raise HTTPException(400, "Username already exists")
    
    # Save to Firebase
    new_user = {
        "username": username,
        "password_hash": get_password_hash(password),
        "created_at": str(datetime.now())
    }
    users_ref.add(new_user)
    return {"message": "User registered successfully!"}

@app.post("/auth/token")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    users_ref = db.collection("users").where("username", "==", form_data.username).stream()
    user_list = list(users_ref)
    
    if not user_list:
        raise HTTPException(401, "Wrong credentials")
        
    user_data = user_list[0].to_dict()
    if not verify_password(form_data.password, user_data['password_hash']):
        raise HTTPException(401, "Wrong credentials")
        
    return {"access_token": create_access_token({"sub": form_data.username}), "token_type": "bearer"}

# ---------- 2. Storage APIs (Supabase & Cloudinary) ----------
@app.post("/upload/supabase")
async def upload_supabase(file: UploadFile = File(...), user=Depends(get_current_user)):
    try:
        content = await file.read()
        supabase.storage.from_(SUPABASE_BUCKET).upload(file.filename, content)
        url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(file.filename)
        return {"url": url, "bucket": SUPABASE_BUCKET}
    except Exception as e:
        raise HTTPException(500, f"Supabase Error: {str(e)}")

@app.post("/upload/cloudinary")
async def upload_cloudinary(file: UploadFile = File(...), user=Depends(get_current_user)):
    if not CLOUDINARY_URL: raise HTTPException(500, "Cloudinary not configured")
    try:
        result = cloudinary.uploader.upload(file.file)
        return {"url": result.get("secure_url")}
    except Exception as e:
        raise HTTPException(500, f"Cloudinary Error: {str(e)}")

# ---------- 3. Posts & Categories (Firebase) ----------
@app.get("/categories")
def get_categories():
    docs = db.collection("categories").stream()
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]

@app.post("/categories")
def create_category(name: str, description: str, user=Depends(get_current_user)):
    if user['username'].lower() != "raaz": raise HTTPException(403, "Only Admin Raaz can create categories")
    db.collection("categories").add({"name": name, "description": description})
    return {"message": "Category Created"}

@app.get("/posts")
def get_posts():
    docs = db.collection("posts").stream()
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]

@app.post("/posts")
def create_post(title: str = Form(...), description: str = Form(...), image_url: str = Form(None), category_id: str = Form(None), user=Depends(get_current_user)):
    new_post = {
        "title": title,
        "description": description,
        "image_url": image_url,
        "category_id": category_id,
        "owner": user['username'],
        "timestamp": str(datetime.now())
    }
    db.collection("posts").add(new_post)
    return {"message": "Post Created Successfully in Firebase"}

# ---------- 4. App System Config (Firebase) ----------
@app.get("/app/config")
def get_app_config():
    docs = list(db.collection("app_config").document("main_config").get())
    # Return default if not exists
    if not docs:
        default_config = {"maintenance": False, "version": "1.0.0", "update_url": "https://playstore.com"}
        db.collection("app_config").document("main_config").set(default_config)
        return default_config
    return docs.to_dict()

# ---------- 5. DARK MODE ADMIN DASHBOARD ----------
@app.get("/admin", response_class=HTMLResponse)
def admin_panel():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <title>Raaz - Firebase Admin Panel</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body { background-color: #0d1117; color: #ff9900; font-family: 'Courier New', Courier, monospace; padding: 20px; text-align: center; }
            .container { max-width: 400px; margin: auto; background: #161b22; padding: 30px; border-radius: 10px; box-shadow: 0px 0px 15px rgba(255, 153, 0, 0.3); border: 1px solid #30363d; }
            input, button { width: 90%; padding: 12px; margin: 10px 0; border-radius: 5px; border: 1px solid #30363d; background: #0d1117; color: #c9d1d9; }
            button { background: #ff9900; color: black; font-weight: bold; cursor: pointer; border: none; }
            button:hover { background: #e68a00; }
            #dashboard { display: none; }
        </style>
    </head>
    <body>
        <div class="container" id="loginBox">
            <h2>🔥 RAAZ FIREBASE ADMIN</h2>
            <input type="text" id="adminUser" placeholder="Username (Raaz)">
            <input type="password" id="adminPass" placeholder="Password">
            <button onclick="adminLogin()">SECURE LOGIN</button>
            <p id="msg" style="color:#ff7b72;"></p>
        </div>

        <div class="container" id="dashboard">
            <h2>Welcome, Master Raaz 👑</h2>
            <p style="color: #8b949e; font-size: 14px;">Firebase Server API Management</p>
            <button onclick="window.location.href='/docs'">Open API Manager (Swagger)</button>
            <button style="background: #da3633; color: white;" onclick="location.reload()">Logout</button>
        </div>

        <script>
            async function adminLogin() {
                let u = document.getElementById("adminUser").value;
                let p = document.getElementById("adminPass").value;
                let formData = new URLSearchParams(); formData.append("username", u); formData.append("password", p);
                let res = await fetch("/auth/token", { method: "POST", body: formData });
                if(res.ok) {
                    if (u.toLowerCase() === "raaz") {
                        document.getElementById("loginBox").style.display = "none";
                        document.getElementById("dashboard").style.display = "block";
                    } else { document.getElementById("msg").innerText = "Access Denied!"; }
                } else { document.getElementById("msg").innerText = "Invalid Credentials!"; }
            }
        </script>
    </body>
    </html>
    """

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
