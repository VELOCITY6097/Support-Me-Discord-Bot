import discord
import asyncio
import os
import sys
import traceback
import re
from discord.ext import commands
from discord import app_commands
from pymongo import MongoClient
from dotenv import load_dotenv
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # Requires tzdata on Windows: pip install tzdata

# ------------------------------------------------------------------------------
# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
MONGO_URI = os.getenv("MONGO_URI")

# ------------------------------------------------------------------------------
# MongoDB Setup
client = MongoClient(MONGO_URI)
db = client["DiscordBot"]
users_collection = db["users"]
# "command_access" document stores two arrays:
#   • "allowlist": role IDs allowed to use moderation commands.
#   • "blacklist": role IDs whose holders are blocked (with warnings and auto-timeout).
settings_collection = db["bot_settings"]
roles_collection = db["roles"]

# ------------------------------------------------------------------------------
# Bot Class (Slash Commands Only)
class MyBot(discord.Client):
    def __init__(self):
        super().__init__(intents=discord.Intents.all())
        self.tree = app_commands.CommandTree(self)
        self.log_channel_id = None
        # Set the bot's start time as a timezone-aware UTC datetime
        self.start_time = datetime.now(tz=ZoneInfo("UTC"))

    async def on_ready(self):
        print(f"✅ {self.user} is online and connected to MongoDB!")
        for guild in self.guilds:
            await self.setup_log_channel(guild)
            # Register existing members from the guild.
            for member in guild.members:
                if not users_collection.find_one({"_id": member.id}):
                    users_collection.insert_one({
                        "_id": member.id,
                        "name": member.name,
                        "roles": [],
                        "banned": False,
                        "muted": False,
                        "warnings": 0
                    })
        await self.tree.sync()  # Global command sync (global commands may take up to an hour to propagate)
        print("✅ Slash commands synced!")
        if os.path.exists("restart_status.txt"):
            with open("restart_status.txt", "r") as f:
                channel_id = int(f.read().strip())
                channel = self.get_channel(channel_id)
                if channel:
                    await channel.send("✅ **Bot restarted successfully and is back online!**")
            os.remove("restart_status.txt")

    async def setup_log_channel(self, guild):
        existing_channel = discord.utils.get(guild.channels, name="bot-logs")
        if existing_channel:
            self.log_channel_id = existing_channel.id
        else:
            new_channel = await guild.create_text_channel("bot-logs")
            self.log_channel_id = new_channel.id

bot = MyBot()

# ------------------------------------------------------------------------------
# Utility Function to Convert Time Formats (e.g., "1h" → seconds)
def convert_time(duration: str):
    time_units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "y": 31536000}
    match = re.match(r"(\d+)([smhdy])", duration.lower())
    if match:
        return int(match[1]) * time_units[match[2]]
    return None

# ------------------------------------------------------------------------------
# Helper: Check Moderation Access with Warning and Auto-Timeout Logic
async def check_moderation_access(interaction: discord.Interaction, user: discord.Member) -> bool:
    if user.guild_permissions.administrator:
        return True
    data = settings_collection.find_one({"_id": "command_access"}) or {}
    allowlist = data.get("allowlist", [])
    blacklist = data.get("blacklist", [])
    user_roles = [role for role in user.roles if role != user.guild.default_role]
    if allowlist:
        if any(role.id in allowlist for role in user_roles):
            return True
        else:
            await interaction.response.send_message("❌ You do not have permission to use this moderation command.", ephemeral=True)
            return False
    if blacklist:
        if any(role.id in blacklist for role in user_roles):
            user_data = users_collection.find_one({"_id": user.id}) or {}
            warnings = user_data.get("warnings", 0) + 1
            users_collection.update_one({"_id": user.id}, {"$set": {"warnings": warnings}}, upsert=True)
            if warnings < 3:
                await interaction.response.send_message(f"⚠️ Warning {warnings}/3: You are blacklisted from using moderation commands.", ephemeral=True)
            else:
                timeout_duration = 259200  # 3 days in seconds
                until = datetime.now(tz=ZoneInfo("UTC")) + timedelta(seconds=timeout_duration)
                try:
                    await user.timeout(until, reason="Auto-timeout for blacklisted user")
                except Exception as e:
                    await interaction.response.send_message(f"❌ Failed to timeout: {e}", ephemeral=True)
                users_collection.update_one({"_id": user.id}, {"$set": {"warnings": 0}}, upsert=True)
                await interaction.response.send_message("🚫 You have been automatically timed out for 3 days due to repeated violations.", ephemeral=True)
            return False
    return True

