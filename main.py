from fastapi import FastAPI, HTTPException, Depends, Request, Query, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from typing import List, Optional
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from database import client, users_collection, books_collection, questions_collection, issued_books_collection
import uvicorn
from models import UserCreate, Token, BookCreate, QuestionCreate, QuizSubmit, OTPVerify
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from bson import ObjectId
import random
import requests
import os
from dotenv import load_dotenv

load_dotenv()  # এই লাইনটি .env ফাইল থেকে তথ্যগুলো লোড করবে

SECRET_KEY = "super_secret_key_for_library_project"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

quiz_results_collection = client.library_quiz_db.get_collection("quiz_results")
otp_collection = client.library_quiz_db.get_collection("otps")
reviews_collection = client.library_quiz_db.get_collection("book_reviews")

# --- 🔥 Brevo Email API Configuration 🔥 ---
# আগের লাইনটি মুছে দিন: BREVO_API_KEY = "xkeysib-..."
# তার বদলে এই লাইনটি লিখুন:
BREVO_API_KEY = os.getenv("BREVO_API_KEY")
SENDER_EMAIL = "simantocb17@gmail.com"
def send_otp_email_background(receiver_email: str, otp: str):
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json"
    }
    payload = {
        "sender": {
            "name": "LMS Pro",
            "email": SENDER_EMAIL
        },
        "to":[{"email": receiver_email}],
        "subject": "LMS Pro - Verify Your Email",
        "htmlContent": f"<html><body><h3>Hello!</h3><p>Your OTP for LMS Pro is: <br><br><b><span style='font-size:24px; color:#4CAF50; letter-spacing: 2px;'>{otp}</span></b><br><br></p><p>Do not share this with anyone. This OTP is valid for a short time.</p></body></html>"
    }
    try:
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code == 201:
            print(f"✅ SUCCESS: OTP safely sent to {receiver_email} via Brevo API")
        else:
            print(f"❌ API Error: {response.status_code} - {response.text}")
    except Exception as e:
        print("❌ Network Error:", e)


exam_status = {"is_active": True, "next_exam_date": "No Exam Scheduled", "exam_topic": "General"}

def verify_password(plain, hashed): return pwd_context.verify(plain, hashed)

