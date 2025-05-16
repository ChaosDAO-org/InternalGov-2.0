from dotenv import load_dotenv
from utils.logger import Logger
from distutils.util import strtobool
import os
import json


class Config:
    def __init__(self):
        try:
            load_dotenv("../.env")
            self.logger = Logger()

            # Discord Settings
            self.DISCORD_API_KEY = os.getenv('DISCORD_API_KEY') or self.raise_error("Missing DISCORD_API_KEY")
            self.DISCORD_SERVER_ID = int(os.getenv('DISCORD_SERVER_ID') or self.raise_error("Missing DISCORD_SERVER_ID"))
            self.DISCORD_FORUM_CHANNEL_ID = int(os.getenv('DISCORD_FORUM_CHANNEL_ID') or self.raise_error("Missing DISCORD_FORUM_CHANNEL_ID"))
            self.DISCORD_SUMMARIZER_CHANNEL_ID = int(os.getenv('DISCORD_SUMMARIZER_CHANNEL_ID')) or None
            self.DISCORD_SUMMARY_ROLE = os.getenv('DISCORD_SUMMARY_ROLE') or None
            self.DISCORD_ADMIN_ROLE = os.getenv('DISCORD_ADMIN_ROLE') or self.raise_error("Missing DISCORD_ADMIN_ROLE")
            self.DISCORD_VOTER_ROLE = os.getenv('DISCORD_VOTER_ROLE') or None
            self.DISCORD_TITLE_MAX_LENGTH = int(os.getenv('DISCORD_TITLE_MAX_LENGTH') or self.raise_error("Missing DISCORD_TITLE_MAX_LENGTH"))
            self.DISCORD_BODY_MAX_LENGTH = int(os.getenv('DISCORD_BODY_MAX_LENGTH') or self.raise_error("Missing DISCORD_BODY_MAX_LENGTH"))
            self.TAG_ROLE_NAME = os.getenv('DISCORD_NOTIFY_ROLE') or self.raise_error("Missing SYMBOL")
            self.EXTRINSIC_ALERT = os.getenv('DISCORD_EXTRINSIC_ROLE') or self.raise_error("Missing DISCORD_EXTRINSIC_ROLE")
            self.ANONYMOUS_MODE = bool(strtobool(os.getenv('DISCORD_ANONYMOUS_MODE', ''))) if os.getenv('DISCORD_ANONYMOUS_MODE') is not None else self.raise_error("Missing ANONYMOUS_MODE")

            # Network Settings
            self.NETWORK_NAME = f"{os.getenv('NETWORK_NAME')}".lower() or self.raise_error("Missing NETWORK_NAME")
            self.SYMBOL = os.getenv('SYMBOL') or self.raise_error("Missing SYMBOL")
            self.TOKEN_DECIMAL = float(os.getenv('TOKEN_DECIMAL') or self.raise_error("Missing TOKEN_DECIMAL"))
            self.SUBSTRATE_WSS = os.getenv('SUBSTRATE_WSS') or self.raise_error("Missing SUBSTRATE_WSS")
            self.PEOPLE_WSS = os.getenv('PEOPLE_WSS')

            # Wallet Settings
            self.SOLO_MODE = bool(strtobool(os.getenv('SOLO_MODE', ''))) if os.getenv('SOLO_MODE') is not None else self.raise_error("Missing SOLO_MODE")
            self.PROXIED_ADDRESS = os.getenv('PROXIED_ADDRESS') or self.raise_error("Missing PROXIED_ADDRESS")
            self.PROXY_ADDRESS = os.getenv('PROXY_ADDRESS') or self.raise_error("Missing PROXY_ADDRESS")
            self.MNEMONIC = os.getenv('MNEMONIC') or self.raise_error("Missing MNEMONIC")
            self.VOTE_WITH_BALANCE = float(os.getenv('VOTE_WITH_BALANCE') or self.raise_error("Missing VOTE_WITH_BALANCE"))
            self.CONVICTION = os.getenv('CONVICTION') or self.raise_error("Missing CONVICTION")
            self.DISCORD_PROXY_BALANCE_ALERT = int(os.getenv('DISCORD_PROXY_BALANCE_ALERT') or self.raise_error("Missing DISCORD_PROXY_BALANCE_ALERT"))
            self.PROXY_BALANCE_ALERT = float(os.getenv('PROXY_BALANCE_ALERT') or self.raise_error("Missing PROXY_BALANCE_ALERT"))
            self.MIN_PARTICIPATION = float(os.getenv('MIN_PARTICIPATION') or self.raise_error("Missing MIN_PARTICIPATION"))
            self.READ_ONLY = bool(strtobool(os.getenv('READ_ONLY', 'False')))

        except ValueError as e:
            print(f"Error: {e}")

    def initialize_environment_files(self):
        """
        Ensure that required files exist for the bot's operation.
        If a file does not exist, create it with an empty JSON object.
        """
        # Define the list of files to check
        files_to_check = [
            '../data/archived_votes.json',
            '../data/governance.cache',
            '../data/onchain-votes.json',
            '../data/vote_counts.json'
        ]

        for file_name in files_to_check:
            if not os.path.exists(file_name):
                with open(file_name, 'w') as file:
                    json.dump({}, file)
                self.logger.info(f"{file_name} missing... creating file")
            else:
                pass

    def __getitem__(self, key):
        return getattr(self, key, None)

    @staticmethod
    def raise_error(msg):
        raise ValueError(msg)
