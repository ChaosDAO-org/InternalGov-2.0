import re
import os
import io
import time
import json
import shutil
import qrcode
import discord
import deepdiff
import markdownify
from PIL import Image
from typing import Dict, Any
from datetime import datetime
from utils.config import Config
from utils.logger import Logger


class Text:
    @staticmethod
    def convert_markdown_to_discord(markdown_text):
        base_url = "https://polkadot.polkassembly.io/"

        def replacer_link(match):
            link_text = match.group(1)
            url = match.group(2)

            if url.startswith("../"):
                url = base_url + url[3:]
            elif url.isdigit():
                url = base_url + "referenda/referendum/" + url

            return f'[{link_text}]({url})'

        def replacer_image(match):
            url = match.group(1)
            return url

        # By default, markdownify adds backslashes before _ and * characters
        # We turn this off by setting escape_underscores and escape_asterisks to False
        # This keeps URLs clean and prevents unwanted backslashes from appearing
        markdown_text = markdownify.markdownify(markdown_text, escape_underscores=False, escape_asterisks=False)

        markdown_text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replacer_link, markdown_text)
        markdown_text = re.sub(r'!\[[^\]]*\]\(([^)]+)\)', replacer_image, markdown_text)
        markdown_text = re.sub(r'(?:\s*\n){3,}', '\n\n', markdown_text)  # Replace three or more newlines with optional spaces with just one newline
        markdown_text = markdown_text.rstrip('\n')                                   # Remove trailing line breaks

        if len(markdown_text) == 0:
            return "Unable to retrieve content"

        return markdown_text

    @staticmethod
    def generate_qr_code(publickey):
        # Create a QR code instance
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=10,
            border=4,
        )

        # Add data to the QR code
        qr.add_data(publickey)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        img = img.resize((250, 250), Image.LANCZOS)

        # Save the image to a bytes object for Discord embed
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)

        return img_byte_arr


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
    def get_details_by_index(data, index):
        for key, value in data.items():
            if value["index"] == str(index):
                return value
        return "No data found for index {}".format(index)

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

    @staticmethod
    def delete_executed_keys_and_archive(json_file_path, active_proposals, archive_filename="archived_votes.json"):

        # Load JSON data from the file
        with open(json_file_path, "r") as json_file:
            json_data = json.load(json_file)

        vote_count_proposals = []
        for key, value in json_data.items():
            vote_count_proposals.append(int(value['index']))

        # Invert the structure to map indexes to keys
        index_to_key = {value['index']: key for key, value in json_data.items()}

        # Add thread id into keys_to_delete if they're not in active proposals
        keys_to_delete = []
        for index in vote_count_proposals:
            if index not in active_proposals:
                keys_to_delete.append(index_to_key[str(index)])

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
    @staticmethod
    def rotating_backup_file(source_path, backup_dir, max_versions=3):
        """
        Creates a rotating backup of a file. Overwrites the oldest backup to maintain
        only max_versions of the backup.

        :param source_path: Path to the original file.
        :param backup_dir: Directory where the backups will be stored.
        :param max_versions: Maximum number of backup versions to keep.
        """
        try:
            # Ensure the backup directory exists
            if not os.path.exists(backup_dir):
                os.makedirs(backup_dir)

            # Create backup file name
            base_name = os.path.basename(source_path)
            backup_path_template = os.path.join(backup_dir, f"{base_name}.{{}}")

            # Find the oldest backup version to overwrite
            existing_backups = [int(backup.split('.')[-1]) for backup in os.listdir(backup_dir) if backup.startswith(base_name) and backup.split('.')[-1].isdigit()]
            if existing_backups:
                existing_backups.sort()
                version_to_overwrite = existing_backups[0] if len(existing_backups) >= max_versions else max(existing_backups) + 1
            else:
                version_to_overwrite = 1

            # Overwrite the oldest backup or create a new one
            backup_path = backup_path_template.format(version_to_overwrite)
            shutil.copy2(source_path, backup_path)
            return f"Backup successful. Backup version: {version_to_overwrite}"
        except Exception as e:
            return f"Error during backup: {e}"


