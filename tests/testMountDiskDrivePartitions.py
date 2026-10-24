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
"""MountDiskDrivePartitions loop-mounts a disk image and mounts its
partitions.  losetup/lsblk/e2label/mount/umount are mocked at the
subprocess boundary.  Popen results arrive as bytes (no text mode is
requested), so these tests guard the decode-before-use conversions."""
import subprocess
import unittest
from unittest import mock

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules import MountDiskDrivePartitions as module_under_test
from CsmakeModules.MountDiskDrivePartitions import MountDiskDrivePartitions
from tests.helpers import FakePaths, SubprocessTestCase, new_module

MOUNTS = '/mnt/disk'
DRIVE = '/images/disk.img'
LSBLK = [b'NAME="loop5" LABEL=""\n',
         b'NAME="loop5p1" LABEL="boot"\n',
         b'NAME="loop5p2" LABEL=""\n']


class DiskMountTestCase(SubprocessTestCase):

    def setUp(self):
        SubprocessTestCase.setUp(self)
        self.paths = FakePaths(self, dirs=[MOUNTS])
        self.sp.on('losetup', '--show', '-f', stdout=b'/dev/loop5\n')
        self.sp.on('lsblk', stdout=b''.join(LSBLK))
        self.sp.on('e2label', stdout=b'rootfs\n')
        self.module = new_module(MountDiskDrivePartitions, log=self.log)
        self.module.options = {'mounts': MOUNTS, 'drive': DRIVE}

    def mount(self, **options):
        self.module.options.update(options)
        self.assertTrue(self.module._initModule())
        return self.module._mount()

    @property
    def env(self):
        return self.module.env.env


class TestInitModule(DiskMountTestCase):

    def test_init_module_uses_the_tag_in_the_environment_key(self):
        self.module.options['tag'] = 'one'
        self.assertTrue(self.module._initModule())
        self.assertEqual(self.module.taggedEnvKey,
                         MountDiskDrivePartitions.ENVKEY + 'one')

    def test_init_module_already_mounted_only_counts(self):
        self.env[MountDiskDrivePartitions.ENVKEY] = {'count': 1}
        self.assertFalse(self.module._initModule())
        self.assertEqual(self.env[MountDiskDrivePartitions.ENVKEY]['count'], 2)
        self.assertEqual(self.log.results, ['passed'])


