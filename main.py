from fastapi import FastAPI, HTTPException, Depends, Request, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from typing import List, Optional
from pydantic import BaseModel
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from database import client, users_collection, books_collection, questions_collection, issued_books_collection
import uvicorn
from models import UserCreate, Token, BookCreate, QuestionCreate, QuizSubmit
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from bson import ObjectId

SECRET_KEY = "super_secret_key_for_library_project"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

quiz_results_collection = client.library_quiz_db.get_collection("quiz_results")
reviews_collection = client.library_quiz_db.get_collection("book_reviews")

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
    except:
        raise HTTPException(status_code=401, detail="Authentication failed")


app = FastAPI(title="Advanced Library & Quiz System")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


@app.get("/", response_class=HTMLResponse)
async def serve_login(request: Request): return templates.TemplateResponse("login.html", {"request": request})


@app.get("/register-page", response_class=HTMLResponse)
async def serve_register(request: Request): return templates.TemplateResponse("register.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard(request: Request): return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/quiz", response_class=HTMLResponse)
async def serve_quiz(request: Request): return templates.TemplateResponse("quiz.html", {"request": request})


@app.get("/profile", response_class=HTMLResponse)
async def serve_profile(request: Request): return templates.TemplateResponse("profile.html", {"request": request})


@app.get("/admin", response_class=HTMLResponse)
async def serve_admin(request: Request): return templates.TemplateResponse("admin.html", {"request": request})


@app.get("/leaderboard", response_class=HTMLResponse)
async def serve_leaderboard(request: Request): return templates.TemplateResponse("leaderboard.html",
                                                                                 {"request": request})


# ---------------------------------------------------------
# 🔐 Auth & User APIs (Real Email Validation, NO OTP)
# ---------------------------------------------------------
@app.post("/register")
async def register_user(user: UserCreate):
    # 🔥 1. Check if email is a REAL format (Gmail, Yahoo, Outlook, etc.)
    allowed_domains = ["gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "edu.bd"]
    email_domain = user.email.split("@")[-1].lower()

    if email_domain not in allowed_domains:
        raise HTTPException(status_code=400,
                            detail="Invalid Email! Please use a real @gmail.com or @yahoo.com address.")

    # 2. Check if user already exists
    existing_user = await users_collection.find_one({"email": user.email})
    if existing_user:
        raise HTTPException(status_code=400, detail="Account already exists with this Email! Please Login.")

    # 3. Save User Directly
    hashed = get_password_hash(user.password)
    user_dict = {"name": user.name, "email": user.email, "password": hashed, "role": user.role, "is_verified": True,
                 "is_blocked": False, "block_until": ""}
    await users_collection.insert_one(user_dict)

    return {"message": "Account created successfully! You can now login."}


@app.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await users_collection.find_one({"email": form_data.username})
    if not user or not verify_password(form_data.password, user.get("password", "")):
        raise HTTPException(status_code=401, detail="Incorrect Email or Password")

    if user.get("is_blocked"):
        block_time_str = user.get("block_until", "")
        if block_time_str:
            if datetime.now() < datetime.strptime(block_time_str, "%Y-%m-%d %H:%M"):
                raise HTTPException(status_code=403, detail=f"Your account is BLOCKED until {block_time_str}!")
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
    category_data = await books_collection.aggregate([{"$group": {"_id": "$category", "count": {"$sum": 1}}}]).to_list(
        100)
    return {"stats": {"total_books": total_books, "total_students": total_students, "total_issued": total_issued},
            "charts": {"labels": [item["_id"] for item in category_data],
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
    if search: query["$or"] = [{"title": {"$regex": search, "$options": "i"}},
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


@app.get("/books/trending")
async def get_trending_books(): return {"trending_author": "Humayun Ahmed"}


@app.post("/books/borrow/{isbn}")
async def borrow_book(isbn: str, days: int = Query(7), token: str = Depends(oauth2_scheme)):
    book = await books_collection.find_one({"isbn": isbn})
    if not book or book["available_copies"] < 1: raise HTTPException(400, "Unavailable")
    await books_collection.update_one({"isbn": isbn}, {"$inc": {"available_copies": -1}})
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    record = {
        "user_email": payload.get("sub"), "book_title": book["title"], "isbn": isbn,
        "issue_date": datetime.now().strftime("%Y-%m-%d"),
        "return_date": (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d"),
        "read_link": book.get("read_link", "#"), "download_link": book.get("download_link", "#"),
        "is_premium": book.get("is_premium", False), "price": book.get("price", 0)
    }
    await issued_books_collection.insert_one(record)
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
        return {"message": "Force Returned"}
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
    exam_status["is_active"] = status;
    return {"message": "Updated"}


@app.post("/admin/set-exam-info", dependencies=[Depends(admin_required)])
async def set_exam_info(date_str: str, topic: str):
    global exam_status
    exam_status["next_exam_date"] = date_str;
    exam_status["exam_topic"] = topic;
    return {"message": "Updated"}


@app.post("/admin/clear-exam-info", dependencies=[Depends(admin_required)])
async def clear_exam_info():
    global exam_status
    exam_status["next_exam_date"] = "No Exam Scheduled";
    exam_status["exam_topic"] = "General";
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
    pipeline = []
    target_topic = exam_status.get("exam_topic", "General")
    if target_topic and target_topic != "General":
        pipeline.append({"$match": {"category": {"$regex": target_topic, "$options": "i"}}})
    elif category != "All":
        pipeline.append({"$match": {"category": {"$regex": category, "$options": "i"}}})
    pipeline.append({"$sample": {"size": limit}})
    q = await questions_collection.aggregate(pipeline).to_list(limit)
    if len(q) == 0: return {"questions": [], "message": "No questions found!"}
    return {"questions": [{"id": str(x["_id"]), "question": x["question_text"], "options": x["options"]} for x in q]}


@app.post("/quiz/submit")
async def submit_quiz(answers: List[QuizSubmit], token: str = Depends(oauth2_scheme)):
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    score = 0;
    res = []
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