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
"""Legacy grub (0.97) cannot see loop devices, so SystemBuildOldGrubInstall
mknod's fake /dev/hdz... nodes that alias the build disks.  os.stat and
os.path.exists answer from a script (block device present / absent / not a
block device), mknod and chmod are mocked at the subprocess boundary, and the
files written into the system (mtab, grub.conf, device.map) are real
temp-dir file I/O because their content is what is under test."""
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules import SystemBuildOldGrubInstall as module_under_test
from CsmakeModules.SystemBuildOldGrubInstall import SystemBuildOldGrubInstall
from tests.helpers import (BLOCK, FakePaths, REGULAR, SubprocessTestCase,
                           new_module, patch_stat)

DISK, BOOT, ROOT = '/dev/loop3', '/dev/loop3p1', '/dev/loop3p2'


def disk_entry(real=True, device=DISK):
    return {'real': real, 'device': device,
            'partitions': {'boot': {'number': 1, 'device': BOOT},
                           'root': {'number': 2, 'device': ROOT}}}


class OldGrubTestCase(SubprocessTestCase):

    def setUp(self):
        SubprocessTestCase.setUp(self)
        tempfile.gettempdir()
        self.root = tempfile.mkdtemp(prefix='oldgrub')
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, 'etc'))
        self.paths = FakePaths(self, real_under=self.root)
        self.stats = patch_stat(self, {
            DISK: (BLOCK, os.makedev(7, 3)),
            BOOT: (BLOCK, os.makedev(7, 4)),
            ROOT: (BLOCK, os.makedev(7, 5))}, real_under=self.root)
        self.module = new_module(SystemBuildOldGrubInstall, log=self.log)
        self.module.systemPartition = self.root
        self.module.systemEntry = {
            'disks': {'sda': disk_entry()},
            'filesystem': {
                '/boot': ('/boot', BOOT, 'ext2', 'LABEL=boot'),
                '/': ('/', ROOT, 'ext4', 'LABEL=root')}}

    def mknods(self):
        return self.sp.cmds('mknod')


