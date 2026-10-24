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
"""SystemBuildFileSystem runs mkfs and a filesystem-specific labeler per
mount point and records the result in the system entry.  mkfs/e2label/...
are mocked at the subprocess boundary."""
import subprocess

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.SystemBuildFileSystem import SystemBuildFileSystem
from tests.helpers import SubprocessTestCase, new_module

KEY = '__SystemBuild_demo__'


class FileSystemTestCase(SubprocessTestCase):

    def setUp(self):
        SubprocessTestCase.setUp(self)
        self.sda = {
            'device': '/dev/loop2', 'fstab-id': '/dev/sda',
            'partitions': {
                'root': {'device': '/dev/loop2p2', 'fstab-id': '/dev/sda2'},
                'boot': {'device': '/dev/loop2p1', 'fstab-id': '/dev/sda1'},
                'efi': {'device': '/dev/loop2p3', 'fstab-id': '/dev/sda3'},
                'preset': {'device': '/dev/loop2p4', 'fstab-id': 'UUID=1234'},
            }}
        self.lv = {'device': '/dev/data/var', 'fstab-id': '/dev/mapper/data-var'}
        self.system = {'disks': {'sda': self.sda, 'var': self.lv}}
        self.module = new_module(SystemBuildFileSystem, log=self.log,
                                 env={KEY: self.system})

    def opts(self, *pairs):
        options = {'system': 'demo'}
        options.update(pairs)
        return options


class TestBuild(FileSystemTestCase):

    def test_build_makes_labels_and_syncs_in_mount_order(self):
        # '/boot/efi' is listed first but must be made after its parents
        fs = self.module.build(self.opts(
            ('/boot/efi', 'sda.efi, vfat'), ('/', 'sda.root, ext4'),
            ('/boot', 'sda.boot, ext2')))
        self.assertEqual(self.sp.all_cmds(), [
            ['mkfs', '-t', 'ext4', '/dev/loop2p2'],
            ['e2label', '/dev/loop2p2', 'root'],
            ['mkfs', '-t', 'ext2', '/dev/loop2p1'],
            ['e2label', '/dev/loop2p1', 'boot'],
            ['mkfs', '-t', 'vfat', '/dev/loop2p3'],
            ['fatlabel', '/dev/loop2p3', 'EFI'],
            ['sync']])
        self.assertEqual(list(fs), ['/', '/boot', '/boot/efi'])
        self.assertEqual(self.log.results, ['passed'])

    def test_build_records_filesystem_and_info_entries(self):
        fs = self.module.build(self.opts(('/', 'sda.root, ext4')))
        self.assertEqual(fs['/'], ('/', '/dev/loop2p2', 'ext4', 'LABEL=root'))
        self.assertIs(self.system['filesystem'], fs)
        info = self.system['filesystem-info']['/']
        self.assertIs(info['disk'], self.sda)
        self.assertIs(info['partition'], self.sda['partitions']['root'])
        self.assertEqual(self.sda['partitions']['root']['fstab-id'], 'LABEL=root')

    def test_build_passes_extra_mkfs_options_before_the_device(self):
        self.module.build(self.opts(('/', 'sda.root, ext4, -L mine -E lazy')))
        self.assertEqual(self.sp.cmds('mkfs')[0], [
            'mkfs', '-t', 'ext4', '-L', 'mine', '-E', 'lazy', '/dev/loop2p2'])

    def test_build_whole_disk_logical_volume_is_labelled_by_disk_name(self):
        fs = self.module.build(self.opts(('/', 'var, ext4')))
        self.assertEqual(fs['/'], ('/', '/dev/data/var', 'ext4', 'LABEL=var'))
        self.assertEqual(self.lv['fstab-id'], 'LABEL=var')
        self.assertEqual(self.sp.cmds('e2label'),
                         [['e2label', '/dev/data/var', 'var']])

    def test_build_existing_fstab_id_skips_labelling(self):
        fs = self.module.build(self.opts(('/', 'sda.preset, ext4')))
        self.assertEqual(self.sp.cmds('e2label'), [])
        self.assertEqual(fs['/'][3], 'UUID=1234')

    def test_build_filesystem_without_a_labeler_keeps_the_device_fstab_id(self):
        fs = self.module.build(self.opts(('/', 'sda.root, reiserfs')))
        self.assertEqual(self.sp.all_cmds(), [
            ['mkfs', '-t', 'reiserfs', '/dev/loop2p2'], ['sync']])
        self.assertEqual(fs['/'][3], '/dev/sda2')

    def test_build_mkfs_failure_propagates_and_nothing_else_runs(self):
        self.sp.on('mkfs', rc=1)
        with self.assertRaises(subprocess.CalledProcessError):
            self.module.build(self.opts(('/', 'sda.root, ext4')))
        self.assertEqual(self.sp.cmds('e2label'), [])
        self.assertEqual(self.sp.cmds('sync'), [])

    def test_build_label_failure_is_logged_and_keeps_going(self):
        self.sp.on('e2label', rc=1)
        fs = self.module.build(self.opts(('/', 'sda.root, ext4')))
        self.assertEqual(len(self.log.messages('exception')), 1)
        self.assertEqual(fs['/'][3], '/dev/sda2')
        self.assertEqual(self.log.results, ['passed'])

    def test_build_non_ascii_partition_name_is_passed_as_the_label(self):
        self.sda['partitions']['données'] = {
            'device': '/dev/loop2p5', 'fstab-id': '/dev/sda5'}
        self.module.build(self.opts(('/', 'sda.données, ext4')))
        self.assertEqual(self.sp.cmds('e2label'),
                         [['e2label', '/dev/loop2p5', 'données']])


