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
"""Msdos/GPT partitioning drives parted, sfdisk and mkswap through
subprocess.  parted etc. are mocked; the tests script success and failure
and assert the exact command lines and their order."""
import subprocess
import types

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.SystemBuildGptPartitions import SystemBuildGptPartitions
from CsmakeModules.SystemBuildMsdosPartitions import SystemBuildMsdosPartitions
from tests.helpers import SubprocessTestCase, new_module

KEY = '__SystemBuild_demo__'
DEV = '/dev/loop2'


def size_in_bytes(size):
    return int(size.rstrip('GM')) << (30 if size.endswith('G') else 20)


class PartitionTestCase(SubprocessTestCase):
    MODULE = SystemBuildMsdosPartitions

    def setUp(self):
        SubprocessTestCase.setUp(self)
        self.disk = {'device': DEV, 'fstab-id': '/dev/sda', 'size': 10 << 30}
        self.system = {
            'system': types.SimpleNamespace(_getSizeInBytes=size_in_bytes),
            'disks': {'sda': self.disk},
        }
        self.module = new_module(self.MODULE, log=self.log,
                                 env={KEY: self.system})

    def options(self, **parts):
        options = {'system': 'demo', 'disk-name': 'sda'}
        options.update(('part_' + name, value) for name, value in parts.items())
        return options

    def parted(self, *tail):
        return ['parted', '-s'] + list(tail)


class TestMsdosPrimaryLayout(PartitionTestCase):

    def layout(self):
        # Options arrive in an arbitrary order; the <order> field decides
        return self.options(
            root='3, 7G, linux, root', boot='1, 1G, ext2, boot',
            swap='2, 2G, linux-swap')

    def test_build_issues_label_partitions_probe_and_mkswap_in_order(self):
        self.module.build(self.layout())
        self.assertEqual(self.sp.all_cmds(), [
            self.parted(DEV, '--', 'mklabel', 'msdos'),
            self.parted('-a', 'optimal', DEV, '--', 'mkpart', 'primary',
                        'ext2', '2048s', '10%'),
            self.parted(DEV, '--', 'name', '1', 'boot'),
            self.parted(DEV, '--', 'set', '1', 'boot', 'on'),
            self.parted('-a', 'optimal', DEV, '--', 'mkpart', 'primary',
                        'linux-swap', '10%', '30%'),
            self.parted(DEV, '--', 'name', '2', 'swap'),
            self.parted('-a', 'optimal', DEV, '--', 'mkpart', 'primary',
                        'ext2', '30%', '100%'),
            self.parted(DEV, '--', 'name', '3', 'root'),
            self.parted(DEV, '--', 'set', '3', 'root', 'on'),
            ['partprobe', DEV],
            ['udevadm', 'settle'],
            ['mkswap', '-L', 'swap', DEV + 'p2'],
        ])
        self.assertEqual(self.log.results, ['passed'])

    def test_build_returns_partition_entries_with_loop_device_names(self):
        entries = self.module.build(self.layout())
        self.assertEqual(
            [(name, entry['number'], entry['device'], entry['fstab-id'])
             for name, entry in sorted(entries.items())],
            [('boot', 1, DEV + 'p1', '/dev/sda1'),
             ('root', 3, DEV + 'p3', '/dev/sda3'),
             ('swap', 2, DEV + 'p2', 'LABEL=swap')])
        self.assertEqual(self.disk['swaps'], [('swap', entries['swap'])])
        self.assertIs(self.disk['partitions'], entries)

    def test_use_system_build_probes_but_never_partitions(self):
        entries = self.module.use_system_build(self.layout())
        self.assertEqual(self.sp.all_cmds(),
                         [['partprobe', DEV], ['udevadm', 'settle']])
        self.assertEqual(entries['boot']['device'], DEV + 'p1')

    def test_build_mkpart_failure_fails_without_probing(self):
        self.sp.on('parted', '-s', '-a', 'optimal', DEV, '--', 'mkpart',
                   'primary', 'linux-swap', rc=1)
        self.assertIsNone(self.module.build(self.layout()))
        self.assertEqual(self.log.results, ['failed'])
        self.assertEqual(self.sp.cmds('partprobe'), [])

    def test_build_mklabel_failure_propagates(self):
        self.sp.on('parted', '-s', DEV, '--', 'mklabel', rc=1)
        with self.assertRaises(subprocess.CalledProcessError):
            self.module.build(self.layout())
        self.assertEqual(self.sp.cmds('parted', '-s', '-a'), [])

    def test_build_probe_failures_only_warn(self):
        self.sp.on('partprobe', rc=1)
        self.sp.on('udevadm', rc=1)
        self.assertIsNotNone(self.module.build(self.layout()))
        self.assertEqual(len(self.log.messages('warning')), 2)
        self.assertEqual(self.log.results, ['passed'])

    def test_build_mkswap_failure_is_logged_and_swap_not_recorded(self):
        self.sp.on('mkswap', rc=1)
        entries = self.module.build(self.layout())
        self.assertEqual(self.disk['swaps'], [])
        self.assertEqual(len(self.log.messages('exception')), 1)
        self.assertEqual(entries['swap']['fstab-id'], '/dev/sda2')

    def test_build_unlisted_type_is_set_with_sfdisk(self):
        self.module.build(self.options(boot='1, 1G, 0x84'))
        self.assertIn(['sfdisk', '--part-type', DEV, '1', '0x84'],
                      self.sp.all_cmds())

    def test_build_sfdisk_failure_only_warns(self):
        self.sp.on('sfdisk', rc=1)
        self.assertIsNotNone(self.module.build(self.options(boot='1, 1G, 0x84')))
        self.assertEqual(len(self.log.messages('warning')), 1)

    def test_build_tiny_partition_is_rounded_up_to_one_percent(self):
        self.disk['size'] = 1 << 40
        self.module.build(self.options(boot='1, 1G, ext2'))
        self.assertIn(self.parted('-a', 'optimal', DEV, '--', 'mkpart',
                                  'primary', 'ext2', '2048s', '1%'),
                      self.sp.all_cmds())
        self.assertEqual(len(self.log.messages('warning')), 1)

    def test_build_oversized_partition_is_truncated_to_the_disk(self):
        self.module.build(self.options(root='1, 20G, ext2'))
        self.assertIn(self.parted('-a', 'optimal', DEV, '--', 'mkpart',
                                  'primary', 'ext2', '2048s', '100%'),
                      self.sp.all_cmds())
        self.assertEqual(len(self.log.messages('warning')), 1)