# ------------------------------------------------------------------------------
# UI Views for Settings Dropdown and Command Access Settings
class SettingsSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Command Access", value="command access", description="Configure command access settings")
        ]
        super().__init__(placeholder="Select a settings option...", min_values=1, max_values=1, options=options)
    
    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "command access":
            await interaction.response.send_message("🔧 **Command Access Settings:**", view=ModerationAccessSettingsView(), ephemeral=True)
        else:
            await interaction.response.send_message("❌ Unknown option.", ephemeral=True)

class SettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(SettingsSelect())

# UI Views for Command Access Settings (Existing Views)
class ViewAllowlistRolesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="📜 View Allowlist Roles", style=discord.ButtonStyle.blurple)
    async def callback(self, interaction: discord.Interaction):
        data = settings_collection.find_one({"_id": "command_access"}) or {}
        allowlist = data.get("allowlist", [])
        roles = [interaction.guild.get_role(rid) for rid in allowlist]
        role_mentions = [role.mention for role in roles if role]
        if not role_mentions:
            return await interaction.response.send_message("❌ No allowlist roles set for moderation commands.", ephemeral=True)
        await interaction.response.send_message(f"✅ Allowlist roles: {', '.join(role_mentions)}", ephemeral=True)

class AddAllowlistRolesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="➕ Add Allowlist Role(s)", style=discord.ButtonStyle.green)
    async def callback(self, interaction: discord.Interaction):
        roles = [role for role in interaction.guild.roles if role.name != "@everyone"]
        view = discord.ui.View()
        view.add_item(MultiRoleSelectForAllowlist(roles, action="add"))
        await interaction.response.send_message("Select one or more roles to add to the allowlist:", view=view, ephemeral=True)

class RemoveAllowlistRolesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="➖ Remove Allowlist Role(s)", style=discord.ButtonStyle.red)
    async def callback(self, interaction: discord.Interaction):
        data = settings_collection.find_one({"_id": "command_access"}) or {}
        allowlist = data.get("allowlist", [])
        roles = [role for role in interaction.guild.roles if role.id in allowlist]
        if not roles:
            return await interaction.response.send_message("❌ No allowlist roles set.", ephemeral=True)
        view = discord.ui.View()
        view.add_item(MultiRoleSelectForAllowlist(roles, action="remove"))
        await interaction.response.send_message("Select one or more roles to remove from the allowlist:", view=view, ephemeral=True)

class ViewBlacklistRolesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="📜 View Blacklist Roles", style=discord.ButtonStyle.blurple)
    async def callback(self, interaction: discord.Interaction):
        data = settings_collection.find_one({"_id": "command_access"}) or {}
        blacklist = data.get("blacklist", [])
        roles = [interaction.guild.get_role(rid) for rid in blacklist]
        role_mentions = [role.mention for role in roles if role]
        if not role_mentions:
            return await interaction.response.send_message("❌ No blacklist roles set for moderation commands.", ephemeral=True)
        await interaction.response.send_message(f"✅ Blacklist roles: {', '.join(role_mentions)}", ephemeral=True)

class AddBlacklistRolesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="➕ Add Blacklist Role(s)", style=discord.ButtonStyle.green)
    async def callback(self, interaction: discord.Interaction):
        roles = [role for role in interaction.guild.roles if role.name != "@everyone"]
        view = discord.ui.View()
        view.add_item(MultiRoleSelectForBlacklist(roles, action="add"))
        await interaction.response.send_message("Select one or more roles to add to the blacklist:", view=view, ephemeral=True)

class RemoveBlacklistRolesButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="➖ Remove Blacklist Role(s)", style=discord.ButtonStyle.red)
    async def callback(self, interaction: discord.Interaction):
        data = settings_collection.find_one({"_id": "command_access"}) or {}
        blacklist = data.get("blacklist", [])
        roles = [role for role in interaction.guild.roles if role.id in blacklist]
        if not roles:
            return await interaction.response.send_message("❌ No blacklist roles set.", ephemeral=True)
        view = discord.ui.View()
        view.add_item(MultiRoleSelectForBlacklist(roles, action="remove"))
        await interaction.response.send_message("Select one or more roles to remove from the blacklist:", view=view, ephemeral=True)

