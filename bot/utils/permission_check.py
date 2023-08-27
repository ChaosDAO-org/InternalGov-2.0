import discord
import logging
from discord import Permissions

class PermissionCheck:
    def __init__(self, logger):
        self.logger = logger
        

    async def check_permissions(self, guild, channel_id):
        channel = guild.get_channel(channel_id)
        if channel is None:
            self.logger.missing_role(f"Channel with ID {channel_id} not found for {guild.name} ({guild.id})")
            return
    
        perms = channel.permissions_for(guild.me)
        # There are some edge cases where the permissions is not checked correctly as channels can override 
        if not perms.manage_roles:
            self.logger.missing_role(f"'Manage Roles' permission in channel {channel.name} for {guild.name}")
        if not perms.manage_threads:
            self.logger.missing_role(f"'Manage Threads' permission in channel {channel.name} for {guild.name}")
        if not perms.send_messages_in_threads:
            self.logger.missing_role(f"'Send Messages in Threads' permission in channel {channel.name} for {guild.name}")
        if not perms.manage_messages:
            self.logger.missing_role(f"'Manage Messages' permission in channel {channel.name} for {guild.name}")
        if not perms.mention_everyone:
            self.logger.missing_role(f"'Mention Everyone' permission in channel {channel.name} for {guild.name}")
        if not perms.create_public_threads:
            self.logger.missing_role(f"'Create Public Threads' permission in channel {channel.name} for {guild.name}")
