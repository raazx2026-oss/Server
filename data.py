from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship

# SQLite database (Render free tier pe refresh ho jata hai, Production me PostgreSQL use karein)
SQLALCHEMY_DATABASE_URL = "sqlite:///./app.db"

engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# 1. Users Table
class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)
    posts = relationship("Post", back_populates="owner")

# 2. Categories Table
class Category(Base):
    __tablename__ = "categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True)
    description = Column(String)
    posts = relationship("Post", back_populates="category")

# 3. Posts Table (Title, Description, Image)
class Post(Base):
    __tablename__ = "posts"
    id = Column(Integer, primary_key=True, index=True)
    title = Column(String)
    description = Column(String)
    image_url = Column(String, nullable=True) # Upload ki hui image ka link
    owner_id = Column(Integer, ForeignKey("users.id"))
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True)
    
    owner = relationship("User", back_populates="posts")
    category = relationship("Category", back_populates="posts")

# 4. App Config (Maintenance & Updates)
class AppConfig(Base):
    __tablename__ = "app_config"
    id = Column(Integer, primary_key=True, index=True)
    maintenance_mode = Column(Boolean, default=False)
    latest_version = Column(String, default="1.0.0")
    update_url = Column(String, default="")

# 5. App Plugins
class Plugin(Base):
    __tablename__ = "plugins"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    version = Column(String)
    download_url = Column(String) # Sirf App me kaam karega

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
