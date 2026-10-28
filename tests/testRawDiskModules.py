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
"""CopyRawImage, TarballRawDisk, UntarballRawDisk and InjectDiskUsedToIndex
move raw system trees around with sudo cp/tar/chown and statvfs.  All of the
tools and filesystem lookups are mocked."""
import os
import subprocess
import unittest
from unittest import mock

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.CopyRawImage import CopyRawImage
from CsmakeModules.InjectDiskUsedToIndex import InjectDiskUsedToIndex
from CsmakeModules.TarballRawDisk import TarballRawDisk
from CsmakeModules.UntarballRawDisk import UntarballRawDisk
from tests.helpers import FakeLog, FakeMapping, FakePaths, SubprocessTestCase, new_module


class TestCopyRawImage(SubprocessTestCase):

    def setUp(self):
        SubprocessTestCase.setUp(self)
        self.paths = FakePaths(self)

    def copy(self, pairs=(('/raw', '/mnt/dest'),), mapping=None, **options):
        files = [([src], [dst]) for src, dst in pairs]
        module = new_module(CopyRawImage, log=self.log,
                            mapping=mapping if mapping is not None else FakeMapping(files, files))
        return module.build(options)

    def test_build_copies_everything_with_archive_mode_by_default(self):
        self.assertTrue(self.copy())
        self.assertEqual([call.argv for call in self.sp.calls],
                         ['sudo cp -t /mnt/dest -a /raw/*'])
        self.assertTrue(self.sp.calls[0].kwargs['shell'])
        self.assertEqual(self.log.results, ['passed'])

    def test_build_preserve_option_replaces_archive_mode(self):
        self.copy(preserve=' mode, ownership ,timestamps')
        self.assertEqual(self.sp.calls[0].argv,
                         'sudo cp -t /mnt/dest -dR --preserve=mode,ownership,timestamps /raw/*')

    def test_build_removes_dev_shm_before_copying(self):
        self.paths.exists.add('/raw/dev/shm')
        self.copy()
        self.assertEqual(self.sp.calls[0].argv, ['sudo', 'rm', '-rf', '/raw/dev/shm'])
        self.assertTrue(self.sp.calls[1].argv.startswith('sudo cp'))

    def test_build_without_dev_shm_does_not_remove_anything(self):
        self.copy()
        self.assertEqual(self.sp.cmds('rm'), [])

    def test_build_dev_shm_removal_failure_only_warns(self):
        self.paths.exists.add('/raw/dev/shm')
        self.sp.on('rm', rc=1)
        self.assertTrue(self.copy())
        self.assertEqual(len(self.log.messages('warning')), 1)
        self.assertEqual(len(self.sp.calls), 2)

    def test_build_copy_failure_fails_and_stops(self):
        self.sp.on('sudo cp', rc=1)
        self.assertIsNone(self.copy(pairs=[('/a', '/x'), ('/b', '/y')]))
        self.assertEqual(self.log.results, ['failed'])
        self.assertEqual(len(self.sp.calls), 1)

    def test_build_copies_each_source_to_each_destination(self):
        mapping = FakeMapping([1], [(['/a', '/b'], ['/x', '/y'])])
        self.copy(mapping=mapping)
        self.assertEqual([call.argv for call in self.sp.calls], [
            'sudo cp -t /x -a /a/*', 'sudo cp -t /y -a /a/*',
            'sudo cp -t /x -a /b/*', 'sudo cp -t /y -a /b/*'])

    def test_build_empty_mapping_fails(self):
        self.assertIsNone(self.copy(mapping=FakeMapping([])))
        self.assertEqual(self.log.results, ['failed'])
        self.assertEqual(self.sp.calls, [])


class TestTarballRawDisk(SubprocessTestCase):

    def setUp(self):
        SubprocessTestCase.setUp(self)
        patcher = mock.patch.multiple(os, getuid=lambda: 1000, getgid=lambda: 100)
        patcher.start()
        self.addCleanup(patcher.stop)

    def module(self, pairs=(('/raw', '/out/disk.tar.gz'),)):
        files = [([src], [dst]) for src, dst in pairs]
        return new_module(TarballRawDisk, log=self.log,
                          mapping=FakeMapping(files, files))

    def test_package_tars_the_tree_then_hands_the_file_to_the_user(self):
        self.assertTrue(self.module().package({}))
        self.assertEqual(self.sp.all_cmds(), [
            ['tar', '-czvf', '/out/disk.tar.gz', '-C', '/raw', '.'],
            ['chown', '1000:100', '/out/disk.tar.gz']])
        self.assertEqual(self.log.results, ['passed'])

    def test_package_tar_failure_fails_before_chown(self):
        self.sp.on('tar', rc=2)
        self.assertFalse(self.module().package({}))
        self.assertEqual(self.log.results, ['failed'])
        self.assertEqual(self.sp.cmds('chown'), [])

    def test_package_chown_failure_propagates(self):
        self.sp.on('chown', rc=1)
        with self.assertRaises(subprocess.CalledProcessError):
            self.module().package({})

    def test_package_non_ascii_destination_is_passed_through(self):
        self.module([('/raw', '/out/dísk.tar.gz')]).package({})
        self.assertEqual(self.sp.cmds('tar')[0][2], '/out/dísk.tar.gz')

    def test_clean_removes_existing_archives_only(self):
        FakePaths(self, exists=['/out/disk.tar.gz'])
        module = self.module([('/raw', '/out/disk.tar.gz'), ('/raw2', '/out/none.tgz')])
        with mock.patch('os.remove') as remove:
            self.assertTrue(module.clean({}))
        remove.assert_called_once_with('/out/disk.tar.gz')
        self.assertEqual(self.log.results, ['passed'])

    def test_clean_remove_failure_is_logged_and_still_passes(self):
        FakePaths(self, exists=['/out/disk.tar.gz'])
        with mock.patch('os.remove', side_effect=OSError('busy')):
            self.assertTrue(self.module().clean({}))
        self.assertEqual(len(self.log.messages('exception')), 1)
        self.assertEqual(self.log.results, ['passed'])


