__author__ = "Martin Blais <blais@furius.ca>"

import logging
import unittest
import tempfile
import textwrap
import re
import os
import time
import subprocess
import shutil
from unittest import mock
from os import path

from beancount import loader
from beancount.parser import parser
from beancount.utils import test_utils
from beancount.utils import file_utils


TEST_INPUT = """

2014-01-01 open Assets:MyBank:Checking   USD
2014-01-01 open Expenses:Restaurant   USD

2014-02-22 * "Something happened."
  Assets:MyBank:Checking       100.00 USD
  Expenses:Restaurant         -100.00 USD

2015-01-01 close Assets:MyBank:Checking
2015-01-01 close Expenses:Restaurant

"""


class TestLoader(unittest.TestCase):

    def test_run_transformations(self):
        # Test success case.
        entries, errors, options_map = parser.parse_string(TEST_INPUT)
        trans_entries, trans_errors = loader.run_transformations(
            entries, errors, options_map, None)
        self.assertEqual(0, len(trans_errors))

        # Test an invalid plugin name.
        entries, errors, options_map = parser.parse_string(
            'plugin "invalid.module.name"\n\n' + TEST_INPUT)
        trans_entries, trans_errors = loader.run_transformations(
            entries, errors, options_map, None)
        self.assertEqual(1, len(trans_errors))

    def test_load(self):
        with test_utils.capture():
            with tempfile.NamedTemporaryFile('w') as tmpfile:
                tmpfile.write(TEST_INPUT)
                tmpfile.flush()
                entries, errors, options_map = loader.load_file(tmpfile.name)
                self.assertTrue(isinstance(entries, list))
                self.assertTrue(isinstance(errors, list))
                self.assertTrue(isinstance(options_map, dict))

                entries, errors, options_map = loader.load_file(tmpfile.name,
                                                                log_timings=logging.info)
                self.assertTrue(isinstance(entries, list))
                self.assertTrue(isinstance(errors, list))
                self.assertTrue(isinstance(options_map, dict))

    def test_load_string(self):
        with test_utils.capture():
            entries, errors, options_map = loader.load_string(TEST_INPUT)
            self.assertTrue(isinstance(entries, list))
            self.assertTrue(isinstance(errors, list))
            self.assertTrue(isinstance(options_map, dict))

            entries, errors, options_map = loader.load_string(TEST_INPUT,
                                                              log_timings=logging.info)
            self.assertTrue(isinstance(entries, list))
            self.assertTrue(isinstance(errors, list))
            self.assertTrue(isinstance(options_map, dict))

    def test_load_nonexist(self):
        entries, errors, options_map = loader.load_file('/some/bullshit/filename.beancount')
        self.assertEqual([], entries)
        self.assertTrue(errors)
        self.assertTrue(re.search('does not exist', errors[0].message))

    @mock.patch.dict(loader.DEPRECATED_MODULES,
                     {"beancount.ops.auto_accounts": "beancount.plugins.auto_accounts"},
                     clear=True)
    @mock.patch('warnings.warn')
    def test_deprecated_plugin_warnings(self, warn):
        with test_utils.capture('stderr'):
            entries, errors, options_map = loader.load_string("""
              plugin "beancount.ops.auto_accounts"
            """, dedent=True)
        self.assertTrue(warn.called)
        self.assertFalse(errors)


class TestLoadDoc(unittest.TestCase):

    def test_load_doc(self):
        def test_function(self_, entries, errors, options_map):
            self.assertTrue(isinstance(entries, list))
            self.assertTrue(isinstance(errors, list))
            self.assertTrue(isinstance(options_map, dict))

        test_function.__doc__ = TEST_INPUT
        test_function = loader.load_doc(test_function)
        test_function(self)

    @loader.load_doc()
    def test_load_doc_empty(self, entries, errors, options_map):
        """
        """
        self.assertTrue(isinstance(entries, list))
        self.assertTrue(isinstance(errors, list))
        self.assertTrue(isinstance(options_map, dict))

    @loader.load_doc(expect_errors=True)
    def test_load_doc_plugin(self, entries, errors, options_map):
        """
        plugin "beancount.does.not.exist"
        """
        self.assertTrue(isinstance(entries, list))
        self.assertTrue(isinstance(options_map, dict))
        self.assertTrue([loader.LoadError], list(map(type, errors)))


