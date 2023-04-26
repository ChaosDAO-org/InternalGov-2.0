import os
import time
import json
from typing import Dict, Any
import deepdiff


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
        time_threshold = days * 24 * 60 * 60  # Convert days to seconds

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
