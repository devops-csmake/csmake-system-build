# <copyright>
# (c) Copyright 2026 Autumn Patterson
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the
# Free Software Foundation, either version 3 of the License, or (at your
# option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
# </copyright>
"""VersionedPackager derives the archive name from Packager's version
fields.  Packager's own bookkeeping lives in csmake core, so that one method
is stubbed to supply the name/version/result directory."""
import unittest
from unittest import mock

from tests import csmake_alias
csmake_alias.install()

try:
    # Packager lives in csmake core
    from CsmakeModules.Packager import Packager
    from CsmakeModules.VersionedPackager import VersionedPackager
except ImportError as importFailure:
    if not (importFailure.name or '').startswith(
            ('CsmakeModules.Packager', 'CsmakeCore')):
        raise
    raise unittest.SkipTest("csmake core's Packager is not importable: %s"
                            % importFailure)
from tests.helpers import FakeLog, new_module


def packager_stub(self):
    self.packageName = 'pkg'
    self.version = 'default-version'
    self.packageVersion = '3'
    self.resultdir = '/results'


class TestVersionedPackager(unittest.TestCase):

    def setUp(self):
        patcher = mock.patch.object(Packager, '_calculateFileNameAndVersioning',
                                    packager_stub)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.log = FakeLog()
        metadata = mock.Mock()
        metadata._parseVersionFormatString.side_effect = lambda fmt: 'v-' + fmt
        self.module = new_module(VersionedPackager, log=self.log,
                                 metadata=metadata)

    def calculate(self, **options):
        self.module.options = options
        self.module._calculateFileNameAndVersioning()
        return self.module

    def test_calculate_defaults_to_a_gzip_tarball_with_package_version(self):
        module = self.calculate(**{'package-version': '3'})
        self.assertEqual(module.fullVersion, 'default-version-3')
        self.assertEqual(module.archiveFileName, 'pkg-default-version-3.tar.gz')
        self.assertEqual(module.fullPathToArchive,
                         '/results/pkg-default-version-3.tar.gz')
        self.assertEqual((module.format, module.filetype), ('gzip', 'gz'))

    def test_calculate_bzip2_format(self):
        module = self.calculate(format='bzip2', **{'package-version': '3'})
        self.assertEqual(module.filetype, 'bz')
        self.assertTrue(module.archiveFileName.endswith('.tar.bz2'))

    def test_calculate_unknown_format_warns_and_falls_back_to_gzip(self):
        module = self.calculate(format='lzma', **{'package-version': '3'})
        self.assertEqual(module.format, 'gzip')
        self.assertTrue(module.archiveFileName.endswith('.tar.gz'))
        self.assertEqual(len(self.log.messages('warning')), 1)

    def test_calculate_extension_option_replaces_the_default(self):
        module = self.calculate(extension='tgz', **{'package-version': '3'})
        self.assertTrue(module.archiveFileName.endswith('.tgz'))

    def test_calculate_without_package_version_leaves_it_off(self):
        module = self.calculate()
        self.assertEqual(module.fullVersion, 'default-version')
        self.assertEqual(module.archiveFileName, 'pkg-default-version.tar.gz')

    def test_calculate_version_option_is_parsed_as_a_version_format(self):
        module = self.calculate(version='{major}', **{'package-version': '3'})
        self.assertEqual(module.fullVersion, 'v-{major}-3')

    def test_map_path_root_uses_a_top_level_directory_by_default(self):
        module = self.calculate(**{'package-version': '3'})
        pathmaps, keymaps = {}, {}
        module._map_path_root('root', pathmaps, keymaps)
        self.assertEqual(pathmaps, {'root': ['pkg-default-version-3']})
        self.assertEqual(keymaps, {'root': ['pkg-default-version-3']})

    def test_map_path_root_no_root_dir_uses_the_archive_top(self):
        module = self.calculate(**{'package-version': '3', 'no-root-dir': 'True'})
        pathmaps, keymaps = {}, {}
        module._map_path_root('root', pathmaps, keymaps)
        self.assertEqual(pathmaps, {'root': ['.']})
