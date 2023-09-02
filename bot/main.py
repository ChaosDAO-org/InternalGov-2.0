import time
import requests
import logging
import json
import re
import discord
import asyncio
import argparse
from utils.logger import Logger
from utils.gov2 import OpenGovernance2
from utils.data_processing import CacheManager, Text
from utils.config import Config
from utils.button_handler import ButtonHandler, ExternalLinkButton
from utils.argument_parser import ArgumentParser
from utils.permission_check import PermissionCheck
from logging.handlers import TimedRotatingFileHandler
from governance_monitor import GovernanceMonitor
from utils.database_handler import DatabaseHandler
from discord.ext import tasks
import psycopg2
from psycopg2 import extras
from discord import app_commands, Embed


def get_requested_spend(data, current_price):
    requested_spend = ""
    
    if data.get('title') != 'None':
        try:
            if 'polkassembly' in data.get('successful_url', '') and 'proposed_call' in data:
                if data['proposed_call']['method'] == 'spend':
                    amount = int(data['proposed_call']['args']['amount']) / float(config.TOKEN_DECIMAL)
                    requested_spend = f"```markdown\n{config.SYMBOL}: {amount}\nUSD: ${format(amount * current_price['usd'], ',.2f')}```\n"
            elif 'subsquare' in data.get('successful_url', '') and 'proposal' in data.get('onchainData', {}):
                if data['onchainData']['proposal'] and data['onchainData']['proposal']['call']['method'] == 'spend':
                    amount = int(data['onchainData']['proposal']['call']['args'][0]['value']) / float(config.TOKEN_DECIMAL)
                    requested_spend = f"```markdown\n{config.SYMBOL}: {amount}\nUSD: ${format(amount * current_price['usd'], ',.2f')}```\n"
            else:
                logging.error("Data does not match any known sources")
                requested_spend = ""
        except Exception as e:
            logging.error(f"Unable to pull information from data sources due to: {e}")
            requested_spend = ""
    else:
        logging.error("Title: None")
        requested_spend = ""
    
    return requested_spend

async def get_or_create_governance_tag(available_channel_tags, governance_origin, channel):
    try:
        governance_tag = next((tag for tag in available_channel_tags if tag.name == governance_origin[0]), None)
    except Exception as e:
        logging.error(f"Error while searching for tag: {e}")
        governance_tag = None

    if governance_tag is None:
        try:
            governance_tag = await channel.create_tag(name=governance_origin[0])
        except Exception as e:
            logging.error(f"Failed to create tag: {e}")
            governance_tag = None

    return governance_tag

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

async def manage_discord_thread(
        channel, 
        operation, 
        title, 
        index, 
        requested_spend, 
        content, 
        governance_tag, 
        message_id, 
        client
    ):
    thread = None
    char_exceed_msg = "\n```For more insights, visit the provided links below.```"
    content = Text.convert_markdown_to_discord(content) if content is not None else None
    
    try:
        
        other_components_length = len(requested_spend + "\n\n")  # Newlines are 2 characters
        final_content = content or ''
        if len(final_content) + other_components_length > BODY_MAX_LENGTH:
            available_space = BODY_MAX_LENGTH - other_components_length - len(char_exceed_msg + "...")
            truncated_content = re.sub(r'\s+\S+$', '', final_content[:available_space])
            final_content = f"{truncated_content}...{char_exceed_msg}"

        thread_content = f"{requested_spend}{final_content}\n\n"
        thread_title = f"{index}: {title}"
        
        if operation == 'create':
            thread = await channel.create_thread(
                name=thread_title,
                content=thread_content,
                reason=f"Created by an incoming proposal on the {config.NETWORK_NAME} network",
                applied_tags=[governance_tag]
            )
        elif operation == 'edit' and client is not None and key is not None:
            await client.edit_thread(
                forum_channel=config.DISCORD_FORUM_CHANNEL_ID,
                message_id=message_id,
                name=thread_title,
                content=thread_content
            )
            logging.info(f"Title updated from None -> {title} in vote_counts.json")
            logging.info("Discord thread successfully amended")
        else:
            logging.error(f"Invalid operation or missing parameters for {operation}")
    except Exception as e:
        logging.error(f"Failed to manage Discord thread: {e}")
    return thread

