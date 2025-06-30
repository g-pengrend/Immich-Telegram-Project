import asyncio
from telethon.sync import TelegramClient
from telethon.tl.types import Message, MessageMediaPhoto, MessageMediaDocument
from datetime import time, datetime, timezone, timedelta
import subprocess
from dotenv import load_dotenv
import os
import json

# --- Configuration ---

load_dotenv()

API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")
PHONE_NUMBER = os.getenv("PHONE_NUMBER")
EXAMPLE_1_GROUP_ID = os.getenv("EXAMPLE_1_GROUP_ID")
EXAMPE_2_GROUP_ID = os.getenv("EXAMPE_2_GROUP_ID")
IMMICH_API_KEY = os.getenv("IMMICH_API_KEY")

EXAMPLE_1_GROUP_ID = int(os.getenv("EXAMPLE_1_GROUP_ID"))
EXAMPE_2_GROUP_ID = int(os.getenv("EXAMPE_2_GROUP_ID"))

# Single JSON file to store last IDs for all channels
ALL_CHANNELS_LAST_ID_FILE = 'telegram_channel_last_ids.json'

CHANNELS = {
    "Example 1": {
        "group_id": EXAMPLE_1_GROUP_ID,
        "download_dir": '/home/<your user name>/telegram_project/Example_1', # change accordingly
        "album_name": "Example 1 Dearest"
    },
    "Example 2": {
        "group_id": EXAMPE_2_GROUP_ID,
        "download_dir": '/home/<your user name>/telegram_project/Example_2', # change accordingly
        "album_name": "Example 2 Dearest"
    }
}

# === Helpers ===
async def get_all_last_downloaded_ids():
    """Reads all last downloaded message IDs from a single JSON file."""
    if os.path.exists(ALL_CHANNELS_LAST_ID_FILE):
        try:
            with open(ALL_CHANNELS_LAST_ID_FILE, 'r') as f:
                return json.load(f)
        except json.JSONDecodeError:
            print(f"Warning: {ALL_CHANNELS_LAST_ID_FILE} is empty or malformed. Starting fresh.")
            return {}
    return {} # Return an empty dictionary if file doesn't exist

async def set_last_downloaded_id_for_channel(channel_name, msg_id):
    """Updates the last downloaded message ID for a specific channel in the single JSON file."""
    all_ids = await get_all_last_downloaded_ids() # Re-read to ensure we have the latest state
    all_ids[channel_name] = msg_id
    with open(ALL_CHANNELS_LAST_ID_FILE, 'w') as f:
        json.dump(all_ids, f, indent=4) # Use indent for readability

async def process_channel(client, channel_name, config):
    """Processes media download and Immich upload for a given channel."""
    group_id = config["group_id"]
    download_dir = config["download_dir"]
    album_name = config["album_name"]

    print(f"\n--- Processing {channel_name.capitalize()}'s channel ---")

    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
        print(f"Created download directory: {download_dir}")

    try:
        entity = await client.get_entity(group_id)
        print(f"Found group: {entity.title} (ID: {entity.id})")
    except Exception as e:
        print(f"❌ Could not find group with ID {group_id} for {channel_name}: {e}")
        return

    # Get last_id for the current channel from the loaded dictionary
    # We load it directly here, not from a passed parameter in this version,
    # as set_last_downloaded_id_for_channel will handle re-reading.
    current_channel_ids = await get_all_last_downloaded_ids()
    last_id = current_channel_ids.get(channel_name, 0)
    print(f"Last downloaded message ID for {channel_name}: {last_id}")

    media_count = 0
    max_id_found = last_id

    print("Fetching messages...")
    async for message in client.iter_messages(entity, min_id=last_id, reverse=False):
        # We need to explicitly check message.id > last_id because min_id is "inclusive"
        # and reverse=False means it starts from older messages.
        if message.id <= last_id:
            continue

        print(f"Checking message {message.id} at {message.date}")

        if message.media:
            timestamp = message.date.strftime('%Y%m%d_%H%M%S')
            filename = f"{message.id}_{timestamp}"
            try:
                path = await message.download_media(file=os.path.join(download_dir, filename))
                print(f"✅ Downloaded media from message {message.id} to {path}")
                media_count += 1
                max_id_found = max(max_id_found, message.id)
            except Exception as e:
                print(f"❌ Failed to download media from message {message.id}: {e}")
        else:
            print(f"Message {message.id} has no media.")

    if max_id_found > last_id:
        # Update the last ID for this channel in the single JSON file
        await set_last_downloaded_id_for_channel(channel_name, max_id_found)
        print(f"Updated last downloaded message ID for {channel_name} to {max_id_found}")

    # === Immich Upload via Docker ===
    if media_count > 0:
        print("Checking for Docker availability...")
        try:
            subprocess.run(["docker", "--version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print("✅ Docker is available. Proceeding with Immich upload...")

            subprocess.run([
                'docker', 'run', '--rm', '-i',
                '-v', f'{os.path.abspath(download_dir)}:/import:ro',
                '-e', 'IMMICH_INSTANCE_URL=http://host.docker.internal:2283/api',
                '-e', f"IMMICH_API_KEY={IMMICH_API_KEY}",
                'ghcr.io/immich-app/immich-cli:latest',
                'upload', '--album-name', album_name, '/import'
            ], check=True)

            print("✅ Upload to Immich completed successfully.")

            # Optional cleanup
            print(f"Cleaning up downloaded media from: {download_dir}")
            for file in os.listdir(download_dir):
                try:
                    os.remove(os.path.join(download_dir, file))
                except Exception as e:
                    print(f"❌ Failed to delete {file}: {e}")
            print("✅ Download folder cleaned up.")

        except FileNotFoundError:
            print("❌ Docker not found. Please ensure Docker is installed and in your PATH.")
        except subprocess.CalledProcessError as e:
            print(f"❌ Docker command failed: {e}")
        except Exception as e: # Catch other potential errors during Docker ops
            print(f"❌ An unexpected error occurred during Docker operations: {e}")
    else:
        print(f"No new media to upload or clean up for {channel_name.capitalize()}.")
    
    print(f"Finished processing {channel_name.capitalize()}. Downloaded {media_count} new media files.")


async def main():
    # Get and print the current time at the start of the script execution
    run_time = datetime.now()
    print(f"Script started at: {run_time.strftime('%Y-%m-%d %H:%M:%S')}")
    
    client = TelegramClient('my_session', API_ID, API_HASH)
    print("Connecting to Telegram...")
    await client.start(phone=PHONE_NUMBER)
    print("Client connected.")

    for channel_name, config in CHANNELS.items():
        # process_channel will now handle reading and writing from the single JSON file
        await process_channel(client, channel_name, config)

    await client.disconnect()
    print("Client disconnected.")

if __name__ == "__main__":
    asyncio.run(main())