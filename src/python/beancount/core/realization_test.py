"""
Unit tests for realizations.
"""
import unittest
import textwrap
import functools
import re

from beancount import parser

from beancount.core.amount import to_decimal as D
from beancount.core.realization import RealAccount
from beancount.core import realization
from beancount.core import data
from beancount.core import inventory
from beancount.core import amount
from beancount.core import account_types
from beancount.parser import documents
from beancount.parser import parsedoc
from beancount.parser import printer
from beancount.loader import loaddoc


def create_simple_account():
    ra = RealAccount('')
    ra['Assets'] = RealAccount('Assets')
    ra['Assets']['US'] = RealAccount('Assets:US')
    ra['Assets']['US']['Bank'] = RealAccount('Assets:US:Bank')
    ra['Assets']['US']['Bank']['Checking'] = RealAccount('Assets:US:Bank:Checking')
    return ra


class TestRealAccount(unittest.TestCase):

    def test_ctor(self):
        ra = RealAccount('Assets:US:Bank:Checking')
        self.assertEqual(0, len(ra))
        ra = RealAccount('Equity')
        ra = RealAccount('')
        with self.assertRaises(Exception):
            ra = RealAccount(None)

    def test_str(self):
        ra = RealAccount('Assets:US:Bank:Checking')
        self.assertEqual('{}', str(ra))

        ra = create_simple_account()
        ra_str = str(ra)
        self.assertTrue(re.search('Assets', ra_str))
        self.assertTrue(re.search('Bank', ra_str))
        self.assertTrue(re.search('Checking', ra_str))

    def test_getitem_setitem(self):
        ra = create_simple_account()
        self.assertTrue(isinstance(ra['Assets'], RealAccount))
        self.assertTrue(isinstance(ra['Assets']['US'], RealAccount))
        with self.assertRaises(KeyError):
            ra['Liabilities']

    def test_setitem_constraints(self):
        ra = RealAccount('')
        ra['Assets'] = RealAccount('Assets')
        with self.assertRaises(KeyError):
            ra['Assets'][42] = RealAccount('Assets:US')
        with self.assertRaises(ValueError):
            ra['Assets']['US'] = 42
        with self.assertRaises(ValueError):
            ra['Assets']['US'] = RealAccount('Assets:US:Checking')


class TestRealGetters(unittest.TestCase):

    def test_get(self):
        ra = create_simple_account()
        self.assertEqual('Assets',
                         realization.get(ra, 'Assets').account)
        self.assertEqual('Assets:US:Bank',
                         realization.get(ra, 'Assets:US:Bank').account)
        self.assertEqual('Assets:US:Bank:Checking',
                         realization.get(ra, 'Assets:US:Bank:Checking').account)
        self.assertEqual(None, realization.get(ra, 'Assets:US:Bank:Savings'))
        self.assertEqual(42, realization.get(ra, 'Assets:US:Bank:Savings', 42))
        with self.assertRaises(ValueError):
            self.assertEqual(42, realization.get(ra, None))
        self.assertEqual(None, realization.get(ra, ''))

    def test_get_or_create(self):
        ra = RealAccount('')
        ra_checking = realization.get_or_create(ra, 'Assets:US:Bank:Checking')
        ra_savings = realization.get_or_create(ra, 'Assets:US:Bank:Savings')
        self.assertEqual('Assets:US:Bank:Checking', ra_checking.account)
        self.assertEqual({'Assets'}, ra.keys())
        self.assertEqual({'Checking', 'Savings'}, ra['Assets']['US']['Bank'].keys())

        ra_assets = ra['Assets']
        ra_assets2 = realization.get_or_create(ra, 'Assets')
        self.assertTrue(ra_assets2 is ra_assets)

    def test_contains(self):
        ra = RealAccount('')
        ra_checking = realization.get_or_create(ra, 'Assets:US:Bank:Checking')
        ra_savings = realization.get_or_create(ra, 'Assets:US:Bank:Savings')
        self.assertTrue(realization.contains(ra, 'Assets:US:Bank:Checking'))
        self.assertTrue(realization.contains(ra, 'Assets:US:Bank:Savings'))
        self.assertFalse(realization.contains(ra, 'Assets:US:Cash'))

    def test_iter_children(self):
        ra = RealAccount('')
        for account_name in ['Assets:US:Bank:Checking',
                             'Assets:US:Bank:Savings',
                             'Assets:US:Cash',
                             'Assets:CA:Cash']:
            realization.get_or_create(ra, account_name)

        # Test enumerating all accounts.
        self.assertEqual(['',
                          'Assets',
                          'Assets:CA',
                          'Assets:CA:Cash',
                          'Assets:US',
                          'Assets:US:Bank',
                          'Assets:US:Bank:Checking',
                          'Assets:US:Bank:Savings',
                          'Assets:US:Cash'],
                         [ra.account for ra in realization.iter_children(ra)])

        # Test enumerating leaves only.
        self.assertEqual(['Assets:CA:Cash',
                          'Assets:US:Bank:Checking',
                          'Assets:US:Bank:Savings',
                          'Assets:US:Cash'],
                         [ra.account for ra in realization.iter_children(ra, True)])


