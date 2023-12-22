from dotenv import load_dotenv
import os


class Config:
    def __init__(self):
        try:
            load_dotenv("../.env")

            # Discord Settings
            self.DISCORD_API_KEY = os.getenv('DISCORD_API_KEY') or self.raise_error("Missing DISCORD_API_KEY")
            self.DISCORD_FORUM_CHANNEL_ID = int(os.getenv('DISCORD_FORUM_CHANNEL_ID') or self.raise_error("Missing DISCORD_FORUM_CHANNEL_ID"))
            self.DISCORD_LOCK_THREAD = int(os.getenv('DISCORD_LOCK_THREAD') or self.raise_error("Missing DISCORD_LOCK_THREAD"))
            self.DISCORD_ADMIN_ROLE = os.getenv('DISCORD_ADMIN_ROLE') or self.raise_error("Missing DISCORD_ADMIN_ROLE")
            self.DISCORD_VOTER_ROLE = os.getenv('DISCORD_VOTER_ROLE') or None
            self.DISCORD_SERVER_ID = int(os.getenv('DISCORD_SERVER_ID') or self.raise_error("Missing DISCORD_SERVER_ID"))
            self.DISCORD_TITLE_MAX_LENGTH = int(os.getenv('DISCORD_TITLE_MAX_LENGTH') or self.raise_error("Missing DISCORD_TITLE_MAX_LENGTH"))
            self.DISCORD_BODY_MAX_LENGTH = int(os.getenv('DISCORD_BODY_MAX_LENGTH') or self.raise_error("Missing DISCORD_BODY_MAX_LENGTH"))
            self.TAG_ROLE_NAME = os.getenv('DISCORD_NOTIFY_ROLE') or self.raise_error("Missing SYMBOL")

            # Network Settings
            self.NETWORK_NAME = f"{os.getenv('NETWORK_NAME')}" or self.raise_error("Missing NETWORK_NAME")
            self.SYMBOL = os.getenv('SYMBOL') or self.raise_error("Missing SYMBOL")
            self.TOKEN_DECIMAL = float(os.getenv('TOKEN_DECIMAL') or self.raise_error("Missing TOKEN_DECIMAL"))
            self.SUBSTRATE_WSS = os.getenv('SUBSTRATE_WSS') or self.raise_error("Missing SUBSTRATE_WSS")

            # Wallet Settings
            self.PROXIED_ADDRESS = os.getenv('PROXIED_ADDRESS') or self.raise_error("Missing PROXIED_ADDRESS")
            self.MNEMONIC = os.getenv('MNEMONIC') or self.raise_error("Missing MNEMONIC")
            self.CONVICTION = os.getenv('CONVICTION') or self.raise_error("Missing CONVICTION")

        except ValueError as e:
            print(f"Error: {e}")

    def __getitem__(self, key):
        return getattr(self, key, None)

    @staticmethod
    def raise_error(msg):
        raise ValueError(msg)
