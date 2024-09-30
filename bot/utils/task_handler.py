from discord.ext.tasks import Loop
from datetime import datetime, timezone
from utils.logger import Logger

logging = Logger()


class TaskHandler:
    def __init__(self):
        self.logging = Logger()

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
                logging.info(f"The tasks are scheduled within 20 minutes of each other. Time difference: {time_difference / 60:.2f} minutes.")
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
                    logging.info(f"Stopping tasks [{task.get_name()}]")
                    task.cancel()
            except Exception as e:
                logging.error(f"Error stopping {task.get_task().get_name()} task: {e}")

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
                logging.error(f"Error starting {task.get_task().get_name()} task: {e}")
