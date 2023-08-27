import logging
from logging.handlers import TimedRotatingFileHandler

class Logger:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.setup_logging()
        self.logger = logging.getLogger()

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
    
    def debug(self, message):
        self.logger.debug(message)

    def info(self, message):
        self.logger.info(message)

    def warning(self, message):
        self.logger.warning(message)

    def error(self, message):
        self.logger.error(message)

    def critical(self, message):
        self.logger.critical(message)
        
    def missing_role(self, message):
        warning_roles = ["Manage Roles"]
    
        if any(role in message for role in warning_roles):
            log_level = self.logger.warning
        else:
            log_level = self.logger.critical  # Default to critical for unspecified roles
            
        message = f"***** MISSING ROLE: {message} *****"
        self.logger.critical(message)
        print(message)