class MultiRoleSelectForAllowlist(discord.ui.Select):
    def __init__(self, roles: list, action: str):
        self.action = action
        options = [discord.SelectOption(label=role.name, value=str(role.id)) for role in roles]
        super().__init__(placeholder="Select role(s)", min_values=1, max_values=len(options), options=options)
    async def callback(self, interaction: discord.Interaction):
        selected_ids = [int(val) for val in self.values]
        if self.action == "add":
            settings_collection.update_one({"_id": "command_access"}, {"$addToSet": {"allowlist": {"$each": selected_ids}}}, upsert=True)
            await interaction.response.send_message(f"✅ Added roles {', '.join(f'<@&{rid}>' for rid in selected_ids)} to the allowlist.", ephemeral=True)
        elif self.action == "remove":
            for rid in selected_ids:
                settings_collection.update_one({"_id": "command_access"}, {"$pull": {"allowlist": rid}})
            await interaction.response.send_message(f"✅ Removed roles {', '.join(f'<@&{rid}>' for rid in selected_ids)} from the allowlist.", ephemeral=True)

class MultiRoleSelectForBlacklist(discord.ui.Select):
    def __init__(self, roles: list, action: str):
        self.action = action
        options = [discord.SelectOption(label=role.name, value=str(role.id)) for role in roles]
        super().__init__(placeholder="Select role(s)", min_values=1, max_values=len(options), options=options)
    async def callback(self, interaction: discord.Interaction):
        selected_ids = [int(val) for val in self.values]
        if self.action == "add":
            settings_collection.update_one({"_id": "command_access"}, {"$addToSet": {"blacklist": {"$each": selected_ids}}}, upsert=True)
            await interaction.response.send_message(f"✅ Added roles {', '.join(f'<@&{rid}>' for rid in selected_ids)} to the blacklist.", ephemeral=True)
        elif self.action == "remove":
            for rid in selected_ids:
                settings_collection.update_one({"_id": "command_access"}, {"$pull": {"blacklist": rid}})
            await interaction.response.send_message(f"✅ Removed roles {', '.join(f'<@&{rid}>' for rid in selected_ids)} from the blacklist.", ephemeral=True)

class ModerationAccessSettingsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(ViewAllowlistRolesButton())
        self.add_item(AddAllowlistRolesButton())
        self.add_item(RemoveAllowlistRolesButton())
        self.add_item(ViewBlacklistRolesButton())
        self.add_item(AddBlacklistRolesButton())
        self.add_item(RemoveBlacklistRolesButton())

# ------------------------------------------------------------------------------
# Global /setting Command (no additional argument)
@bot.tree.command(name="setting", description="Access bot settings")
async def setting(interaction: discord.Interaction):
    view = SettingsView()
    await interaction.response.send_message("Please select a settings option:", view=view, ephemeral=True)