class ProcessCallData:
    def __init__(self, price, substrate=None):
        self.config = Config()
        self.substrate = substrate
        self.price = price
        self.general_index = None

    @staticmethod
    def format_key(key):
        """
        Formats a given key by splitting it on underscores, capitalizing each part except
        for those containing 'id' which are made uppercase, and then joining them back together
        with spaces in between.

        :param key: The key to be formatted.
        :type key: str
        :return: The formatted key.
        :rtype: str
        """
        parts = key.split('_')
        formatted_parts = []
        for part in parts:
            if "id" in part.lower():
                formatted_part = part.upper()
            else:
                formatted_part = part.capitalize()
            formatted_parts.append(formatted_part)
        return ' '.join(formatted_parts)

    async def find_and_collect_values(self, data, preimagehash, indent=0, path='', current_embed=None):
        """
        Recursively traverses through the given data (list, dictionary or other data types)
        and collects certain values to be added to a list of discord Embed objects.
        The function modifies the given `embeds` list in-place,
        appending new Embed objects when required.

        :param data: The data to traverse
        :type data: list, dict or other
        :param preimagehash: The hash of the preimage associated with the data
        :type preimagehash: str
        :param indent: The current indentation level for formatting Embed descriptions, default is 0
        :type indent: int
        :param path: The path to the current data element, default is ''
        :type path: str
        :param current_embed: The currently active Embed object, default is None
        :type current_embed: Embed or None
        :return: The extended list of Embed objects
        :rtype: list
        """

        if current_embed is None:
            if data is False:
                description = preimagehash
            else:
                description = ""
            current_embed = discord.Embed(title=":ballot_box: Call Detail", description=description, color=0x00ff00, timestamp=datetime.utcnow())
            current_embed.set_thumbnail(url="attachment://symbol.png")

        max_description_length = 1000
        call_function = 0
        call_module = 0

        if isinstance(data, dict):
            for key, value in data.items():
                new_path = f"{path}.{hash(key)}" if path else str(hash(key))

                if key == 'call_index':
                    continue

                if len(current_embed.description) >= max_description_length:
                    return current_embed

                if isinstance(value, (dict, list)):
                    await self.find_and_collect_values(value, preimagehash, indent, new_path, current_embed)
                else:
                    value_str = str(value)

                    if key == 'call_function':
                        call_function = call_function + 1

                    if key == 'call_module':
                        call_module = call_module + 1

                    if key in ['X1', 'X2', 'X3', 'X4', 'X5']:
                        indent = indent + 1

                    if call_function == 1 and call_module == 0:
                        indent = indent + 1

                    if key == 'GeneralIndex':
                        self.general_index = value

                    #print(f"{key:<20} {call_function:<15} {call_module:<15} {indent:<15} {len(current_embed.description):<15} {key not in ['call_function', 'call_module']}")  # debugging

                    if key not in ['call_function', 'call_module']:
                        if key == 'amount':
                            asset_dict = {1337: 'USDC', 1984: 'USDT'}
                            if str(self.general_index) in ['1337', '1984']:
                                decimal = 1e6
                            else:
                                decimal = self.config.TOKEN_DECIMAL

                            asset_name = asset_dict.get(self.general_index, self.config.SYMBOL)

                            value_str = float(value_str) / decimal
                            current_embed.description += f"\n{'　' * (indent + 1)} **{self.format_key(key)[:256]}**: {value_str:,.0f} `{asset_name}`"

                            if self.general_index is None:
                                current_embed.description += f"\n{'　' * (indent + 1)} **USD**: {value_str * self.price:,.0f}"

                        elif key in ['beneficiary', 'signed', 'curator']:
                            display_name = await self.substrate.check_identity(address=value_str, network=self.config.NETWORK_NAME)
                            current_embed.description += f"\n{'　' * (indent + 1)} **{self.format_key(key)[:256]}**: [{display_name}](https://{self.config.NETWORK_NAME}.subscan.io/account/{value_str})"
                        else:
                            current_embed.description += f"\n{'　' * (indent + 1)} **{self.format_key(key)[:256]}**: {(value_str[:253] + '...') if len(value_str) > 256 else value_str}"
                    else:
                        current_embed.description += f"\n{'　' * indent} **{self.format_key(key)[:256]}**: `{value_str[:253]}`"

                    if len(current_embed.description) >= max_description_length:
                        return current_embed

                    await self.find_and_collect_values(value, preimagehash, indent, new_path, current_embed)

        elif isinstance(data, (list, tuple)):
            for index, item in enumerate(data):
                if len(current_embed.description) >= max_description_length:
                    current_embed.description += (f"\n\nThe call is too large to display here. Visit [**Subscan**](https://{self.config.NETWORK_NAME}.subscan.io/preimage/{preimagehash}) for more details")
                    return current_embed

                new_path = f"{path}[{index}]"
                await self.find_and_collect_values(item, preimagehash, indent, new_path, current_embed)

        return current_embed

    async def consolidate_call_args(self, data):
        """
        Modifies the given data in-place by consolidating 'call_args' entries
        from list of dictionaries into a single dictionary where the key is 'name'
        and the value is 'value'.

        :param data: The data to consolidate
        :type data: dict or list
        :return: The consolidated data
        :rtype: dict or list
        """
        if isinstance(data, dict):
            if "call_args" in data:
                new_args = {}
                for arg in data["call_args"]:
                    if "name" in arg and "value" in arg:
                        new_args[arg["name"]] = arg["value"]
                data["call_args"] = new_args
            for key, value in data.items():
                data[key] = await self.consolidate_call_args(value)  # Recursive call for nested dictionaries
        elif isinstance(data, list):
            for index, item in enumerate(data):
                data[index] = await self.consolidate_call_args(item)  # Recursive call for lists
        return data

