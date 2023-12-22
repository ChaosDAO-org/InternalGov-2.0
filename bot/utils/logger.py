import logging
from logging.handlers import TimedRotatingFileHandler


class Logger:
    _instance = None

    def __new__(cls, verbose=False):
        if cls._instance is None:
            cls._instance = super(Logger, cls).__new__(cls)
            cls._instance.verbose = verbose
            cls._instance.setup_logging()
            cls._instance.logger = logging.getLogger()
        return cls._instance

    def setup_logging(self):
        log_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
        log_handler = TimedRotatingFileHandler('../data/logs/governance_bot.log', when='D', interval=1, backupCount=12)
        log_handler.setFormatter(log_formatter)

        logger = logging.getLogger()
        if self.verbose:
            logger.setLevel(logging.DEBUG)
        else:
            logger.setLevel(logging.INFO)
        logger.addHandler(log_handler)

    def exception(self, message):
        self.logger.exception(message)

    def debug(self, message):
        self.logger.debug(message)

    def info(self, message):
        self.logger.info(message)

    def warning(self, message):
        self.logger.warning(message)

    def error(self, message):
        self.logger.error(message, exc_info=True)

    def critical(self, message):
        self.logger.critical(message)

    def write_out(self, message, log_filename):
        with open(log_filename, 'a') as f:
            print(message, file=f)

    def console(self, message):
        print(message)

    def missing_role(self, message):
        warning_roles = ["Manage Roles"]

        if any(role in message for role in warning_roles):
            log_level = self.logger.warning
        else:
            log_level = self.logger.critical  # Default to critical for unspecified roles

        message = f"MISSING ROLE: {message}"
        self.logger.critical(message)
        print(message)