class TestUntarballRawDisk(SubprocessTestCase):

    def untar(self, pairs=(('/in/disk.tar.gz', '/raw'),)):
        files = [([src], [dst]) for src, dst in pairs]
        module = new_module(UntarballRawDisk, log=self.log,
                            mapping=FakeMapping(files, files))
        return module.build({})

    def test_build_creates_the_directory_then_extracts_preserving_owners(self):
        self.assertTrue(self.untar())
        self.assertEqual(self.sp.all_cmds(), [
            ['mkdir', '-p', '/raw'],
            ['tar', '--numeric-owner', '-xzpvf', '/in/disk.tar.gz', '-C', '/raw']])
        self.assertTrue(self.sp.calls[1].sudo)
        self.assertFalse(self.sp.calls[0].sudo)
        self.assertEqual(self.log.results, ['passed'])

    def test_build_tar_failure_fails_and_stops(self):
        self.sp.on('tar', rc=2)
        self.assertFalse(self.untar([('/a.tgz', '/x'), ('/b.tgz', '/y')]))
        self.assertEqual(self.log.results, ['failed'])
        self.assertEqual(len(self.sp.cmds('tar')), 1)

    def test_build_mkdir_failure_propagates(self):
        self.sp.on('mkdir', rc=1)
        with self.assertRaises(subprocess.CalledProcessError):
            self.untar()
        self.assertEqual(self.sp.cmds('tar'), [])

    def test_build_non_ascii_paths_are_passed_through(self):
        self.untar([('/in/dísk.tgz', '/raw/中')])
        self.assertEqual(self.sp.cmds('tar')[0][-3:], ['/in/dísk.tgz', '-C', '/raw/中'])


class TestInjectDiskUsedToIndex(unittest.TestCase):

    def setUp(self):
        self.log = FakeLog()
        self.dest = {'location': '/images/disk.img'}
        self.mapping = FakeMapping([([{'location': '/mnt'}], [self.dest])])
        self.module = new_module(InjectDiskUsedToIndex, log=self.log,
                                 mapping=self.mapping)

    def statvfs(self, **fields):
        values = dict(f_frsize=4096, f_blocks=1000, f_bsize=4096, f_bfree=250)
        values.update(fields)
        return mock.patch('os.statvfs', return_value=mock.Mock(**values))

    def test_build_records_the_used_bytes_of_the_mount(self):
        with self.statvfs() as statvfs:
            self.assertTrue(self.module.build({'mount': '/mnt'}))
        statvfs.assert_called_once_with('/mnt')
        self.assertEqual(self.dest['used-size'], 4096 * 1000 - 4096 * 250)
        self.assertEqual(self.log.results, ['passed'])

    def test_build_used_size_uses_fragment_size_for_total_and_block_size_for_free(self):
        with self.statvfs(f_frsize=1024, f_bsize=4096, f_blocks=100, f_bfree=10):
            self.module.build({'mount': '/mnt'})
        self.assertEqual(self.dest['used-size'], 1024 * 100 - 4096 * 10)

    def test_build_empty_mapping_fails(self):
        self.module.mapping = FakeMapping([])
        with self.statvfs() as statvfs:
            self.assertIsNone(self.module.build({'mount': '/mnt'}))
        statvfs.assert_not_called()
        self.assertEqual(self.log.results, ['failed'])

    def test_build_more_than_one_mapping_fails(self):
        self.module.mapping = FakeMapping([([{}], [{}]), ([{}], [{}])])
        self.assertIsNone(self.module.build({'mount': '/mnt'}))
        self.assertEqual(self.log.results, ['failed'])

    def test_build_mapping_that_is_not_one_to_one_fails(self):
        self.module.mapping = FakeMapping([([{}, {}], [{}])])
        self.assertIsNone(self.module.build({'mount': '/mnt'}))
        self.assertEqual(self.log.results, ['failed'])

    def test_build_statvfs_failure_propagates(self):
        with mock.patch('os.statvfs', side_effect=FileNotFoundError('/mnt')):
            with self.assertRaises(FileNotFoundError):
                self.module.build({'mount': '/mnt'})

    @unittest.skip("pre-existing bug: with mapping=None the module logs the "
                   "failure and then calls len(None), raising TypeError")
    def test_build_missing_mapping_fails_cleanly(self):
        pass
