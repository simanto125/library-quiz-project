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

# --- Book Models ---
class BookCreate(BaseModel):
    title: str
    author: str
    isbn: str
    category: str
    total_copies: int
    available_copies: int

# --- Quiz Models (নতুন অ্যাড করা হলো) ---
class QuestionCreate(BaseModel):
    question_text: str
    options: List[str]      # যেমন: ["Dhaka", "Khulna", "Sylhet", "Rajshahi"]
    correct_answer: str     # যেমন: "Dhaka"
    category: str           # যেমন: "General Knowledge"

class QuizSubmit(BaseModel):
    question_id: str
    selected_answer: str