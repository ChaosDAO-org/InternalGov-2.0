import discord
import asyncio
import json
import os
from discord.ui import View, Button
from utils.logger import Logger

logger = Logger()

# Define the persistent view for role reaction buttons
class RoleButtonView(View):
    def __init__(self, bot, config):
        super().__init__(timeout=None)  # No timeout for persistent view
        self.bot = bot
        self.config = config
        self.logger = logger
        
        # Add the buttons with custom_ids that will persist across restarts
        add_button = Button(style=discord.ButtonStyle.success, label="Get Notifications", emoji="🔔", custom_id="add_gov_role_button")
        remove_button = Button(style=discord.ButtonStyle.secondary, label="Remove Notifications", emoji="🔕", custom_id="remove_gov_role_button")
        
        # Add items to the view
        self.add_item(add_button)
        self.add_item(remove_button)

class RoleReactionManager:
    def __init__(self, bot, config):
        self.bot = bot
        self.config = config
        self.logger = logger
        self.reaction_data_file = "../data/reaction_roles.json"
        self.reaction_data = self.load_reaction_data()
        
        # Setup persistent view
        self.setup_persistent_view()
        
    def load_reaction_data(self):
        """Load reaction role data from file"""
        try:
            if os.path.exists(self.reaction_data_file):
                with open(self.reaction_data_file, 'r') as file:
                    data = json.load(file)
                    self.logger.info(f"Loaded reaction data: {data}")
                    return data
            self.logger.info(f"No reaction data file found at {self.reaction_data_file}")
            return {}
        except Exception as e:
            self.logger.error(f"Error loading reaction data: {e}")
            return {}
    
    def save_reaction_data(self):
        """Save reaction role data to file"""
        try:
            # Ensure data directory exists
            os.makedirs(os.path.dirname(self.reaction_data_file), exist_ok=True)
            
            with open(self.reaction_data_file, 'w') as file:
                json.dump(self.reaction_data, file, indent=4)
                self.logger.info(f"Saved reaction data: {self.reaction_data}")
        except Exception as e:
            self.logger.error(f"Error saving reaction data: {e}")
    
    async def create_gov_notification_thread(self, guild_id, channel_id):
        """Create a thread for governance notifications if it doesn't exist"""
        try:
            # Check if thread already exists
            if "gov_notification_thread" in self.reaction_data:
                try:
                    # Try to fetch existing thread
                    thread_id = self.reaction_data["gov_notification_thread"]["thread_id"]
                    thread = await self.bot.fetch_channel(thread_id)
                    self.logger.info(f"Gov notification thread already exists with ID: {thread.id}")
                    return thread
                except discord.NotFound:
                    self.logger.info("Gov notification thread no longer exists, creating a new one")
                except Exception as e:
                    self.logger.error(f"Error fetching existing thread: {e}")
            
            # Get the channel and guild
            guild = self.bot.get_guild(guild_id)
            if not guild:
                self.logger.error(f"Guild with ID {guild_id} not found")
                return None
            
            channel = self.bot.get_channel(channel_id)
            if not channel:
                self.logger.error(f"Channel with ID {channel_id} not found")
                return None
            
            # Create thread content
            content = ("# Governance Notification Role\n\n"
                      "React with the following emojis to manage your notification settings:\n\n"
                      "- 🔔 Add the governance notification role to receive alerts for new proposals\n"
                      "- 🔕 Remove the governance notification role and stop receiving alerts\n\n"
                      "You will be notified when new governance proposals are posted.\n"
                      "This thread is locked for comments. Please use the reactions on the main post to manage your notification settings.")
            
            # Get or create a tag for the thread
            available_tags = [tag for tag in channel.available_tags]
            gov_tag = next((tag for tag in available_tags if tag.name.lower() == "announcement"), None)
            
            if not gov_tag:
                try:
                    gov_tag = await channel.create_tag(name="Announcement")
                except Exception as e:
                    self.logger.error(f"Failed to create tag: {e}")
                    gov_tag = None
            
            # Create the thread
            thread_message = await channel.create_thread(
                name="Get Governance Notification Role",
                content=content,
                applied_tags=[gov_tag] if gov_tag else [],
                slowmode_delay=21600
            )
            
            # Get the actual thread
            thread = await guild.fetch_channel(thread_message.thread.id)
            
            # Pin the initial message in the thread
            messages = [msg async for msg in thread.history(limit=1, oldest_first=True)]
            if messages:
                first_message = messages[0]
                
                # Use the persistent view for the buttons
                view = self.create_role_buttons()
                await first_message.edit(content=first_message.content, view=view)
                
                # Save the message ID for persistence across restarts
                self.bot.persistent_view_message_ids = getattr(self.bot, 'persistent_view_message_ids', [])
                self.bot.persistent_view_message_ids.append(first_message.id)
                
                # Save thread data
                self.reaction_data["gov_notification_thread"] = {
                    "thread_id": thread.id,
                    "message_id": first_message.id,
                    "guild_id": guild_id,
                    "add_emoji": "🔔",
                    "remove_emoji": "🔕",
                    "role_name": self.config.TAG_ROLE_NAME
                }
                self.save_reaction_data()
                
                # Don't lock the thread (would disable buttons)
                self.logger.info(f"Created notification thread {thread.id}")
            
                # Pin the thread itself
                await thread.edit(pinned=True)
                
                # Update thread content to indicate messages will be deleted
                thread_content = ("# Governance Notification Role\n\n"
                                "Use the buttons below to manage your notification settings:\n\n"
                                "- 🔔 **Get Notifications** - Receive alerts for new governance proposals\n"
                                "- 🔕 **Remove Notifications** - Stop receiving alerts\n\n"
                                "Messages from non-admins will be automatically deleted from this thread.")
                await first_message.edit(content=thread_content, view=view)
            
            return thread
            
        except Exception as e:
            self.logger.error(f"Error creating notification thread: {e}")
            return None
    
    def setup_persistent_view(self):
        """Setup persistent view for the bot"""
        # Create persistent view
        view = RoleButtonView(self.bot, self.config)
        self.bot.add_view(view)
        
        # If we have a stored message_id, add a view specifically for that message
        if "gov_notification_thread" in self.reaction_data and "message_id" in self.reaction_data["gov_notification_thread"]:
            message_id = self.reaction_data["gov_notification_thread"]["message_id"]
            self.logger.info(f"Registering persistent view for message ID: {message_id}")
            # Add a message-specific view
            specific_view = RoleButtonView(self.bot, self.config)
            self.bot.add_view(specific_view, message_id=int(message_id))
                
    async def handle_add_role(self, interaction):
        """Handle add role button interaction"""
        try:
            # Get data
            thread_data = self.reaction_data.get("gov_notification_thread", {})
            guild = self.bot.get_guild(thread_data.get("guild_id", self.config.DISCORD_SERVER_ID))
            if not guild:
                await interaction.response.send_message("Error: Server not found", ephemeral=True)
                return
            
            # Get role
            role = discord.utils.get(guild.roles, name=self.config.TAG_ROLE_NAME)
            if not role:
                await interaction.response.send_message(f"Error: Role {self.config.TAG_ROLE_NAME} not found", ephemeral=True)
                return
            
            try:
                # First acknowledge the interaction to prevent timeout
                await interaction.response.defer(ephemeral=True)
            except discord.errors.InteractionResponded:
                self.logger.info("Interaction already responded to")
            
            # Add role
            await interaction.user.add_roles(role)
            self.logger.info(f"Added role {role.name} to {interaction.user.display_name}")
            
            # Now send the followup message
            try:
                await interaction.followup.send(f"You now have the {role.name} role and will receive notifications for new governance proposals.", ephemeral=True)
            except Exception as e:
                self.logger.error(f"Error sending followup message: {e}")
        except Exception as e:
            self.logger.error(f"Error in add button callback: {e}")
    
    async def handle_remove_role(self, interaction):
        """Handle remove role button interaction"""
        try:
            # Get data
            thread_data = self.reaction_data.get("gov_notification_thread", {})
            guild = self.bot.get_guild(thread_data.get("guild_id", self.config.DISCORD_SERVER_ID))
            if not guild:
                await interaction.response.send_message("Error: Server not found", ephemeral=True)
                return
            
            # Get role
            role = discord.utils.get(guild.roles, name=self.config.TAG_ROLE_NAME)
            if not role:
                await interaction.response.send_message(f"Error: Role {self.config.TAG_ROLE_NAME} not found", ephemeral=True)
                return
            
            try:
                # First acknowledge the interaction to prevent timeout
                await interaction.response.defer(ephemeral=True)
            except discord.errors.InteractionResponded:
                self.logger.info("Interaction already responded to")
            
            # Remove role
            await interaction.user.remove_roles(role)
            self.logger.info(f"Removed role {role.name} from {interaction.user.display_name}")
            
            # Now send the followup message
            try:
                await interaction.followup.send(f"You no longer have the {role.name} role and won't receive notifications for new governance proposals.", ephemeral=True)
            except Exception as e:
                self.logger.error(f"Error sending followup message: {e}")
        except Exception as e:
            self.logger.error(f"Error in remove button callback: {e}")
            
    def create_role_buttons(self):
        """Create buttons for role management"""
        return RoleButtonView(self.bot, self.config)

    async def handle_reaction(self, payload):
        """Legacy method kept for compatibility"""
        # This is now handled by button callbacks
        pass
        
    async def on_message(self, message):
        """Delete messages from non-admins in the notification thread"""
        if "gov_notification_thread" not in self.reaction_data:
            return
            
        thread_data = self.reaction_data["gov_notification_thread"]
        
        # Only process messages in our thread
        if message.channel.id != thread_data["thread_id"]:
            return
            
        # Don't delete bot messages
        if message.author.bot:
            return
            
        # Don't delete the thread's initial message
        if message.id == thread_data["message_id"]:
            return
            
        # Check if user is admin
        is_admin = False
        admin_role = discord.utils.get(message.guild.roles, name=self.config.DISCORD_ADMIN_ROLE)
        
        if admin_role and admin_role in message.author.roles:
            is_admin = True
            
        if not is_admin:
            try:
                await message.delete()
                self.logger.info(f"Deleted message from non-admin user {message.author.display_name} in notification thread")
            except Exception as e:
                self.logger.error(f"Failed to delete message: {e}")
