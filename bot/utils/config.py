from dotenv import load_dotenv
import os

class Config:
    def __init__(self):
        try:
            load_dotenv("../.env")
            
            self.DISCORD_ADMIN_ROLE = os.getenv('DISCORD_ADMIN_ROLE') or self.raise_error("Missing DISCORD_ADMIN_ROLE")
            self.DISCORD_API_KEY = os.getenv('DISCORD_API_KEY') or self.raise_error("Missing DISCORD_API_KEY")
            self.DISCORD_FORUM_CHANNEL_ID = int(os.getenv('DISCORD_FORUM_CHANNEL_ID') or self.raise_error("Missing DISCORD_FORUM_CHANNEL_ID"))
            self.DISCORD_LOCK_THREAD = int(os.getenv('DISCORD_LOCK_THREAD') or self.raise_error("Missing DISCORD_LOCK_THREAD"))
            self.DISCORD_ROLE = os.getenv('DISCORD_ROLE') or self.raise_error("Missing DISCORD_ROLE")
            self.DISCORD_SERVER_ID = int(os.getenv('DISCORD_SERVER_ID') or self.raise_error("Missing DISCORD_SERVER_ID"))
            self.NETWORK_NAME = f"{os.getenv('NETWORK')}" or self.raise_error("Missing NETWORK")
            self.SUBSTRATE_WSS = os.getenv('SUBSTRATE_WSS') or self.raise_error("Missing SUBSTRATE_WSS")
            self.SYMBOL = os.getenv('SYMBOL') or self.raise_error("Missing SYMBOL")
            self.TAG_ROLE_NAME = f"{os.getenv('SYMBOL')}-GOV" or self.raise_error("Missing SYMBOL")
            self.TOKEN_DECIMAL = float(os.getenv('TOKEN_DECIMAL') or self.raise_error("Missing TOKEN_DECIMAL"))
            
        except ValueError as e:
            print(f"Error: {e}")
            
    def __getitem__(self, key):
        return getattr(self, key, None)


    @staticmethod
    def raise_error(msg):
        raise ValueError(msg)