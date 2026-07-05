"""
Discord Bot - Message Logger
Logs messages, edits, deletes, attachments, and replies to SQLite database
"""

import discord
from discord import Intents
from datetime import datetime
import json
import logging
from database import Message, Attachment, EditedMessage, DeletedMessage, get_db, close_db, init_db

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class MessageLoggerBot(discord.Client):
    """Discord bot that logs all messages to database"""

    def __init__(self):
        # Enable required intents
        intents = Intents.default()
        intents.message_content = True  # Required to read message content
        intents.messages = True
        intents.guilds = True
        intents.members = True
        intents.reactions = True

        super().__init__(intents=intents)

    async def on_ready(self):
        """Called when bot is ready"""
        logger.info(f'Bot logged in as {self.user}')
        logger.info(f'Bot ID: {self.user.id}')
        logger.info(f'Total servers: {len(self.guilds)}')
        logger.info('Bot is ready and listening for messages!')

    async def on_message(self, message):
        """Called when a message is sent"""
        # Ignore bots (optional - set to True to ignore bot messages)
        if message.author.bot and False:  # Change to True to ignore bots
            return

        # Ignore system messages
        if message.type != discord.MessageType.default:
            return

        db = get_db()
        try:
            # Extract mentions
            mentioned_users = [str(m.id) for m in message.mentions]
            mentioned_roles = [str(r.id) for r in message.role_mentions]

            # Extract reply info
            reply_to_message_id = None
            reply_to_author = None
            if message.reference and message.reference.message_id:
                try:
                    referenced_msg = await message.channel.fetch_message(message.reference.message_id)
                    reply_to_message_id = str(referenced_msg.id)
                    reply_to_author = str(referenced_msg.author)
                except:
                    reply_to_message_id = str(message.reference.message_id)

            # Create message record
            msg_record = Message(
                message_id=str(message.id),
                channel_id=str(message.channel.id),
                channel_name=getattr(message.channel, 'name', None),
                guild_id=str(message.guild.id) if message.guild else None,
                guild_name=message.guild.name if message.guild else None,
                author_id=str(message.author.id),
                author_name=message.author.name,
                author_discriminator=message.author.discriminator if hasattr(message.author, 'discriminator') else '0',
                author_nickname=message.author.nick if hasattr(message.author, 'nick') else None,
                content=message.content if message.content else None,
                timestamp=message.created_at,
                is_bot=message.author.bot,
                mentions=json.dumps(mentioned_users) if mentioned_users else None,
                mentioned_roles=json.dumps(mentioned_roles) if mentioned_roles else None,
                has_attachments=len(message.attachments) > 0,
                has_embed=len(message.embeds) > 0,
                has_reactions=len(message.reactions) > 0,
                reply_to_message_id=reply_to_message_id,
                reply_to_author=reply_to_author
            )
            db.add(msg_record)

            # Store attachments
            for attachment in message.attachments:
                att_record = Attachment(
                    message_id=str(message.id),
                    attachment_id=str(attachment.id),
                    filename=attachment.filename,
                    content_type=attachment.content_type,
                    url=attachment.url,
                    size=attachment.size,
                    proxy_url=attachment.proxy_url
                )
                db.add(att_record)

            db.commit()
            logger.info(f'Logged message {message.id} from {message.author} in #{message.channel}')

        except Exception as e:
            logger.error(f'Error logging message: {e}')
            db.rollback()
        finally:
            close_db(db)

    async def on_message_edit(self, before, after):
        """Called when a message is edited"""
        # Ignore if content didn't change
        if before.content == after.content:
            return

        # Skip system messages
        if after.type != discord.MessageType.default:
            return

        db = get_db()
        try:
            # Update the original message record
            msg_record = db.query(Message).filter_by(message_id=str(after.id)).first()
            if msg_record:
                msg_record.content = after.content
                msg_record.edited_timestamp = discord.utils.utcnow()

                # Store edit history
                edit_record = EditedMessage(
                    message_id=str(after.id),
                    old_content=before.content,
                    new_content=after.content,
                    edited_at=discord.utils.utcnow()
                )
                db.add(edit_record)
                db.commit()
                logger.info(f'Logged edit for message {after.id}')

        except Exception as e:
            logger.error(f'Error logging message edit: {e}')
            db.rollback()
        finally:
            close_db(db)

    async def on_message_delete(self, message):
        """Called when a message is deleted"""
        # Skip system messages
        if message.type != discord.MessageType.default:
            return

        db = get_db()
        try:
            # Get original message data
            msg_record = db.query(Message).filter_by(message_id=str(message.id)).first()

            # Create deleted message record
            deleted_record = DeletedMessage(
                message_id=str(message.id),
                channel_id=str(message.channel.id),
                channel_name=getattr(message.channel, 'name', None),
                guild_id=str(message.guild.id) if message.guild else None,
                guild_name=message.guild.name if message.guild else None,
                author_id=str(message.author.id),
                author_name=message.author.name,
                author_discriminator=message.author.discriminator if hasattr(message.author, 'discriminator') else '0',
                content=message.content,
                original_timestamp=message.created_at,
                has_attachments=len(message.attachments) > 0,
                reply_to_message_id=msg_record.reply_to_message_id if msg_record else None
            )
            db.add(deleted_record)

            # Update original message if exists
            if msg_record:
                msg_record.content = "[MESSAGE DELETED]"

            db.commit()
            logger.info(f'Logged deletion of message {message.id}')

        except Exception as e:
            logger.error(f'Error logging message deletion: {e}')
            db.rollback()
        finally:
            close_db(db)


def run_bot(token: str):
    """Run the Discord bot"""
    # Initialize database
    init_db()
    logger.info('Database initialized')

    # Create and run bot
    bot = MessageLoggerBot()
    bot.run(token)


if __name__ == '__main__':
    import os
    from dotenv import load_dotenv

    load_dotenv()

    DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')
    if not DISCORD_TOKEN:
        logger.error('DISCORD_TOKEN not found! Please set it in .env file')
        exit(1)

    run_bot(DISCORD_TOKEN)
