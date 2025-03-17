# 📌 bot.py
import os
import discord
import asyncio
from discord.ext import commands
from dotenv import load_dotenv
from zoneinfo import ZoneInfo



# 📌 Load environment variables from the .env file
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")  # 📌 Your bot token from the Discord Developer Portal

# 📌 Set up intents (adjust as needed; here we use all intents)
intents = discord.Intents.all()

# 📌 Create a Bot instance using the commands.Bot class.
# 📌 The command_prefix is only used for text-based commands; slash commands use the application command tree.
bot = commands.Bot(command_prefix="!", intents=intents)

# 📌 Set the bot's start time for use in commands (like /info) later.
# 📌 We use UTC with a timezone-aware datetime.
bot.start_time = discord.utils.utcnow().replace(tzinfo=ZoneInfo("UTC"))

@bot.event
async def on_ready():
    """
    📌 Called when the bot has connected to Discord and is ready.
    📌 This function syncs all global slash commands.
    """
    print(f"✅ Logged in as {bot.user} ({bot.user.id})")
    try:
        # 📌 Sync global slash commands. Global commands may take up to an hour to propagate.
        await bot.tree.sync()
        print("✅ Global slash commands synced!")
    except Exception as e:
        print("📌 Error syncing slash commands:", e)

async def load_extensions():
    """
    📌 Dynamically loads all command modules from the commands/ folder.
    📌 Each Python file (except __init__.py) in this folder is loaded as an extension (Cog).
    """
    for filename in os.listdir("./commands"):
        if filename.endswith(".py") and filename != "__init__.py":
            extension = f"commands.{filename[:-3]}"
            await bot.load_extension(extension)
            print(f"📌 Loaded extension: {extension}")

async def main():
    """
    📌 Main entry point: load extensions and start the bot.
    """
    async with bot:
        await load_extensions()
        await bot.start(TOKEN)

# 📌 Run the main function using asyncio.
asyncio.run(main())