async def set_voting_button_lock_status(threads, lock: bool):
    if threads:
        logging.info(f"{len(threads)} threads to {'lock' if lock else 'unlock'}")
        for message_id in threads:
            thread = client.get_channel(int(message_id))
            if thread is not None:
                async for message in thread.history(oldest_first=True, limit=1):
                    view = ButtonHandler(client, message)
                    view.set_buttons_lock_status(lock_status=lock)
                    await message.edit(view=view)
        logging.info(f"The following threads have been {'locked' if lock else 'unlocked'}: {threads}")

async def lock_threads(threads_to_lock, user):
    try:
        if threads_to_lock:
            username = user.name
            user_id = user.id
            logging.info(f"{len(threads_to_lock)} threads have been archived by {username} (ID: {user_id})")
            
            for message_id in threads_to_lock:
                thread = client.get_channel(config.DISCORD_FORUM_CHANNEL_ID).get_thread(int(message_id))
                if thread is None:
                    logging.warning(f"Thread with ID {message_id} not found.")
                    continue
                
                async for message_id in thread.history(oldest_first=True, limit=1):
                    results_message_id = message_id.id
                
                view = ButtonHandler(client, message_id)
                view.set_buttons_lock_status(lock_status=True)
                await message_id.edit(view=view)
            
            logging.info(f"The following threads have been locked by {username} (ID: {user_id}): {threads_to_lock}")

    except Exception as e:
        logging.error(f"An error occurred while locking threads: {str(e)}")



