# Discord Bot

🔹 Moderation Features
Auto-Register Users – When a user joins, they are automatically added to the database with default attributes.
User Info (/userinfo) – Check a user's stored data, including mute/ban history, roles, and join date.
Ban User (/ban) – Ban a user and store their ban reason in the database.
Mute User (/mute) – Temporarily mute a user for a set duration (e.g., 30m, 1h).
Temporary Role (/temprole) – Assign a role to a user for a specified time and remove it automatically.
Track Penalties – Records bans and mutes, and tracks recent penalties (last 30 days).
Automatic Logging – Logs errors and important actions in a bot-logs channel.
<BR>
<BR>
🔹 Utility Features
Bot Restart (/restart) – Authorized users can restart the bot and refresh the database.
Copy User ID Button – Provides a button to copy a user’s ID directly.
MongoDB Integration – Stores user data persistently, including penalties and role history.
Error Handling – Detects and logs errors from both normal and slash commands.
Log Channel Setup – Ensures a bot-logs channel exists in every server for logging errors and bot activity.
