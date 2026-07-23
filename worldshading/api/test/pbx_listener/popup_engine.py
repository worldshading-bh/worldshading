class PopupEngine(object):
    """Prevents duplicate popup candidates for one call and extension."""

    def __init__(self):
        self.sent = set()

    def should_send(self, linkedid, extension):
        key = (linkedid, extension)

        if key in self.sent:
            return False

        self.sent.add(key)
        return True

    def clear_call(self, linkedid):
        self.sent = set([
            key for key in self.sent
            if key[0] != linkedid
        ])