# ------------------------------------------------------------------------------
# UI View: Copy User ID Button
class CopyUserIDButton(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.add_item(CopyUserIDButton.CopyButton(user_id))
    class CopyButton(discord.ui.Button):
        def __init__(self, user_id: int):
            super().__init__(label="📋 Copy User ID", style=discord.ButtonStyle.primary, custom_id=f"copy_{user_id}")
            self.user_id = user_id
        async def callback(self, interaction: discord.Interaction):
            await interaction.response.send_message(f"✅ Copied!\n```\n{self.user_id}\n```", ephemeral=True)

# ------------------------------------------------------------------------------
# Slash Command: User Info (Moderation)
@app_commands.describe(user="User to check (mention, ID, or username)")
@bot.tree.command(name="userinfo", description="Get user information (Moderation)")
async def userinfo(interaction: discord.Interaction, user: str):
    if not await check_moderation_access(interaction, interaction.user):
        return
    member = None
    if user.startswith("<@") and user.endswith(">"):
        user_id_str = user.replace("<@!", "").replace("<@", "").replace(">", "")
        try:
            user_id_int = int(user_id_str)
            member = interaction.guild.get_member(user_id_int) or await interaction.guild.fetch_member(user_id_int)
        except Exception:
            pass
    else:
        try:
            user_id_int = int(user)
            member = interaction.guild.get_member(user_id_int) or await interaction.guild.fetch_member(user_id_int)
        except ValueError:
            member = discord.utils.find(lambda m: m.name.lower() == user.lower(), interaction.guild.members)
    if member is None:
        return await interaction.response.send_message("❌ Could not find a member matching that input.", ephemeral=True)
    user_data = users_collection.find_one({"_id": member.id})
    if not user_data:
        return await interaction.response.send_message(f"❌ {member.mention} is not registered!", ephemeral=True)
    timeout_until = member.timed_out_until
    timeout_status = "🔇 **Timed Out**" if timeout_until and timeout_until > discord.utils.utcnow() else "✅ Not Timed Out"
    join_date = member.joined_at.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%Y-%m-%d %H:%M:%S") if member.joined_at else "Unknown"
    try:
        ban_entry = await interaction.guild.fetch_ban(member)
        ban_status = f"❌ **Banned** (Reason: {ban_entry.reason})" if ban_entry else "✅ Not Banned"
    except discord.NotFound:
        ban_status = "✅ Not Banned"
    thirty_days_ago = discord.utils.utcnow() - timedelta(days=30)
    recent_penalties = []
    if "timeout_history" in user_data:
        recent_timeouts = [t for t in user_data["timeout_history"] if datetime.strptime(t["date"], "%Y-%m-%d") >= thirty_days_ago.replace(tzinfo=None)]
        if recent_timeouts:
            recent_penalties.append(f"🔇 **Timed Out {len(recent_timeouts)} times** in the last 30 days")
    if "ban_history" in user_data:
        recent_bans = [b for b in user_data["ban_history"] if datetime.strptime(b["date"], "%Y-%m-%d") >= thirty_days_ago.replace(tzinfo=None)]
        if recent_bans:
            recent_penalties.append(f"🚫 **Banned {len(recent_bans)} times** in the last 30 days")
    penalty_status = "\n".join(recent_penalties) if recent_penalties else "✅ No penalties in the last 30 days"
    embed = discord.Embed(title=f"User Info - {member.name}", color=discord.Color.blue())
    embed.add_field(name="🆔 ID", value=f"`{member.id}`", inline=True)
    embed.add_field(name="🚨 Timeout Status", value=timeout_status, inline=True)
    embed.add_field(name="🚫 Ban Status", value=ban_status, inline=False)
    embed.add_field(name="📅 Joined Server (IST)", value=join_date, inline=False)
    embed.add_field(name="⚖️ Recent Penalties", value=penalty_status, inline=False)
    view = CopyUserIDButton(member.id)
    await interaction.response.send_message(embed=embed, view=view)

# ------------------------------------------------------------------------------
# Slash Command: Timeout a User (Moderation)
@app_commands.describe(user="User to timeout", duration="Duration (e.g., 1h, 30m, 45s)", reason="Reason for timeout")
@bot.tree.command(name="timeout", description="Timeout a user (Moderation)")
async def timeout(interaction: discord.Interaction, user: discord.Member, duration: str, reason: str = "No reason provided"):
    await interaction.response.defer()
    time_in_seconds = convert_time(duration)
    if time_in_seconds is None:
        return await interaction.followup.send("❌ Invalid time format! Use `1h`, `30m`, or `45s`.", ephemeral=True)
    until = discord.utils.utcnow() + timedelta(seconds=time_in_seconds)
    try:
        await user.timeout(until, reason=reason)
    except Exception as e:
        return await interaction.followup.send(f"❌ Failed to timeout user: {e}", ephemeral=True)
    users_collection.update_one(
        {"_id": user.id},
        {"$set": {"muted": True, "mute_end": until.isoformat()},
         "$push": {"timeout_history": {"date": discord.utils.utcnow().strftime("%Y-%m-%d"), "reason": reason}}},
        upsert=True
    )
    await interaction.followup.send(f"🔇 {user.mention} has been timed out for `{duration}`. Reason: `{reason}`")
    await asyncio.sleep(time_in_seconds)
    try:
        await user.timeout(None, reason="Timeout expired")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to remove timeout: {e}", ephemeral=True)
    users_collection.update_one({"_id": user.id}, {"$set": {"muted": False}})
    await interaction.channel.send(f"🔊 {user.mention} is no longer timed out.")

# ------------------------------------------------------------------------------
# Slash Command: Remove Timeout from a User (Moderation)
@app_commands.describe(user="User to remove timeout from")
@bot.tree.command(name="removetimeout", description="Remove timeout from a user manually (Moderation)")
async def removetimeout(interaction: discord.Interaction, user: discord.Member):
    await interaction.response.defer()
    if not user.timed_out_until or user.timed_out_until <= discord.utils.utcnow():
        return await interaction.followup.send(f"⚠️ {user.mention} is not currently timed out!", ephemeral=True)
    try:
        await user.timeout(None, reason="Manual timeout removal")
    except Exception as e:
        return await interaction.followup.send(f"❌ Failed to remove timeout: {e}", ephemeral=True)
    users_collection.update_one({"_id": user.id}, {"$set": {"muted": False}})
    await interaction.followup.send(f"🔊 {user.mention} has been removed from timeout.")

# ------------------------------------------------------------------------------
# Slash Command: Temporary Role (Moderation)
@app_commands.describe(user="User to assign role", role="Role to assign", duration="Duration (e.g., 1h, 30m)")
@bot.tree.command(name="temprole", description="Assign a temporary role to a user (Moderation)")
async def temprole(interaction: discord.Interaction, user: discord.Member, role: discord.Role, duration: str):
    await interaction.response.defer(ephemeral=True)
    time_in_seconds = convert_time(duration)
    if time_in_seconds is None:
        return await interaction.followup.send("❌ Invalid time format! Use `1h`, `30m`, or `45s`.", ephemeral=True)
    try:
        await user.add_roles(role, reason=f"Temporary role assigned for {duration}")
    except Exception as e:
        return await interaction.followup.send(f"❌ Failed to add role: {e}", ephemeral=True)
    roles_collection.insert_one({"user_id": user.id, "role_id": role.id, "expires_in": time_in_seconds})
    await interaction.followup.send(f"✅ {user.mention} has been given {role.mention} for {duration}.", ephemeral=True)
    await asyncio.sleep(time_in_seconds)
    try:
        await user.remove_roles(role, reason=f"Temporary role expired after {duration}")
    except Exception as e:
        await interaction.followup.send(f"❌ Failed to remove role: {e}", ephemeral=True)
    roles_collection.delete_one({"user_id": user.id, "role_id": role.id})
    await interaction.channel.send(f"❌ {role.mention} has been removed from {user.mention} after {duration}.")

# ------------------------------------------------------------------------------
# Slash Command: Ban a User (Moderation)
@app_commands.describe(user="User to ban", reason="Reason for ban")
@bot.tree.command(name="ban", description="Ban a user (Moderation)")
async def ban(interaction: discord.Interaction, user: discord.Member, reason: str = "No reason provided"):
    if not await check_moderation_access(interaction, interaction.user):
        return
    if not interaction.user.guild_permissions.ban_members:
        return await interaction.response.send_message("❌ You don’t have permission to ban users!", ephemeral=True)
    await user.ban(reason=reason)
    users_collection.update_one({"_id": user.id}, {"$set": {"banned": True, "ban_reason": reason}}, upsert=True)
    await interaction.response.send_message(f"✅ {user.mention} was banned! Reason: {reason}")

# ------------------------------------------------------------------------------
# Slash Command: Unban a User (Moderation)
@app_commands.describe(user_id="User ID of the user to unban", reason="Reason for unban (optional)")
@bot.tree.command(name="unban", description="Unban a user by their ID (Moderation)")
async def unban(interaction: discord.Interaction, user_id: str, reason: str = "No reason provided"):
    if not await check_moderation_access(interaction, interaction.user):
        return
    if not interaction.user.guild_permissions.ban_members:
        return await interaction.response.send_message("⛔ You don’t have permission to unban users!", ephemeral=True)
    try:
        user_id_int = int(user_id)
    except ValueError:
        return await interaction.response.send_message("❌ Invalid user ID format. Please provide a valid numeric ID.", ephemeral=True)
    try:
        user_to_unban = None
        async for ban_entry in interaction.guild.bans():
            if ban_entry.user.id == user_id_int:
                user_to_unban = ban_entry.user
                break
        if user_to_unban is None:
            return await interaction.response.send_message("❌ That user is not currently banned.", ephemeral=True)
        await interaction.guild.unban(user_to_unban, reason=reason)
        users_collection.update_one({"_id": user_id_int}, {"$set": {"banned": False}}, upsert=True)
        await interaction.response.send_message(f"✅ Successfully unbanned {user_to_unban.mention}!")
    except discord.Forbidden:
        await interaction.response.send_message("❌ I don't have permission to unban users.", ephemeral=True)
    except discord.HTTPException as e:
        await interaction.response.send_message(f"❌ Failed to unban user due to an error: {e}", ephemeral=True)

# ------------------------------------------------------------------------------
# New Slash Command: Info (Bot Uptime and Ping)
@bot.tree.command(name="info", description="Display bot uptime and ping")
async def info(interaction: discord.Interaction):
    # Calculate uptime as a timedelta (timezone-aware)
    uptime_delta = datetime.now(tz=ZoneInfo("UTC")) - bot.start_time
    total_seconds = int(uptime_delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"
    
    ping = round(bot.latency * 1000, 2)
    embed = discord.Embed(title="Bot Info", color=discord.Color.blue())
    embed.add_field(name="Uptime", value=uptime_str, inline=False)
    embed.add_field(name="Ping", value=f"{ping} ms", inline=False)
    await interaction.response.send_message(embed=embed)

# ------------------------------------------------------------------------------
# Run the Bot
bot.run(TOKEN)