class TestLoadIncludes(unittest.TestCase):

    def test_load_file_no_includes(self):
        with test_utils.tempdir() as tmp:
            test_utils.create_temporary_files(tmp, {
                'apples.beancount': """
                  2014-01-01 open Assets:Apples
                """})
            entries, errors, options_map = loader.load_file(
                path.join(tmp, 'apples.beancount'))
            self.assertEqual(0, len(errors))
            self.assertEqual(['apples.beancount'],
                             list(map(path.basename, options_map['include'])))

    def test_load_file_nonexist(self):
        entries, errors, options_map = loader.load_file('/bull/bla/root.beancount')
        self.assertEqual(1, len(errors))
        self.assertTrue(re.search('does not exist', errors[0].message))
        self.assertEqual([], list(map(path.basename, options_map['include'])))

    def test_load_file_with_nonexist_include(self):
        with test_utils.tempdir() as tmp:
            test_utils.create_temporary_files(tmp, {
                'root.beancount': """
                  include "/some/file/that/does/not/exist.beancount"
                """})
            entries, errors, options_map = loader.load_file(
                path.join(tmp, 'root.beancount'))
            self.assertEqual(1, len(errors))
            self.assertTrue(re.search('does not exist', errors[0].message))
        self.assertEqual(['root.beancount'],
                         list(map(path.basename, options_map['include'])))

    def test_load_file_with_absolute_include(self):
        with test_utils.tempdir() as tmp:
            test_utils.create_temporary_files(tmp, {
                'apples.beancount': """
                  include "{root}/fruits/oranges.beancount"
                  2014-01-01 open Assets:Apples
                """,
                'fruits/oranges.beancount': """
                  2014-01-02 open Assets:Oranges
                """})
            entries, errors, options_map = loader.load_file(
                path.join(tmp, 'apples.beancount'))
        self.assertFalse(errors)
        self.assertEqual(2, len(entries))
        self.assertEqual(['apples.beancount', 'oranges.beancount'],
                         list(map(path.basename, options_map['include'])))

    def test_load_file_with_relative_include(self):
        with test_utils.tempdir() as tmp:
            test_utils.create_temporary_files(tmp, {
                'apples.beancount': """
                  include "fruits/oranges.beancount"
                  2014-01-01 open Assets:Apples
                """,
                'fruits/oranges.beancount': """
                  2014-01-02 open Assets:Oranges
                """})
            entries, errors, options_map = loader.load_file(
                path.join(tmp, 'apples.beancount'))
        self.assertFalse(errors)
        self.assertEqual(2, len(entries))
        self.assertEqual(['apples.beancount', 'oranges.beancount'],
                         list(map(path.basename, options_map['include'])))

    def test_load_file_with_multiple_includes(self):
        # Including recursive includes and mixed and absolute.
        with test_utils.tempdir() as tmp:
            test_utils.create_temporary_files(tmp, {
                'apples.beancount': """
                  include "fruits/oranges.beancount"
                  include "{root}/legumes/patates.beancount"
                  2014-01-01 open Assets:Apples
                """,
                'fruits/oranges.beancount': """
                  include "../legumes/tomates.beancount"
                  2014-01-02 open Assets:Oranges
                """,
                'legumes/tomates.beancount': """
                  2014-01-03 open Assets:Tomates
                """,
                'legumes/patates.beancount': """
                  2014-01-04 open Assets:Patates
                """})
            entries, errors, options_map = loader.load_file(
                path.join(tmp, 'apples.beancount'))
        self.assertFalse(errors)
        self.assertEqual(4, len(entries))
        self.assertEqual(['apples.beancount', 'oranges.beancount',
                          'patates.beancount', 'tomates.beancount'],
                         list(map(path.basename, options_map['include'])))

    def test_load_file_with_duplicate_includes(self):
        with test_utils.tempdir() as tmp:
            test_utils.create_temporary_files(tmp, {
                'apples.beancount': """
                  include "fruits/oranges.beancount"
                  include "{root}/legumes/tomates.beancount"
                  2014-01-01 open Assets:Apples
                """,
                'fruits/oranges.beancount': """
                  include "../legumes/tomates.beancount"
                  2014-01-02 open Assets:Oranges
                """,
                'legumes/tomates.beancount': """
                  2014-01-03 open Assets:Tomates
                """,
                'legumes/patates.beancount': """
                  2014-01-04 open Assets:Patates
                """})
            entries, errors, options_map = loader.load_file(
                path.join(tmp, 'apples.beancount'))
        self.assertTrue(errors)
        self.assertEqual(3, len(entries))
        self.assertEqual(['apples.beancount', 'oranges.beancount', 'tomates.beancount'],
                         list(map(path.basename, options_map['include'])))

    def test_load_string_with_relative_include(self):
        with test_utils.tempdir() as tmp:
            test_utils.create_temporary_files(tmp, {
                'apples.beancount': """
                  include "fruits/oranges.beancount"
                  2014-01-01 open Assets:Apples
                """,
                'fruits/oranges.beancount': """
                  2014-01-02 open Assets:Oranges
                """})
            try:
                cwd = os.getcwd()
                os.chdir(tmp)
                entries, errors, options_map = loader.load_file(
                    path.join(tmp, 'apples.beancount'))
            finally:
                os.chdir(cwd)
        self.assertFalse(errors)
        self.assertEqual(2, len(entries))
        self.assertEqual(['apples.beancount', 'oranges.beancount'],
                         list(map(path.basename, options_map['include'])))

    def test_load_file_return_include_filenames(self):
        # Also check that they are normalized paths.
        with test_utils.tempdir() as tmp:
            test_utils.create_temporary_files(tmp, {
                'apples.beancount': """
                  include "oranges.beancount"
                  2014-01-01 open Assets:Apples
                """,
                'oranges.beancount': """
                  include "bananas.beancount"
                  2014-01-02 open Assets:Oranges
                """,
                'bananas.beancount': """
                  2014-01-02 open Assets:Bananas
                """})
            entries, errors, options_map = loader.load_file(
                path.join(tmp, 'apples.beancount'))
        self.assertFalse(errors)
        self.assertEqual(3, len(entries))
        self.assertTrue(all(path.isabs(filename)
                            for filename in options_map['include']))
        self.assertEqual(['apples.beancount', 'bananas.beancount', 'oranges.beancount'],
                         list(map(path.basename, options_map['include'])))