class DiscordFormatting:
    def __init__(self, substrate=None):
        self.config = Config()
        self.substrate = substrate
        self.logging = Logger()

    async def format_key(self, key, parent_key):
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
                "Ongoing.track": "TRACK",
                "call.section": "SECTION",
                "call.method": "METHOD"
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
        if 'polkassembly' in data.get('successful_url', {}):
            data = data.get('proposed_call', {})

        if 'subsquare' in data.get('successful_url', {}):
            data = data.get('onchainData', {}).get('proposal', {}).get('call', {})

        for key, value in data.items():
            new_key = f"{parent_key}.{key}" if parent_key else key
            valid_address = await self.substrate.check_ss58_address(address=value)
            if valid_address and len(value) < 49:
                display_name = await self.substrate.check_identity(address=value, network=self.config.NETWORK_NAME)
                value = f"[{display_name if display_name else value}](https://{self.config.NETWORK_NAME}.subscan.io/account/{value})"

            if new_key == 'CALL.CALLS':
                for idx, call_item in enumerate(value):
                    for call_key, call_value in call_item.items():
                        formatted_key = await self.format_key(f"{call_key.upper()} {idx + 1}", parent_key)
                        embed.add_field(name=formatted_key, value=call_value, inline=True)
                continue

            if key.upper() in ["AMOUNT", "FEE", "DECISION_DEPOSIT_AMOUNT"] and isinstance(value, (int, float, str)):
                value = "{:,.0f}".format(int(value) / self.config.TOKEN_DECIMAL)
                value = f"{value} {self.config.SYMBOL}"  # Add a dollar sign before the value

            if isinstance(value, dict):
                await self.extract_and_embed(value, embed, new_key)
            else:
                formatted_key = await self.format_key(new_key, "")
                if len(str(value)) > 255:
                    value = str(value)[:252] + "..."
                embed.add_field(name=formatted_key, value=value, inline=True)
        return embed

    async def flatten_dict(self, data, parent_key='', sep='.'):
        items = {}
        for k, v in data.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.update(await self.flatten_dict(v, new_key, sep=sep))
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

        flat_data = await self.flatten_dict(data)

        for key, value in flat_data.items():
            if parent_key == "comments" or key in ["PROPOSAL LENGTH", "PROPOSAL HASH"]:
                continue
            formatted_key = await self.format_key(key, parent_key)

            # Look up and add display name for specific keys
            valid_address = await self.substrate.check_ss58_address(address=value)
            if valid_address and len(value) < 50:
                identity = await self.substrate.check_identity(address=value, network=self.config.NETWORK_NAME)
                value = f"[{identity if identity else value}](https://{self.config.NETWORK_NAME}.subscan.io/account/{value})"

            if formatted_key == "ENDING BLOCK" and value is not None:
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
                embed = await self.add_fields_to_embed(embed, value, formatted_key)
            else:
                field_data[formatted_key] = value

            char_count = next_count

        for key in field_order:
            if key in field_data:
                embed.add_field(name=key, value=field_data[key], inline=True)

        return embed

    @staticmethod
    async def find_msgid_by_index(cache_data, json_data):
        output = {}
        for index in cache_data.keys():
            key_name = next((key for key, item in json_data.items() if item['index'] == index), None)
            if key_name:
                output[index] = key_name
        return output