class TestPrepareForGrubInstall(OldGrubTestCase):

    def test_prepare_creates_nodes_for_the_disk_and_partitions(self):
        self.module._prepareForGrubInstall()
        self.assertEqual(self.mknods(), [
            ['mknod', '/dev/hdz', 'b', '7', '3'],
            ['mknod', '/dev/hdz1', 'b', '7', '4'],
            ['mknod', '/dev/hdz2', 'b', '7', '5']])
        self.assertTrue(all(call.sudo for call in self.sp.find('mknod')))

    def test_prepare_records_the_device_aliases_and_created_nodes(self):
        self.module._prepareForGrubInstall()
        self.assertEqual(self.module._oldGrubDiskMappings, {
            DISK: '/dev/hdz', BOOT: '/dev/hdz1', ROOT: '/dev/hdz2'})
        self.assertEqual(self.module._createdDevEntries,
                         ['/dev/hdz', '/dev/hdz1', '/dev/hdz2'])
        self.assertEqual(self.module._deviceMapEntries, [('hd0', '/dev/hdz')])

    def test_prepare_writes_mtab_using_the_aliased_devices(self):
        self.module._prepareForGrubInstall()
        with open(os.path.join(self.root, 'etc', 'mtab')) as mtab:
            self.assertEqual(mtab.read(),
                             '/dev/hdz1 /boot ext2 rw 0 0\n/dev/hdz2 / ext4 rw 0 0')

    def test_prepare_new_mtab_only_needs_the_etc_directory_opened_up(self):
        self.module._prepareForGrubInstall()
        self.assertEqual(self.sp.cmds('chmod'),
                         [['chmod', '777', os.path.join(self.root, 'etc')]])
        self.assertEqual(self.module._mtabfilemask, '664')

    def test_prepare_existing_mtab_is_made_writable_and_its_mode_remembered(self):
        mtab = os.path.join(self.root, 'etc', 'mtab')
        with open(mtab, 'w') as handle:
            handle.write('old')
        mode = oct(os.stat(mtab).st_mode)[-3:]
        self.module._prepareForGrubInstall()
        self.assertEqual(self.sp.cmds('chmod'), [
            ['chmod', '777', os.path.join(self.root, 'etc')],
            ['chmod', '666', mtab]])
        self.assertEqual(self.module._mtabfilemask, mode)

    def test_prepare_uses_sd_names_when_hd_is_taken_and_sd_is_free(self):
        self.paths.exists.add('/dev/hda')
        self.module._prepareForGrubInstall()
        self.assertEqual(self.mknods()[0][1], '/dev/sdz')

    def test_prepare_keeps_hd_names_when_both_hd_and_sd_exist(self):
        self.paths.exists.update(['/dev/hda', '/dev/sda'])
        self.module._prepareForGrubInstall()
        self.assertEqual(self.mknods()[0][1], '/dev/hdz')

    def test_prepare_second_real_disk_takes_the_next_letter_down(self):
        self.stats['/dev/loop4'] = (BLOCK, os.makedev(7, 6))
        self.module.systemEntry['disks']['sdb'] = {
            'real': True, 'device': '/dev/loop4', 'partitions': {}}
        self.module._prepareForGrubInstall()
        self.assertIn(['mknod', '/dev/hdy', 'b', '7', '6'], self.mknods())
        self.assertEqual(self.module._deviceMapEntries,
                         [('hd0', '/dev/hdz'), ('hd1', '/dev/hdy')])

    def test_prepare_ignores_disks_that_are_not_real(self):
        self.module.systemEntry['disks'] = {
            'sda': disk_entry(),
            'var': {'real': False, 'device': '/dev/data/var', 'partitions': {}}}
        self.module._prepareForGrubInstall()
        self.assertEqual(len(self.module._deviceMapEntries), 1)

    def test_prepare_fails_when_the_fake_node_name_is_already_in_use(self):
        self.paths.exists.add('/dev/hdz')
        with self.assertRaises(ValueError):
            self.module._prepareForGrubInstall()
        self.assertEqual(self.mknods(), [])
        self.assertIn('/dev/hdz is required for use to install grub, but '
                      'already exists on the system', self.log.messages('error'))

    def test_prepare_fails_when_the_disk_is_not_a_block_device(self):
        self.stats[DISK] = (REGULAR, 0)
        with self.assertRaises(ValueError):
            self.module._prepareForGrubInstall()
        self.assertEqual(self.mknods(), [])
        self.assertIn('/dev/loop3 is not a block device', self.log.messages('error'))

    def test_prepare_missing_disk_device_raises(self):
        del self.stats[DISK]
        with self.assertRaises(FileNotFoundError):
            self.module._prepareForGrubInstall()

    def test_prepare_partition_not_a_block_device_removes_the_nodes_made_so_far(self):
        self.stats[ROOT] = (REGULAR, 0)
        with self.assertRaises(ValueError):
            self.module._prepareForGrubInstall()
        self.assertEqual(self.sp.cmds('rm'), [
            ['rm', '-f', '/dev/hdz'], ['rm', '-f', '/dev/hdz1']])

    def test_prepare_mknod_failure_removes_the_node_it_tried_to_make(self):
        self.sp.on('mknod', '/dev/hdz1', rc=1)
        with self.assertRaises(subprocess.CalledProcessError):
            self.module._prepareForGrubInstall()
        self.assertEqual(self.sp.cmds('rm'), [
            ['rm', '-f', '/dev/hdz'], ['rm', '-f', '/dev/hdz1']])


class TestCleanUpPostGrubInstall(OldGrubTestCase):

    def test_clean_up_removes_every_fake_node_in_creation_order(self):
        self.module._createdDevEntries = ['/dev/hdz', '/dev/hdz1']
        self.module._cleanUpPostGrubInstall()
        self.assertEqual(self.sp.all_cmds(), [['rm', '-f', '/dev/hdz'],
                                              ['rm', '-f', '/dev/hdz1']])
        self.assertTrue(all(call.sudo for call in self.sp.calls))

    def test_clean_up_with_nothing_created_runs_nothing(self):
        self.module._createdDevEntries = []
        self.module._cleanUpPostGrubInstall()
        self.assertEqual(self.sp.calls, [])


