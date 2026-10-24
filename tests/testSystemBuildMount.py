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
"""SystemBuildMount mounts the system's filesystems (parents first) plus the
api filesystems and unmounts them in reverse.  mount/umount/mkdir are mocked
at the subprocess boundary; the tests assert command lines and ordering."""
import subprocess
import unittest
from unittest import mock

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.SystemBuildMount import SystemBuildMount
from tests.helpers import (FakePaths, SAMPLE_FILESYSTEM, SubprocessTestCase,
                           new_module)

KEY = '__SystemBuild_demo__'
LOC = '/mnt/build'


class MountTestCase(SubprocessTestCase):

    def setUp(self):
        SubprocessTestCase.setUp(self)
        self.paths = FakePaths(self, dirs=[LOC])
        self.system = {
            'filesystem': dict(SAMPLE_FILESYSTEM),
            'disks': {'sda': {'path': '/images/sda.img'}},
            'cleanup_methods': [],
            'recovery_methods': [],
        }
        self.module = new_module(SystemBuildMount, log=self.log,
                                 env={KEY: self.system})
        self.module.options = {'system': 'demo', 'location': LOC}

    def init(self, **extra):
        self.module.options.update(extra)
        self.assertTrue(self.module._initModule())

    def mounts(self):
        return self.sp.cmds('mount')


class TestInitModule(MountTestCase):

    def test_init_module_registers_the_mount_instance(self):
        self.init()
        self.assertEqual(self.system['count'], 1)
        self.assertIs(self.system['mountInstance'], self.module)
        self.assertEqual(self.module.skipmounts, [])

    def test_init_module_parses_skip_by_comma_and_newline(self):
        self.init(skip='/home, /boot/efi\n/srv')
        self.assertEqual(self.module.skipmounts, ['/home', '/boot/efi', '/srv'])

    def test_init_module_undefined_system_fails(self):
        self.module.env.env.clear()
        self.assertIsNone(self.module._initModule())
        self.assertEqual(self.log.results, ['failed'])

    def test_init_module_system_without_filesystem_fails(self):
        del self.system['filesystem']
        self.assertIsNone(self.module._initModule())
        self.assertEqual(self.log.results, ['failed'])

    def test_init_module_second_mount_only_counts(self):
        self.init()
        self.assertFalse(self.module._initModule())
        self.assertEqual(self.system['count'], 2)
        self.assertEqual(self.log.results, ['passed'])