@tasks.loop(seconds=20)
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
        
        # Get the guild object where the role is located
        guild = client.get_guild(config.DISCORD_SERVER_ID)

        if new_referendums:
            logging.info(f"{len(new_referendums)} new proposal(s) found")
            channel = client.get_channel(config.DISCORD_FORUM_CHANNEL_ID)
            current_price = client.get_asset_price(asset_id=config.NETWORK_NAME)
                    
            referendum_info = opengov2.referendumInfoFor()
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
                    governance_tag = await get_or_create_governance_tag(available_channel_tags, governance_origin, channel)
                    
                    if values['successful_url']:
                        logging.info(f"Getting on-chain data from: {values['successful_url']}")
                        #  get_requested_spend handles the differences in returned JSON between Polkassembly & Subsquare
                        requested_spend = get_requested_spend(values, current_price)
                    else:
                        logging.error(f"No value: ", values['successful_url'])
                        requested_spend = ""

                    title = values['title'][:TITLE_MAX_LENGTH].strip() if values['title'] is not None else None

                    logging.info(f"Creating thread on Discord: #{index} {title}")
                    
                    try:                        
                        thread = await manage_discord_thread(
                            channel=channel,
                            operation='create',
                            title=title,
                            index=index,
                            requested_spend=requested_spend,
                            content=values['content'],
                            governance_tag=governance_tag,
                            message_id=None,
                            client=client
                        )
                        logging.info(f"Thread created: {thread.message.id}")
                    except Exception as e:
                        logging.error(f"Failed to create thread: {e}")
                        return None  # Make sure to return None if an exception occurs
                    # Send an initial results message in the thread
                    initial_results_message = "👍 AYE: 0    |    👎 NAY: 0    |    ⛔️ RECUSE: 0"

                    channel_thread = channel.get_thread(thread.message.id)
                    client.vote_counts[str(thread.message.id)] = {
                        "index": index,
                        "title": values['title'][:200].strip(),
                        "aye": 0,
                        "nay": 0,
                        "recuse": 0,
                        "users": {},
                        "epoch": int(time.time())
                        }
                    client.save_vote_counts()
                    external_links = ExternalLinkButton(index, config.NETWORK_NAME)
                    results_message = await channel_thread.send(content=initial_results_message,view=external_links)
                    await thread.message.pin()
                    await results_message.pin()
                    # Searches the last 5 messages
                    async for message in channel_thread.history(limit=5):
                        if message.type == discord.MessageType.pins_add:
                            await message.delete()

                    
                    if guild is None:
                        logging.error(f"Guild not found")
                    else:
                        try:
                            role = await create_or_get_role(guild, config.TAG_ROLE_NAME)
                            if role:
                                await channel_thread.send(content=
                                f"||<@&{role.id}>||"
                                f"\n**INSTRUCTIONS:**"
                                f"\n- Vote **AYE** if you want to see this proposal pass"
                                f"\n- Vote **NAY** if you want to see this proposal fail"
                                f"\n- Vote **RECUSE** if and **ONLY** if you have a conflict of interest with this proposal"
                                )
                                logging.info(f"Vote results message added instruction message added for {index}")
                        except Exception as error:
                            logging.error(f"An unexpected error occurred: {error}")
                    
                    #results_message_id = results_message.id
                    message_id = thread.message.id
                    voting_buttons = ButtonHandler(client, message_id)
                    
                    general_info_embed = Embed(color=0x00ff00)
                    polkasembly_info_embed = Embed(color=0x00ff00)
                    
                    try:
                        
                        # Add fields to embed
                        general_info = opengov2.add_fields_to_embed(general_info_embed, referendum_info[index])
                        passembly_call_data = opengov2.extract_and_embed(values, polkasembly_info_embed)
                        await asyncio.sleep(0.5)
                        await channel_thread.send(embed=passembly_call_data)
                        await asyncio.sleep(0.5)
                        # Edit the message
                        await thread.message.edit(view=voting_buttons, embed=general_info)
                        #await channel_thread.send(view=initial_results_message,view=external_links)
                    except Exception as e:
                        # Log the exception
                        logging.error(f"An error occurred: {e}")
                        



                except discord.errors.Forbidden as forbidden:
                    logging.exception(f"Forbidden error occurred:  {forbidden}")
                    raise forbidden
                except discord.errors.HTTPException as http:
                    logging.exception(f"HTTP exception occurred: {http}")
                    raise http
                except Exception as error:
                    logging.exception(f"An unexpected error occurred: {error}")
                    raise error
                
        # Move votes from vote_counts.json -> archived_votes.json once they exceed X amount of days
        # lock threads once archived (prevents regular users from continuing to vote).
        threads_to_lock = CacheManager.delete_old_keys_and_archive(json_file_path='../data/vote_counts.json', days=config.DISCORD_LOCK_THREAD, archive_filename='../data/archived_votes.json')
        if threads_to_lock:
            try:
                await lock_threads(threads_to_lock, client.user)
            except Exception as e:
                logging.error(f"Failed to lock threads: {threads_to_lock}. Error: {e}")
        else:
            logging.info("0 proposals found since last checking")
    except Exception as error:
        logging.exception(f"An unexpected error occurred: {error}")
        raise error


#@tasks.loop(seconds=10)
#async def sync_embeds():
#    
#    referendum_info = opengov2.referendumInfoFor()
#    print(referendum_info)

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
    logging.info("Checking past proposals where title/content is None")
    proposals_without_context = client.proposals_with_no_context('../data/vote_counts.json')
    #opengov2 = OpenGovernance2(config)
    channel = client.get_channel(config.DISCORD_FORUM_CHANNEL_ID)
    current_price = client.get_asset_price(asset_id=config.NETWORK_NAME)

    for message_id, value in proposals_without_context.items():
        requested_spend = ""
        proposal_index = value['index']
        opengov = await opengov2.fetch_referendum_data(referendum_id=int(proposal_index), network=config.NETWORK_NAME)

        if opengov['title'] != 'None':
            requested_spend = get_requested_spend(opengov, current_price)
            client.vote_counts[message_id]['title'] = title = opengov['title'][:TITLE_MAX_LENGTH].strip()
            # set title on thread id contained in vote_counts.json
            client.save_vote_counts()

            # Edit existing thread with new data found from Polkassembly or SubSquare
            logging.info(f"Editing discord thread with title + content: {proposal_index}# {title}")
            
            try:
                await manage_discord_thread(
                    channel=channel, 
                    operation='edit', 
                    title=title, 
                    index=proposal_index, 
                    requested_spend=requested_spend, 
                    content=opengov['content'], 
                    governance_tag="", 
                    message_id='', 
                    client=client
                    )
                logging.info(f"Title updated from None -> {title} in vote_counts.json")
                logging.info(f"Discord thread successfully amended")
            except Exception as e:
                logging.error(f"Failed to edit Discord thread: {e}")
        else:
            continue

