from motor.motor_asyncio import AsyncIOMotorClient

# 👇 এই লাইনে তোমার ডাটাবেসের লিংক দেওয়া হলো
# নোট: আমি পাসওয়ার্ডের জায়গায় '12345' লিখে দিয়েছি।
# তুমি যদি অন্য পাসওয়ার্ড দিয়ে থাকো, তবে '12345' কেটে তোমার সঠিক পাসওয়ার্ডটি বসাবে।
MONGO_URL = "mongodb+srv://simanto:simanto1234@cluster0.syalsry.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

# ক্লাউড ডাটাবেস কানেকশন
client = AsyncIOMotorClient(MONGO_URL)
database = client.library_quiz_db

# কালেকশনগুলো
users_collection = database.get_collection("users")
books_collection = database.get_collection("books")
questions_collection = database.get_collection("questions")
issued_books_collection = database.get_collection("issued_books")

print("✅ Connected to MongoDB Cloud Atlas!")