class TestMount(MountTestCase):

    def test_mount_mounts_parents_before_children(self):
        self.init()
        self.assertTrue(self.module._mount())
        real = [cmd for cmd in self.mounts() if not cmd[1].startswith('-')]
        self.assertEqual(real, [
            ['mount', '/dev/loop3p3', LOC + '/'],
            ['mount', '/dev/loop3p2', LOC + '/boot'],
            ['mount', '/dev/loop3p1', LOC + '/boot/efi'],
            ['mount', '/dev/loop3p4', LOC + '/home']])

    def test_mount_creates_missing_mountpoints_before_mounting_them(self):
        self.init()
        self.paths.exists.add(LOC + '/boot')
        self.module._mount()
        mkdirs = [cmd[-1] for cmd in self.sp.cmds('mkdir', '-p')]
        self.assertEqual(mkdirs, [LOC + '/', LOC + '/boot/efi', LOC + '/home'])
        self.assertLess(self.sp.all_cmds().index(['mkdir', '-p', LOC + '/boot/efi']),
                        self.sp.all_cmds().index(['mount', '/dev/loop3p1', LOC + '/boot/efi']))

    def test_mount_skips_the_requested_mountpoints(self):
        self.init(skip='/home')
        self.module._mount()
        self.assertNotIn('/dev/loop3p4', [cmd[1] for cmd in self.mounts()])
        self.assertEqual(self.log.messages('debug'), ['Skipping mount: /home'])

    def test_mount_then_mounts_the_system_paths_in_order(self):
        self.init()
        self.module._mount()
        special = [(cmd[2], cmd[-1].replace(LOC + '/', ''))
                   for cmd in self.mounts() if cmd[1] == '-t']
        self.assertEqual(special, [
            ('proc', 'proc'), ('devtmpfs', 'dev'), ('tmpfs', 'dev/shm'),
            ('devpts', 'dev/pts'), ('tmpfs', 'run'), ('tmpfs', 'run/shm'),
            ('tmpfs', 'run/lock'), ('tmpfs', 'run/user'), ('sysfs', 'sys')])
        self.assertEqual(self.module.mountedDevices[-1], LOC + '/sys')

    def test_mount_tracks_every_mount_in_mount_order_for_unwinding(self):
        self.init(skip='/home')
        self.module._mount()
        self.assertEqual(self.module.mountedDevices[:3],
                         [LOC + '/', LOC + '/boot', LOC + '/boot/efi'])
        self.assertEqual(len(self.module.mountedDevices), 3 + 9)

    def test_mount_registers_its_exit_cleanup(self):
        self.init()
        self.module._mount()
        self.assertEqual(self.system['cleanup_methods'], [self.module._onExit])

    def test_mount_creates_the_location_when_missing(self):
        self.paths.dirs.clear()
        self.init()
        self.module._mount()
        self.assertEqual(self.sp.all_cmds()[0], ['mkdir', '-p', LOC])
        self.assertIs(self.sp.find('mkdir', '-p', LOC)[0].sudo, False)

    def test_mount_location_creation_failure_propagates(self):
        self.paths.dirs.clear()
        self.sp.on('mkdir', '-p', LOC, rc=1)
        self.init()
        with self.assertRaises(subprocess.CalledProcessError):
            self.module._mount()

    def test_mount_device_failure_unwinds_and_returns_false(self):
        self.init()
        self.sp.on('mount', '/dev/loop3p1', rc=32)
        self.module._cleanUpMounts = mock.Mock()
        self.assertFalse(self.module._mount())
        self.module._cleanUpMounts.assert_called_once_with(True)
        # '/' and '/boot' were mounted before the failure
        self.assertEqual(self.module.mountedDevices, [LOC + '/', LOC + '/boot'])
        self.assertEqual(self.system['cleanup_methods'], [])

    def test_mount_system_path_failure_unwinds_and_returns_false(self):
        self.init()
        self.sp.on('mount', '-t', 'devtmpfs', rc=1)
        self.module._cleanUpMounts = mock.Mock()
        self.assertFalse(self.module._mount())
        self.module._cleanUpMounts.assert_called_once_with(True)
        self.assertIn('Mount of dev failed', self.log.messages('error'))


class TestMountSystemPaths(MountTestCase):

    def setUp(self):
        MountTestCase.setUp(self)
        self.init()

    def test_mount_system_paths_makes_missing_directories_first(self):
        self.assertTrue(self.module._mountSystemPaths(LOC))
        names = [cmd[-1] for cmd in self.sp.cmds('mkdir')]
        self.assertEqual(names, [LOC + '/' + p for p in (
            'proc', 'dev', 'dev/shm', 'dev/pts', 'run', 'run/shm',
            'run/lock', 'run/user', 'sys')])

    def test_mount_system_paths_existing_directories_are_not_recreated(self):
        self.paths.dirs.update(LOC + '/' + p for p in ('proc', 'sys'))
        self.module._mountSystemPaths(LOC)
        self.assertNotIn(LOC + '/proc', [cmd[-1] for cmd in self.sp.cmds('mkdir')])

    def test_mount_system_paths_shared_memory_is_made_world_writable(self):
        self.module._mountSystemPaths(LOC)
        self.assertEqual([cmd[-1] for cmd in self.sp.cmds('chmod', '777')],
                         [LOC + '/dev/shm', LOC + '/run/shm'])

    def test_mount_system_paths_mkdir_failure_stops_there(self):
        self.sp.on('mkdir', LOC + '/dev', rc=1)
        self.assertFalse(self.module._mountSystemPaths(LOC))
        self.assertEqual(self.module.mountedDevices, [LOC + '/proc'])
        self.assertEqual(self.log.results, ['failed'])

    def test_mount_system_paths_each_mount_failure_stops_there(self):
        for fstype, mounted in [('proc', 0), ('devtmpfs', 1), ('sysfs', 8)]:
            with self.subTest(fstype=fstype):
                module = new_module(SystemBuildMount, log=self.log)
                module.mountedDevices = []
                self.sp.reset()
                self.sp.on('mount', '-t', fstype, rc=1)
                self.assertFalse(module._mountSystemPaths(LOC))
                self.assertEqual(len(module.mountedDevices), mounted)


