import os
import json
import subprocess
from datetime import datetime, timedelta
from typing import List

from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from supabase import create_client, Client

from data import get_db, User, Item  # Import from data.py

# ---------- Configuration ----------
SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Supabase (set these in environment or .env)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Supabase URL and key must be set in environment variables")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ---------- Security ----------
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

def verify_password(plain, hashed):
    return pwd_context.verify(plain, hashed)

def get_password_hash(password):
    return pwd_context.hash(password)

def authenticate_user(db: Session, username: str, password: str):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        return False
    return user

def create_access_token(data: dict, expires_delta: timedelta | None = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.username == username).first()
    if user is None:
        raise credentials_exception
    return user

# ---------- FastAPI App ----------
app = FastAPI(title="Two-File Modular Server")

# ---------- Authentication Endpoints ----------
@app.post("/auth/register")
def register(username: str, password: str, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed = get_password_hash(password)
    new_user = User(username=username, password_hash=hashed)
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    access_token = create_access_token(data={"sub": new_user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/auth/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

@app.get("/auth/me")
def read_users_me(current_user = Depends(get_current_user)):
    return {"id": current_user.id, "username": current_user.username}

# ---------- File Upload (Supabase) ----------
@app.post("/upload/")
async def upload_file(file: UploadFile = File(...), user = Depends(get_current_user)):
    try:
        content = await file.read()
        # Upload to Supabase bucket "uploads"
        supabase.storage.from_("uploads").upload(file.filename, content)
        public_url = supabase.storage.from_("uploads").get_public_url(file.filename)
        return {"filename": file.filename, "url": public_url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ---------- WebSocket Chat ----------
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            await connection.send_text(message)

manager = ConnectionManager()

@app.websocket("/chat/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            await manager.broadcast(f"User says: {data}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
        await manager.broadcast("User left the chat")

# ---------- Data Store (CRUD) ----------
@app.post("/store/items")
def create_item(name: str, description: str, db: Session = Depends(get_db), user = Depends(get_current_user)):
    item = Item(name=name, description=description, owner_id=user.id)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

@app.get("/store/items")
def read_items(db: Session = Depends(get_db), user = Depends(get_current_user)):
    return db.query(Item).filter(Item.owner_id == user.id).all()

@app.put("/store/items/{item_id}")
def update_item(item_id: int, name: str, description: str, db: Session = Depends(get_db), user = Depends(get_current_user)):
    item = db.query(Item).filter(Item.id == item_id, Item.owner_id == user.id).first()
    if not item:
        raise HTTPException(404, "Item not found")
    item.name = name
    item.description = description
    db.commit()
    return item

@app.delete("/store/items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db), user = Depends(get_current_user)):
    item = db.query(Item).filter(Item.id == item_id, Item.owner_id == user.id).first()
    if not item:
        raise HTTPException(404, "Item not found")
    db.delete(item)
    db.commit()
    return {"ok": True}

# ---------- Pendrive Detection (Linux) ----------
@app.get("/pendrive/list")
def list_usb_drives():
    try:
        result = subprocess.run(["lsblk", "-o", "NAME,MOUNTPOINT,LABEL,SIZE,TYPE", "-J"],
                                capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        usb_drives = []
        for device in data.get("blockdevices", []):
            # Look for disks with mount points (assuming USB are mounted)
            if device.get("type") == "disk" and device.get("mountpoint"):
                usb_drives.append({
                    "name": device["name"],
                    "size": device["size"],
                    "mountpoint": device.get("mountpoint"),
                    "label": device.get("label")
                })
        return {"drives": usb_drives}
    except Exception as e:
        raise HTTPException(500, str(e))

# ---------- WiFi Management (Linux, requires root) ----------
from wifi import Cell, Scheme  # pip install wifi

INTERFACE = "wlan0"  # Change to your WiFi interface

@app.get("/wifi/scan")
def scan_wifi():
    try:
        cells = list(Cell.all(INTERFACE))
        return [{"ssid": c.ssid, "signal": c.signal, "encrypted": c.encrypted} for c in cells]
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/wifi/connect")
def connect_wifi(ssid: str, password: str):
    try:
        cells = Cell.all(INTERFACE)
        cell = next((c for c in cells if c.ssid == ssid), None)
        if not cell:
            raise HTTPException(404, "Network not found")
        scheme = Scheme.for_cell(INTERFACE, "my_wifi", cell, password)
        scheme.save()
        scheme.activate()
        return {"message": f"Connected to {ssid}"}
    except Exception as e:
        raise HTTPException(500, str(e))

# ---------- Run ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)