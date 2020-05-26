"""This plugin filters future transactions.
"""

import datetime

from beancount.core import data, flags

__plugins__ = ('filter_future_transaction',)


def filter_future_transaction(entries, unused_options_map):
    today = datetime.date.today()
    return [entry for entry in entries if not isinstance(entry, data.Transaction) or entry.date <= today], []
