import re
import time
import json
import asyncio
import discord
import requests
import aiofiles
from typing import Dict, Any
from discord import app_commands, Embed
from utils.logger import Logger
from utils.config import Config
from utils.proxy import ProxyVoter
from utils.data_processing import Text
from utils.button_handler import ButtonHandler, ExternalLinkButton
from aiohttp.web_exceptions import HTTPException
from datetime import datetime, timezone
import sys


class GovernanceMonitor(discord.Client):
    def __init__(self, guild, discord_role, permission_checker, intents):
        super().__init__(intents=intents)
        self.button_cooldowns = {}
        self.config = Config()
        self.logger = Logger()
        self.discord_role = discord_role
        self.guild = guild
        self.permission_checker = permission_checker
        self.tree = app_commands.CommandTree(self)
        loop = asyncio.get_event_loop()
        self.vote_counts = loop.run_until_complete(self.load_vote_counts())

    async def setup_hook(self):
        self.tree.copy_global_to(guild=self.guild)
        await self.tree.sync(guild=self.guild)

    def get_asset_price_v2(self, asset_id, currencies='usd'):
        """
        Fetches the price of an asset in the specified currencies from the CoinGecko API.

        Args:
            asset_id (str): The ID of the asset for which to fetch the price (e.g., "bitcoin").
            currencies (str, optional): A comma-separated string of currency symbols
                                         (default is 'usd,gbp,eur').

        Returns:
            dict: A dictionary containing the prices in the specified currencies, or None
                  if an error occurred or the asset ID was not found.
        """
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={asset_id}&vs_currencies={currencies}"

        try:
            response = requests.get(url)
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            self.logger.error(f"An HTTP error occurred: {e}")
            return 0
        except requests.exceptions.RequestException as e:
            self.logger.error(f"A request error occurred: {e}")
            return 0

        data = response.json()

        if asset_id not in data:
            self.logger.warning(f"Asset ID '{asset_id}' not found in CoinGecko.")
            return 0

        return data[asset_id]['usd']

    async def check_permissions(self, interaction, required_role, user_id, user_roles):
        self.logger.info(f"Checking {interaction.user.name} has the appropriate permissions")
        if required_role and not any(role.name == required_role for role in user_roles):
            self.logger.warning(f"<@{user_id}> doesn't have the necessary role assigned to participate: {required_role}")
            interaction_message = await interaction.followup.send(
                f"You have insufficient access to execute this command! Required role: `{required_role}`.",
                ephemeral=True)
            await asyncio.sleep(10)
            await interaction_message.delete()
            return False
        elif any(role.name == required_role for role in user_roles):
            self.logger.info(f"TRUE")
            return True

    async def check_balance(self, interaction):
        self.logger.info(f"Checking wallet balance of {self.config.PROXIED_ADDRESS}")
        voter = ProxyVoter(main_address=self.config.PROXIED_ADDRESS, proxy_mnemonic=self.config.MNEMONIC, url=self.config.SUBSTRATE_WSS)
        proxy_balance = await voter.proxy_balance()

        if proxy_balance <= self.config.PROXY_BALANCE_ALERT:
            self.logger.warning(f"Wallet balance is too low: {proxy_balance}")

            # Post on discord with balance and public address to make it easier to top up
            proxy_address_qr = Text.generate_qr_code(publickey=self.config.PROXY_ADDRESS)
            balance_embed = Embed(color=0xFF0000, title=f'Low balance detected',
                                  description=f'Balance is {proxy_balance:.4f}, which is below the minimum required for voting with the proxy. Please add funds to continue without interruption.',
                                  timestamp=datetime.now(timezone.utc))
            balance_embed.add_field(name='Address', value=f'{self.config.PROXY_ADDRESS}', inline=True)
            balance_embed.set_thumbnail(url="attachment://proxy_address_qr.png")
            await interaction.followup.send(embed=balance_embed, file=discord.File(proxy_address_qr, "proxy_address_qr.png"))

            return False
        return True

    @staticmethod
    def proposals_with_no_context(filename):
        """
        Extracts and returns items from a JSON file whose 'title' attribute is set to 'None'.

        This function reads a JSON file, iterates through its items, and filters out those items
        where the 'title' attribute is equal to the string 'None'. It stores these items in a dictionary
        with the same structure as the original data and returns this dictionary.

        Parameters:
        filename (str): The path to the input JSON file. The file is expected to contain a dictionary
                        where each value is another dictionary having at least a 'title' key.

        Returns:
        dict: A dictionary containing items from the input JSON file where the 'title' attribute is 'None'.
              The keys in the returned dictionary are the same as in the original data.

        Example:
        Consider the input file ('data.json') has the following content:
        {
            "proposal1": {"title": "None", "description": "This is a test"},
            "proposal2": {"title": "Example", "description": "This is another test"},
            "proposal3": {"title": "None", "description": "This is a final test"}
        }

        Calling the function as `proposals_with_no_context('data.json')` will return:
        {
            "proposal1": {"title": "None", "description": "This is a test"},
            "proposal3": {"title": "None", "description": "This is a final test"}
        }
        """
        with open(filename, 'r') as f:
            data = json.load(f)

        items_with_title_none = {}

        for key, value in data.items():
            if value['title'] == 'None':
                items_with_title_none[key] = value

        return items_with_title_none

    @staticmethod
    def calculate_vote_result(aye_votes: int, nay_votes: int, threshold: float = 0.66) -> str:
        """
        Calculate and return the result of a vote based on the numbers of 'aye', 'nay' votes,
        and a specified threshold.

        This function takes in the number of 'aye', 'nay' votes, and calculates the percentages
        of each. It then compares the percentage of 'aye' votes to a specified threshold to determine if the
        vote is successful. If the 'aye' percentage is below the threshold, it checks if the 'nay' percentage
        meets the threshold to determine if the vote is unsuccessful. If neither 'aye' nor 'nay' meets the threshold,
        the function returns that the vote is inconclusive.

        Parameters:
        aye_votes (int): The number of 'aye' votes. Must be non-negative.
        nay_votes (int): The number of 'nay' votes. Must be non-negative.
        threshold (float, optional): The percentage threshold required for the vote to be successful. Defaults to 0.66.
                                    Must be between 0 and 1.

        Returns:
        str: A string describing the result of the vote. The string contains the status of the vote (successful,
             unsuccessful, or inconclusive) and the percentages of 'aye', 'nay' votes.

        Example:

        >>> calculate_vote_result(70, 30)
        >>>'The vote is currently successful with 70.00% **AYE**'

        """
        total_votes = aye_votes + nay_votes

        # Handle the edge case where total_votes is zero
        if total_votes == 0:
            return "No on-chain votes have been casted."

        aye_percentage = aye_votes / total_votes
        nay_percentage = nay_votes / total_votes

        if aye_percentage >= threshold:
            return "The vote currently meets or exceeds the threshold for **AYE** with {:.2%}".format(aye_percentage)
        elif nay_percentage >= threshold:
            return "The vote currently meets or exceeds the threshold for **NAY** with {:.2%}".format(nay_percentage)
        else:
            return "The vote is currently inconclusive with {:.2%} **AYE**, {:.2%} **NAY**".format(
                aye_percentage, nay_percentage)

    @staticmethod
    def check_minimum_participation(total_members, total_vote_count, min_participation):
        participation_percentage = (total_vote_count / total_members) * 100
        meets_minimum = participation_percentage >= min_participation
        return meets_minimum, participation_percentage

    @staticmethod
    async def load_vote_counts():
        try:
            async with aiofiles.open("../data/vote_counts.json", "r") as file:
                data = await file.read()
                return json.loads(data)
        except FileNotFoundError:
            return {}

    @staticmethod
    async def load_onchain_votes():
        try:
            async with aiofiles.open("../data/onchain-votes.json", "r") as file:
                data = await file.read()
                return json.loads(data)
        except FileNotFoundError:
            return {}

    @staticmethod
    def load_governance_cache():
        try:
            with open("../data/governance.cache", "r") as file:
                return json.load(file)
        except FileNotFoundError:
            return {}

    @staticmethod
    async def load_vote_periods(network: str):
        file_path = f"../data/vote_periods/{network}.json"
        try:
            async with aiofiles.open(file_path, "r") as file:
                data = await file.read()
                return json.loads(data)
        except FileNotFoundError:
            return {}

    async def save_vote_counts(self):
        async with aiofiles.open("../data/vote_counts.json", "w") as file:
            await file.write(json.dumps(self.vote_counts, indent=4))

    async def set_buttons_lock_status(self, channel, message_ids, lock_status):
        self.logger.info(f"Setting buttons lock status to {lock_status} for channel ID {channel} and message IDs {message_ids}")
        self.logger.info(f"Channel type: {type(channel)}, attributes: {dir(channel)}")

        for message_id in message_ids:
            self.logger.info(f"Fetching message with ID {message_id}")

            message = channel.get_thread(message_id)
            if message is None:
                self.logger.error(f"Error: Could not find thread for message ID {message_id}")
                continue

            view = message.view
            self.logger.info(f"Current view: {view}")

            self.logger.info(f"Editing message with new view: {view}")
            await message.edit(view=view)

        self.logger.info("Finished setting buttons lock status")

    async def lock_threads_by_message_ids(self, guild_id, message_ids):
        """
        Locks Discord threads by their associated message IDs in a given guild (server).

        This asynchronous function locks specified threads in a Discord guild. The threads are identified
        by their associated message IDs. The function checks if the bot has the necessary permissions to lock
        threads and logs error messages if it lacks permissions or if an invalid thread ID is provided.

        Parameters:
        guild_id (int or str): The ID of the Discord guild (server) where the threads are located.
        message_ids (list or int or str): A single message ID or a list of message IDs corresponding to
                                          the threads to be locked. Each message ID should be an integer
                                          or a string that can be cast to an integer.

        Returns:
        None

        Note:

        - This function requires that a Discord client object named 'client' exists and is logged in.
        - The bot needs the 'Manage Threads' permission in the guild to be able to lock threads.
        - The function is asynchronous and must be called from within an async function or an event loop.
        - If the bot does not have the required permissions, or if an invalid message ID is passed,
          error messages are logged but the function does not raise an exception.

        Example usage:

        >>> await lock_threads_by_message_ids(123456789012345678, [111111111111111111, 222222222222222222])

        or

        >>> await lock_threads_by_message_ids(123456789012345678, 111111111111111111)
        """
        if not isinstance(message_ids, list):
            message_ids = [message_ids]

        server = self.get_guild(guild_id)

        # Check if the bot has the required permissions
        bot_member = server.get_member(self.user.id)

        if not bot_member.guild_permissions.manage_threads:
            self.logger.error("The bot lacks the necessary permissions to lock threads. Please update the permissions.")
            return

        for message_id in message_ids:
            # Get the thread from the forum by the message ID
            thread = self.get_channel(int(message_id))

            if not thread:
                self.logger.error(f"Invalid Discord forum thread ID: {message_id}")
                continue

            # Lock the thread
            self.logger.info(f"Discord forum thread '{thread.name}' is >= threshold set in config, locking thread from future interactions.")
            await thread.edit(locked=True)

    async def edit_thread(self, forum_channel: int, message_id: int, name: str, content: str) -> bool:
        """
        Edits the title and the first post of a specific thread in a given forum channel on Discord.

        Parameters:
        forum_channel (int): The ID of the forum channel where the thread is located.
        message_id (int): The ID of the thread to be edited.
        name (str): The new title to assign to the thread.
        content (str): The new content to assign to the first post of the thread.

        Returns:
        bool: Returns True if the function executes successfully.
        """

        # Retrieve the specific thread within the forum channel
        thread = self.get_channel(forum_channel).get_thread(int(message_id))

        # Use asynchronous iteration to retrieve the first post of the thread (the bots post)
        async for message in thread.history(oldest_first=True, limit=1):
            # Update thread title
            await thread.edit(name=name, reason="Edited by hourly recheck job - (Rechecks proposals with no context to add context to existing posts)")

            # Update the content of the first post in the thread
            await message.edit(content=content)

        return True

    async def on_interaction(self, interaction: discord.Interaction):
        """
        Asynchronously handles interactions within a Discord guild.

        This method handles interactions from users and updates vote counts for a poll.
        It logs the interaction, checks for the user's roles, and ensures the user
        doesn't spam the voting buttons.

        Parameters:
        - interaction (discord.Interaction): The interaction object containing data
          about the user interaction in the Discord guild.

        Behavior:

        - Logs user interaction.
        - Fetches member and their roles from the guild.
        - Checks if the user has the necessary role to participate.
        - If the user doesn’t have the required role, sends a message informing them.
        - Handles vote counting for "aye", "nay" buttons.
        - Throttles the user's ability to vote within a 15-second interval to prevent spam.
        - Updates the vote counts and informs the user of a successful vote.

        Note:

        - Ensure that 'discord_role', 'button_cooldowns', and 'vote_counts' are
          defined globally or are accessible within the scope of this function.
        - Ensure that 'self.fetch_channel' and 'self.save_vote_counts' methods are
          defined in the class where this function is.
        - Ensure that 'self.calculate_vote_result' method is defined, it should take
          aye_votes, and nay_votes as parameters and return a string.
        """
        await interaction.response.defer()
        if interaction.data and interaction.data.get("component_type") == 2:
            custom_id = interaction.data.get("custom_id")

            user_id = interaction.user.id
            username = interaction.user.name + '#' + interaction.user.discriminator

            self.logger.info(f"User interaction from {username}")
            await asyncio.sleep(2)
            member = await interaction.guild.fetch_member(user_id)
            roles = member.roles

            current_time = time.time()
            cooldown_time = self.button_cooldowns.get(user_id, 0) + 5  # 5 second cooldown to mitigate button spam

            if self.discord_role and not any(role.name == self.discord_role for role in roles):
                self.logger.warning(f"{username} doesn't have the necessary role assigned to participate:: {self.discord_role}")
                interaction_message = await interaction.followup.send(
                    f"To participate, please ensure that you have the necessary role assigned: {self.discord_role}. This is a prerequisite for engaging in this activity.",
                    ephemeral=True)
                await asyncio.sleep(5)
                await interaction_message.delete()
                return

            message_id = str(interaction.message.id)
            discord_thread = interaction.message.channel

            if custom_id in ["aye_button", "nay_button", "recuse_button"] and current_time >= cooldown_time:
                self.vote_counts = await self.load_vote_counts()
                self.button_cooldowns[user_id] = current_time
                vote_type = "aye" if custom_id == "aye_button" else "recuse" if custom_id == "recuse_button" else "nay"
                # Save or update vote in the database
                if message_id not in list(self.vote_counts.keys()):
                    # If the thread gets created but the data isn't available in vote_counts.json
                    # then create it.
                    origin_tag = discord_thread.applied_tags[0].name
                    thread_index = discord_thread.name.split(':')[0]
                    thread_proposal_title = discord_thread.name.split(':')[1].lstrip(' ')

                    self.vote_counts[message_id] = {
                        "index": thread_index,
                        "title": thread_proposal_title,
                        "origin": [
                            origin_tag
                        ],
                        "aye": 0,
                        "nay": 0,
                        "recuse": 0,
                        "users": {},
                        "epoch": int(time.time())}

                # Check if the user has already voted
                if str(user_id) in self.vote_counts[message_id]["users"]:
                    previous_vote = self.vote_counts[message_id]["users"][str(user_id)]["vote_type"]

                    # If the user has voted for the same option, ignore the vote
                    if previous_vote == vote_type:
                        await interaction.followup.send(
                            f"Your vote of __**{previous_vote.upper()}**__ has already been recorded. To change it, select an alternative option.",
                            ephemeral=True)
                        await asyncio.sleep(2)
                        # await interaction.delete_original_response()
                        return
                    else:
                        # Remove the previous vote
                        self.vote_counts[message_id][previous_vote] -= 1

                # Update the vote count and save the user's vote
                self.vote_counts[message_id][vote_type] += 1
                self.vote_counts[message_id]["users"][str(user_id)] = {"username": username,
                                                                       "vote_type": vote_type}
                await self.save_vote_counts()

                # Update the results message
                thread = await self.fetch_channel(interaction.channel_id)
                async for message in thread.history(oldest_first=True):
                    if message.author == self.user and message.content.startswith("👍 AYE:"):
                        results_message = message
                        break
                else:
                    results_message = await thread.send("👍 AYE: 0    |    👎 NAY: 0    |    ☯ RECUSE: 0")

                proposal_index = self.vote_counts[message_id]['index']
                external_links = ExternalLinkButton(proposal_index, self.config.NETWORK_NAME)

                new_results_message = f"👍 AYE: {self.vote_counts[message_id]['aye']}    |    👎 NAY: {self.vote_counts[message_id]['nay']}    |    ☯ RECUSE: {self.vote_counts[message_id]['recuse']}\n" \
                                      f"{self.calculate_vote_result(aye_votes=self.vote_counts[message_id]['aye'], nay_votes=self.vote_counts[message_id]['nay'])}"
                await results_message.edit(content=new_results_message, view=external_links)

                # Acknowledge the vote and notify the user with a message
                if self.config.ANONYMOUS_MODE is True:
                    await interaction.followup.send(
                        f"Your vote of __**{vote_type.upper()}**__ has been successfully registered. We appreciate your valuable input in this decision-making process.", ephemeral=True)
                    await asyncio.sleep(2)

                if self.config.ANONYMOUS_MODE is False:
                    await interaction.followup.send(
                        f"<@{interaction.user.id}> Your vote of __**{vote_type.upper()}**__ has been successfully registered. We appreciate your valuable input in this decision-making process.", ephemeral=False)
                    await asyncio.sleep(2)

            else:
                # Block the user from pressing the AYE, NAY to prevent unnecessary spam
                remaining_time = cooldown_time - current_time
                seconds = int(remaining_time)

                interaction_message = await interaction.followup.send(f"{seconds} second waiting period remaining before you may cast your vote again. We appreciate your patience and understanding.",
                                                                      ephemeral=True)
                await asyncio.sleep(seconds)
                await interaction_message.delete()

    async def manage_discord_thread(self, channel, operation, title, index, content, governance_tag, message_id, client):
        thread = None
        char_exceed_msg = "\n```For more insights, visit the provided links below.```"
        content = Text.convert_markdown_to_discord(content) if content is not None else None
        try:
            final_content = content or ''
            if len(final_content) > self.config.DISCORD_BODY_MAX_LENGTH:
                available_space = self.config.DISCORD_BODY_MAX_LENGTH - len(char_exceed_msg + "...")
                truncated_content = re.sub(r'\s+\S+$', '', final_content[:available_space])
                final_content = f"{truncated_content}...{char_exceed_msg}"

            thread_content = f"{final_content}\n\n"
            thread_title = f"{index}: {title}"
            thread_title = thread_title if len(thread_title) <= self.config.DISCORD_TITLE_MAX_LENGTH else thread_title[:self.config.DISCORD_TITLE_MAX_LENGTH - 3] + "..."

            if operation == 'create':
                thread = await channel.create_thread(
                    name=thread_title,
                    content=thread_content,
                    reason=f"Created by an incoming proposal on the {self.config.NETWORK_NAME} network",
                    applied_tags=[governance_tag]
                )
            elif operation == 'edit' and client is not None:
                await client.edit_thread(
                    forum_channel=self.config.DISCORD_FORUM_CHANNEL_ID,
                    message_id=message_id,
                    name=thread_title,
                    content=thread_content
                )
                self.logger.info(f"Title updated from None -> {title} in vote_counts.json")
                self.logger.info("Discord thread successfully amended")
            else:
                self.logger.error(f"Invalid operation or missing parameters for {operation}")
        except Exception as e:
            self.logger.error(f"Failed to manage Discord thread: {e}")
        return thread

    async def get_or_create_governance_tag(self, available_channel_tags, governance_origin, channel):
        try:
            governance_tag = next((tag for tag in available_channel_tags if tag.name == governance_origin[0]), None)
        except Exception as e:
            self.logger.error(f"Error while searching for tag: {e}")
            governance_tag = None

        if governance_tag is None:
            try:
                governance_tag = await channel.create_tag(name=governance_origin[0])
            except Exception as e:
                self.logger.error(f"Failed to create tag: {e}")
                governance_tag = None

        return governance_tag

    async def total_member_contributors(self, guild, role_name):

        try:
            guild = self.get_guild(guild)
            existing_role = discord.utils.get(guild.roles, name=role_name)
            total_members = guild.get_role(existing_role.id).members

            if existing_role:
                member_count = len(total_members)
                return member_count
        except discord.Forbidden:
            self.logger.error(f"Permission error: Unable to get total members from {role_name} in guild {guild.id}")
            raise
        except discord.HTTPException as e:
            self.logger.error(f"HTTP error while fetching total members from {role_name} in guild {guild.id}: {e}")
            raise

    async def create_or_get_role(self, guild, role_name):
        # Check if the role already exists
        existing_role = discord.utils.get(guild.roles, name=role_name)

        if existing_role:
            return existing_role

        # If the role doesn't exist, try to create it
        try:
            # Create the role with the specified name
            new_role = await guild.create_role(name=role_name)
            return new_role
        except discord.Forbidden:
            self.logger.error(f"Permission error: Unable to create role {role_name} in guild {guild.id}")
            raise  # You can raise the exception or return None based on your use case
        except discord.HTTPException as e:
            self.logger.error(f"HTTP error while creating role {role_name} in guild {guild.id}: {e}")
            raise  # You can raise the exception or return None based on your use case

    async def set_voting_button_lock_status(self, threads, lock: bool):
        if threads:
            self.logger.info(f"{len(threads)} threads to {'lock' if lock else 'unlock'}")
            for message_id in threads:
                thread = self.get_channel(int(message_id))
                if thread is not None:
                    async for message in thread.history(oldest_first=True, limit=1):
                        view = ButtonHandler(self, message)
                        await view.set_buttons_lock_status(lock_status=lock)
                        await message.edit(view=view)
            self.logger.info(f"The following threads have been {'locked' if lock else 'unlocked'}: {threads}")

    async def lock_threads(self, threads_to_lock, user):
        try:
            if threads_to_lock:
                username = user.name
                user_id = user.id
                self.logger.info(f"{len(threads_to_lock)} threads have been archived by {username} (ID: {user_id})")

                for message_id in threads_to_lock:
                    thread = self.get_channel(self.config.DISCORD_FORUM_CHANNEL_ID).get_thread(int(message_id))
                    if thread is None:
                        self.logger.info(f"Unable to see thread {message_id} using get_channel() - Attempting to fetch_channel and set archived=False")
                        thread = await self.fetch_channel(int(message_id))
                        await thread.edit(archived=False)

                    if thread is None:
                        self.logger.warning(f"Thread with ID {message_id} not found.")
                        continue

                    async for message_id in thread.history(oldest_first=True, limit=1):
                        results_message_id = message_id.id

                    view = ButtonHandler(self, message_id)
                    await view.set_buttons_lock_status(lock_status=True)
                    await message_id.edit(view=view)
                    self.logger.info(f"Locking thread: {thread.name}")

                self.logger.info(f"The following threads have been locked by {username} (ID: {user_id}): {threads_to_lock}")

        except Exception as e:
            self.logger.error(f"An error occurred while locking threads: {str(e)}")

    async def calculate_proxy_vote(self, aye_votes: int, nay_votes: int, threshold: float = 0.66) -> str:
        """ Calculate and return the result of a vote based on 'aye' and 'nay' counts. """
        total_votes = aye_votes + nay_votes

        # Default to abstain if the turnout internally is <= config.MIN_PARTICIPATION
        # Set to 0 to turn off this feature
        if self.config.MIN_PARTICIPATION > 0:
            total_members = await self.total_member_contributors(guild=self.config.DISCORD_SERVER_ID, role_name=self.config.DISCORD_VOTER_ROLE)
            meets_minimum, participation_percentage = self.check_minimum_participation(total_members=total_members, total_vote_count=total_votes, min_participation=self.config.MIN_PARTICIPATION)

            if not meets_minimum:
                self.logger.warning("Participation too low, defaulting to Abstain")
                return "abstain"

        if total_votes == 0:
            return "abstain"

        aye_percentage = aye_votes / total_votes
        nay_percentage = nay_votes / total_votes

        if aye_percentage >= threshold:
            return "aye"
        elif nay_percentage >= threshold:
            return "nay"
        else:
            return "abstain"

    async def determine_vote_action(self, vote_data: Dict[str, Any], origin: Dict[str, Any], proposal_epoch: int):
        """ Determine the appropriate vote action based on elapsed time since epoch and role periods. """
        SECONDS_IN_A_DAY = 86400
        current_time = int(time.time())

        elapsed_time = int(current_time - (proposal_epoch / 1000))

        decision_period_seconds = origin["decision_period"] * SECONDS_IN_A_DAY
        internal_vote_period = origin["internal_vote_period"] * SECONDS_IN_A_DAY
        revote_period = origin["revote_period"] * SECONDS_IN_A_DAY

        _1st_vote = elapsed_time >= internal_vote_period
        _2nd_vote = elapsed_time >= revote_period

        if elapsed_time >= decision_period_seconds:
            return 0, "Vote period has ended."

        if _1st_vote and not _2nd_vote:
            vote = await self.calculate_proxy_vote(aye_votes=vote_data['aye'], nay_votes=vote_data['nay'])
            return 1, vote

        if _1st_vote and _2nd_vote:
            vote = await self.calculate_proxy_vote(aye_votes=vote_data['aye'], nay_votes=vote_data['nay'])
            return 2, vote

        if not _1st_vote:
            return 99, f"Waiting for 1st vote conditions to be met. is {elapsed_time} > {internal_vote_period}?"

    async def on_error(self, event, *args, **kwargs):
        exc = sys.exc_info()

        if isinstance(exc, HTTPException) and exc.status == 429:
            self.logger.warning(f"We are being rate-limited. Waiting for {exc.retry_after} seconds.")
        else:
            # Handle other types of exceptions or log them
            self.logger.error(f"An error occurred: {exc}")

    # Synchronize the app commands to one guild.
#   async def setup_hook(self):
#       # This copies the global commands over to your guild.
#       self.tree.copy_global_to(guild=self.guild)
#       await self.tree.sync(guild=self.guild)