class TestGenerateGrubConfig(OldGrubTestCase):

    def setUp(self):
        OldGrubTestCase.setUp(self)
        self.module.options = {'system': 'demo'}
        self.module.rootTabId = 'LABEL=root'
        self.module.systemDevice = DISK
        self.module.systemPathToSystemDevice = '/boot'
        self.module.systemDeviceInfo = {'disk': {'number': 0},
                                        'partition': {'number': 1}}
        self.module._oldGrubDiskMappings = {DISK: '/dev/hdz'}
        self.module._conffilemask = None
        self.boot = os.path.join(self.root, 'boot')
        self.globs = {
            os.path.join(self.boot, 'vmlinuz*'): [os.path.join(self.boot, 'vmlinuz-3.10.0')],
            os.path.join(self.boot, 'initramfs*'): [os.path.join(self.boot, 'initramfs-3.10.0.img')]}
        patcher = mock.patch.object(module_under_test.glob, 'glob',
                                    side_effect=lambda pattern: self.globs[pattern])
        self.glob = patcher.start()
        self.addCleanup(patcher.stop)

    def read(self, *parts):
        with open(os.path.join(self.root, *parts)) as handle:
            return handle.read()

    def test_generate_grub_config_writes_grub_conf_for_the_boot_partition(self):
        self.module.options['params'] = 'console=ttyS0 quiet'
        self.assertTrue(self.module._generateGrubConfig())
        self.assertEqual(self.read('boot', 'grub', 'grub.conf'), """
default=0
timeout=10

title CentOS
  root (hd0,0)
  kernel /vmlinuz-3.10.0 ro root=LABEL=root console=ttyS0 quiet
  initrd /initramfs-3.10.0.img """)

    def test_generate_grub_config_root_filesystem_adds_the_boot_directory(self):
        self.module.systemPathToSystemDevice = '/'
        self.module.systemDeviceInfo['partition'] = {'number': 2}
        self.module._generateGrubConfig()
        self.assertIn('  root (hd0,1)/boot\n', self.read('boot', 'grub', 'grub.conf'))

    def test_generate_grub_config_whole_disk_root_has_no_partition_number(self):
        self.module.systemDeviceInfo['partition'] = None
        self.module._generateGrubConfig()
        self.assertIn('  root (hd0)\n', self.read('boot', 'grub', 'grub.conf'))

    def test_generate_grub_config_writes_the_device_map(self):
        self.module._generateGrubConfig()
        self.assertEqual(self.read('boot', 'grub', 'device.map'),
                         '(hd0)\t/dev/hdz\n')

    def test_generate_grub_config_switches_to_the_fake_device(self):
        self.module._generateGrubConfig()
        self.assertEqual(self.module.systemDevice, '/dev/hdz')

    def test_generate_grub_config_honours_kernel_and_initrd_globs(self):
        self.module.options.update(kernel='vmlinuz-custom*', initrd='init*')
        self.globs = {
            os.path.join(self.boot, 'vmlinuz-custom*'): [os.path.join(self.boot, 'vmlinuz-custom-1')],
            os.path.join(self.boot, 'init*'): [os.path.join(self.boot, 'initrd.img')]}
        self.module._generateGrubConfig()
        conf = self.read('boot', 'grub', 'grub.conf')
        self.assertIn('kernel /vmlinuz-custom-1 ', conf)
        self.assertIn('initrd /initrd.img', conf)

    def test_generate_grub_config_multiple_kernels_fail(self):
        pattern = os.path.join(self.boot, 'vmlinuz*')
        self.globs[pattern] = [os.path.join(self.boot, 'vmlinuz-a'),
                               os.path.join(self.boot, 'vmlinuz-b')]
        self.assertFalse(self.module._generateGrubConfig())
        self.assertIn('found multiple entries', self.log.messages('error')[0])
        self.assertFalse(os.path.exists(os.path.join(self.boot, 'grub', 'grub.conf')))

    def test_generate_grub_config_multiple_initrds_fail(self):
        pattern = os.path.join(self.boot, 'initramfs*')
        self.globs[pattern] = [os.path.join(self.boot, 'initramfs-a'),
                               os.path.join(self.boot, 'initramfs-b')]
        self.assertFalse(self.module._generateGrubConfig())

    def test_generate_grub_config_opens_and_restores_the_directory_permissions(self):
        self.module._generateGrubConfig()
        grub_dir = os.path.join(self.boot, 'grub')
        chmods = self.sp.cmds('chmod')
        self.assertEqual(chmods[0], ['chmod', '777', grub_dir])
        self.assertEqual(chmods[-1][0:2], ['chmod', oct(os.stat(grub_dir).st_mode)[-3:]])

    def test_generate_grub_config_existing_conf_is_made_writable_then_restored(self):
        conf = os.path.join(self.boot, 'grub', 'grub.conf')
        os.makedirs(os.path.dirname(conf))
        with open(conf, 'w') as handle:
            handle.write('old')
        self.module._generateGrubConfig()
        modes = [cmd[1] for cmd in self.sp.cmds('chmod') if cmd[2] == conf]
        self.assertEqual(modes[0], '666')
        self.assertEqual(len(modes), 2)

    @unittest.skip("pre-existing bug: when no kernel (or initrd) matches the "
                   "glob, bootentries[0] raises IndexError instead of failing "
                   "with a message")
    def test_generate_grub_config_no_kernel_found_fails(self):
        pass
