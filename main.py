import os
import requests
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from passlib.context import CryptContext

# Cloud Storage
from supabase import create_client, Client
import cloudinary
import cloudinary.uploader

# Firebase
import firebase_admin
from firebase_admin import credentials, firestore

# ---------- Firebase Setup ----------
try:
    cred = credentials.Certificate("firebase.json")
    firebase_admin.initialize_app(cred)
except Exception as e:
    print(f"Firebase Error: {e}. Secret file missing!")

db = firestore.client()

# ---------- Configs ----------
SECRET_KEY = os.getenv("SECRET_KEY", "Raaz-Master-Key-2026")
ALGORITHM = "HS256"

# Supabase Auth
SUPABASE_URL = os.getenv("SUPABASE_URL", "https://bvulvlcwjuligeaaligq.supabase.co")
SUPABASE_KEY = os.getenv("SUPABASE_KEY") # Render env se aayega
SUPABASE_BUCKET = "Raaz"
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_KEY else None

# Cloudinary Auth
CLOUDINARY_URL = os.getenv("CLOUDINARY_URL")
if CLOUDINARY_URL:
    cloudinary.config(url=CLOUDINARY_URL)

# GitHub Category JSON URL (Isko apne asli github raw link se change kar lena)
GITHUB_CATEGORY_URL = "https://raw.githubusercontent.com/username/repo/main/category.json"

# ---------- Security & Auth ----------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

def verify_password(plain, hashed): return pwd_context.verify(plain, hashed)
def get_password_hash(password): return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    to_encode.update({"exp": datetime.utcnow() + timedelta(days=30)}) # 30 days login
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        if username is None: raise HTTPException(401)
        return {"username": username, "role": role}
    except JWTError:
        raise HTTPException(401, "Invalid or expired token")

# ---------- FastAPI Setup ----------
app = FastAPI(title="Raaz Master API", description="4 Heavy Features Architecture")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


# ==========================================
# 1. STORAGE API (Supabase & Cloudinary)
# ==========================================
@app.post("/upload/supabase", tags=["1. Storage API"])
async def upload_supabase(file: UploadFile = File(...), user=Depends(get_current_user)):
    if not supabase: raise HTTPException(500, "Supabase key missing")
    content = await file.read()
    supabase.storage.from_(SUPABASE_BUCKET).upload(file.filename, content)
    url = supabase.storage.from_(SUPABASE_BUCKET).get_public_url(file.filename)
    return {"url": url, "bucket": SUPABASE_BUCKET}

@app.post("/upload/cloudinary", tags=["1. Storage API"])
async def upload_cloudinary(file: UploadFile = File(...), user=Depends(get_current_user)):
    if not CLOUDINARY_URL: raise HTTPException(500, "Cloudinary not configured")
    result = cloudinary.uploader.upload(file.file)
    return {"url": result.get("secure_url")}


# ==========================================
# 2. POSTS & AUTH API (Firebase)
# ==========================================
@app.post("/auth/register", tags=["2. Posts & Users API"])
def register(username: str, password: str):
    if username.lower() == "raaz": raise HTTPException(400, "Master username is reserved")
    users_ref = db.collection("users")
    if len(list(users_ref.where("username", "==", username).stream())) > 0:
        raise HTTPException(400, "Username already exists")
    
    users_ref.add({"username": username, "password_hash": get_password_hash(password)})
    return {"message": "User registered! You can now login."}

@app.post("/auth/token", tags=["2. Posts & Users API"])
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    # 🔥 MASTER ADMIN LOGIN (Raaz / 2570)
    if form_data.username == "Raaz" and form_data.password == "2570":
        return {"access_token": create_access_token({"sub": "Raaz", "role": "admin"}), "token_type": "bearer"}
    
    # NORMAL USER LOGIN
    users_ref = list(db.collection("users").where("username", "==", form_data.username).stream())
    if not users_ref or not verify_password(form_data.password, users_ref[0].to_dict()['password_hash']):
        raise HTTPException(401, "Wrong credentials")
        
    return {"access_token": create_access_token({"sub": form_data.username, "role": "user"}), "token_type": "bearer"}

