import json
import time
import requests
import logging
from logging.handlers import TimedRotatingFileHandler

import asyncio
import discord
from discord.ext import tasks
from discord import app_commands


class GovernanceMonitor(discord.Client):
    def __init__(self, guild,  discord_role, button_cooldowns, *, intents: discord.Intents):
        super().__init__(intents=intents)
        # A CommandTree is a special type that holds all the application command
        # state required to make it work. This is a separate class because it
        # allows all the extra state to be opt-in.
        # Whenever you want to work with application commands, your tree is used
        # to store and work with them.
        # Note: When using commands.Bot instead of discord.Client, the bot will
        # maintain its own tree instead.
        self.guild = guild
        self.button_cooldowns = button_cooldowns
        self.discord_role = discord_role
        self.tree = app_commands.CommandTree(self)
        self.vote_counts = self.load_vote_counts()

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
            return "The vote is currently successful with {:.2%} **AYE**".format(aye_percentage)
        elif nay_percentage >= threshold:
            return "The vote is currently unsuccessful with {:.2%} **NAY**".format(nay_percentage)
        else:
            return "The vote is currently inconclusive with {:.2%} **AYE**, {:.2%} **NAY**".format(
                aye_percentage, nay_percentage)

    @staticmethod
    def get_asset_price(asset_id, currencies='usd,gbp,eur'):
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
            print(f"An HTTP error occurred: {e}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"A request error occurred: {e}")
            return None

        data = response.json()

        if asset_id not in data:
            print(f"Asset ID '{asset_id}' not found in CoinGecko.")
            return None

        return data[asset_id]

    @staticmethod
    def load_vote_counts():
        try:
            with open("../data/vote_counts.json", "r") as file:
                return json.load(file)
        except FileNotFoundError:
            return {}

    def save_vote_counts(self):
        with open("../data/vote_counts.json", "w") as file:
            json.dump(self.vote_counts, file, indent=4)

 #   async def set_buttons_lock_status(client, channel_id, message_ids, lock_status=True):
 #       for message_id in message_ids:
 #           message = await message_id.fetch_message(message_id)
 #           view = message.view
 #           # Set the disabled status of the buttons
 #           for button in view.children:
 #               button.disabled = lock_status
 #           # Update the message with the new view
 #           await message.edit(view=view)

    async def set_buttons_lock_status(self, channel, message_ids, lock_status):
        print(f"Setting buttons lock status to {lock_status} for channel ID {channel} and message IDs {message_ids}")
        print(f"Channel type: {type(channel)}, attributes: {dir(channel)}")  # Debug print

        for message_id in message_ids:
            print(f"Fetching message with ID {message_id}")

            message = channel.get_thread(message_id)
            if message is None:
                print(f"Error: Could not find thread for message ID {message_id}")  # Debug print
                continue

            view = message.view
            print(f"Current view: {view}")

            # Set the disabled status of the buttons
            #for button in view.children:
            #    print(f"Setting disabled status of button {button.label} to {lock_status}")
            #    button.disabled = lock_status

            # Update the message with the new view
            print(f"Editing message with new view: {view}")
            await message.edit(view=view)

        print("Finished setting buttons lock status")


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
            logging.error("The bot lacks the necessary permissions to lock threads. Please update the permissions.")
            return

        for message_id in message_ids:
            # Get the thread from the forum by the message ID
            thread = self.get_channel(int(message_id))

            if not thread:
                logging.error(f"Invalid Discord forum thread ID: {message_id}")
                continue

            # Lock the thread
            logging.info(f"Discord forum thread '{thread.name}' is >= threshold set in config, locking thread from future interactions.")
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
        if interaction.data and interaction.data.get("component_type") == 2:
            custom_id = interaction.data.get("custom_id")

            if custom_id == 'abstain_button':
                await interaction.response.send_message(f"Choose Aye, Nay, or Recuse if there's a conflict of interest. Abstain has been removed", ephemeral=True)
                await asyncio.sleep(10)
                await interaction.delete_original_response()
                return

            user_id = interaction.user.id
            username = interaction.user.name + '#' + interaction.user.discriminator

            logging.info(f"User interaction from {username}")

            member = await interaction.guild.fetch_member(user_id)
            roles = member.roles

            if self.discord_role and not any(role.name == self.discord_role for role in roles):
                logging.warning(f"{username} doesn't have the necessary role assigned to participate:: {self.discord_role}")
                await interaction.response.send_message(
                    f"To participate, please ensure that you have the necessary role assigned: {self.discord_role}. This is a prerequisite for engaging in this activity.",
                    ephemeral=True)
                await asyncio.sleep(5)
                await interaction.delete_original_response()
                return

            message_id = str(interaction.message.id)
            discord_thread = interaction.message.channel

            current_time = time.time()
            cooldown_time = self.button_cooldowns.get(user_id, 0) + 2

            if custom_id in ["aye_button", "nay_button", "recuse_button"] and current_time >= cooldown_time:
                self.vote_counts = self.load_vote_counts()  # tmp-workaround for reloading vote_counts to avoid memory caching
                self.button_cooldowns[user_id] = current_time
                vote_type = "aye" if custom_id == "aye_button" else "recuse" if custom_id == "recuse_button" else "nay"

                if message_id not in list(self.vote_counts.keys()):
                    self.vote_counts[message_id] = {
                        "index": 'Proposal detected; corresponding vote_count.json entry absent, now added using first vote interaction.',
                        "title": discord_thread.name,
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
                        await interaction.response.send_message(
                            "Your vote for this option has already been recorded. If you wish to change your decision, please feel free to choose an alternative option.",
                            ephemeral=True)
                        await asyncio.sleep(5)
                        # await interaction.delete_original_response()
                        return
                    else:
                        # Remove the previous vote
                        self.vote_counts[message_id][previous_vote] -= 1

                # Update the vote count and save the user's vote
                self.vote_counts[message_id][vote_type] += 1
                self.vote_counts[message_id]["users"][str(user_id)] = {"username": username,
                                                                       "vote_type": vote_type}
                self.save_vote_counts()

                # Update the results message
                thread = await self.fetch_channel(interaction.channel_id)
                async for message in thread.history(oldest_first=True):
                    if message.author == self.user and message.content.startswith("👍 AYE:"):
                        results_message = message
                        break
                else:
                    results_message = await thread.send("👍 AYE: 0    |    👎 NAY: 0    |    ☯ RECUSE: 0")

                new_results_message = f"👍 AYE: {self.vote_counts[message_id]['aye']}    |    👎 NAY: {self.vote_counts[message_id]['nay']}    |    ☯ RECUSE: {self.vote_counts[message_id]['recuse']}\n" \
                                      f"{self.calculate_vote_result(aye_votes=self.vote_counts[message_id]['aye'], nay_votes=self.vote_counts[message_id]['nay'])}"
                await results_message.edit(content=new_results_message)

                # Acknowledge the vote and delete the message 10 seconds later
                # (this notification is only visible to the user that interacts with AYE, NAY
                await interaction.response.send_message(
                    f"Your vote of **{vote_type}** has been successfully registered. We appreciate your valuable input in this decision-making process.",
                    ephemeral=True)
                await asyncio.sleep(60*60*24*14)
                # await interaction.delete_original_response()
            else:
                # block the user from pressing the AYE, NAY to prevent unnecessary spam
                remaining_time = cooldown_time - current_time
                seconds = int(remaining_time)

                await interaction.response.send_message(f"{seconds} second waiting period remaining before you may cast your vote again. We appreciate your patience and understanding.",
                                                        ephemeral=True)
                await asyncio.sleep(5)
                await interaction.delete_original_response()


    # Synchronize the app commands to one guild.
    async def setup_hook(self):
        # This copies the global commands over to your guild.
        self.tree.copy_global_to(guild=self.guild)
        await self.tree.sync(guild=self.guild)
