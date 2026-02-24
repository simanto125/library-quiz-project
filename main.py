from fastapi import FastAPI, HTTPException, Depends, Request, Query
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from typing import List, Optional
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


def verify_password(plain_password, hashed_password): return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password): return pwd_context.hash(password)


def create_access_token(data: dict):
    to_encode = data.copy()
    to_encode.update({"exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user_role(token: str = Depends(oauth2_scheme)):
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=["HS256"]).get("role")
    except:
        raise HTTPException(status_code=401, detail="Invalid Session")


async def admin_required(role: str = Depends(get_current_user_role)):
    if role != "admin": raise HTTPException(status_code=403, detail="Admin Only!")
    return role


app = FastAPI(title="Advanced Library & Quiz System")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


# --- HTML Routes ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request): return templates.TemplateResponse("login.html", {"request": request})


@app.get("/register-page", response_class=HTMLResponse)
async def get_register_page(request: Request): return templates.TemplateResponse("register.html", {"request": request})


@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard(request: Request): return templates.TemplateResponse("dashboard.html", {"request": request})


@app.get("/quiz", response_class=HTMLResponse)
async def get_quiz_page(request: Request): return templates.TemplateResponse("quiz.html", {"request": request})


@app.get("/profile", response_class=HTMLResponse)
async def get_profile_page(request: Request): return templates.TemplateResponse("profile.html", {"request": request})


@app.get("/admin", response_class=HTMLResponse)
async def get_admin_page(request: Request): return templates.TemplateResponse("admin.html", {"request": request})


@app.get("/leaderboard", response_class=HTMLResponse)
async def get_leaderboard_page(request: Request): return templates.TemplateResponse("leaderboard.html",
                                                                                    {"request": request})


# --- User API ---
@app.post("/register")
async def register_user(user: UserCreate):
    if await users_collection.find_one({"email": user.email}): raise HTTPException(status_code=400,
                                                                                   detail="User exists")
    hashed = get_password_hash(user.password)
    await users_collection.insert_one({"name": user.name, "email": user.email, "password": hashed, "role": user.role})
    return {"message": "Account created successfully"}


@app.post("/login", response_model=Token)
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    user = await users_collection.find_one({"email": form_data.username})
    if not user or not verify_password(form_data.password, user.get("password", "")): raise HTTPException(
        status_code=401, detail="Incorrect credentials")
    access_token = create_access_token(
        data={"sub": str(user["email"]), "name": str(user.get("name", "Student")), "role": user.get("role", "student")})
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/users/me")
async def read_users_me(token: str = Depends(oauth2_scheme)):
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    return {"email": payload.get("sub"), "name": payload.get("name"), "role": payload.get("role")}


# --- Book APIs ---
@app.post("/books/bulk-add", dependencies=[Depends(admin_required)])
async def bulk_add_books(books: List[BookCreate]):
    if books: await books_collection.insert_many([b.dict() for b in books])
    return {"message": "Books added successfully"}


@app.get("/books")
async def get_books(search: str = None, category: str = None):
    query = {}
    if search: query["$or"] = [{"title": {"$regex": search, "$options": "i"}},
                               {"author": {"$regex": search, "$options": "i"}}]
    if category and category != "All": query["category"] = category
    books = await books_collection.find(query).to_list(length=1000)
    for b in books: b["_id"] = str(b["_id"])
    return books


@app.get("/books/trending")
async def get_trending_books():
    return {"trending_author": "Rabindranath Tagore", "message": "Trending data loaded"}


@app.post("/books/borrow/{isbn}")
async def borrow_book(isbn: str, days: int = Query(7), token: str = Depends(oauth2_scheme)):
    book = await books_collection.find_one({"isbn": isbn})
    if not book or book["available_copies"] < 1: raise HTTPException(status_code=400, detail="Book is out of stock")

    await books_collection.update_one({"isbn": isbn}, {"$inc": {"available_copies": -1}})
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])

    record = {
        "user_email": payload.get("sub"), "book_title": book["title"], "isbn": isbn,
        "issue_date": datetime.now().strftime("%Y-%m-%d"),
        "return_date": (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d"),
        "read_link": book.get("read_link", "#"), "download_link": book.get("download_link", "#"),
        "is_premium": book.get("is_premium", False), "price": book.get("price", 0)
    }
    await issued_books_collection.insert_one(record)
    return {"message": f"বইটি {days} দিনের জন্য ধার নেওয়া হয়েছে!"}


@app.post("/books/return/{isbn}")
async def return_book(isbn: str, token: str = Depends(oauth2_scheme)):
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    record = await issued_books_collection.find_one({"user_email": payload.get("sub"), "isbn": isbn})
    if not record: raise HTTPException(status_code=404, detail="No borrow record found")

    await issued_books_collection.delete_one({"_id": record["_id"]})
    await books_collection.update_one({"isbn": isbn}, {"$inc": {"available_copies": 1}})
    return {"message": "Book returned successfully"}


# 🔥 100% Fixed Delete Logic
@app.delete("/books/delete/{isbn}", dependencies=[Depends(admin_required)])
async def delete_book(isbn: str):
    result = await books_collection.delete_one({"isbn": isbn})
    if result.deleted_count == 1:
        return {"message": "Book deleted successfully"}
    raise HTTPException(status_code=404, detail="Book not found in database")


@app.get("/users/borrowed-books")
async def get_my_borrowed_books(token: str = Depends(oauth2_scheme)):
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    books = await issued_books_collection.find({"user_email": payload.get("sub")}).to_list(length=100)
    for b in books: b["_id"] = str(b["_id"])
    return books


@app.get("/admin/issued-books", dependencies=[Depends(admin_required)])
async def get_all_issued_books():
    books = await issued_books_collection.find().to_list(length=1000)
    for b in books: b["_id"] = str(b["_id"])
    return books


# --- Quiz APIs (Cleaned & Simple) ---
@app.post("/quiz/bulk-add", dependencies=[Depends(admin_required)])
async def bulk_add_questions(questions: List[QuestionCreate]):
    if questions: await questions_collection.insert_many([q.dict() for q in questions])
    return {"message": "Questions added successfully"}


@app.get("/quiz/all")
async def get_all_questions():
    q = await questions_collection.find().to_list(1000)
    for x in q: x["_id"] = str(x["_id"])
    return q


@app.delete("/quiz/delete/{q_id}", dependencies=[Depends(admin_required)])
async def delete_question(q_id: str):
    await questions_collection.delete_one({"_id": ObjectId(q_id)})
    return {"message": "Question deleted"}


@app.get("/quiz/start")
async def start_quiz(limit: int = 5, category: str = "All"):
    pipeline = []

    # টপিক ফিল্টার (যদি All না হয়)
    if category != "All":
        pipeline.append({"$match": {"category": {"$regex": category, "$options": "i"}}})

    pipeline.append({"$sample": {"size": limit}})

    q = await questions_collection.aggregate(pipeline).to_list(limit)
    return {"questions": [{"id": str(x["_id"]), "question": x["question_text"], "options": x["options"]} for x in q]}


@app.post("/quiz/submit")
async def submit_quiz(answers: List[QuizSubmit], token: str = Depends(oauth2_scheme)):
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    email = payload.get("sub")
    name = payload.get("name", "Student")

    score = 0;
    res = []
    for ans in answers:
        q = await questions_collection.find_one({"_id": ObjectId(ans.question_id)})
        if q:
            correct = (q["correct_answer"] == ans.selected_answer)
            if correct: score += 1
            res.append({"question": q["question_text"], "your_answer": ans.selected_answer,
                        "correct_answer": q["correct_answer"], "status": "Correct" if correct else "Wrong"})

    percentage = (score / len(answers)) * 100 if len(answers) > 0 else 0
    await quiz_results_collection.insert_one(
        {"student_name": name, "student_email": email, "score": score, "out_of": len(answers), "percentage": percentage,
         "date": datetime.now().strftime("%Y-%m-%d %H:%M")})
    return {"total_score": score, "out_of": len(answers), "percentage": percentage, "detailed_results": res}


@app.get("/quiz/leaderboard")
async def get_leaderboard():
    results = await quiz_results_collection.find().sort("percentage", -1).limit(10).to_list(10)
    for r in results: r["_id"] = str(r["_id"])
    return results


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)