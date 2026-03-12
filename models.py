from pydantic import BaseModel, EmailStr
from typing import List, Optional

# --- User Models ---
class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "student"
    is_verified: bool = False

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

class OTPVerify(BaseModel):
    email: str
    otp: str

# --- 🔥 Book Models (Updated with Cover Image) ---
class BookCreate(BaseModel):
    title: str
    author: str
    isbn: str
    category: str
    total_copies: int
    available_copies: int
    read_link: Optional[str] = "#"
    download_link: Optional[str] = "#"
    is_premium: bool = False
    price: int = 0
    # 🔥 নতুন যোগ করা হলো: বইয়ের কভার ছবির লিংক
    image_url: Optional[str] = "https://via.placeholder.com/150x200.png?text=No+Cover"

# --- Quiz Models ---
class QuestionCreate(BaseModel):
    question_text: str
    options: List[str]
    correct_answer: str
    category: str

class QuizSubmit(BaseModel):
    question_id: str
    selected_answer: str

class QuizResult(BaseModel):
    student_email: str
    score: int
    out_of: int
    percentage: float
    category: str