class TestLoadCache(unittest.TestCase):

    def setUp(self):
        self.num_calls = 0
        mock.patch('beancount.loader._load_file',
                   loader.pickle_cache_function(loader.PICKLE_CACHE_FILENAME,
                                                0,  # No time threshold.
                                                self._load_file)).start()
    def tearDown(self):
        mock.patch.stopall()

    def _load_file(self, filename, *args, **kw):
        self.num_calls += 1
        return loader._load([(filename, True)], *args, **kw)

    def test_load_cache(self):
        # Create an initial set of files and load file, thus creating a cache.
        with test_utils.tempdir() as tmp:
            test_utils.create_temporary_files(tmp, {
                'apples.beancount': """
                  include "oranges.beancount"
                  2014-01-01 open Assets:Apples
                """,
                'oranges.beancount': """
                  include "bananas.beancount"
                  2014-01-02 open Assets:Oranges
                """,
                'bananas.beancount': """
                  2014-01-02 open Assets:Bananas
                """})
            top_filename = path.join(tmp, 'apples.beancount')
            other_filename = path.join(tmp, 'bananas.beancount')
            entries, errors, options_map = loader.load_file(top_filename)
            self.assertFalse(errors)
            self.assertEqual(3, len(entries))
            self.assertEqual(1, self.num_calls)

            # Make sure the cache was created.
            self.assertTrue(path.exists(path.join(tmp, '.apples.beancount.picklecache')))

            # Load the root file again, make sure the cache is being hit.
            entries, errors, options_map = loader.load_file(top_filename)
            self.assertEqual(1, self.num_calls)

            # Touch the top-level file and ensure it's a cache miss.
            with open(top_filename, 'a') as file:
                file.write('\n')
            entries, errors, options_map = loader.load_file(top_filename)
            self.assertEqual(2, self.num_calls)

            # Load the root file again, make sure the cache is being hit.
            entries, errors, options_map = loader.load_file(top_filename)
            self.assertEqual(2, self.num_calls)

            # Touch the top-level file and ensure it's a cache miss.
            with open(top_filename, 'a') as file:
                file.write('\n')
            entries, errors, options_map = loader.load_file(top_filename)
            self.assertEqual(3, self.num_calls)

    def test_load_cache_moved_file(self):
        # Create an initial set of files and load file, thus creating a cache.
        with test_utils.tempdir() as tmp:
            test_utils.create_temporary_files(tmp, {
                'apples.beancount': """
                  include "oranges.beancount"
                  2014-01-01 open Assets:Apples
                """,
                'oranges.beancount': """
                  2014-01-02 open Assets:Oranges
                """})
            top_filename = path.join(tmp, 'apples.beancount')
            entries, errors, options_map = loader.load_file(top_filename)
            self.assertFalse(errors)
            self.assertEqual(2, len(entries))
            self.assertEqual(1, self.num_calls)

            # Make sure the cache was created.
            self.assertTrue(path.exists(path.join(tmp, '.apples.beancount.picklecache')))

            # CHeck that it doesn't need refresh
            self.assertFalse(loader.needs_refresh(options_map))

            # Move the input file.
            new_top_filename = path.join(tmp, 'bigapples.beancount')
            os.rename(top_filename, new_top_filename)

            # Check that it needs refresh.
            self.assertTrue(loader.needs_refresh(options_map))

            # Load the root file again, make sure the cache is being hit.
            entries, errors, options_map = loader.load_file(top_filename)
            self.assertEqual(2, self.num_calls)