class TestLabelers(FileSystemTestCase):

    def label(self, fstype, partition='root'):
        """Run a fresh build for one filesystem; return non-mkfs commands."""
        self.sp.calls.clear()
        self.system.pop('filesystem', None)
        self.system.pop('filesystem-info', None)
        for part in self.sda['partitions'].values():
            if part['fstab-id'].startswith('LABEL='):
                part['fstab-id'] = '/dev/sda?'
        self.module.build(self.opts(('/', 'sda.%s, %s' % (partition, fstype))))
        return [cmd for cmd in self.sp.all_cmds()
                if cmd[0] not in ('mkfs', 'sync')]

    def test_labeler_ext_family_uses_e2label(self):
        for fstype in ('ext2', 'ext3', 'ext4'):
            with self.subTest(fstype=fstype):
                self.assertEqual(self.label(fstype),
                                 [['e2label', '/dev/loop2p2', 'root']])

    def test_labeler_vfat_truncates_to_eleven_upper_case_characters(self):
        self.sda['partitions']['efi_partition_long'] = {
            'device': '/dev/loop2p6', 'fstab-id': '/dev/sda6'}
        self.assertEqual(self.label('vfat', 'efi_partition_long'),
                         [['fatlabel', '/dev/loop2p6', 'EFI_PARTITI']])
        self.assertEqual(self.system['filesystem']['/'][3], 'LABEL=EFI_PARTITI')

    def test_labeler_other_filesystems_use_their_own_tools(self):
        expected = {
            'btrfs': ['btrfs', 'filesystem', 'label', '/dev/loop2p2', 'root'],
            'xfs': ['xfs_admin', '-L', 'root', '/dev/loop2p2'],
            'jfs': ['jfs_tune', '-L', 'root', '/dev/loop2p2'],
            'NTFS': ['ntfslabel', '/dev/loop2p2', 'root'],
        }
        for fstype, command in expected.items():
            with self.subTest(fstype=fstype):
                self.assertEqual(self.label(fstype), [command])

    def test_labeler_use_system_build_labels_without_running_tools(self):
        fs = self.module.use_system_build(self.opts(('/', 'sda.root, ext4')))
        self.assertEqual(self.sp.all_cmds(), [['sync']])
        self.assertEqual(fs['/'][3], 'LABEL=root')


class TestInvalidSpecifications(FileSystemTestCase):

    def assertFails(self, options):
        self.assertIsNone(self.module.build(options))
        self.assertEqual(self.log.results, ['failed'])
        self.assertEqual(self.sp.cmds('mkfs'), [])

    def test_build_undefined_system_fails(self):
        self.module.env.env.clear()
        self.assertFails(self.opts(('/', 'sda.root, ext4')))

    def test_build_second_filesystem_for_a_system_fails(self):
        self.system['filesystem'] = {}
        self.assertFails(self.opts(('/', 'sda.root, ext4')))

    def test_build_spec_with_one_field_fails(self):
        self.assertFails(self.opts(('/', 'sda.root')))

    def test_build_spec_with_four_fields_fails(self):
        self.assertFails(self.opts(('/', 'sda.root, ext4, -L x, extra')))

    def test_build_undefined_disk_fails(self):
        self.assertFails(self.opts(('/', 'nodisk.root, ext4')))

    def test_build_undefined_partition_fails(self):
        self.assertFails(self.opts(('/', 'sda.nopart, ext4')))