@app.get("/posts", tags=["2. Posts & Users API"])
def read_all_posts():
    # Public route - Bina login ke koi bhi padh sakta hai!
    docs = db.collection("posts").stream()
    return [{"id": doc.id, **doc.to_dict()} for doc in docs]

@app.post("/posts", tags=["2. Posts & Users API"])
def publish_post(title: str = Form(...), description: str = Form(...), image_url: str = Form(""), category: str = Form(""), user=Depends(get_current_user)):
    # User ko logged in hona zaroori hai post karne ke liye
    new_post = {"title": title, "description": description, "image_url": image_url, "category": category, "owner": user['username'], "date": str(datetime.now().date())}
    db.collection("posts").add(new_post)
    return {"message": "Post Published Successfully!"}

@app.delete("/posts/{post_id}", tags=["2. Posts & Users API"])
def delete_post(post_id: str, user=Depends(get_current_user)):
    # Sirf ADMIN delete kar sakta hai
    if user['role'] != 'admin': raise HTTPException(403, "Only Master Raaz can delete posts")
    db.collection("posts").document(post_id).delete()
    return {"message": "Post Deleted from Firebase"}


# ==========================================
# 3. CATEGORY API (GitHub JSON)
# ==========================================
@app.get("/categories", tags=["3. Category API"])
def get_categories_from_github():
    try:
        # GitHub se live data fetch karna
        response = requests.get(GITHUB_CATEGORY_URL)
        if response.status_code == 200:
            return response.json()
        else:
            # Agar file na mile toh default return karo
            return [{"id": 1, "name": "Default", "desc": "Edit GITHUB_CATEGORY_URL in code"}]
    except:
        return [{"error": "Failed to load from GitHub"}]


# ==========================================
# 4. APP SETTINGS API
# ==========================================
@app.get("/app/config", tags=["4. App Settings API"])
def get_app_settings(request: Request):
    docs = list(db.collection("app_settings").document("main").get())
    
    # Device Detection (User-Agent header read karke)
    user_device = request.headers.get('User-Agent', 'Unknown Device')
    
    if not docs:
        default_cfg = {
            "maintenance": False, 
            "version": "1.0.0", 
            "update_url": "https://playstore.com",
            "night_mode": True,
            "security_check": "Safe"
        }
        db.collection("app_settings").document("main").set(default_cfg)
        return {"settings": default_cfg, "detected_device": user_device}
        
    return {"settings": docs.to_dict(), "detected_device": user_device}

@app.post("/app/config", tags=["4. App Settings API"])
def update_app_settings(maintenance: bool = Form(...), version: str = Form(...), update_url: str = Form(...), night_mode: bool = Form(...), security_check: str = Form(...), user=Depends(get_current_user)):
    if user['role'] != 'admin': raise HTTPException(403, "Access Denied")
    
    new_cfg = {
        "maintenance": maintenance, "version": version, 
        "update_url": update_url, "night_mode": night_mode, "security_check": security_check
    }
    db.collection("app_settings").document("main").set(new_cfg)
    return {"message": "Settings Updated Live!"}


