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
"""SystemBuildDisk creates the disk file and attaches it to a loop device.
truncate/losetup/cp are mocked at the subprocess boundary; losetup's stdout
arrives as bytes exactly as it does from the real check_output."""
import types
from unittest import mock

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.SystemBuildDisk import SystemBuildDisk
from tests.helpers import FakePaths, SubprocessTestCase, new_module

KEY = '__SystemBuild_demo__'
DISK = '/images/root.img'


class DiskTestCase(SubprocessTestCase):

    def setUp(self):
        SubprocessTestCase.setUp(self)
        self.sp.on('losetup', '--show', '-f', stdout=b'/dev/loop7\n')
        self.system = {
            'system': types.SimpleNamespace(
                _getSizeInBytes=lambda size: 1 << 30),
            'cleanup_methods': [],
        }
        self.module = new_module(SystemBuildDisk, log=self.log,
                                 env={KEY: self.system})
        self.paths = FakePaths(self, exists=[])

    def options(self, **extra):
        options = {'system': 'demo', 'disk-name': 'root',
                   'disk-file': DISK, 'size': '1G'}
        options.update(extra)
        return options


class TestSetupDiskBuild(DiskTestCase):

    def test_setup_disk_build_truncates_then_attaches_loop_device(self):
        disk = self.module.build(self.options())
        self.assertEqual(self.sp.all_cmds(), [
            ['truncate', '-s', '1G', DISK],
            ['losetup', '--show', '-f', DISK]])
        self.assertEqual(disk, {
            'path': DISK, 'real': True, 'size': 1 << 30,
            'device': '/dev/loop7', 'fstab-id': '/dev/sda', 'number': 0})
        self.assertEqual(self.log.results, ['passed'])

    def test_setup_disk_losetup_output_is_decoded_to_a_clean_str(self):
        self.sp.on('losetup', stdout=b'  /dev/loop12 \n')
        disk = self.module.build(self.options())
        self.assertEqual(disk['device'], '/dev/loop12')
        self.assertIsInstance(disk['device'], str)
        # the fake check_output returns bytes unless a text mode was asked
        # for, so reaching a str here means the module decoded it itself
        losetup = self.sp.find('losetup')[0]
        self.assertNotIn('universal_newlines', losetup.kwargs)
        self.assertNotIn('text', losetup.kwargs)

    def test_setup_disk_second_disk_gets_next_designation_and_number(self):
        self.module.build(self.options())
        second = self.module.build(self.options(**{'disk-name': 'data'}))
        self.assertEqual((second['number'], second['fstab-id']), (1, '/dev/sdb'))

    def test_setup_disk_build_removes_an_existing_disk_file_first(self):
        self.paths.exists.add(DISK)
        with mock.patch('os.remove') as remove:
            self.module.build(self.options())
        remove.assert_called_once_with(DISK)
        self.assertEqual(len(self.log.messages('warning')), 1)

    def test_setup_disk_non_ascii_path_is_passed_through_unchanged(self):
        path = '/images/dísk-中.img'
        self.module.build(self.options(**{'disk-file': path}))
        self.assertEqual(self.sp.cmds('losetup')[0][-1], path)

    def test_setup_disk_registers_the_full_cleanup(self):
        self.module.build(self.options())
        self.assertEqual(self.system['cleanup_methods'], [self.module._cleanup])

    def test_setup_disk_truncate_failure_fails_before_attaching(self):
        self.sp.on('truncate', rc=1)
        self.assertIsNone(self.module.build(self.options()))
        self.assertEqual(self.log.results, ['failed'])
        self.assertEqual(self.sp.cmds('losetup'), [])
        self.assertEqual(self.system['disks'], {})

    def test_setup_disk_losetup_failure_fails_and_registers_nothing(self):
        self.sp.on('losetup', rc=1)
        self.assertIsNone(self.module.build(self.options()))
        self.assertEqual(self.log.results, ['failed'])
        self.assertEqual(self.system['disks'], {})
        self.assertEqual(self.system['cleanup_methods'], [])

    def test_setup_disk_undefined_system_fails(self):
        self.module.env.env.clear()
        self.assertIsNone(self.module.build(self.options()))
        self.assertEqual(self.log.results, ['failed'])
        self.assertEqual(self.sp.calls, [])

    def test_setup_disk_duplicate_name_fails(self):
        self.module.build(self.options())
        self.sp.calls.clear()
        self.log.results.clear()
        self.assertIsNone(self.module.build(self.options()))
        self.assertEqual(self.log.results, ['failed'])
        self.assertEqual(self.sp.calls, [])


class TestSetupDiskUse(DiskTestCase):

    def test_use_system_build_only_attaches_the_existing_file(self):
        disk = self.module.use_system_build(self.options())
        self.assertEqual(self.sp.all_cmds(), [['losetup', '--show', '-f', DISK]])
        self.assertEqual(disk['device'], '/dev/loop7')
        self.assertEqual(self.system['cleanup_methods'],
                         [self.module._cleanupUse])


class TestDiskCleanup(DiskTestCase):

    def setUp(self):
        DiskTestCase.setUp(self)
        self.module.build(self.options())
        self.sp.calls.clear()
        self.log.records.clear()

    def test_cleanup_use_detaches_the_device_and_forgets_the_disk(self):
        self.module._cleanupUse()
        self.assertEqual(self.sp.all_cmds(), [
            ['losetup', '-d', '/dev/loop7'],
            ['ioctl', '/dev/loop7', '19457']])
        self.assertNotIn('root', self.system['disks'])

    def test_cleanup_use_detach_failure_is_a_warning_not_an_error(self):
        self.sp.on('losetup', '-d', rc=1)
        self.module._cleanupUse()
        self.assertEqual(len(self.log.messages('warning')), 1)
        self.assertNotIn('root', self.system['disks'])

    def test_cleanup_use_unknown_disk_does_nothing(self):
        self.system['disks'].clear()
        self.module._cleanupUse()
        self.assertEqual(self.sp.calls, [])

    def test_cleanup_create_resparsifies_by_copy_and_move(self):
        self.module._cleanupCreate()
        self.assertEqual(self.sp.all_cmds(), [
            ['cp', '--sparse=always', DISK, DISK + '.save'],
            ['mv', DISK + '.save', DISK]])

    def test_cleanup_create_copy_failure_skips_the_move(self):
        self.sp.on('cp', rc=1)
        self.module._cleanupCreate()
        self.assertEqual(self.sp.cmds('mv'), [])
        self.assertEqual(len(self.log.messages('warning')), 1)

    def test_cleanup_runs_use_cleanup_before_create_cleanup(self):
        self.module._cleanup()
        names = [cmd[0] for cmd in self.sp.all_cmds()]
        # create cleanup finds no disk any more because use cleanup removed it
        self.assertEqual(names, ['losetup', 'ioctl'])

    def test_clean_removes_the_disk_file(self):
        with mock.patch('os.remove') as remove:
            self.module.clean(self.options())
        remove.assert_called_once_with(DISK)
        self.assertEqual(self.log.results[-1], 'passed')

    def test_clean_remove_failure_is_logged_and_still_passes(self):
        with mock.patch('os.remove', side_effect=OSError('busy')):
            self.module.clean(self.options())
        self.assertEqual(len(self.log.messages('exception')), 1)
        self.assertEqual(self.log.results[-1], 'passed')
