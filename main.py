import os
from datetime import datetime, timedelta
from typing import List

from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, WebSocket, WebSocketDisconnect
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from supabase import create_client, Client

from data import get_db, User, Item  # Importing from our data.py

# ---------- Configuration ----------
SECRET_KEY = "your-secret-key-change-in-production-please"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

# Supabase (Render Environment Variables se aayega)
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

# Sirf tabhi connect karein jab details available hon (warna crash nahi hoga, bas file upload block hoga)
if SUPABASE_URL and SUPABASE_KEY:
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
else:
    supabase = None

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

# ---------- FastAPI App Setup ----------
app = FastAPI(title="Advanced Cloud-Ready Server")

# CORS Setup - Ye bohot zaroori hai agar frontend se API call karni hai
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Production me isko apne domain se replace karein
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Health Check ----------
@app.get("/")
def root():
    return {"message": "Server is 100% Live and Working on Render!"}

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
    if not supabase:
        raise HTTPException(status_code=500, detail="Supabase credentials not configured in environment")
    try:
        content = await file.read()
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

# Hardware APIs (Wifi/Pendrive) removed because they will crash a cloud server like Render.

# ---------- Run ----------
if __name__ == "__main__":
    import uvicorn
    # Render assigns a dynamic port via environment variable. Fallback to 8000 for local testing.
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