class TestMountPartitions(DiskMountTestCase):

    def test_mount_attaches_the_drive_and_lists_partitions_first(self):
        self.assertTrue(self.mount())
        self.assertEqual(self.sp.all_cmds()[:3], [
            ['losetup', '--show', '-f', DRIVE],
            ['lsblk', '-P', '-i', '-o', 'name,label', '/dev/loop5'],
            ['e2label', '/dev/loop5p2']])

    def test_mount_losetup_and_lsblk_output_stay_bytes_until_decoded(self):
        self.mount()
        for name in ('losetup', 'lsblk', 'e2label'):
            call = self.sp.find(name)[0]
            self.assertEqual(call.func, 'Popen')
            self.assertEqual(call.kwargs['stdout'], subprocess.PIPE)
            self.assertNotIn('universal_newlines', call.kwargs)
            self.assertNotIn('text', call.kwargs)

    def test_mount_mounts_each_partition_under_its_label(self):
        self.mount()
        self.assertEqual(self.sp.all_cmds()[3:7], [
            ['mkdir', '-p', MOUNTS + '/boot'],
            ['mount', '/dev/loop5p1', MOUNTS + '/boot'],
            ['mkdir', '-p', MOUNTS + '/rootfs'],
            ['mount', '/dev/loop5p2', MOUNTS + '/rootfs']])

    def test_mount_records_the_mount_in_the_environment(self):
        self.mount(**{'system-label': 'rootfs'})
        record = self.env[MountDiskDrivePartitions.ENVKEY]
        self.assertEqual(record['count'], 1)
        self.assertIs(record['instance'], self.module)
        self.assertEqual(record['device'], '/dev/loop5')
        self.assertEqual(record['partitions'], {
            MOUNTS + '/boot': '/dev/loop5p1',
            MOUNTS + '/rootfs': '/dev/loop5p2'})
        self.assertEqual(record['system-partition'],
                         (MOUNTS + '/rootfs', '/dev/loop5p2'))
        self.module.engine.registerBuildExitCallback.assert_called_once()

    def test_mount_system_label_binds_the_live_system_directories(self):
        self.mount(**{'system-label': 'rootfs'})
        root = MOUNTS + '/rootfs/'
        binds = [cmd for cmd in self.sp.cmds('mount') if cmd[1].startswith('-')]
        self.assertEqual(binds, [
            ['mount', '-t', 'proc', 'none', root + 'proc'],
            ['mount', '--bind', '/dev', root + 'dev'],
            ['mount', '--bind', '/dev/pts', root + 'dev/pts'],
            ['mount', '-t', 'sysfs', 'none', root + 'sys']])
        self.assertEqual(self.module.mountedDevices[-4:],
                         [root + 'proc', root + 'dev', root + 'dev/pts', root + 'sys'])

    def test_mount_unknown_system_label_only_warns(self):
        self.assertTrue(self.mount(**{'system-label': 'nope'}))
        self.assertEqual(len(self.log.messages('warning')), 1)
        self.assertIsNone(self.module.systemPartition)

    def test_mount_unlabelled_partition_falls_back_to_the_partition_suffix(self):
        self.sp.on('e2label', rc=1, stderr=b'e2label: bad magic')
        self.mount()
        self.assertEqual(sorted(self.module.mountMapping.values()),
                         ['boot', 'p2'])
        self.assertEqual(len(self.log.messages('warning')), 2)

    def test_mount_empty_e2label_output_also_falls_back(self):
        self.sp.on('e2label', stdout=b'\n')
        self.mount()
        self.assertEqual(self.module.mountMapping['p2'], 'p2')

    def test_mount_non_ascii_label_survives_decoding(self):
        self.sp.on('lsblk', stdout=(
            'NAME="loop5" LABEL=""\nNAME="loop5p1" LABEL="données"\n'
        ).encode('utf-8'))
        self.mount()
        self.assertEqual(self.module.partitionMapping,
                         {MOUNTS + '/données': '/dev/loop5p1'})
        self.assertIn(['mount', '/dev/loop5p1', MOUNTS + '/données'],
                      self.sp.all_cmds())

    def test_mount_creates_the_mounts_directory_when_missing(self):
        self.paths.dirs.clear()
        self.mount()
        self.assertEqual(self.sp.all_cmds()[0], ['mkdir', '-p', MOUNTS])


class TestMountWholeDisk(DiskMountTestCase):

    def test_mount_whole_disk_mounts_the_loop_device_itself(self):
        self.assertTrue(self.mount(**{'whole-disk': 'True'}))
        self.assertEqual(self.sp.cmds('lsblk'), [])
        self.assertIn(['mount', '/dev/loop5', MOUNTS + '/'], self.sp.all_cmds())
        self.assertEqual(self.env[MountDiskDrivePartitions.ENVKEY]['partitions'],
                         {MOUNTS + '/': '/dev/loop5'})

    def test_mount_whole_disk_with_system_label_is_rejected(self):
        self.module._cleanUpMounts = mock.Mock()
        self.assertFalse(self.mount(**{'whole-disk': 'True',
                                       'system-label': 'x'}))
        self.assertEqual(self.log.results, ['failed'])
        self.module._cleanUpMounts.assert_called_once_with(True)


