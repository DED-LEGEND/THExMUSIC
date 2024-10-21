from VIPMUSIC import app
from VIPMUSIC.core.mongo import mongodb
from pyrogram import filters
from pyrogram.types import Message
from datetime import timedelta, datetime
from pyrogram.enums import ChatMemberStatus
from pyrogram.errors import UserNotParticipant

# Database collection and default action
antiflood_collection = mongodb.antiflood_settings
DEFAULT_FLOOD_ACTION = "mute"

# Function to fetch flood settings for a chat
async def get_chat_flood_settings(chat_id):
    settings = await antiflood_collection.find_one({"chat_id": chat_id})
    if not settings:
        return {
            "flood_limit": 0,
            "flood_timer": 0,  # Ensure default flood_timer is 0
            "flood_action": DEFAULT_FLOOD_ACTION,
            "delete_flood": False
        }
    
    # Ensure all keys have default values even if missing in the database
    return {
        "flood_limit": settings.get("flood_limit", 0),
        "flood_timer": settings.get("flood_timer", 0),  # Default to 0 if not set
        "flood_action": settings.get("flood_action", DEFAULT_FLOOD_ACTION),
        "delete_flood": settings.get("delete_flood", False)
    }

# Function to update flood settings for a chat
def update_chat_flood_settings(chat_id, update_data):
    antiflood_collection.update_one({"chat_id": chat_id}, {"$set": update_data}, upsert=True)

# Function to check if user has admin rights
async def check_admin_rights(client, message: Message):
    try:
        participant = await client.get_chat_member(message.chat.id, message.from_user.id)
        if participant.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER):
            return True
    except UserNotParticipant:
        pass
    await message.reply("**You are not an admin.**")
    return False

# Command to fetch current flood settings
@app.on_message(filters.command("flood"))
async def get_flood_settings(client, message: Message):
    if not await check_admin_rights(client, message):
        return
    chat_id = message.chat.id
    settings = await get_chat_flood_settings(chat_id)
    await message.reply(
        f"Flood Limit: {settings['flood_limit']}\n"
        f"Flood Timer: {settings['flood_timer']} seconds\n"
        f"Flood Action: {settings['flood_action']}\n"
        f"Delete Flood Messages: {settings['delete_flood']}"
    )

# Command to set the flood limit
@app.on_message(filters.command("setflood"))
async def set_flood_limit(client, message: Message):
    if not await check_admin_rights(client, message):
        return
    chat_id = message.chat.id
    command_args = message.command[1:]
    
    if len(command_args) == 0:
        await message.reply("Please provide a flood limit or 'off'.")
        return
    
    flood_limit = command_args[0].lower()
    
    if flood_limit in ["off", "no", "0"]:
        update_chat_flood_settings(chat_id, {"flood_limit": 0})
        await message.reply("Antiflood has been disabled.")
    else:
        try:
            flood_limit = int(flood_limit)
            update_chat_flood_settings(chat_id, {"flood_limit": flood_limit})
            await message.reply(f"Flood limit set to {flood_limit} consecutive messages.")
        except ValueError:
            await message.reply("Invalid flood limit. Please provide a valid number or 'off'.")

# Command to set the flood timer
@app.on_message(filters.command("setfloodtimer"))
async def set_flood_timer(client, message: Message):
    if not await check_admin_rights(client, message):
        return
    chat_id = message.chat.id
    command_args = message.command[1:]
    
    if len(command_args) == 0 or command_args[0].lower() in ["off", "no"]:
        update_chat_flood_settings(chat_id, {"flood_timer": 0})
        await message.reply("Timed antiflood has been disabled.")
        return

    if len(command_args) != 2:
        await message.reply("Please provide both message count and duration in seconds.")
        return
    
    try:
        count = int(command_args[0])
        duration = int(command_args[1].replace('s', ''))
        update_chat_flood_settings(chat_id, {"flood_timer": duration, "flood_limit": count})
        await message.reply(f"Flood timer set to {count} messages in {duration} seconds.")
    except ValueError:
        await message.reply("Invalid timer settings. Please provide a valid number.")

# Command to set the action for flood violations
@app.on_message(filters.command("floodmode"))
async def set_flood_mode(client, message: Message):
    if not await check_admin_rights(client, message):
        return
    chat_id = message.chat.id
    command_args = message.command[1:]
    
    if len(command_args) == 0:
        await message.reply("Please provide a valid action (ban/mute/kick/tban/tmute).")
        return
    
    action = command_args[0].lower()
    if action not in ["ban", "mute", "kick", "tban", "tmute"]:
        await message.reply("Invalid action. Choose from ban/mute/kick/tban/tmute.")
        return
    
    update_chat_flood_settings(chat_id, {"flood_action": action})
    await message.reply(f"Flood action set to {action}.")

# Command to toggle flood message deletion
@app.on_message(filters.command("clearflood"))
async def set_flood_clear(client, message: Message):
    if not await check_admin_rights(client, message):
        return
    chat_id = message.chat.id
    command_args = message.command[1:]
    
    if len(command_args) == 0 or command_args[0].lower() not in ["yes", "no", "on", "off"]:
        await message.reply("Please choose either 'yes' or 'no'.")
        return
    
    delete_flood = command_args[0].lower() in ["yes", "on"]
    update_chat_flood_settings(chat_id, {"delete_flood": delete_flood})
    await message.reply(f"Delete flood messages set to {delete_flood}.")

# Flood detection mechanism
flood_count = {}

@app.on_message(filters.group)
async def flood_detector(client, message: Message):
    chat_id = message.chat.id
    user_id = message.from_user.id
    
    settings = await get_chat_flood_settings(chat_id)

    if settings['flood_limit'] == 0:
        return
    
    if chat_id not in flood_count:
        flood_count[chat_id] = {}
    
    user_flood_data = flood_count[chat_id].get(user_id, {"count": 0, "first_message_time": datetime.now()})

    # Ensure flood_timer is set and avoid KeyError
    flood_timer = settings.get('flood_timer', 0)
    
    if (datetime.now() - user_flood_data['first_message_time']).seconds > flood_timer:
        user_flood_data = {"count": 1, "first_message_time": datetime.now()}
    else:
        user_flood_data['count'] += 1
    
    flood_count[chat_id][user_id] = user_flood_data

    if user_flood_data['count'] > settings['flood_limit']:
        action = settings['flood_action']
        await take_flood_action(client, message, action)
        
        if settings['delete_flood']:
            await message.delete()
# Function to handle flood actions
async def take_flood_action(client, message, action):
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    if action == "ban":
        await client.kick_chat_member(chat_id, user_id)
    elif action == "mute":
        await client.restrict_chat_member(chat_id, user_id, permissions=[])
    elif action == "kick":
        await client.kick_chat_member(chat_id, user_id)
        await client.unban_chat_member(chat_id, user_id)
    elif action == "tban":
        await client.kick_chat_member(chat_id, user_id, until_date=datetime.now() + timedelta(days=3))
    elif action == "tmute":
        await client.restrict_chat_member(chat_id, user_id, permissions=[], until_date=datetime.now() + timedelta(days=3))

    await message.reply(f"User {message.from_user.first_name} was {action}ed for flooding.")
