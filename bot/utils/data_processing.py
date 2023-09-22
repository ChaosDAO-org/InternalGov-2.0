import re
import os
import time
import json
import deepdiff
import markdownify
from typing import Dict, Any
from utils.config import Config
from utils.subquery import SubstrateAPI
from utils.logger import Logger


class Text:
    @staticmethod
    def convert_markdown_to_discord(markdown_text):
        base_url = "https://polkadot.polkassembly.io/"

        def replacer_link(match):
            link_text = match.group(1)
            url = match.group(2)

            # Check if the URL is relative
            if url.startswith("../"):
                # Construct the absolute URL
                url = base_url + url[3:]

            # If the URL is just a positive integer, it's considered relative
            elif url.isdigit():
                url = base_url + "referenda/referendum/" + url

            return f'[{link_text}]({url})'

        def replacer_image(match):
            url = match.group(1)
            return url

        markdown_text = markdownify.markdownify(markdown_text)
        markdown_text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replacer_link, markdown_text)
        markdown_text = re.sub(r'!\[[^\]]*\]\(([^)]+)\)', replacer_image, markdown_text)
        markdown_text = re.sub(r'(?:\s*\n){3,}', '\n\n', markdown_text)  # Replace three or more newlines with optional spaces with just one newline
        markdown_text = markdown_text.rstrip('\n')  # Remove trailing line breaks

        return markdown_text


