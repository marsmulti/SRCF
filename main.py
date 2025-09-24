import os
import asyncio
import logging
from urllib.parse import urlparse

from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.errors import FloodWait, RPCError

from fastapi import FastAPI, Depends, Request, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from starlette.background import BackgroundTasks

import pymongo
from dotenv import load_dotenv

load_dotenv()

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Env variables
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "adminpass")
USER_PASSWORD = os.getenv("USER_PASSWORD", "userpass")

# MongoDB setup
mongo_client = pymongo.MongoClient(MONGO_URI)
db = mongo_client["restricted_saver_bot"]
users_collection = db["users"]

# Pyrogram Client
bot = Client("restricted_saver_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# FastAPI App
app = FastAPI()
security = HTTPBasic()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")  # If you add CSS later

# Helper functions
def is_logged_in(user_id: int) -> bool:
    user = users_collection.find_one({"user_id": user_id, "status": "active"})
    return user is not None

def add_user(user_id: int):
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"status": "active"}},
        upsert=True
    )

def ban_user(user_id: int):
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"status": "banned"}}
    )

def unban_user(user_id: int):
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"status": "active"}}
    )

# Pyrogram Handlers
@bot.on_message(filters.command("start") & filters.private)
async def start(client: Client, message: Message):
    await message.reply("Welcome! Use /login <password> to access features. Then send a message link to save restricted content.")

@bot.on_message(filters.command("login") & filters.private)
async def login(client: Client, message: Message):
    if len(message.command) < 2:
        return await message.reply("Usage: /login <password>")
    provided_pass = message.command[1]
    if provided_pass == USER_PASSWORD:
        add_user(message.from_user.id)
        await message.reply("Logged in successfully! You can now use /save.")
    else:
        await message.reply("Incorrect password.")

@bot.on_message(filters.command("save") & filters.private)
async def save_content(client: Client, message: Message):
    user_id = message.from_user.id
    if not is_logged_in(user_id):
        return await message.reply("Please /login first.")
    
    if len(message.command) < 2:
        return await message.reply("Usage: /save <message_link>")
    
    link = message.command[1]
    try:
        parsed = urlparse(link)
        path_parts = parsed.path.strip("/").split("/")
        if len(path_parts) < 2:
            raise ValueError("Invalid link")
        
        if path_parts[0] == "c":  # Private link: t.me/c/123456/12
            chat_id = -100 - int(path_parts[1])
            message_id = int(path_parts[2])
        else:  # Public: t.me/channel/12
            chat_id = f"@{path_parts[0]}"
            message_id = int(path_parts[1])
        
        await client.copy_message(
            chat_id=message.chat.id,
            from_chat_id=chat_id,
            message_id=message_id
        )
        await message.reply("Content saved and sent!")
    except ValueError:
        await message.reply("Invalid link format.")
    except RPCError as e:
        if "CHAT_FORBIDDEN" in str(e) or "CHAT_ADMIN_REQUIRED" in str(e):
            await message.reply("Add me to the channel/group as a member to access.")
        else:
            logger.error(f"Error: {e}")
            await message.reply("Error fetching content. Check logs.")
    except FloodWait as e:
        await asyncio.sleep(e.value)
        await save_content(client, message)  # Retry

# FastAPI Routes (Admin Panel)
def verify_admin(credentials: HTTPBasicCredentials = Depends(security)):
    if credentials.username != ADMIN_USERNAME or credentials.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    return credentials.username

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})  # Dummy home page

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel(request: Request, username: str = Depends(verify_admin)):
    users = list(users_collection.find({}, {"_id": 0}))
    return templates.TemplateResponse("admin.html", {"request": request, "users": users})

@app.post("/admin/ban")
async def ban_post(user_id: int = Form(...), username: str = Depends(verify_admin)):
    ban_user(user_id)
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

@app.post("/admin/unban")
async def unban_post(user_id: int = Form(...), username: str = Depends(verify_admin)):
    unban_user(user_id)
    return RedirectResponse("/admin", status_code=status.HTTP_303_SEE_OTHER)

# Lifespan for bot start/stop
async def start_bot():
    await bot.start()
    logger.info("Bot started")

async def stop_bot():
    await bot.stop()
    logger.info("Bot stopped")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(start_bot())

@app.on_event("shutdown")
async def shutdown_event():
    await stop_bot()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
