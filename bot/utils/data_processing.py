import os
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
