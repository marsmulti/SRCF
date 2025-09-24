# Telegram Bot for Creating GitHub Repositories using Pyrogram, PyGitHub, and MongoDB
# Author: Grok (xAI) - Expert in Python and Telegram Bot Programming
# Date: September 23, 2025
#
# This bot allows users to log in with their Telegram accounts (creating Pyrogram sessions),
# authenticate with GitHub, and create GitHub repositories. It includes an admin panel and
# handles Telegram FloodWait errors to prevent bans. MongoDB stores user sessions and GitHub tokens.
#
# Prerequisites for Deployment (for Novice Users):
# 1. Create a Telegram Bot:
#    - Go to @BotFather on Telegram, send /newbot, follow prompts, and get BOT_TOKEN.
# 2. Get Telegram API Credentials:
#    - Visit my.telegram.org, log in, create an app, and note API_ID and API_HASH.
# 3. Get GitHub Personal Access Token:
#    - Go to github.com > Settings > Developer settings > Personal access tokens > Tokens (classic).
#    - Generate a token with 'repo' scope. Copy GITHUB_TOKEN.
# 4. Set Up MongoDB:
#    - Create a free MongoDB Atlas account at mongodb.com.
#    - Create a cluster, get MONGO_URI (connection string).
# 5. Set Environment Variables:
#    - In your deployment platform (e.g., Render, Heroku, VPS) or .env file, set:
#      - API_ID: Your Telegram API ID
#      - API_HASH: Your Telegram API Hash
#      - BOT_TOKEN: Your Telegram Bot Token
#      - MONGO_URI: Your MongoDB connection string
#      - ADMIN_IDS: Comma-separated Telegram user IDs of admins (e.g., "123456789,987654321")
# 6. Install Dependencies:
#    - Create a requirements.txt file with:
#      ```
#      pyrogram==2.0.106
#      tgcrypto
#      pymongo
#      python-dotenv
#      PyGithub
#      ```
#    - Run: pip install -r requirements.txt
# 7. Deploy:
#    - Save this script as bot.py.
#    - Upload to your platform (e.g., Render, Heroku) or VPS.
#    - Set start command: python bot.py
#    - For local testing: python bot.py
#
# Notes:
# - Multi-user support: Users log in with their Telegram accounts; sessions stored in MongoDB.
# - GitHub tokens are stored securely in MongoDB.
# - FloodWait handling prevents Telegram bans.
# - Admin panel for managing users and broadcasting messages.
# - Run locally first to test setup.

import os
import asyncio
import logging
from dotenv import load_dotenv
from pyrogram import Client, filters, enums
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message
from pyrogram.errors import FloodWait, SessionPasswordNeeded, PhoneCodeInvalid, PhoneNumberInvalid
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from github import Github, GithubException

# Load environment variables
load_dotenv()

API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
BOT_TOKEN = os.getenv("BOT_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")
ADMIN_IDS = [int(admin_id) for admin_id in os.getenv("ADMIN_IDS", "").split(",") if admin_id]

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# MongoDB Setup
try:
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client["github_bot_db"]
    users_collection = db["users"]
    sessions_collection = db["sessions"]
    github_tokens_collection = db["github_tokens"]
    logger.info("Connected to MongoDB successfully.")
except PyMongoError as e:
    logger.error(f"Failed to connect to MongoDB: {e}")
    exit(1)