class TestMsdosExtendedAndLogical(PartitionTestCase):

    def test_build_logical_partitions_start_at_five_inside_the_extended(self):
        entries = self.module.build(self.options(
            boot='1, 1G, ext2', ext='2E, 8G', data='2E:5L, 4G, ext2'))
        self.assertEqual(entries['ext']['number'], 2)
        self.assertEqual((entries['data']['number'], entries['data']['device']),
                         (5, DEV + 'p5'))
        kinds = [cmd[cmd.index('mkpart') + 1] for cmd in self.sp.all_cmds()
                 if 'mkpart' in cmd]
        self.assertEqual(kinds, ['primary', 'extended', 'logical'])
        self.assertEqual(self.log.results, ['passed'])

    def test_build_logical_without_an_extended_raises(self):
        with self.assertRaises(SystemError):
            self.module.build(self.options(data='2E:5L, 4G, ext2'))
        self.assertEqual(self.sp.cmds('parted', '-s', '-a'), [])

    def test_build_logical_with_malformed_order_fails(self):
        self.assertIsNone(self.module.build(self.options(data='2L, 4G, ext2')))
        self.assertEqual(self.log.results, ['failed'])

    def test_build_second_extended_partition_fails(self):
        self.assertIsNone(self.module.build(self.options(
            a='1E, 2G', b='2E, 2G')))
        self.assertEqual(self.log.results, ['failed'])

    def test_build_fifth_primary_partition_fails(self):
        parts = dict(('p%d' % n, '%d, 1G, ext2' % n) for n in range(1, 6))
        self.assertIsNone(self.module.build(self.options(**parts)))
        self.assertEqual(self.log.results, ['failed'])
        self.assertEqual(len(self.sp.cmds('parted', '-s', '-a')), 4)


class TestPartitionEnvironmentErrors(PartitionTestCase):

    def test_build_undefined_system_fails(self):
        self.module.env.env.clear()
        self.assertIsNone(self.module.build(self.options()))
        self.assertEqual(self.log.results, ['failed'])

    def test_build_undefined_disk_fails(self):
        options = self.options()
        options['disk-name'] = 'nope'
        self.assertIsNone(self.module.build(options))
        self.assertEqual(self.log.results, ['failed'])

    def test_build_already_partitioned_disk_fails(self):
        self.disk['partitions'] = {}
        self.assertIsNone(self.module.build(self.options()))
        self.assertEqual(self.log.results, ['failed'])
        self.assertEqual(self.sp.calls, [])


class TestGptPartitions(PartitionTestCase):
    MODULE = SystemBuildGptPartitions

    def test_build_labels_the_disk_gpt(self):
        self.module.build(self.options(boot='1, 1G, ext2'))
        self.assertEqual(self.sp.all_cmds()[0],
                         self.parted(DEV, '--', 'mklabel', 'gpt'))

    def test_build_allows_more_than_four_primary_partitions(self):
        parts = dict(('p%d' % n, '%d, 1G, ext2' % n) for n in range(1, 7))
        entries = self.module.build(self.options(**parts))
        self.assertEqual(len(entries), 6)
        self.assertEqual(self.log.results, ['passed'])

    def test_build_rejects_logical_partitions(self):
        self.assertIsNone(self.module.build(self.options(
            a='1E, 2G', b='1E:5L, 1G, ext2')))
        self.assertEqual(self.log.results, ['failed'])

    def test_build_rejects_extended_partitions(self):
        self.assertIsNone(self.module.build(self.options(a='1E, 2G')))
        self.assertEqual(self.log.results, ['failed'])

    def test_build_unlisted_type_sets_the_gpt_typecode(self):
        self.module.build(self.options(boot='1, 1G, 8300'))
        self.assertTrue(any('--typecode=1:8300' in cmd
                            for cmd in self.sp.all_cmds()))
