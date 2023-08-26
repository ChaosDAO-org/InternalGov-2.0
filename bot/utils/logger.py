import logging
from logging.handlers import TimedRotatingFileHandler

class Logger:
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.setup_logging()

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
