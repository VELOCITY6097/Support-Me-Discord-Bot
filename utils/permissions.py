# 📌 utils/permissions.py

import discord
from utils.database import settings_collection, users_collection

async def check_moderation_access(interaction: discord.Interaction, user: discord.Member) -> bool:
    """
    📌 Checks if the user has access to moderation commands.
    📌 Administrators are always allowed.
    📌 If an allowlist exists, the user must have a role from that list.
    📌 If a blacklist exists, the user is blocked and may receive warnings and auto-timeout.
    """
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
                from datetime import datetime, timedelta
                from zoneinfo import ZoneInfo
                timeout_duration = 259200  # 📌 3 days in seconds
                until = datetime.now(tz=ZoneInfo("UTC")) + timedelta(seconds=timeout_duration)
                try:
                    await user.timeout(until, reason="Auto-timeout for blacklisted user")
                except Exception as e:
                    await interaction.response.send_message(f"❌ Failed to timeout: {e}", ephemeral=True)
                users_collection.update_one({"_id": user.id}, {"$set": {"warnings": 0}}, upsert=True)
                await interaction.response.send_message("🚫 You have been automatically timed out for 3 days due to repeated violations.", ephemeral=True)
            return False
    return True