class TestEncoding(unittest.TestCase):

    def test_string_unicode(self):
        utf8_bytes = textwrap.dedent("""
          2015-01-01 open Assets:Something
          2015-05-23 note Assets:Something "¡¢£¤¥¦§¨©ª«¬®¯°±²³´µ¶·¸¹º»¼ "
        """).encode('utf-8')
        entries, errors, options_map = loader.load_string(utf8_bytes, encoding='utf8')
        self.assertFalse(errors)

    def test_string_latin1(self):
        utf8_bytes = textwrap.dedent("""
          2015-01-01 open Assets:Something
          2015-05-23 note Assets:Something "¡¢£¤¥¦§¨©ª«¬®¯°±²³´µ¶·¸¹º»¼ "
        """).encode('latin1')
        entries, errors, options_map = loader.load_string(utf8_bytes, encoding='latin1')
        self.assertFalse(errors)


class TestOptionsAggregation(unittest.TestCase):

    def test_aggregate_operating_currencies(self):
        with test_utils.tempdir() as tmp:
            test_utils.create_temporary_files(tmp, {
                'apples.beancount': """
                  include "oranges.beancount"
                  include "bananas.beancount"
                  option "operating_currency" "USD"
                """,
                'oranges.beancount': """
                  option "operating_currency" "CAD"
                """,
                'bananas.beancount': """
                  option "operating_currency" "EUR"
                """})
            top_filename = path.join(tmp, 'apples.beancount')
            other_filename = path.join(tmp, 'bananas.beancount')
            entries, errors, options_map = loader.load_file(top_filename)

            self.assertEqual({'USD', 'EUR', 'CAD'}, set(options_map['operating_currency']))

    def test_aggregate_commodities(self):
        with test_utils.tempdir() as tmp:
            test_utils.create_temporary_files(tmp, {
                'apples.beancount': """
                  include "oranges.beancount"
                  include "bananas.beancount"
                  option "operating_currency" "USD"
                """,
                'oranges.beancount': """
                  2015-12-12 open Assets:CA:Checking  CAD
                """,
                'bananas.beancount': """
                  2015-12-13 open Assets:FR:Checking  EUR
                """})
            top_filename = path.join(tmp, 'apples.beancount')
            other_filename = path.join(tmp, 'bananas.beancount')
            entries, errors, options_map = loader.load_file(top_filename)

            self.assertEqual({'EUR', 'CAD'}, options_map['commodities'])
