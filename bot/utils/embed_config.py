class EmbedVoteScheme:
    vote_type_emojis = {
        "aye": "👍",
        "nay": "👎",
        "abstain": "⛔"
    }

    vote_type_color = {
        "aye": 0x00FF00,
        "nay": 0xFF0000,
        "abstain": 0xFFFFFF
    }

    def __init__(self, vote_type):
        if vote_type not in self.vote_type_emojis:
            raise ValueError("Invalid vote type. Choose from 'aye', 'nay', 'abstain'.")
        self._vote_type = vote_type

    @property
    def color(self):
        return self.vote_type_color[self._vote_type]

    @property
    def emoji(self):
        return self.vote_type_emojis[self._vote_type]