import time
import requests
import logging
import json
import discord
import asyncio
import argparse
from utils.logger import Logger
from utils.gov2 import OpenGovernance2
from utils.data_processing import CacheManager, Text
from utils.config import Config
from utils.button_handler import ButtonHandler
from utils.argument_parser import ArgumentParser
from logging.handlers import TimedRotatingFileHandler
from governance_monitor import GovernanceMonitor
from discord.ext import tasks

async def create_or_get_role(guild, role_name):
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
        logging.error(f"Permission error: Unable to create role {role_name} in guild {guild.id}")
        raise  # You can raise the exception or return None based on your use case
    except discord.HTTPException as e:
        logging.error(f"HTTP error while creating role {role_name} in guild {guild.id}: {e}")
        raise  # You can raise the exception or return None based on your use case

@tasks.loop(hours=6)
async def check_governance():
    """A function that checks for new referendums on OpenGovernance2, creates a thread for each new
    referendum on a Discord channel with a specified ID, and adds reactions to the thread.

    This function uses the Discord API to interact with the Discord platform. The Discord API provides
    methods for creating a thread and adding reactions to it, as well as accessing information about
    channels and tags.

    The `check_referendums` function from the `OpenGovernance2` class is called to get the new
    referendums. The code then iterates through each new referendum and performs the following actions:

        - Gets the available tags for the Discord channel.
        - Creates a new tag for the origin of the referendum if it doesn't already exist.
        - Creates a new thread for the referendum on the Discord channel, with the title and content
        of the referendum, and the newly created or existing tag.
        - Adds reactions to the thread to allow users to vote on the referendum.

    The loop is set to run every 6 hrs, so the bot will continuously check for new referendums
    and create threads for them on the Discord channel.
    """
    try:
        logging.info("Checking for new proposals")
        opengov2 = OpenGovernance2(config)
        new_referendums = await opengov2.check_referendums()
        channel = client.get_channel(config.DISCORD_FORUM_CHANNEL_ID)
        # Get the guild object where the role is located
        guild = client.get_guild(config.DISCORD_SERVER_ID)
        # Construct the role name based on the symbol in config
        
        # Find the role by its name
        role = discord.utils.get(guild.roles, name=config.TAG_ROLE_NAME)
        # Move votes from vote_counts.json -> archived_votes.json once they exceed X amount of days
        # lock threads once archived (prevents regular users from continuing to vote).
        threads_to_lock = CacheManager().delete_old_keys_and_archive(json_file_path='../data/vote_counts.json', days=config.DISCORD_LOCK_THREAD, archive_filename='../data/archived_votes.json')
        if threads_to_lock:
            logging.info(f"{len(threads_to_lock)} threads have been archived")
            await client.lock_threads_by_message_ids(guild_id=config.DISCORD_SERVER_ID, message_ids=threads_to_lock)
            logging.info(f"The following threads have been locked: {threads_to_lock}")

        if new_referendums:
            logging.info(f"{len(new_referendums)} new proposal(s) found")
            channel = client.get_channel(config.DISCORD_FORUM_CHANNEL_ID)
            current_price = client.get_asset_price(asset_id=config.NETWORK_NAME)
                    
            # Get the guild object where the role is located
            guild = client.get_guild(config.DISCORD_SERVER_ID)  # Replace discord_guild_id with the actual guild ID

            # Construct the role name based on the symbol in config

            # go through each referendum if more than 1 was submitted in the given scheduled time
            for index, values in new_referendums.items():
                requested_spend = ""
                try:
                    #proposal_ends = opengov2.time_until_block(target_block=values['onchain']['alarm'][0])
                    available_channel_tags = []
                    if channel is not None:
                        available_channel_tags = [tag for tag in channel.available_tags]
                    else:
                        logging.error(f"Channel with ID {config.DISCORD_FORUM_CHANNEL_ID} not found")
                        # Handle the error as appropriate for your application
                    governance_origin = [v for i, v in values['onchain']['origin'].items()]

                    # Create forum tags if they don't already exist.
                    governance_tag = next((tag for tag in available_channel_tags if tag.name == governance_origin[0]), None)
                    if governance_tag is None:
                        governance_tag = await channel.create_tag(name=governance_origin[0])

                    #  Written to accommodate differences in returned JSON between Polkassembly & Subsquare
                    if values['successful_url']:
                        logging.info(f"Getting on-chain data from: {values['successful_url']}")

                        if 'polkassembly' in values['successful_url'] and 'proposed_call' in list(values.keys()):
                            if values['proposed_call']['method'] == 'spend':
                                amount = int(values['proposed_call']['args']['amount']) / config.TOKEN_DECIMAL
                                requested_spend = f"```yaml\n" \
                                                  f"{config.SYMBOL}: {amount}\n" \
                                                  f"USD: ${format(amount * current_price['usd'], ',.2f')}```\n"

                        elif 'subsquare' in values['successful_url'] and 'proposal' in list(values['onchainData'].keys()):
                            if values['onchainData']['proposal'] is not None and values['onchainData']['proposal']['call']['method'] == 'spend':
                                amount = int(values['onchainData']['proposal']['call']['args'][0]['value']) / config.TOKEN_DECIMAL
                                requested_spend = f"```yaml\n" \
                                                  f"{config.SYMBOL}: {amount}\n" \
                                                  f"USD: ${format(amount * current_price['usd'], ',.2f')}```\n"
                        else:
                            logging.error(f"Unable to pull information from data sources")
                            requested_spend = ""
                    else:
                        logging.error(f"Unable to pull information from data sources")
                        requested_spend = ""

                    title = values['title'][:95].strip() if values['title'] is not None else None
                    content = Text.convert_markdown_to_discord(values['content'])[:1451].strip() if values['content'] is not None else None
                    #content = values['content'][:1451].strip() if values['content'] is not None else None

                    char_exceed_msg = "\n```Character count exceeded. For more insights, kindly visit the provided links```"
                    logging.info(f"Creating thread on Discord: {index}# {title}")

                    # Create Discord thread
                    #   content starts with `requested_spend`,
                    #   followed by `content` (or an empty string if `content` is None).
                    #   If `content` is long enough (1450 characters or more), it appends '...' and `char_exceed_msg`.
                    #   The string ends with two newline characters.
                    thread = await channel.create_thread(
                        name=f"#{index}: {title}",
                        content=f"""{requested_spend}{content if content is not None else ''}{'...' + char_exceed_msg if content is not None and len(content) >= 1450 else ''}\n\n"""
                                f"**External links**"
                                f"\n<https://{config.NETWORK_NAME}.polkassembly.io/referenda/{index}>"
                                f"\n<https://{config.NETWORK_NAME}.subsquare.io/referenda/referendum/{index}>"
                                f"\n<https://{config.NETWORK_NAME}.subscan.io/referenda_v2/{index}>",
                        reason=f"Created by an incoming proposal on the {config.NETWORK_NAME} network",
                        applied_tags=[governance_tag]
                    )

                    logging.info(f"Thread created: {thread.message.id}")
                    # Send an initial results message in the thread
                    initial_results_message = "👍 AYE: 0    |    👎 NAY: 0    |    ☯ RECUSE: 0"

                    channel_thread = channel.get_thread(thread.message.id)
                    client.vote_counts[str(thread.message.id)] = {"index": index,
                                                                  "title": values['title'][:200].strip(),
                                                                  "aye": 0,
                                                                  "nay": 0,
                                                                  "recuse": 0,
                                                                  "users": {},
                                                                  "epoch": int(time.time())}
                    client.save_vote_counts()

                    results_message = await channel_thread.send(content=initial_results_message)
                    await thread.message.pin()
                    await results_message.pin()
                    #await asyncio.sleep(1)
                    # Searches the last 5 messages
                    async for message in channel_thread.history(limit=5):
                        if message.type == discord.MessageType.pins_add:
                            await message.delete()

                    if guild is None:
                        logging.error(f"Guild with ID {guild_id} not found")
                    else:
                        role = await create_or_get_role(guild, config.TAG_ROLE_NAME)
                        if role:
                            await channel_thread.send(content=
                            f"<@&{role.id}>"
                            f"\n**INSTRUCTIONS:**"
                            f"\n- Vote **AYE** if you want to see this proposal pass"
                            f"\n- Vote **NAY** if you want to see this proposal fail"
                            f"\n- Vote **RECUSE** if and **ONLY** if you have a conflict of interest with this proposal"
                            )
                    
                    results_message_id = results_message.id

                    message_id = thread.message.id
                    buttons = ButtonHandler(client, message_id)  # Pass the results_message_id
                    logging.info(f"Vote results message added: {message_id}")
                    await thread.message.edit(view=buttons)  # Update the thread message with the new view
                    #await asyncio.sleep(1)

                except discord.errors.Forbidden as forbidden:
                    logging.exception(f"Forbidden error occurred:  {forbidden}")
                    raise forbidden
                except discord.errors.HTTPException as http:
                    logging.exception(f"HTTP exception occurred: {http}")
                    raise http
                except Exception as error:
                    logging.exception(f"An unexpected error occurred: {error}")
                    raise error
        else:
            logging.info("0 proposals found since last checking")
    except Exception as error:
        logging.exception(f"An unexpected error occurred: {error}")
        raise error


