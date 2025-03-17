# 📌 utils/database.py

import os
from pymongo import MongoClient
from dotenv import load_dotenv

# 📌 Load environment variables to get the MongoDB URI
load_dotenv()
MONGO_URI = os.getenv("MONGO_URI")

# 📌 Create a MongoDB client using the provided URI.
client = MongoClient(MONGO_URI)

# 📌 Select the database (change "DiscordBot" to your database name if needed)
db = client["DiscordBot"]

def get_collection(collection_name: str):
    """
    📌 Returns a collection from the MongoDB database.
    """
    return db[collection_name]

# 📌 Export commonly used collections for easier imports.
users_collection = get_collection("users")
settings_collection = get_collection("bot_settings")
roles_collection = get_collection("roles")
