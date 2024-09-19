import os
from datetime import datetime
from dotenv import load_dotenv
import random
import asyncio
import discord
from discord.ext import commands, tasks

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Load the .env file
load_dotenv()

# Get the DISCORD_TOKEN from the environment
discord_token = os.getenv('DISCORD_TOKEN')


def get_timestamp():
    """Returns the current timestamp in a readable format."""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def evaluate_task_schedule(task1, task2, minutes=2):
    """
    Output the next run times for the given tasks and check if they are within 2 minutes of each other.

    Args:
        task1: The first task to check.
        task2: The second task to check.
    """
    task1_next_run = task1.next_iteration
    task2_next_run = task2.next_iteration

    if task1_next_run and task2_next_run:
        task1_str = task1_next_run.strftime('%Y-%m-%d %H:%M:%S')
        task2_str = task2_next_run.strftime('%Y-%m-%d %H:%M:%S')

        print(f"* {task2.get_task().get_name()} next schedule: {task2_str}")
        print(f"* {task1.get_task().get_name()} next schedule: {task1_str}")

        # Check if the runs are within 2 minutes (default) of each other
        time_difference = abs((task1_next_run - task2_next_run).total_seconds())
        if time_difference <= minutes * 60:
            print(f"{get_timestamp()} - The tasks are scheduled within 20 minutes of each other. Time difference: {time_difference / 60} minutes.")
            return True


async def stop_tasks(coroutine_task):
    """
    Stops specified asynchronous tasks if they are currently running.
    """
    for task in coroutine_task:
        try:
            if task.is_running():
                task = task.get_task()
                print(f"{get_timestamp()} - Stopping {task.get_name()}, please wait...")
                task.cancel()
                await asyncio.wait([task])
        except Exception as e:
            task_name = task.get_task().get_name() if task.get_task() else "Unknown"
            print(f"Error stopping {task_name} task: {e}")


async def start_tasks(coroutine_task):
    """
    Restarts specified asynchronous tasks if they are not already running.
    """
    for task in coroutine_task:
        try:
            if not task.is_running():
                print(f"{get_timestamp()} - Starting task, please wait...")
                task.start()
        except Exception as e:
            task_name = task.get_task().get_name() if task.get_task() else "Unknown"
            print(f"Error starting {task_name} task: {e}")


@tasks.loop(hours=3)
async def check_governance():
    try:
        await stop_tasks(coroutine_task=[sync_embeds, recheck_proposals])
        task_name = check_governance.get_task().get_name()
        print(f"{get_timestamp()} - [{task_name}] is running")

        evaluated_time = evaluate_task_schedule(autonomous_voting, check_governance)
        if evaluated_time:
            await stop_tasks([autonomous_voting])

        await asyncio.sleep(20)
    finally:
        await start_tasks([autonomous_voting])


@tasks.loop(hours=6)
async def autonomous_voting():
    try:
        await stop_tasks(coroutine_task=[sync_embeds, recheck_proposals])
        task_name = autonomous_voting.get_task().get_name()
        print(f"{get_timestamp()} - [{task_name}] is running")
        for i in range(0, 60):
            print(f"Voting on: {i}")
            await asyncio.sleep(random.uniform(0.1, 2.0))
    finally:
        await start_tasks([sync_embeds, recheck_proposals])


@tasks.loop(hours=2)
async def sync_embeds():
    try:
        await stop_tasks(coroutine_task=[recheck_proposals])
        task_name = sync_embeds.get_task().get_name()
        print(f"{get_timestamp()} - [{task_name}] is running.")
        for i in range (0, 60):
            print(f"Synchronizing: {i}")
            await asyncio.sleep(random.uniform(0.1, 2.0))
    finally:
        await start_tasks([recheck_proposals])


@tasks.loop(hours=1)
async def recheck_proposals():
    try:
        task_name = recheck_proposals.get_task().get_name()
        print(f"{get_timestamp()} - [{task_name}] is running")
        for i in range (0, 60):
            print(f"Rechecking proposal: {i}")
            await asyncio.sleep(random.uniform(0.1, 1))
    finally:
        pass


@autonomous_voting.before_loop
async def before_voting():
    autonomous_voting.get_task().set_name('autonomous_governance')


@check_governance.before_loop
async def before_governance():
    check_governance.get_task().set_name('check_governance')


@sync_embeds.before_loop
async def before_sync_embeds():
    sync_embeds.get_task().set_name('sync_embeds')


@recheck_proposals.before_loop
async def before_recheck_proposals():
    recheck_proposals.get_task().set_name('recheck_proposals')


@bot.event
async def on_ready():
    print(f'Logged in as {bot.user}')
    await start_tasks([check_governance])

bot.run(discord_token)