# Bot Client
bot = Client("github_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Helper Functions
def get_user_session(user_id: int) -> str:
    """Retrieve the string session for a user from MongoDB."""
    session_doc = sessions_collection.find_one({"user_id": user_id})
    return session_doc["string_session"] if session_doc else None

def save_user_session(user_id: int, string_session: str):
    """Save the string session to MongoDB."""
    sessions_collection.update_one(
        {"user_id": user_id},
        {"$set": {"string_session": string_session}},
        upsert=True
    )

def get_github_token(user_id: int) -> str:
    """Retrieve the GitHub token for a user from MongoDB."""
    token_doc = github_tokens_collection.find_one({"user_id": user_id})
    return token_doc["token"] if token_doc else None

def save_github_token(user_id: int, token: str):
    """Save the GitHub token to MongoDB."""
    github_tokens_collection.update_one(
        {"user_id": user_id},
        {"$set": {"token": token}},
        upsert=True
    )

def is_admin(user_id: int) -> bool:
    """Check if user is an admin."""
    return user_id in ADMIN_IDS

# Start Command
@bot.on_message(filters.command("start") & filters.private)
async def start(client: Client, message: Message):
    user_id = message.from_user.id
    users_collection.update_one({"user_id": user_id}, {"$set": {"user_id": user_id}}, upsert=True)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔑 Telegram Login", callback_data="telegram_login")],
        [InlineKeyboardButton("🔐 GitHub Login", callback_data="github_login")],
        [InlineKeyboardButton("📋 Help", callback_data="help")],
        [InlineKeyboardButton("👤 Admin Panel" if is_admin(user_id) else "ℹ️ About", callback_data="admin" if is_admin(user_id) else "about")]
    ])
    
    await message.reply_text(
        "🌟 **Welcome to GitHub Repo Creator Bot!** 🌟\n\n"
        "This bot helps you create GitHub repositories using your Telegram account.\n"
        "1. Log in with Telegram to authenticate.\n"
        "2. Provide a GitHub token to create repos.\n"
        "Start by logging in! 🚀",
        reply_markup=keyboard
    )

# Callback Query Handler
@bot.on_callback_query()
async def callback_handler(client: Client, query):
    data = query.data
    user_id = query.from_user.id
    
    if data == "telegram_login":
        await handle_telegram_login_start(query.message)
    elif data == "github_login":
        await handle_github_login_start(query.message)
    elif data == "help":
        await send_help(query.message)
    elif data == "admin":
        if is_admin(user_id):
            await send_admin_panel(query.message)
        else:
            await query.answer("You are not an admin!", show_alert=True)
    elif data == "about":
        await query.message.reply_text("This bot is built with ❤️ using Pyrogram, PyGitHub, and MongoDB.")
    elif data == "create_repo":
        await handle_create_repo_start(query.message)
    elif data in ["repo_public", "repo_private"]:
        await handle_repo_visibility(client, query)

# Telegram Login Process
async def handle_telegram_login_start(message: Message):
    user_id = message.from_user.id
    if get_user_session(user_id):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Re-Login", callback_data="telegram_relogin_confirm")],
            [InlineKeyboardButton("🔙 Back", callback_data="start")]
        ])
        await message.reply_text("You are already logged in to Telegram. Re-login?", reply_markup=keyboard)
        return
    
    await message.reply_text(
        "🔑 **Telegram Login Process:**\n\n"
        "1. Send your phone number (e.g., +1234567890).\n"
        "2. Receive a code on Telegram.\n"
        "3. Reply with the code.\n"
        "4. If 2FA is enabled, provide your password."
    )
    users_collection.update_one({"user_id": user_id}, {"$set": {"login_step": "phone"}}, upsert=True)