class CacheManager:
    @staticmethod
    def save_data_to_cache(filename: str, data: Dict[str, Any]) -> None:
        """Save data to a JSON file."""
        with open(filename, 'w') as cache:
            json.dump(data, cache, indent=4)

    @staticmethod
    def load_data_from_cache(filename: str) -> Dict[str, Any]:
        """Load data from a JSON file."""
        with open(filename, 'r') as cache:
            cached_file = json.load(cache)
        return cached_file

    @staticmethod
    def get_cache_difference(filename: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """Compare the provided data with the cached data and return the difference using deepdiff."""
        full_path = os.path.join("../data", filename)

        if not os.path.isfile(full_path):
            CacheManager.save_data_to_cache(full_path, data)
            return {}

        cached_data = CacheManager.load_data_from_cache(full_path)

        # use DeepDiff to check if any values have changed since we ran has_commission_updated().
        difference = deepdiff.DeepDiff(cached_data, data, ignore_order=True).to_json()
        result = json.loads(difference)
        if len(result) == 0:
            return {}
        else:
            return result

    @staticmethod
    def delete_old_keys_and_archive(json_file_path, days=14, archive_filename="archived_votes.json"):
        current_time = int(time.time())
        time_threshold = int(days) * 24 * 60 * 60  # Convert days to seconds

        # Load JSON data from the file
        with open(json_file_path, "r") as json_file:
            json_data = json.load(json_file)

        keys_to_delete = []

        for key, value in json_data.items():
            if current_time - value["epoch"] > time_threshold:
                keys_to_delete.append(key)

        # Load archived data or create an empty dictionary if the file doesn't exist
        if os.path.exists(archive_filename):
            with open(archive_filename, "r") as archive_file:
                archived_data = json.load(archive_file)
        else:
            archived_data = {}

        # Archive keys to be deleted
        for key in keys_to_delete:
            archived_data[key] = json_data[key]
            del json_data[key]

        # Save the archived data to the file
        with open(archive_filename, "w") as archive_file:
            json.dump(archived_data, archive_file, indent=2)

        # Save the updated JSON data back to the original file
        with open(json_file_path, "w") as json_file:
            json.dump(json_data, json_file, indent=2)

        # Return the list of archived keys
        return keys_to_delete


class DiscordFormatting:
    def __init__(self):
        self.config = Config()
        self.substrate = SubstrateAPI()
        self.logging = Logger()

    def format_key(self, key, parent_key):
        try:
            FIELD_NAME_MAP = {
                "Ongoing.alarm": "ENDING BLOCK",
                "Ongoing.deciding.confirming": "CONFIRMING",
                "Ongoing.deciding.since": "CONFIRMING SINCE",
                "Ongoing.decision_deposit.amount": "DECISION DEPOSIT AMOUNT",
                "Ongoing.decision_deposit.who": "DECISION DEPOSITER",
                "Ongoing.enactment.After": "ENACTMENT AFTER",
                "Ongoing.in_queue": "IN QUEUE",
                "Ongoing.origin.Origins": "ORIGIN",
                "Ongoing.proposal.Lookup.hash": "PROPOSAL HASH",
                "Ongoing.proposal.Lookup.len": "PROPOSAL LENGTH",
                "Ongoing.submission_deposit.amount": "SUBMISSION DEPOSIT AMOUNT",
                "Ongoing.submission_deposit.who": "SUBMITTER",
                "Ongoing.submitted": "SUBMITTED",
                "Ongoing.tally.ayes": "AYES",
                "Ongoing.tally.nays": "NAYS",
                "Ongoing.tally.support": "SUPPORT",
                "Ongoing.track": "TRACK"
            }

            if isinstance(key, list):
                key = ','.join(map(str, key))
            if isinstance(parent_key, list):
                parent_key = ','.join(map(str, parent_key))

            full_key = f"{parent_key}.{key}" if parent_key else key
            if full_key.startswith("args."):
                full_key = full_key.replace("args.", "", 1)
            formatted_key = FIELD_NAME_MAP.get(full_key, full_key)
        except Exception as e:
            # Handle or log error
            self.logging.error(f"Error occurred: {e}")
        return formatted_key.upper()

    async def extract_and_embed(self, data, embed, parent_key=""):
        if 'proposed_call' in data:
            data = data['proposed_call']

        for key, value in data.items():
            new_key = f"{parent_key}.{key}" if parent_key else key
            valid_address = await self.substrate.is_valid_ss58_address(address=value)
            if valid_address and len(value) < 49:
                display_name = await self.substrate.get_display_name(address=value)
                # display_name = identity.get('display', {}).get('Raw', None)
                value = f"[{display_name if display_name else value}](https://{self.config.NETWORK_NAME}.subscan.io/account/{value})"

            if new_key == 'CALL.CALLS':
                for idx, call_item in enumerate(value):
                    for call_key, call_value in call_item.items():
                        formatted_key = self.format_key(f"{call_key.upper()} {idx + 1}", parent_key)
                        embed.add_field(name=formatted_key, value=call_value, inline=True)
                continue

            if key.upper() in ["AMOUNT", "FEE", "DECISION_DEPOSIT_AMOUNT"] and isinstance(value, (int, float, str)):
                value = "{:,.0f}".format(int(value) / self.config.TOKEN_DECIMAL)
                value = f"{value} {self.config.SYMBOL}"  # Add a dollar sign before the value

            if isinstance(value, dict):
                await self.extract_and_embed(value, embed, new_key)
            else:
                formatted_key = self.format_key(new_key, "")
                if len(str(value)) > 255:
                    value = str(value)[:252] + "..."
                embed.add_field(name=formatted_key, value=value, inline=True)

        return embed

    def flatten_dict(self, data, parent_key='', sep='.'):
        items = {}
        for k, v in data.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.update(self.flatten_dict(v, new_key, sep=sep))
            else:
                items[new_key] = v
        return items

    async def add_fields_to_embed(self, embed, data, parent_key=""):
        char_count = 0
        field_data = {}
        field_order = [
            'ORIGIN',
            'DECISION DEPOSIT AMOUNT',
            'SUBMISSION DEPOSIT AMOUNT',
            'ENDING BLOCK',
            'CONFIRMING',
            'CONFIRMING SINCE',
            'DECISION DEPOSITER',
            'SUBMITTER',
            'SINCE',
            'ENACTMENT AFTER',
            'AYES',
            'NAYS',
            'SUPPORT',
            'SUBMITTED'
        ]

        flat_data = self.flatten_dict(data)

        for key, value in flat_data.items():
            if parent_key == "comments" or key in ["PROPOSAL LENGTH", "PROPOSAL HASH"]:
                continue
            formatted_key = self.format_key(key, parent_key)

            # Look up and add display name for specific keys
            valid_address = await self.substrate.is_valid_ss58_address(address=value)
            if valid_address and len(value) < 50:
                identity = await self.substrate.get_identity_or_super_identity(address=value)
                display_name = identity['display']['Raw'] if identity and 'display' in identity else None
                value = f"[{display_name if display_name else value}](https://{self.config.NETWORK_NAME}.subscan.io/account/{value})"

            if formatted_key == "ENDING BLOCK":
                value = f"[{value[0]}](https://{self.config.NETWORK_NAME}.subscan.io/block/{value[0]})"

            if formatted_key in ["CONFIRMING SINCE", "SUBMITTED"]:
                value = f"[{value}](https://{self.config.NETWORK_NAME}.subscan.io/block/{value})"

            if formatted_key == "CONFIRMING":
                value = "True" if isinstance(value, int) or (isinstance(value, str) and value.isdigit()) else "False"

            if any(keyword in formatted_key for keyword in ["AYES", "NAYS", "SUPPORT"]) and isinstance(value, (int, float, str)):
                value = str("{:,.0f}".format(int(value) / self.config.TOKEN_DECIMAL))  # Add a dollar sign before the value

            if "AMOUNT" in formatted_key and isinstance(value, (int, float, str)):
                value = "{:,.0f}".format(int(value) / self.config.TOKEN_DECIMAL)
                value = f"{value} {self.config.SYMBOL}"  # Add a dollar sign before the value

            # print(f"Char count: {char_count}, Key: {formatted_key}, Value: {value}")  # Debug line

            next_count = char_count + len(str(formatted_key)) + len(str(value))

            if next_count > 6000:
                self.logging.info("Stopping due to char limit")
                break

            if isinstance(value, dict):
                embed = self.add_fields_to_embed(embed, value, formatted_key)
            else:
                field_data[formatted_key] = value

            char_count = next_count

        for key in field_order:
            if key in field_data:
                embed.add_field(name=key, value=field_data[key], inline=True)

        return embed

    @staticmethod
    def find_msgid_by_index(cache_data, json_data):
        output = {}
        for index in cache_data.keys():
            key_name = next((key for key, item in json_data.items() if item['index'] == index), None)
            if key_name:
                output[index] = key_name
        return output
