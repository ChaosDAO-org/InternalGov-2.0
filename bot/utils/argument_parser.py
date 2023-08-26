import argparse

class ArgumentParser:
    def __init__(self):
        self.args = self.parse_arguments()

    def parse_arguments(self):
        parser = argparse.ArgumentParser(description='Governance Monitor Bot')
        parser.add_argument('-v', '--verbose', action='store_true', help='Enable verbose logging')
        args = parser.parse_args()
        return args