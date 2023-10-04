import discord
from utils.logger import Logger


class PermissionCheck:
    def __init__(self):
        self.logging = Logger()

    async def check_permissions(self, guild, channel_id):
        channel = guild.get_channel(channel_id)
        if channel is None:
            self.logging.warning(f"Channel with ID {channel_id} not found for {guild.name} ({guild.id})")
            return

        perms = channel.permissions_for(guild.me)
        # There are some edge cases where the permissions is not checked correctly as channels can override 
        if not perms.manage_roles:
            self.logging.warning(f"'Manage Roles' permission in channel {channel.name} for {guild.name}")
        if not perms.manage_threads:
            self.logging.warning(f"'Manage Threads' permission in channel {channel.name} for {guild.name}")
        if not perms.send_messages_in_threads:
            self.logging.warning(f"'Send Messages in Threads' permission in channel {channel.name} for {guild.name}")
        if not perms.manage_messages:
            self.logging.warning(f"'Manage Messages' permission in channel {channel.name} for {guild.name}")
        if not perms.mention_everyone:
            self.logging.warning(f"'Mention Everyone' permission in channel {channel.name} for {guild.name}")
        if not perms.create_public_threads:
            self.logging.warning(f"'Create Public Threads' permission in channel {channel.name} for {guild.name}")
