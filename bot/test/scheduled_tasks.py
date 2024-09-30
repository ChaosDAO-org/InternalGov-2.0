import os
from datetime import datetime, timezone
from dotenv import load_dotenv
import random
import asyncio
import discord
from discord.ext import commands, tasks
from discord.ext.tasks import Loop
from asyncio import coroutine

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# Load the .env file
load_dotenv()

# Get the DISCORD_TOKEN from the environment
discord_token = os.getenv('DISCORD_TOKEN')


def get_timestamp():
    """Returns the current timestamp in a readable format."""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


async def evaluate_task_schedule(self, task: Loop, minutes: int = 2) -> bool:
    """
    Evaluates the given task and checks whether the task's next iteration is scheduled
    within a specific time gap. By default, this function checks if the next iteration of
    the task is within 2 minutes from the current time.

    Args:
        task (discord.ext.tasks.Loop): The task to evaluate.
        minutes (int, optional): The time gap in minutes to check. Default is 2 minutes.

    Returns:
        bool: True if the next iteration of the task is within the given minutes from
              the current time, else False.

    Note: This function also has a side-effect of stopping the task if the next iteration
    of the task is within the given minutes from the current time.
    """
    current_time_utc = datetime.now(timezone.utc)

    if current_time_utc and task.next_iteration:

        # Check if the runs are within 2 minutes (default) of each other
        time_difference = abs((current_time_utc - task.next_iteration).total_seconds())

        if time_difference <= minutes * 60:
            print(f"The tasks are scheduled within 20 minutes of each other. Time difference: {time_difference / 60:.2f} minutes.")
            await self.stop_tasks([task])
            return True


@staticmethod
async def stop_tasks(coroutine_task):
    """
    Stops specified asynchronous tasks if they are currently running.

    This function iterates through a list of predefined tasks. For each task, it checks if the task is running and, if so, attempts to stop it.
    """
    for task in coroutine_task:
        try:
            if task.is_running():
                task = task.get_task()
                print(f"Stopping tasks [{task.get_name()}]")
                task.cancel()
        except Exception as e:
            print(f"Error stopping {task.get_task().get_name()} task: {e}")


@staticmethod
async def start_tasks(coroutine_task):
    """
    Restarts specified asynchronous tasks if they are not already running.

    This function iterates through a list of predefined tasks. For each task, it checks if the task is not running and, if so, attempts to start it. It logs the start of each task. If an exception occurs while starting a task, it logs the error.
    """
    for task in coroutine_task:
        try:
            if not task.is_running():
                task.start()
        except Exception as e:
            print(f"Error starting {task.get_task().get_name()} task: {e}")


@tasks.loop(minutes=3)
async def check_governance():
    try:
        print("\n")
        await evaluate_task_schedule(autonomous_voting)
        await stop_tasks([sync_embeds, recheck_proposals])
        task_name = check_governance.get_task().get_name()
        print(f"{get_timestamp()} - [{task_name}] is running")
        await asyncio.sleep(3)
        print(f"{get_timestamp()} - 1 new proposal found")
        await asyncio.sleep(random.uniform(0.1, 25.0))
        print(f"{get_timestamp()} - Thread created")
        await asyncio.sleep(random.uniform(0.1, 5.0))
    finally:
        await start_tasks([autonomous_voting, sync_embeds, recheck_proposals])
        print("\n")


@tasks.loop(minutes=12)
async def autonomous_voting():
    try:
        await stop_tasks([sync_embeds, recheck_proposals])
        task_name = autonomous_voting.get_task().get_name()
        print(f"{get_timestamp()} - [{task_name}] is running")
        for i in range(0, 5):
            print(f"{get_timestamp()} - Voting on: {i}")
            await asyncio.sleep(random.uniform(0.1, 5.0))
    finally:
        await start_tasks([sync_embeds, recheck_proposals])
        print("\n")


@tasks.loop(minutes=1)
async def sync_embeds():
    try:
        await stop_tasks([recheck_proposals])
        task_name = sync_embeds.get_task().get_name()
        print(f"{get_timestamp()} - [{task_name}] is running.")
        for i in range (0, 5):
            print(f"{get_timestamp()} - Synchronizing: {i}")
            await asyncio.sleep(random.uniform(0.1, 5.0))
    finally:
        await start_tasks([recheck_proposals])
        print("\n")


@tasks.loop(minutes=1)
async def recheck_proposals():
    task_name = recheck_proposals.get_task().get_name()
    print(f"{get_timestamp()} - [{task_name}] is running")

    for i in range (0, 5):
        print(f"{get_timestamp()} - Rechecking proposal: {i}")
        await asyncio.sleep(random.uniform(0.1, 5.0))
    print("\n")

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