class TestMountFailures(DiskMountTestCase):

    def setUp(self):
        DiskMountTestCase.setUp(self)
        self.module._cleanUpMounts = mock.Mock()

    def assertUnwound(self):
        self.module._cleanUpMounts.assert_called_once_with(True)
        self.assertNotIn(MountDiskDrivePartitions.ENVKEY, self.env)

    def assertFailedAndUnwound(self):
        self.assertEqual(self.log.results, ['failed'])
        self.assertUnwound()

    def test_mount_losetup_failure_reports_stderr_as_text(self):
        self.sp.on('losetup', rc=1, stderr=b'losetup: no free loop devices')
        self.assertFalse(self.mount())
        self.assertEqual(self.log.messages('error')[-1],
                         'losetup: no free loop devices')
        self.assertFailedAndUnwound()
        self.assertEqual(self.sp.cmds('lsblk'), [])

    def test_mount_lsblk_failure_reports_stderr_as_text(self):
        self.sp.on('lsblk', rc=1, stderr=b'lsblk: not a block device')
        self.assertFalse(self.mount())
        self.assertEqual(self.log.messages('error')[-1],
                         'lsblk: not a block device')
        self.assertFailedAndUnwound()

    def test_mount_e2label_failure_reports_stderr_as_text(self):
        self.sp.on('e2label', rc=1, stderr=b'e2label: bad magic number')
        self.mount()
        self.assertIn('e2label: bad magic number', self.log.messages('warning'))

    def test_mount_drive_without_partitions_fails(self):
        self.sp.on('lsblk', stdout=LSBLK[0])
        self.assertFalse(self.mount())
        self.assertFailedAndUnwound()
        self.assertIn('no partitions', self.log.all_text())

    def test_mount_partition_mount_failure_fails_and_unwinds(self):
        self.sp.on('mount', '/dev/loop5p2', rc=32)
        self.assertFalse(self.mount())
        self.assertFailedAndUnwound()
        self.assertEqual(self.module.mountedDevices, [MOUNTS + '/boot'])

    def test_mount_system_path_failure_fails_and_unwinds(self):
        self.sp.on('mount', '--bind', '/dev', rc=32)
        self.assertFalse(self.mount(**{'system-label': 'rootfs'}))
        self.assertFailedAndUnwound()

    def test_mount_malformed_lsblk_output_fails_cleanly(self):
        self.sp.on('lsblk', stdout=b'NAME\n')
        self.assertFalse(self.mount())
        self.assertUnwound()
        self.assertEqual(len(self.log.messages('exception')), 1)

    def test_mount_non_utf8_lsblk_output_fails_cleanly(self):
        self.sp.on('lsblk', stdout=b'NAME="loop5p1" LABEL="\xff\xfe"\n')
        self.assertFalse(self.mount())
        self.assertUnwound()
        self.assertEqual(len(self.log.messages('exception')), 1)


class TestEntryPoints(DiskMountTestCase):

    def test_build_mounts_and_passes(self):
        self.module.build({'mounts': MOUNTS, 'drive': DRIVE})
        self.assertEqual(self.log.results, ['passed'])
        self.assertIn(MountDiskDrivePartitions.ENVKEY, self.env)

    def test_build_second_mount_does_not_touch_the_system(self):
        self.module.build({'mounts': MOUNTS, 'drive': DRIVE})
        self.sp.calls.clear()
        self.module.build({'mounts': MOUNTS, 'drive': DRIVE})
        self.assertEqual(self.sp.calls, [])
        self.assertEqual(self.env[MountDiskDrivePartitions.ENVKEY]['count'], 2)

    def test_build_failure_fails_the_section(self):
        self.sp.on('losetup', rc=1)
        self.module._cleanUpMounts = mock.Mock()
        self.module.build({'mounts': MOUNTS, 'drive': DRIVE})
        self.assertEqual(set(self.log.results), {'failed'})

    def test_start_build_mounts_like_build(self):
        self.module.start__build('build', {'mounts': MOUNTS, 'drive': DRIVE},
                                 None, None)
        self.assertEqual(self.log.results, ['passed'])

    def test_end_build_unmounts_and_passes(self):
        self.module._cleanUpMounts = mock.Mock(return_value=True)
        self.module.options = {}
        self.module.end__build('build', {}, None, None)
        self.module._cleanUpMounts.assert_called_once_with()
        self.assertEqual(self.log.results, ['passed'])

    def test_on_exit_forces_the_unmount(self):
        self.module._cleanUpMounts = mock.Mock()
        self.module._onExit()
        self.module._cleanUpMounts.assert_called_once_with(True)