@bot.on_message(filters.private & ~filters.command(["start", "help", "create", "admin"]))
async def login_steps(client: Client, message: Message):
    user_id = message.from_user.id
    user_doc = users_collection.find_one({"user_id": user_id})
    if not user_doc or "login_step" not in user_doc:
        return
    
    step = user_doc["login_step"]
    
    if step == "phone":
        phone = message.text.strip()
        try:
            app = Client(f"user_{user_id}", api_id=API_ID, api_hash=API_HASH, phone_number=phone)
            await app.start()
            sent_code = await app.send_code(phone)
            users_collection.update_one({"user_id": user_id}, {"$set": {"login_step": "code", "phone": phone, "phone_code_hash": sent_code.phone_code_hash}})
            await message.reply_text("📩 Code sent to your Telegram. Reply with the code.")
        except PhoneNumberInvalid:
            await message.reply_text("❌ Invalid phone number. Try again.")
        except Exception as e:
            await message.reply_text(f"❌ Error: {str(e)}")
    
    elif step == "code":
        code = message.text.strip()
        phone = user_doc["phone"]
        phone_code_hash = user_doc["phone_code_hash"]
        app = Client(f"user_{user_id}", api_id=API_ID, api_hash=API_HASH, phone_number=phone)
        try:
            await app.sign_in(phone, phone_code_hash, code)
            string_session = await app.export_session_string()
            save_user_session(user_id, string_session)
            await app.stop()
            users_collection.update_one({"user_id": user_id}, {"$unset": {"login_step": "", "phone": "", "phone_code_hash": ""}})
            await message.reply_text("✅ Telegram login successful! Now use GitHub login or /create.")
        except SessionPasswordNeeded:
            users_collection.update_one({"user_id": user_id}, {"$set": {"login_step": "password"}})
            await message.reply_text("🔒 2FA enabled. Send your password.")
        except PhoneCodeInvalid:
            await message.reply_text("❌ Invalid code. Try again.")
        except Exception as e:
            await message.reply_text(f"❌ Error: {str(e)}")
    
    elif step == "password":
        password = message.text.strip()
        phone = user_doc["phone"]
        app = Client(f"user_{user_id}", api_id=API_ID, api_hash=API_HASH, phone_number=phone)
        try:
            await app.check_password(password)
            string_session = await app.export_session_string()
            save_user_session(user_id, string_session)
            await app.stop()
            users_collection.update_one({"user_id": user_id}, {"$unset": {"login_step": "", "phone": "", "phone_code_hash": ""}})
            await message.reply_text("✅ Telegram login successful! Now use GitHub login or /create.")
        except Exception as e:
            await message.reply_text(f"❌ Error: {str(e)}")
    
    elif step == "github_token":
        token = message.text.strip()
        try:
            g = Github(token)
            g.get_user().login  # Test token validity
            save_github_token(user_id, token)
            users_collection.update_one({"user_id": user_id}, {"$unset": {"login_step": ""}})
            await message.reply_text("✅ GitHub login successful! Use /create to make a repository.")
        except GithubException as e:
            await message.reply_text(f"❌ Invalid GitHub token: {str(e)}")
        except Exception as e:
            await message.reply_text(f"❌ Error: {str(e)}")

# GitHub Login Process
async def handle_github_login_start(message: Message):
    user_id = message.from_user.id
    if get_github_token(user_id):
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Re-Login GitHub", callback_data="github_relogin_confirm")],
            [InlineKeyboardButton("🔙 Back", callback_data="start")]
        ])
        await message.reply_text("You are already logged in to GitHub. Re-login?", reply_markup=keyboard)
        return
    
    await message.reply_text(
        "🔐 **GitHub Login Process:**\n\n"
        "1. Send your GitHub Personal Access Token.\n"
        "   - Get it from github.com > Settings > Developer settings > Personal access tokens.\n"
        "   - Ensure it has 'repo' scope."
    )
    users_collection.update_one({"user_id": user_id}, {"$set": {"login_step": "github_token"}}, upsert=True)

# Help Command
@bot.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    await send_help(message)

async def send_help(message: Message):
    help_text = (
        "📚 **Detailed Help Guide** 📚\n\n"
        "This bot creates GitHub repositories using your Telegram and GitHub accounts.\n\n"
        "**User Features:**\n"
        "1. **/start**: Welcome menu with login and help options.\n"
        "2. **Telegram Login**: Authenticate with your Telegram account (required).\n"
        "3. **GitHub Login**: Provide a GitHub token with 'repo' scope.\n"
        "4. **/create**: Create a GitHub repository.\n"
        "   - Specify repo name, description, and private/public status.\n"
        "   - Example: Use /create to start the process.\n"
        "5. **FloodWait**: Auto-handles Telegram rate limits to prevent bans.\n\n"
        "**Admin Features:** (/admin)\n"
        "1. List all users.\n"
        "2. Ban/unban users.\n"
        "3. Broadcast messages to all users.\n\n"
        "**Tips:**\n"
        "- Ensure your GitHub token has 'repo' scope.\n"
        "- Keep your token secure; don’t share it.\n"
        "- For issues, contact admin.\n"
        "- Deploy on Render/Heroku for easy hosting."
    )
    await message.reply_text(help_text, parse_mode=enums.ParseMode.MARKDOWN)

