import os
import json


class Settings:

    def __init__(self, local_fullpath):
        self.get = {}

        try:
            with open(os.path.join(os.path.dirname(__file__), local_fullpath), 'r') as log_handle:
                self.get = json.load(log_handle)
        except IOError:
            print('FATAL ERROR - Settings Not Found - Expecting %s' % local_fullpath)
            exit()

