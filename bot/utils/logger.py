import os
import sys
import logging
import inspect
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime, timedelta


class Logger:
    """
    Logger Utility Class

    This class provides methods for configuring logging, automatically managing log files &
    rotating them daily.
    """

    @staticmethod
    def configure(log_level, filename_prefix, output_dir="../data/logs", days_to_keep=10):
        """
        Configure the logging settings for the application. Uses TimedRotatingFileHandler
        to rotate logs daily and delete old logs periodically.

        Args:
            log_level (int): The logging level (1=ERROR, 2=WARNING, 3=INFO, 4=DEBUG).
            filename_prefix (str): The prefix for the log file name.
            output_dir (str): The directory to store log files. Defaults to "../data/logs".
            days_to_keep (int): The number of days to keep log files. Older files will be deleted.
        """
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # Get the command line command used to execute the script
        command = " ".join(sys.argv)

        # Map numeric levels to logging levels
        level_mapping = {
            1: logging.ERROR,
            2: logging.WARNING,
            3: logging.INFO,
            4: logging.DEBUG,  # Enables all logging levels
        }

        numeric_level = level_mapping.get(log_level, logging.DEBUG)

        # Set up the TimedRotatingFileHandler for daily log rotation
        log_file = f"{output_dir}/{filename_prefix}.log"
        handler = TimedRotatingFileHandler(log_file, when='D', interval=1, backupCount=days_to_keep)
        handler.suffix = "%Y-%m-%d"  # Format the rotated log file name

        # Set the log format
        formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
        handler.setFormatter(formatter)

        # Get the root logger and configure it
        logger = logging.getLogger()
        logger.setLevel(numeric_level)
        logger.addHandler(handler)

        # Log the command at the top of the log file
        logger.info("Command executed:\n# %s\n", command)

    @staticmethod
    def get_caller_info():
        """
        Retrieve the name of the calling class and method/function.

        Returns:
            str: A string in the format 'ClassName.method_name' or 'module_name.function_name'.
        """
        stack = inspect.stack()
        for frame_info in stack[2:]:
            frame = frame_info.frame
            code = frame.f_code
            if "self" in frame.f_locals:
                class_name = frame.f_locals["self"].__class__.__name__
                method_name = code.co_name
                return f"{class_name}.{method_name}"

            module_name = frame.f_globals["__name__"]
            function_name = code.co_name
            return f"{module_name}.{function_name}"
        return "Unknown"

    @staticmethod
    def log(log_func, caller_info, message):
        """
        Log a message using the provided log function, including the caller's information.

        Args:
            log_func (function): The logging function (e.g., logging.info).
            caller_info (str): Information about the caller (class and method/function name).
            message (str): The message to log.
        """
        log_func("%s:%s", caller_info, message)

    @staticmethod
    def info(message):
        """
        Log an informational message.

        Args:
            message (str): The message to log.
        """
        caller_info = Logger.get_caller_info()
        Logger.log(logging.info, caller_info, message)

    @staticmethod
    def warning(message):
        """
        Log a warning message.

        Args:
            message (str): The message to log.
        """
        caller_info = Logger.get_caller_info()
        Logger.log(logging.warning, caller_info, message)

    @staticmethod
    def error(message):
        """
        Log an error message.

        Args:
            message (str): The message to log.
        """
        caller_info = Logger.get_caller_info()
        Logger.log(logging.error, caller_info, message)

    @staticmethod
    def exception(message):
        """
        Log an exception message.

        Args:
            message (str): The message to log.
        """
        caller_info = Logger.get_caller_info()
        Logger.log(logging.exception, caller_info, message)

    @staticmethod
    def debug(message):
        """
        Log a debug message.

        Args:
            message (str): The message to log.
        """
        caller_info = Logger.get_caller_info()
        Logger.log(logging.debug, caller_info, message)