if __name__ == '__main__':
    config = Config()
    guild = discord.Object(id=config.DISCORD_SERVER_ID)
    arguments = ArgumentParser()
    logging = Logger(arguments.args.verbose)
    permission_checker = PermissionCheck()
    #db_params = {
    #    'dbname': config.DB_NAME,
    #    'user': config.DB_USER,
    #    'password': config.DB_PASSWORD,
    #    'host': config.DB_HOST,
    #    'port': config.DB_PORT,
    #    'options': '-c password_encryption=scram-sha-256'
    #}

    # Create an instance of DatabaseHandler
    #db_handler = DatabaseHandler(db_params, logging)
    #db_handler.migrated_check()
    client = GovernanceMonitor(
        guild=guild,
        discord_role=config.DISCORD_VOTER_ROLE,
        permission_checker=permission_checker, 
        )
    TITLE_MAX_LENGTH = 95
    BODY_MAX_LENGTH = 2000
    
    @client.event
    async def on_ready():
        #print(f"Logged in as {client.user} (ID: {client.user.id})")
        #print("Connected to the following servers:")
        for server in client.guilds:
            #print(f"- {server.name} (ID: {server.id})")
            # Check permissions for the bot to read/write to the forum channel
            await permission_checker.check_permissions(server, config.DISCORD_FORUM_CHANNEL_ID) 

        if not check_governance.is_running():
            check_governance.start()

        if not recheck_proposals.is_running():
            recheck_proposals.start()
            
        #if not sync_embeds().is_running():
        #    sync_embeds.start()
    
    @client.tree.command()
    @app_commands.choices(action=[
        app_commands.Choice(name='enable', value='enable'),
        app_commands.Choice(name='disable', value='disable')
    ])
    async def thread(interaction: discord.Interaction, action: app_commands.Choice[str], thread_ids: str):
        user = interaction.user
        guild = interaction.guild
        thread_ids_list = None  # Initialize to avoid UnboundLocalError

        # Fetch the Member object for the user
        member = await guild.fetch_member(user.id)

        role = discord.utils.get(guild.roles, name=config.DISCORD_ADMIN_ROLE)
        if role not in member.roles:
            msg = await interaction.response.send_message("You're not cool enough to do this.", ephemeral=True)
            await asyncio.sleep(10)
            await interaction.delete_original_response()

            return

        thread_ids_list = [int(x.strip()) for x in thread_ids.split(',')]
        lock_status = True if action.value == 'disable' else False
        await set_voting_button_lock_status(thread_ids_list, lock_status)
        await interaction.response.send_message(f'The following thread(s) have been {action.name}d: {thread_ids_list}', ephemeral=True)


    try:    
        client.run(config.DISCORD_API_KEY)
    except KeyboardInterrupt:
        # Perform your cleanup here
        print("KeyboardInterrupt caught, cleaning up...")
        
        # Close any aiohttp.ClientSession, database connections, etc.
        # If you're running any asyncio loops, make sure to stop them as well.

        # For example, if you have an aiohttp client session:
        # await session.close()

    except Exception as e:
        # Log any other exceptions
        print(f"An error occurred: {e}")