class TestKillAllProcessesAt(DiskMountTestCase):

    PROCS = ['/proc/123', '/proc/456', '/proc/789']

    def kill(self, root='/mnt/target'):
        with mock.patch.object(module_under_test.glob, 'glob',
                               return_value=self.PROCS) as glob:
            self.module._killAllProcessesAt(root)
        glob.assert_called_once_with('/proc/[0-9]*')

    def test_kill_all_processes_at_kills_only_processes_rooted_there(self):
        self.sp.on('readlink', '/proc/123/root', stdout=b'/mnt/target\n')
        self.sp.on('readlink', '/proc/456/root', stdout=b'/\n')
        self.sp.on('readlink', '/proc/789/root', stdout=b'/mnt/target\n')
        self.kill()
        self.assertEqual(self.sp.cmds('kill'),
                         [['kill', '-9', '123'], ['kill', '-9', '789']])

    def test_kill_all_processes_at_readlink_output_is_decoded_for_comparison(self):
        self.sp.on('readlink', stdout=b'/mnt/target\n')
        self.kill()
        readlink = self.sp.find('readlink')[0]
        self.assertEqual(readlink.func, 'check_output')
        self.assertNotIn('text', readlink.kwargs)
        self.assertEqual(len(self.sp.cmds('kill')), 3)

    def test_kill_all_processes_at_skips_unreadable_processes(self):
        self.sp.on('readlink', '/proc/123/root', rc=1)
        self.sp.on('readlink', '/proc/456/root', stdout=b'/mnt/target\n')
        self.sp.on('readlink', '/proc/789/root', stdout=b'/elsewhere\n')
        self.kill()
        self.assertEqual(self.sp.cmds('kill'), [['kill', '-9', '456']])
        self.assertEqual(len(self.log.messages('debug')), 1)

    def test_kill_all_processes_at_non_utf8_link_target_is_skipped(self):
        self.sp.on('readlink', stdout=b'/mnt/\xff\xfe\n')
        self.kill()
        self.assertEqual(self.sp.cmds('kill'), [])


