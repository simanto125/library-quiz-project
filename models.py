from pydantic import BaseModel, EmailStr
from typing import List, Optional

# --- User Models ---
class UserCreate(BaseModel):
    name: str
    email: EmailStr
    password: str
    role: str = "student"

class UserLogin(BaseModel):
    email: EmailStr
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str

# --- Book Models (Updated with PDF & Premium Info) ---
class BookCreate(BaseModel):
    title: str
    author: str
    isbn: str
    category: str
    total_copies: int
    available_copies: int
    read_link: Optional[str] = "#"      # অনলাইনে পড়ার লিংক (যেমন Google Drive PDF Viewer Link)
    download_link: Optional[str] = "#"  # ডাউনলোড করার আসল লিংক
    is_premium: bool = False            # বইটি কি পেইড? (True/False)
    price: int = 0                      # বইয়ের দাম (যদি Premium হয়)

# --- Quiz Models (Updated) ---
class QuestionCreate(BaseModel):
    question_text: str
    options: List[str]
    correct_answer: str
    category: str

class QuizSubmit(BaseModel):
    question_id: str
    selected_answer: str

# নতুন: কুইজ রেজাল্ট সেভ করার জন্য
class QuizResult(BaseModel):
    student_email: str
    score: int
    out_of: int
    percentage: float
    category: str