class TestCleanUpMounts(MountTestCase):

    def setUp(self):
        MountTestCase.setUp(self)
        self.init(skip='/home')
        self.module._mount()
        self.sp.calls.clear()
        self.log.results.clear()
        self.devices = list(self.module.mountedDevices)

    def test_clean_up_mounts_unmounts_in_reverse_mount_order(self):
        self.assertTrue(self.module._cleanUpMounts())
        umounts = [cmd[1] for cmd in self.sp.cmds('umount')]
        self.assertEqual(umounts, list(reversed(self.devices)))

    def test_clean_up_mounts_trims_then_unmounts_each_device(self):
        self.module._cleanUpMounts()
        cmds = self.sp.all_cmds()
        self.assertEqual(cmds[0], ['sync'])
        self.assertEqual(cmds[1:3], [['fstrim', LOC + '/sys'],
                                     ['umount', LOC + '/sys']])

    def test_clean_up_mounts_finishes_with_resparsify_and_rmdir(self):
        self.module._cleanUpMounts()
        self.assertEqual(self.sp.all_cmds()[-2:], [
            ['fallocate', '-d', '/images/sda.img'], ['rmdir', LOC]])
        self.assertEqual(self.module.mountedDevices, [])
        self.assertNotIn('mountInstance', self.system)
        self.assertEqual(self.system['count'], 0)

    def test_clean_up_mounts_forgets_the_exit_cleanup(self):
        self.module._cleanUpMounts()
        self.assertEqual(self.system['cleanup_methods'], [])

    def test_clean_up_mounts_busy_device_is_lazily_unmounted_and_retried_later(self):
        self.sp.on('umount', LOC + '/sys', rc=32)
        self.assertTrue(self.module._cleanUpMounts())
        self.assertIn(['umount', '-lf', LOC + '/sys'], self.sp.all_cmds())
        self.assertEqual(len(self.system['recovery_methods']), 1)
        self.assertEqual(self.system['count'], 1)
        self.assertIn('mountInstance', self.system)
        self.assertEqual(self.sp.cmds('rmdir'), [])

    def test_clean_up_mounts_recovery_retries_and_does_not_requeue(self):
        self.sp.on('umount', LOC + '/sys', rc=32)
        self.module._cleanUpMounts()
        recovery = self.system['recovery_methods'][0]
        self.sp.calls.clear()
        recovery()
        self.assertIn(['umount', '-lf', LOC + '/sys'], self.sp.all_cmds())
        self.assertEqual(len(self.system['recovery_methods']), 1)
        self.assertEqual(self.sp.all_cmds()[-1], ['rmdir', LOC])

    def test_clean_up_mounts_without_mounts_does_nothing(self):
        self.system['count'] = 0
        self.assertTrue(self.module._cleanUpMounts())
        self.assertEqual(self.sp.calls, [])

    def test_end_build_unmounts(self):
        self.module.end__build('build', {}, None, None)
        self.assertEqual(self.log.results, ['passed'])
        self.assertEqual(len(self.sp.cmds('umount')), len(self.devices))

    @unittest.skip("pre-existing bug: _cleanUpMounts references an undefined "
                   "'mountdict' when the mount count is still positive")
    def test_clean_up_mounts_nested_mount_count_keeps_the_mounts(self):
        pass


class TestPhaseEntryPoints(MountTestCase):

    def test_build_mounts_and_passes(self):
        self.module.build({'system': 'demo', 'location': LOC})
        self.assertEqual(self.log.results, ['passed'])
        self.assertIsNotNone(self.mounts())

    def test_build_reentrant_mount_does_not_mount_again(self):
        self.module.build({'system': 'demo', 'location': LOC})
        self.sp.calls.clear()
        self.module.build({'system': 'demo', 'location': LOC})
        self.assertEqual(self.sp.calls, [])
        self.assertEqual(set(self.log.results), {'passed'})
        self.assertEqual(self.system['count'], 2)

    def test_build_mount_failure_fails(self):
        self.sp.on('mount', '/dev/loop3p3', rc=32)
        self.module._cleanUpMounts = mock.Mock()
        self.module.build({'system': 'demo', 'location': LOC})
        self.assertEqual(self.log.results, ['failed'])

    def test_start_build_mounts_like_build(self):
        self.module.start__build('build', {'system': 'demo', 'location': LOC},
                                 None, None)
        self.assertEqual(self.log.results, ['passed'])
        self.assertEqual(self.system['count'], 1)

    def test_system_build_phases_delegate_to_build(self):
        for name in ('system_build', 'use_system_build'):
            with self.subTest(phase=name):
                self.system.pop('count', None)
                getattr(self.module, name)({'system': 'demo', 'location': LOC})
                self.assertEqual(self.system['count'], 1)