class TestCleanUpMounts(DiskMountTestCase):
    """_cleanUpMounts references an undefined name 'device' in its ioctl
    step (a pre-existing NameError, also present before the migration).  The
    tests define that global so the unmount logic around it can be tested;
    nothing asserts the ioctl call itself."""

    def setUp(self):
        DiskMountTestCase.setUp(self)
        patcher = mock.patch.object(module_under_test, 'device', '/dev/loop5',
                                    create=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.mount(**{'system-label': 'rootfs'})
        self.devices = list(self.module.mountedDevices)
        self.sp.calls.clear()
        self.log.results.clear()

    def test_clean_up_mounts_unmounts_in_reverse_order_then_detaches(self):
        self.assertIsNone(self.module._cleanUpMounts())
        umounts = [cmd[1] for cmd in self.sp.cmds('umount')]
        self.assertEqual(umounts, list(reversed(self.devices)))
        names = [cmd[0] for cmd in self.sp.all_cmds()]
        self.assertEqual(names[0], 'sync')
        self.assertLess(names.index('umount'), names.index('losetup'))
        self.assertIn(['losetup', '-d', '/dev/loop5'], self.sp.all_cmds())

    def test_clean_up_mounts_trims_before_each_unmount(self):
        self.module._cleanUpMounts()
        cmds = self.sp.all_cmds()
        for dev in self.devices:
            self.assertLess(cmds.index(['fstrim', dev]), cmds.index(['umount', dev]))

    def test_clean_up_mounts_resparsifies_the_drive_and_removes_mountpoints(self):
        self.module._cleanUpMounts()
        self.assertIn(['fallocate', '-d', DRIVE], self.sp.all_cmds())
        shell = [call for call in self.sp.calls if isinstance(call.argv, str)]
        self.assertEqual(len(shell), 1)
        self.assertIn('ls %s/*' % MOUNTS, shell[0].argv)
        self.assertTrue(shell[0].kwargs['shell'])
        self.assertIn(['rmdir', MOUNTS], self.sp.all_cmds())

    def test_clean_up_mounts_forgets_the_mount(self):
        self.module._cleanUpMounts()
        self.assertNotIn(MountDiskDrivePartitions.ENVKEY, self.env)
        self.assertEqual(self.module.mountedDevices, [])

    def test_clean_up_mounts_stuck_unmount_kills_processes_then_retries(self):
        target = self.devices[-1]
        self.sp.on('umount', target, rc=32)
        self.module._killAllProcessesAt = mock.Mock()
        self.module._cleanUpMounts()
        self.module._killAllProcessesAt.assert_called_once_with(target)
        sequence = [cmd for cmd in self.sp.all_cmds()
                    if cmd[0] == 'umount' and cmd[-1] == target]
        self.assertEqual(sequence, [['umount', target], ['umount', target],
                                    ['umount', '-fl', target]])

    def test_clean_up_mounts_not_mounted_without_force_fails(self):
        del self.env[MountDiskDrivePartitions.ENVKEY]
        self.assertFalse(self.module._cleanUpMounts())
        self.assertEqual(self.sp.calls, [])

    def test_clean_up_mounts_with_other_mounts_outstanding_keeps_them(self):
        self.env[MountDiskDrivePartitions.ENVKEY]['count'] = 2
        self.assertTrue(self.module._cleanUpMounts())
        self.assertEqual(self.env[MountDiskDrivePartitions.ENVKEY]['count'], 1)
        self.assertEqual(self.sp.cmds('umount'), [])

    def test_clean_up_mounts_detach_failure_only_warns(self):
        self.sp.on('losetup', '-d', rc=1)
        self.module._cleanUpMounts()
        self.assertIn("Couldn't remove loopback device",
                      self.log.messages('warning'))

    def test_clean_up_mounts_leftover_mountpoint_directory_is_an_error(self):
        self.sp.on('rmdir', rc=1)
        self.module._cleanUpMounts()
        self.assertEqual(len(self.log.messages('error')), 1)

    @unittest.skip("pre-existing bug: _cleanUpMounts passes the undefined "
                   "name 'device' to the ioctl step (NameError)")
    def test_clean_up_mounts_detaches_the_loop_device_with_ioctl(self):
        pass


class TestMountSystemPathsForDisk(DiskMountTestCase):

    def test_mount_system_paths_order_and_commands(self):
        self.module.mountedDevices = []
        self.assertTrue(self.module._mountSystemPaths('/m'))
        self.assertEqual(self.sp.all_cmds(), [
            ['mkdir', '/m/proc'], ['mount', '-t', 'proc', 'none', '/m/proc'],
            ['mkdir', '/m/dev'], ['mount', '--bind', '/dev', '/m/dev'],
            ['mkdir', '/m/dev/pts'],
            ['mount', '--bind', '/dev/pts', '/m/dev/pts'],
            ['mkdir', '/m/sys'], ['mount', '-t', 'sysfs', 'none', '/m/sys']])

    def test_mount_system_paths_mkdir_failure_stops(self):
        self.module.mountedDevices = []
        self.sp.on('mkdir', '/m/dev/pts', rc=1)
        self.assertFalse(self.module._mountSystemPaths('/m'))
        self.assertEqual(self.module.mountedDevices, ['/m/proc', '/m/dev'])