# ==========================================
# 👑 THE MASTER ADMIN HTML PANEL
# ==========================================
@app.get("/admin", response_class=HTMLResponse, include_in_schema=False)
def master_admin_panel():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Master Raaz | Control Center</title>
        <style>
            body { font-family: 'Courier New', Courier, monospace; background: #000; color: #0f0; margin: 0; padding: 20px;}
            h1 { text-align: center; border-bottom: 2px solid #0f0; padding-bottom: 10px; text-transform: uppercase;}
            .box { border: 1px solid #0f0; padding: 20px; margin: 20px auto; max-width: 600px; background: #111; box-shadow: 0 0 10px #0f0;}
            input, button, select { width: 95%; padding: 10px; margin: 10px 0; background: #000; color: #0f0; border: 1px solid #0f0;}
            button { background: #0f0; color: #000; font-weight: bold; cursor: pointer;}
            button:hover { background: #fff; box-shadow: 0 0 15px #0f0;}
            .danger { background: red; color: white; border-color: red;}
            .danger:hover { background: #fff; color: red;}
            #dashboard { display: none; }
            .post-item { border-left: 3px solid #0f0; padding: 10px; margin-bottom: 10px; background: #222;}
        </style>
    </head>
    <body>
        <h1>💻 RAAZ HACKER TERMINAL</h1>
        
        <div class="box" id="loginBox">
            <h3>Admin Login</h3>
            <input type="text" id="user" placeholder="Username (Raaz)">
            <input type="password" id="pass" placeholder="Password (2570)">
            <button onclick="login()">INITIALIZE SYSTEM</button>
            <p id="msg" style="color:red;"></p>
        </div>

        <div id="dashboard">
            <div class="box">
                <h2>🎛️ App Settings (Live Sync)</h2>
                <label>Maintenance Mode:</label>
                <select id="cfg-maint"><option value="false">OFF (Live)</option><option value="true">ON (Blocked)</option></select>
                <input type="text" id="cfg-ver" placeholder="App Version (e.g. 1.0.0)">
                <input type="text" id="cfg-url" placeholder="Update URL">
                <label>Force Night Mode:</label>
                <select id="cfg-night"><option value="true">ON</option><option value="false">OFF</option></select>
                <input type="text" id="cfg-sec" placeholder="Security Status (e.g. SAFE)">
                <button onclick="saveSettings()">DEPLOY SETTINGS TO ALL APPS</button>
            </div>

            <div class="box">
                <h2>🗑️ Manage Posts (Firebase)</h2>
                <button onclick="loadPosts()" style="background:transparent; color:#0f0;">Refresh Posts Database</button>
                <div id="postsList">Loading...</div>
            </div>
            
            <button class="danger" style="display:block; margin:auto; width:200px;" onclick="location.reload()">SYSTEM LOGOUT</button>
        </div>

        <script>
            let token = "";
            async function login() {
                let u = document.getElementById("user").value;
                let p = document.getElementById("pass").value;
                let body = new URLSearchParams(); body.append("username", u); body.append("password", p);
                
                let res = await fetch("/auth/token", { method: "POST", body: body });
                if(res.ok) {
                    let data = await res.json();
                    token = data.access_token;
                    document.getElementById("loginBox").style.display = "none";
                    document.getElementById("dashboard").style.display = "block";
                    loadConfig(); loadPosts();
                } else {
                    document.getElementById("msg").innerText = "ACCESS DENIED!";
                }
            }

            async function loadConfig() {
                let res = await fetch("/app/config");
                let data = await res.json();
                let s = data.settings;
                document.getElementById("cfg-maint").value = s.maintenance;
                document.getElementById("cfg-ver").value = s.version;
                document.getElementById("cfg-url").value = s.update_url;
                document.getElementById("cfg-night").value = s.night_mode;
                document.getElementById("cfg-sec").value = s.security_check;
            }

            async function saveSettings() {
                let body = new URLSearchParams();
                body.append("maintenance", document.getElementById("cfg-maint").value);
                body.append("version", document.getElementById("cfg-ver").value);
                body.append("update_url", document.getElementById("cfg-url").value);
                body.append("night_mode", document.getElementById("cfg-night").value);
                body.append("security_check", document.getElementById("cfg-sec").value);

                let res = await fetch("/app/config", {
                    method: "POST",
                    headers: { "Authorization": "Bearer " + token },
                    body: body
                });
                if(res.ok) alert("HACK SUCCESSFUL: App Settings Updated!");
            }

            async function loadPosts() {
                let res = await fetch("/posts");
                let data = await res.json();
                let html = "";
                data.forEach(p => {
                    html += `<div class="post-item">
                        <b>${p.title}</b> (By ${p.owner})<br>
                        <button class="danger" style="width:100px; padding:5px;" onclick="deletePost('${p.id}')">Delete Post</button>
                    </div>`;
                });
                document.getElementById("postsList").innerHTML = html || "No Posts Found.";
            }

            async function deletePost(id) {
                if(!confirm("Are you sure?")) return;
                let res = await fetch("/posts/" + id, { method: "DELETE", headers: { "Authorization": "Bearer " + token } });
                if(res.ok) loadPosts();
            }
        </script>
    </body>
    </html>
    """