def get_password_hash(password): return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    to_encode.update({"exp": datetime.utcnow() + timedelta(minutes=60)})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def admin_required(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if payload.get("role") != "admin": raise HTTPException(status_code=403, detail="Admin Only!")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


app = FastAPI(title="Advanced Library & Quiz System")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# --- 🔥 HTML Routes 🔥 ---
@app.get("/", response_class=HTMLResponse)
async def serve_login(request: Request):
    return templates.TemplateResponse(request=request, name="login.html")

@app.get("/register-page", response_class=HTMLResponse)
async def serve_register(request: Request):
    return templates.TemplateResponse(request=request, name="register.html")

@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    return templates.TemplateResponse(request=request, name="dashboard.html")

@app.get("/quiz", response_class=HTMLResponse)
async def serve_quiz(request: Request):
    return templates.TemplateResponse(request=request, name="quiz.html")

@app.get("/profile", response_class=HTMLResponse)
async def serve_profile(request: Request):
    return templates.TemplateResponse(request=request, name="profile.html")

@app.get("/admin", response_class=HTMLResponse)
async def serve_admin(request: Request):
    return templates.TemplateResponse(request=request, name="admin.html")

@app.get("/leaderboard", response_class=HTMLResponse)
async def serve_leaderboard(request: Request):
    return templates.TemplateResponse(request=request, name="leaderboard.html")


# ---------------------------------------------------------
# 🔐 Auth & User APIs
# ---------------------------------------------------------
@app.post("/register")
async def register_user(user: UserCreate, background_tasks: BackgroundTasks):
    existing_user = await users_collection.find_one({"email": user.email})
    if existing_user:
        if existing_user.get("is_verified"):
            raise HTTPException(status_code=400, detail="User already exists!")
        else:
            await users_collection.delete_one({"email": user.email})

    otp = str(random.randint(100000, 999999))
    background_tasks.add_task(send_otp_email_background, user.email, otp)

    hashed = get_password_hash(user.password)
    user_dict = {"name": user.name, "email": user.email, "password": hashed, "role": user.role, "is_verified": False,
                 "is_blocked": False, "block_until": ""}
    await users_collection.insert_one(user_dict)

    await otp_collection.delete_many({"email": user.email})
    await otp_collection.insert_one({"email": user.email, "otp": otp, "created_at": datetime.utcnow()})
    return {"message": "OTP processing. Check your email shortly."}


@app.post("/verify-otp")
async def verify_otp(data: OTPVerify):
    record = await otp_collection.find_one({"email": data.email, "otp": data.otp})
    if not record: raise HTTPException(status_code=400, detail="Invalid OTP!")
    await users_collection.update_one({"email": data.email}, {"$set": {"is_verified": True}})
    await otp_collection.delete_many({"email": data.email})
    return {"message": "Verified!"}


@app.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await users_collection.find_one({"email": form_data.username})
    if not user or not verify_password(form_data.password, user.get("password", "")):
        raise HTTPException(status_code=401, detail="Incorrect credentials")

    if not user.get("is_verified", False) and user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Email not verified!")

    if user.get("is_blocked"):
        block_time_str = user.get("block_until", "")
        if block_time_str:
            if datetime.now() < datetime.strptime(block_time_str, "%Y-%m-%d %H:%M"):
                raise HTTPException(status_code=403, detail=f"Blocked until {block_time_str}")
            else:
                await users_collection.update_one({"email": user["email"]},
                                                  {"$set": {"is_blocked": False, "block_until": ""}})

    access_token = create_access_token(
        data={"sub": str(user["email"]), "name": str(user.get("name", "Student")), "role": user.get("role", "student")})
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/users/me")
async def read_users_me(token: str = Depends(oauth2_scheme)):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except:
        raise HTTPException(status_code=401)


# ---------------------------------------------------------
# 📊 Admin Management APIs
# ---------------------------------------------------------
@app.get("/admin/analytics", dependencies=[Depends(admin_required)])
async def get_analytics():
    total_books = await books_collection.count_documents({})
    total_students = await users_collection.count_documents({"role": "student"})
    total_issued = await issued_books_collection.count_documents({})
    category_data = await books_collection.aggregate([{"$group": {"_id": "$category", "count": {"$sum": 1}}}]).to_list(100)
    return {"stats": {"total_books": total_books, "total_students": total_students, "total_issued": total_issued},
            "charts": {"labels":[item["_id"] for item in category_data],
                       "data": [item["count"] for item in category_data]}}


@app.get("/admin/users", dependencies=[Depends(admin_required)])
async def get_all_users():
    users = await users_collection.find({"role": "student"}).to_list(1000)
    for u in users: u["_id"] = str(u["_id"]); u.pop("password", None)
    return users


@app.post("/admin/block-user", dependencies=[Depends(admin_required)])
async def block_user(email: str, days: int):
    block_until = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M")
    await users_collection.update_one({"email": email}, {"$set": {"is_blocked": True, "block_until": block_until}})
    return {"message": "Blocked"}


@app.post("/admin/unblock-user", dependencies=[Depends(admin_required)])
async def unblock_user(email: str):
    await users_collection.update_one({"email": email}, {"$set": {"is_blocked": False, "block_until": ""}})
    return {"message": "Unblocked"}


# ---------------------------------------------------------
# 📚 Book APIs
# ---------------------------------------------------------
@app.post("/books/bulk-add", dependencies=[Depends(admin_required)])
async def bulk_add_books(books: List[BookCreate]):
    if books: await books_collection.insert_many([b.dict() for b in books])
    return {"message": "Added"}


@app.get("/books")
async def get_books(search: str = None, category: str = None):
    query = {}
    if search: query["$or"] =[{"title": {"$regex": search, "$options": "i"}},
                               {"author": {"$regex": search, "$options": "i"}}]
    if category and category != "All": query["category"] = category
    books = await books_collection.find(query).to_list(1000)
    for b in books: b["_id"] = str(b["_id"])
    return books


@app.put("/books/edit/{isbn}", dependencies=[Depends(admin_required)])
async def edit_book(isbn: str, book_data: BookCreate):
    await books_collection.update_one({"isbn": isbn}, {"$set": book_data.dict(exclude_unset=True)})
    return {"message": "Updated"}


@app.delete("/books/delete/{isbn}", dependencies=[Depends(admin_required)])
async def delete_book(isbn: str):
    await books_collection.delete_one({"isbn": isbn})
    return {"message": "Deleted"}


@app.post("/books/borrow/{isbn}")
async def borrow_book(isbn: str, days: int = Query(7), token: str = Depends(oauth2_scheme)):
    book = await books_collection.find_one({"isbn": isbn})
    if not book or book["available_copies"] < 1: raise HTTPException(400, "Unavailable")
    await books_collection.update_one({"isbn": isbn}, {"$inc": {"available_copies": -1}})
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    await issued_books_collection.insert_one({
        "user_email": payload.get("sub"), "book_title": book["title"], "isbn": isbn,
        "issue_date": datetime.now().strftime("%Y-%m-%d"),
        "return_date": (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d"),
        "read_link": book.get("read_link", "#"), "download_link": book.get("download_link", "#"),
        "is_premium": book.get("is_premium", False), "price": book.get("price", 0)
    })
    return {"message": "Borrowed"}


@app.post("/books/return/{isbn}")
async def return_book(isbn: str, token: str = Depends(oauth2_scheme)):
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    record = await issued_books_collection.find_one({"user_email": payload.get("sub"), "isbn": isbn})
    if not record: raise HTTPException(404)
    await issued_books_collection.delete_one({"_id": record["_id"]})
    await books_collection.update_one({"isbn": isbn}, {"$inc": {"available_copies": 1}})
    return {"message": "Returned"}


@app.get("/users/borrowed-books")
async def get_my_borrowed_books(token: str = Depends(oauth2_scheme)):
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    books = await issued_books_collection.find({"user_email": payload.get("sub")}).to_list(100)
    for b in books: b["_id"] = str(b["_id"])
    return books


@app.get("/admin/issued-books", dependencies=[Depends(admin_required)])
async def get_all_issued_books():
    books = await issued_books_collection.find().to_list(1000)
    for b in books: b["_id"] = str(b["_id"])
    return books


@app.post("/admin/force-return/{record_id}", dependencies=[Depends(admin_required)])
async def force_return(record_id: str):
    record = await issued_books_collection.find_one({"_id": ObjectId(record_id)})
    if record:
        await issued_books_collection.delete_one({"_id": ObjectId(record_id)})
        await books_collection.update_one({"isbn": record["isbn"]}, {"$inc": {"available_copies": 1}})
        return {"message": "Success"}
    raise HTTPException(404)


# ---------------------------------------------------------
# 💬 Reviews & Comments
# ---------------------------------------------------------
class ReviewModel(BaseModel): isbn: str; comment: str

@app.post("/books/review")
async def add_review(review: ReviewModel, token: str = Depends(oauth2_scheme)):
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    await reviews_collection.insert_one(
        {"isbn": review.isbn, "student_name": payload.get("name"), "comment": review.comment,
         "date": datetime.now().strftime("%Y-%m-%d %H:%M")})
    return {"message": "Added"}


@app.get("/books/reviews/{isbn}")
async def get_reviews(isbn: str):
    reviews = await reviews_collection.find({"isbn": isbn}).sort("date", -1).to_list(100)
    for r in reviews: r["_id"] = str(r["_id"])
    return reviews


@app.get("/admin/all-reviews", dependencies=[Depends(admin_required)])
async def get_all_reviews():
    reviews = await reviews_collection.find().sort("date", -1).to_list(1000)
    for r in reviews: r["_id"] = str(r["_id"])
    return reviews


@app.delete("/admin/delete-review/{review_id}", dependencies=[Depends(admin_required)])
async def delete_review(review_id: str):
    await reviews_collection.delete_one({"_id": ObjectId(review_id)});
    return {"message": "Deleted"}


# ---------------------------------------------------------
# 🎯 Exam Control & Quiz APIs
# ---------------------------------------------------------
@app.post("/admin/exam-control", dependencies=[Depends(admin_required)])
async def toggle_exam(status: bool):
    global exam_status
    exam_status["is_active"] = status
    return {"message": "Updated"}


@app.post("/admin/set-exam-info", dependencies=[Depends(admin_required)])
async def set_exam_info(date_str: str, topic: str):
    global exam_status
    exam_status["next_exam_date"] = date_str;
    exam_status["exam_topic"] = topic
    return {"message": "Updated"}


@app.post("/admin/clear-exam-info", dependencies=[Depends(admin_required)])
async def clear_exam_info():
    global exam_status
    exam_status["next_exam_date"] = "No Exam Scheduled";
    exam_status["exam_topic"] = "General"
    return {"message": "Cleared"}


@app.get("/admin/exam-status")
async def get_exam_status(): return exam_status


@app.post("/quiz/bulk-add", dependencies=[Depends(admin_required)])
async def bulk_add_questions(questions: List[QuestionCreate]):
    if questions: await questions_collection.insert_many([q.dict() for q in questions])
    return {"message": "Added"}


@app.get("/quiz/all")
async def get_all_questions():
    q = await questions_collection.find().to_list(1000)
    for x in q: x["_id"] = str(x["_id"])
    return q


@app.delete("/quiz/delete/{q_id}", dependencies=[Depends(admin_required)])
async def delete_question(q_id: str):
    await questions_collection.delete_one({"_id": ObjectId(q_id)});
    return {"message": "Deleted"}


@app.get("/quiz/start")
async def start_quiz(limit: int = 5, category: str = "All"):
    if not exam_status["is_active"]: raise HTTPException(403, "Exam is CLOSED.")
    pipeline =[]
    target_topic = exam_status.get("exam_topic", "General")

    if target_topic and target_topic != "General":
        pipeline.append({"$match": {"category": {"$regex": target_topic, "$options": "i"}}})
    elif category != "All":
        pipeline.append({"$match": {"category": {"$regex": category, "$options": "i"}}})

    pipeline.append({"$sample": {"size": limit}})
    q = await questions_collection.aggregate(pipeline).to_list(limit)

    if len(q) == 0: return {"questions":[], "message": "No questions found!"}
    return {"questions": [{"id": str(x["_id"]), "question": x["question_text"], "options": x["options"]} for x in q]}


@app.post("/quiz/submit")
async def submit_quiz(answers: List[QuizSubmit], token: str = Depends(oauth2_scheme)):
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    score = 0;
    res =[]
    for a in answers:
        q = await questions_collection.find_one({"_id": ObjectId(a.question_id)})
        if q:
            correct = (q["correct_answer"] == a.selected_answer)
            if correct: score += 1
            res.append({"question": q["question_text"], "your_answer": a.selected_answer,
                        "correct_answer": q["correct_answer"], "status": "Correct" if correct else "Wrong"})
    pct = (score / len(answers)) * 100 if answers else 0
    await quiz_results_collection.insert_one(
        {"student_name": payload.get("name"), "student_email": payload.get("sub"), "score": score,
         "out_of": len(answers), "percentage": pct, "date": datetime.now().strftime("%Y-%m-%d %H:%M")})
    return {"total_score": score, "out_of": len(answers), "percentage": pct, "detailed_results": res}


@app.get("/quiz/leaderboard")
async def get_leaderboard():
    results = await quiz_results_collection.find().sort("percentage", -1).limit(10).to_list(10)
    for r in results: r["_id"] = str(r["_id"])
    return results


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)