class TestRealization(unittest.TestCase):

    @loaddoc
    def test_group_by_account(self, entries, errors, _):
        """
        2012-01-01 open Expenses:Restaurant
        2012-01-01 open Expenses:Movie
        2012-01-01 open Assets:Cash
        2012-01-01 open Liabilities:CreditCard
        2012-01-01 open Equity:OpeningBalances

        2012-01-15 pad Liabilities:CreditCard Equity:OpeningBalances

        2012-03-01 * "Food"
          Expenses:Restaurant     100 CAD
          Assets:Cash

        2012-03-10 * "Food again"
          Expenses:Restaurant     80 CAD
          Liabilities:CreditCard

        ;; Two postings on the same account.
        2012-03-15 * "Two Movies"
          Expenses:Movie     10 CAD
          Expenses:Movie     10 CAD
          Liabilities:CreditCard

        2012-03-20 note Liabilities:CreditCard "Called Amex, asked about 100 CAD dinner"

        2012-03-28 document Liabilities:CreditCard "march-statement.pdf"

        2013-04-01 balance Liabilities:CreditCard   204 CAD

        2014-01-01 close Liabilities:CreditCard
        """
        self.assertEqual([documents.DocumentError], list(map(type, errors)))

        postings_map = realization.group_by_account(entries)
        self.assertTrue(isinstance(postings_map, dict))

        self.assertEqual([data.Open, data.Posting],
                         list(map(type, postings_map['Assets:Cash'])))

        self.assertEqual([data.Open, data.Posting, data.Posting],
                         list(map(type, postings_map['Expenses:Restaurant'])))

        self.assertEqual([data.Open,
                          data.Posting,
                          data.Posting],
                         list(map(type, postings_map['Expenses:Movie'])))

        self.assertEqual([data.Open,
                          data.Pad,
                          data.Posting, data.Posting, data.Posting,
                          data.Note,
                          data.Document,
                          data.Balance,
                          data.Close],
                         list(map(type, postings_map['Liabilities:CreditCard'])))

        self.assertEqual([data.Open, data.Pad, data.Posting],
                         list(map(type, postings_map['Equity:OpeningBalances'])))

    @parsedoc
    def test_compute_postings_balance(self, entries, _, __):
        """
        2014-01-01 open Assets:Bank:Checking
        2014-01-01 open Assets:Bank:Savings
        2014-01-01 open Assets:Investing

        2014-05-26 note Assets:Investing "Buying some Googlies"

        2014-05-30 *
          Assets:Bank:Checking  111.23 USD
          Assets:Bank:Savings   222.74 USD
          Assets:Bank:Savings   17.23 CAD
          Assets:Investing      10000 EUR
          Assets:Investing      32 GOOG {45.203 USD}
          Assets:Other          1000 EUR @ 1.78 GBP
          Assets:Other          1000 EUR @@ 1780 GBP
        """
        postings = entries[:-1] + entries[-1].postings
        balance = realization.compute_postings_balance(postings)

        expected_balance = inventory.Inventory()
        expected_balance.add(amount.Amount('333.97', 'USD'))
        expected_balance.add(amount.Amount('17.23', 'CAD'))
        expected_balance.add(amount.Amount('32', 'GOOG'),
                             amount.Amount('45.203', 'USD'))
        expected_balance.add(amount.Amount('12000', 'EUR'))
        self.assertEqual(expected_balance, balance)

    def test_realize_empty(self):
        real_account = realization.realize([])
        self.assertTrue(isinstance(real_account, realization.RealAccount))
        self.assertEqual(real_account.account, '')

    def test_realize_min_accoumts(self):
        real_account = realization.realize(
            [], account_types.DEFAULT_ACCOUNT_TYPES)
        self.assertTrue(isinstance(real_account, realization.RealAccount))
        self.assertEqual(real_account.account, '')
        self.assertEqual(len(real_account), 5)
        self.assertEqual(set(account_types.DEFAULT_ACCOUNT_TYPES),
                         real_account.keys())

    @parsedoc
    def test_simple_realize(self, entries, errors, options_map):
        """
          2013-05-01 open Assets:US:Checking:Sub   USD
          2013-05-01 open Expenses:Stuff
          2013-05-02 txn "Testing!"
            Assets:US:Checking:Sub            100 USD
            Expenses:Stuff           -100 USD
        """
        real_root = realization.realize(entries)
        for real_account in realization.iter_children(real_root):
            assert isinstance(real_account, realization.RealAccount)

        for account_name in ['Assets:US:Checking:Sub',
                             'Expenses:Stuff']:
            real_account = realization.get(real_root, account_name)
            self.assertEqual(account_name, real_account.account)

    @loaddoc
    def test_realize(self, entries, errors, _):
        """
        2012-01-01 open Expenses:Restaurant
        2012-01-01 open Expenses:Movie
        2012-01-01 open Assets:Cash
        2012-01-01 open Liabilities:CreditCard
        2012-01-01 open Equity:OpeningBalances

        2012-01-15 pad Liabilities:CreditCard Equity:OpeningBalances

        2012-03-01 * "Food"
          Expenses:Restaurant     100 CAD
          Assets:Cash

        2012-03-10 * "Food again"
          Expenses:Restaurant     80 CAD
          Liabilities:CreditCard

        ;; Two postings on the same account.
        2012-03-15 * "Two Movies"
          Expenses:Movie     10 CAD
          Expenses:Movie     10 CAD
          Liabilities:CreditCard

        2012-03-20 note Liabilities:CreditCard "Called Amex, asked about 100 CAD dinner"

        2012-03-28 document Liabilities:CreditCard "march-statement.pdf"

        2013-04-01 balance Liabilities:CreditCard   204 CAD

        2014-01-01 close Liabilities:CreditCard
        """
        real_account = realization.realize(entries)
        self.assertEqual(
            {'Assets': {
                'Cash': {}},
             'Equity': {
                 'OpeningBalances': {}},
             'Expenses': {
                 'Movie': {},
                 'Restaurant': {}},
             'Liabilities': {
                 'CreditCard': {}}},
            real_account)

        ra_movie = realization.get(real_account, 'Expenses:Movie')
        self.assertEqual('Expenses:Movie', ra_movie.account)
        expected_balance = inventory.Inventory()
        expected_balance.add(amount.Amount('20', 'CAD'))
        self.assertEqual(expected_balance, ra_movie.balance)


class TestRealOther(unittest.TestCase):

    def test_filter_tree(self):
        pass

#     def test_get_subpostings(self):
#         pass

#     def test__get_subpostings(self):
#         pass

#     def test_dump_tree_balances(self):
#         pass

#     def test_compare_realizations(self):
#         pass

#     def test_real_cost_as_dict(self):
#         pass

#     def test_iterate_with_balance(self):
#         pass




# do_trace = False

# def realizedoc(fun):
#     """Decorator that parses, pads and realizes the function's docstring as an
#     argument."""
#     @functools.wraps(fun)
#     def newfun(self):
#         entries, errors, options_map = parser.parse_string(textwrap.dedent(fun.__doc__))
#         real_accounts = realization.realize(entries)
#         if do_trace and errors:
#             trace_errors(real_accounts, errors)
#         return fun(self, entries, real_accounts, errors)
#     return newfun











# Loader tests:

# FIXME: please DO test the realization of a transaction that has multiple legs
# on the same account!


__incomplete__ = True