@tasks.loop(hours=1)
async def recheck_proposals():
    """
    Asynchronously rechecks past proposals to populate missing titles and content.

    This function is a periodic task that runs every hour. It checks for past proposals where
    the title or content is missing and attempts to populate them with relevant data.


    Behavior:

    - Logs the start of the checking process for past proposals.
    - Retrieves proposals without context from a JSON file.
    - Initializes an OpenGovernance2 object.
    - Fetches the current price of a specified asset.
    - Iterates through each proposal, fetching and updating the missing data.
    - Updates the titles on the Discord threads for the proposals.
    - Saves the updated proposal data to the JSON file.
    - Logs the successful update of the proposals' data.
    """
    logging.info("Checking past proposals where title/content is None to populate them with relevant data")
    proposals_without_context = client.proposals_with_no_context('../data/vote_counts.json')
    opengov2 = OpenGovernance2(config)

    current_price = client.get_asset_price(asset_id=config.NETWORK_NAME)

    for key, value in proposals_without_context.items():
        requested_spend = ""
        proposal_index = value['index']
        opengov = await opengov2.fetch_referendum_data(referendum_id=int(proposal_index), network=config.NETWORK_NAME)

        if opengov['title'] != 'None':
            logging.info(f"Proposals have been found in the past where no title was set. Rechecking for title + content")
            if 'polkassembly' in opengov['successful_url'] and 'proposed_call' in list(opengov.keys()):
                if opengov['proposed_call']['method'] == 'spend':
                    amount = int(opengov['proposed_call']['args']['amount']) / config.TOKEN_DECIMAL
                    requested_spend = f"```yaml\n" \
                                      f"{config.SYMBOL}: {amount}\n" \
                                      f"USD: ${format(amount * current_price['usd'], ',.2f')}```\n"

            elif 'subsquare' in opengov['successful_url'] and 'proposal' in list(opengov['onchainData'].keys()):
                if opengov['onchainData']['proposal'] is not None and opengov['onchainData']['proposal']['call']['method'] == 'spend':
                    amount = int(opengov['onchainData']['proposal']['call']['args'][0]['value']) / config.TOKEN_DECIMAL
                    requested_spend = f"```yaml\n" \
                                      f"{config.SYMBOL}: {amount}\n" \
                                      f"USD: ${format(amount * current_price['usd'], ',.2f')}```\n"
            else:
                logging.error(f"Unable to pull information from data sources")
                requested_spend = ""

            title = opengov['title'][:95].strip()
            content = Text.convert_markdown_to_discord(values['content'])[:1451].strip() if values['content'] is not None else None
            # governance_tag = next((tag for tag in available_channel_tags if tag.name == opengov['origin']), None)
            char_exceed_msg = "\n```Character count exceeded. For more insights, kindly visit the provided links```"

            # set title on thread id contained in vote_counts.json
            client.vote_counts[key]['title'] = title
            client.save_vote_counts()

            # Edit existing thread with new data found from Polkassembly or SubSquare
            logging.info(f"Editing discord thread with title + content: {proposal_index}# {title}")
            
            await client.edit_thread(forum_channel=config.DISCORD_FORUM_CHANNEL_ID,
                                     message_id=key,
                                     name=f"#{proposal_index}: {opengov['title']}",
                                     content=f"""{requested_spend}{content if content is not None else ''}{'...' + char_exceed_msg if content is not None and len(content) >= 1450 else ''}\n\n"""
                                             f"**External links**"
                                             f"\n<https://{config.NETWORK_NAME}.polkassembly.io/referenda/{proposal_index}>"
                                             f"\n<https://{config.NETWORK_NAME}.subsquare.io/referenda/referendum/{proposal_index}>"
                                             f"\n<https://{config.NETWORK_NAME}.subscan.io/referenda_v2/{proposal_index}>")
            logging.info(f"Title updated from None -> {title} in vote_counts.json")
            logging.info(f"Discord thread successfully amended")
        else:
            continue

if __name__ == '__main__':
    config = Config()
    guild = discord.Object(id=config.DISCORD_SERVER_ID)
    arguments = ArgumentParser()
    Logger(arguments.args.verbose)
    client = GovernanceMonitor(guild=guild,discord_role=config.DISCORD_ROLE)
    
    @client.event
    async def on_ready():
        print(f"Logged in as {client.user} (ID: {client.user.id})")
        print("Connected to the following servers:")
        for server in client.guilds:
            print(f"- {server.name} (ID: {server.id})")

        if not check_governance.is_running():
            check_governance.start()

        if not recheck_proposals.is_running():
            recheck_proposals.start()
            
    client.run(config.DISCORD_API_KEY)
