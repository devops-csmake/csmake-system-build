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
"""dict.iteritems() -> items() in the option and system-entry walkers.  Each
test drives a real code path that was reached through one of those changes."""
import types

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.SystemBuildGetPartitionDevices import \
    SystemBuildGetPartitionDevices
from CsmakeModules.SystemBuildGrubInstall import SystemBuildGrubInstall
from CsmakeModules.SystemBuildMsdosPartitions import SystemBuildMsdosPartitions
from tests.helpers import FakeBinTestCase, SAMPLE_FILESYSTEM


class TestOptionAndSystemEntryWalkers(FakeBinTestCase):

    def test_get_partition_devices_defines_and_removes_env_variables(self):
        module = object.__new__(SystemBuildGetPartitionDevices)
        module.log = self.log
        module.env = types.SimpleNamespace(env={
            '__SystemBuild_demo__': {'filesystem': dict(SAMPLE_FILESYSTEM)}})
        options = {'system': 'demo', 'env_/boot': 'BOOT_DEV',
                   'env_/': 'ROOT_DEV', 'env_/nope': 'MISSING_DEV',
                   '**internal': 'x'}

        module.start__build('build', options, None, None)

        env = module.env.env
        self.assertEqual(env['BOOT_DEV'], '/dev/loop3p2')
        self.assertEqual(env['ROOT_DEV'], '/dev/loop3p3')
        self.assertEqual(env['MISSING_DEV'], '## Device not found')
        module.end__build('build', options, None, None)
        for name in ('BOOT_DEV', 'ROOT_DEV', 'MISSING_DEV'):
            self.assertNotIn(name, env)

    def test_grub_install_finds_the_boot_disk_by_walking_system_disks(self):
        mountInstance = types.SimpleNamespace(
            _systemMountLocation=lambda: '/build/mnt')
        system = {
            'filesystem': dict(SAMPLE_FILESYSTEM),
            'filesystem-info': {'/': 'root-info', '/boot': 'boot-info'},
            'mountInstance': mountInstance,
            'disks': {
                # An lvm-style disk first: not real, and must not match
                'var': {'device': '/dev/data/var', 'real': False},
                'sda': {'device': '/dev/loop3', 'real': True},
            },
        }
        module = object.__new__(SystemBuildGrubInstall)
        module.log = self.log
        module.env = types.SimpleNamespace(env={'sys': system})

        self.assertTrue(module._getSystemBuildProperties('sys'))

        self.assertEqual(module.systemDevice, '/dev/loop3')
        self.assertIs(module.systemDeviceObject, system['disks']['sda'])
        self.assertEqual(module.systemPathToSystemDevice, '/boot')
        self.assertEqual(module.systemDeviceInfo, 'boot-info')
        self.assertEqual(module.rootTabId, 'LABEL=root')
        self.assertEqual(module.systemPartition, '/build/mnt')

    def test_msdos_partitions_are_created_in_order_from_part_options(self):
        disk = {'device': '/dev/loop2', 'fstab-id': '/dev/sda', 'size': 10 << 30}
        system = {
            'system': types.SimpleNamespace(
                _getSizeInBytes=lambda size: int(size.rstrip('G')) << 30),
            'disks': {'sda': disk},
        }
        module = object.__new__(SystemBuildMsdosPartitions)
        module.log = self.log
        module.env = types.SimpleNamespace(
            env={'__SystemBuild_demo__': system})

        # Options arrive in an arbitrary order; the <order> field decides
        entries = module.build({
            'system': 'demo', 'disk-name': 'sda',
            'part_root': '3, 7G, linux, root',
            'part_boot': '1, 1G, ext2, boot',
            'part_swap': '2, 2G, linux-swap',
        })

        self.assertEqual(
            [(name, entry['number'], entry['device'], entry['fstab-id'])
             for name, entry in sorted(entries.items())],
            [('boot', 1, '/dev/loop2p1', '/dev/sda1'),
             ('root', 3, '/dev/loop2p3', '/dev/sda3'),
             ('swap', 2, '/dev/loop2p2', 'LABEL=swap')])
        named = [call[call.index('name') + 1:] for call in self.bin.calls('parted')
                 if 'name' in call]
        self.assertEqual(named, [['1', 'boot'], ['2', 'swap'], ['3', 'root']])
        self.assertEqual(disk['swaps'], [('swap', entries['swap'])])
        self.assertEqual(self.log.results, ['passed'])


if __name__ == '__main__':
    unittest.main()