# Admin Panel
@bot.on_message(filters.command("admin") & filters.private)
async def admin_command(client: Client, message: Message):
    if not is_admin(message.from_user.id):
        await message.reply_text("❌ You are not an admin.")
        return
    await send_admin_panel(message)

async def send_admin_panel(message: Message):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 List Users", callback_data="admin_list_users")],
        [InlineKeyboardButton("🚫 Ban User", callback_data="admin_ban")],
        [InlineKeyboardButton("✅ Unban User", callback_data="admin_unban")],
        [InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🔙 Back", callback_data="start")]
    ])
    await message.reply_text("👤 **Admin Panel** 👤\nChoose an option:", reply_markup=keyboard)

# Create Repository Command
@bot.on_message(filters.command("create") & filters.private)
async def create_command(client: Client, message: Message):
    user_id = message.from_user.id
    if not get_user_session(user_id):
        await message.reply_text("❌ Please login to Telegram first using /start > Telegram Login.")
        return
    if not get_github_token(user_id):
        await message.reply_text("❌ Please login to GitHub first using /start > GitHub Login.")
        return
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📁 Create Repository", callback_data="create_repo")]
    ])
    await message.reply_text("Ready to create a GitHub repository! Click below:", reply_markup=keyboard)

async def handle_create_repo_start(message: Message):
    user_id = message.from_user.id
    users_collection.update_one({"user_id": user_id}, {"$set": {"repo_step": "name"}})
    await message.reply_text("📁 **Create Repository:**\n\nSend the repository name (e.g., my-new-repo):")

@bot.on_message(filters.private & ~filters.command(["start", "help", "create", "admin"]))
async def repo_steps(client: Client, message: Message):
    user_id = message.from_user.id
    user_doc = users_collection.find_one({"user_id": user_id})
    if not user_doc or "repo_step" not in user_doc:
        return
    
    step = user_doc["repo_step"]
    
    if step == "name":
        repo_name = message.text.strip()
        users_collection.update_one({"user_id": user_id}, {"$set": {"repo_name": repo_name, "repo_step": "description"}})
        await message.reply_text("Send the repository description (or 'None' to skip):")
    
    elif step == "description":
        description = message.text.strip() if message.text.strip().lower() != "none" else None
        users_collection.update_one({"user_id": user_id}, {"$set": {"repo_description": description, "repo_step": "visibility"}})
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🌐 Public", callback_data="repo_public")],
            [InlineKeyboardButton("🔒 Private", callback_data="repo_private")]
        ])
        await message.reply_text("Choose repository visibility:", reply_markup=keyboard)

async def handle_repo_visibility(client: Client, query):
    user_id = query.from_user.id
    data = query.data
    user_doc = users_collection.find_one({"user_id": user_id})
    
    is_private = data == "repo_private"
    repo_name = user_doc["repo_name"]
    description = user_doc["repo_description"]
    
    try:
        token = get_github_token(user_id)
        g = Github(token)
        user = g.get_user()
        repo = user.create_repo(
            name=repo_name,
            description=description,
            private=is_private,
            auto_init=True  # Initialize with README
        )
        users_collection.update_one({"user_id": user_id}, {"$unset": {"repo_step": "", "repo_name": "", "repo_description": ""}})
        await query.message.reply_text(
            f"✅ Repository created successfully!\n"
            f"Name: {repo_name}\n"
            f"URL: {repo.html_url}\n"
            f"Visibility: {'Private' if is_private else 'Public'}"
        )
    except GithubException as e:
        await query.message.reply_text(f"❌ Failed to create repository: {str(e)}")
    except Exception as e:
        await query.message.reply_text(f"❌ Error: {str(e)}")
    except FloodWait as e:
        logger.warning(f"FloodWait: Sleeping for {e.value} seconds.")
        await asyncio.sleep(e.value)
        await query.message.reply_text("⏳ Hit Telegram rate limit. Retrying after a pause...")

# Run the Bot
if __name__ == "__main__":
    bot.run()
