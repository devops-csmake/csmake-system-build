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
"""check_output()/communicate() return bytes in Python 3.  These modules use
the output as device paths, compare it against str, or split it, so each was
changed to decode.  The tools (sudo, losetup, lvs, lsblk, ...) are fakes with
canned output; nothing here touches a real device."""
import os
import types
from unittest import mock

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.MountDiskDrivePartitions import MountDiskDrivePartitions
from CsmakeModules.SystemBuildDisk import SystemBuildDisk
from CsmakeModules.SystemBuildLVM import SystemBuildLVM
from tests.helpers import FakeBinTestCase


class TestSystemBuildDisk(FakeBinTestCase):

    def test_loop_device_from_losetup_is_a_clean_str(self):
        self.bin.add('losetup', stdout='/dev/loop7\n')
        self.bin.add('truncate', extra=': > "$3"')
        diskfile = os.path.join(self.tmp, 'root.img')
        system = {
            'system': types.SimpleNamespace(_getSizeInBytes=lambda s: 1 << 30),
            'cleanup_methods': [],
        }
        module = object.__new__(SystemBuildDisk)
        module.log = self.log
        module.env = types.SimpleNamespace(
            env={'__SystemBuild_demo__': system})

        disk = module._setupDisk({'system': 'demo', 'disk-name': 'root',
                                  'disk-file': diskfile, 'size': '1G'}, True)

        self.assertEqual(disk['device'], '/dev/loop7')
        self.assertIsInstance(disk['device'], str)
        self.assertEqual(
            (disk['fstab-id'], disk['number'], disk['size'], disk['real']),
            ('/dev/sda', 0, 1 << 30, True))
        self.assertEqual(self.bin.calls('losetup'),
                         [['losetup', '--show', '-f', diskfile]])
        self.assertTrue(os.path.exists(diskfile))
        self.assertEqual(self.log.results, ['passed'])


class TestSystemBuildLVM(FakeBinTestCase):

    def setUp(self):
        FakeBinTestCase.setUp(self)
        self.system = {
            'system': types.SimpleNamespace(_getSizeInBytes=lambda s: 2 << 30),
            'disks': {'sda': {'device': '/dev/loop4',
                              'partitions': {'root': {'number': 1}}}},
            'cleanup_methods': [],
            'recovery_methods': [],
        }
        self.module = object.__new__(SystemBuildLVM)
        self.module.log = self.log
        self.module.settings = {'verbose': False, 'debug': False}
        self.module.env = types.SimpleNamespace(
            env={'__SystemBuild_demo__': self.system})

    def test_existing_volume_group_is_found_in_vgs_output(self):
        self.bin.add('vgs', stdout='  taken   1   2   0 wz--n- 10.00g 5.00g\n'
                                   '  other   1   0   0 wz--n- 1.00g 1.00g\n')
        result = self.module._setupLvm(
            {'system': 'demo', 'pv_a': 'sda.root', 'vg_taken': 'a'}, True)
        self.assertIsNone(result)
        self.assertIn("Volume group 'taken' already exists on the build system",
                      self.log.messages('error'))
        self.assertEqual(self.log.results, ['failed'])
        self.assertEqual(self.bin.calls('vgcreate'), [])

    def test_build_creates_pv_vg_lv_and_registers_the_logical_volume(self):
        self.bin.add('vgs', stdout='  other   1   0   0 wz--n- 1.00g 1.00g\n')
        result = self.module._setupLvm(
            {'system': 'demo', 'pv_a': 'sda.root',
             'vg_my-data': 'a', 'lv_var': 'my-data, 2G'}, True)

        self.assertEqual(self.log.results, ['passed'])
        self.assertEqual(self.bin.calls('pvcreate'),
                         [['pvcreate', '-M2', '-f', '-y', '/dev/loop4p1']])
        self.assertEqual(self.bin.calls('vgcreate'),
                         [['vgcreate', '-M2', 'my-data', '/dev/loop4p1']])
        self.assertEqual(self.bin.calls('lvcreate'),
                         [['lvcreate', '-n', 'var', '-L', '2G', 'my-data']])
        self.assertEqual(result['var'], {
            'device': '/dev/my-data/var',
            'fstab-id': '/dev/mapper/my--data-var',
            'real': False, 'size': 2 << 30, 'path': 'my-data'})
        self.assertIs(self.system['disks']['var'], result['var'])
        self.assertEqual(self.system['cleanup_methods'], [self.module._cleanup])

    def test_cleanup_removes_only_this_vgs_archive_files(self):
        # 'lvs'/'pvs' failing is how cleanup confirms the volumes are gone
        self.bin.add('lvs', rc=5)
        self.bin.add('pvs', rc=5)
        self.bin.add('ls', stdout='/etc/lvm/archive:\n'
                                  'vg0_00000-111.vg\nvg0_00001-222.vg\n'
                                  'other_00000-333.vg\n')
        self.module.systemEntry = self.system
        self.module.vgsCreated = [('vg0', ['/dev/loop4p1'])]
        self.module.pvsCreated = ['/dev/loop4p1']
        self.module.lvsCreated = []

        self.module._cleanup(recover=True)

        # sudo is a recorder here: nothing was really removed
        removed = [call[2:] for call in self.bin.calls('rm')]
        self.assertEqual(removed, [
            ['/etc/lvm/archive/vg0_00000-111.vg'],
            ['/etc/lvm/archive/vg0_00001-222.vg'],
            ['/etc/lvm/backup/vg0'],
        ])
        self.assertEqual(self.module.vgsCreated, [])


class TestMountDiskDrivePartitions(FakeBinTestCase):

    def newModule(self, options):
        module = object.__new__(MountDiskDrivePartitions)
        module.log = self.log
        module.options = options
        module.env = types.SimpleNamespace(env={})
        module.engine = types.SimpleNamespace(
            registerBuildExitCallback=lambda callback: 1)
        return module

    def test_mount_parses_losetup_lsblk_and_e2label_output(self):
        self.bin.add('losetup', stdout='/dev/loop5\n')
        self.bin.add('lsblk', stdout='NAME="loop5" LABEL=""\n'
                                     'NAME="loop5p1" LABEL="boot"\n'
                                     'NAME="loop5p2" LABEL=""\n')
        self.bin.add('e2label', stdout='rootfs\n')
        mounts = os.path.join(self.tmp, 'mnt')
        module = self.newModule({
            'mounts': mounts, 'drive': os.path.join(self.tmp, 'disk.img'),
            'system-label': 'rootfs'})

        self.assertTrue(module._initModule())
        self.assertTrue(module._mount())

        record = module.env.env[MountDiskDrivePartitions.ENVKEY]
        self.assertEqual(record['device'], '/dev/loop5')
        self.assertEqual(record['partitions'], {
            os.path.join(mounts, 'boot'): '/dev/loop5p1',
            os.path.join(mounts, 'rootfs'): '/dev/loop5p2'})
        # The unlabelled partition got its name from e2label's output
        self.assertEqual(self.bin.calls('e2label'),
                         [['e2label', '/dev/loop5p2']])
        self.assertEqual(record['system-partition'],
                         (os.path.join(mounts, 'rootfs'), '/dev/loop5p2'))
        self.assertEqual(self.bin.calls('losetup'),
                         [['losetup', '--show', '-f', module.options['drive']]])

    def test_kill_all_processes_at_matches_readlink_output_to_the_root(self):
        procdir = os.path.join(self.tmp, 'proc')
        procs = [os.path.join(procdir, str(pid)) for pid in (123, 456)]
        self.bin.add('readlink',
                     extra='case "$1" in */123/root) echo /mnt/target;; '
                           '*) echo /somewhere/else;; esac')
        module = self.newModule({})

        with mock.patch('glob.glob', return_value=procs):
            module._killAllProcessesAt('/mnt/target')

        self.assertEqual(self.bin.calls('kill'), [['kill', '-9', '123']])
