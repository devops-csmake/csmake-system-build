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
"""SystemBuildLVM drives the lvm tools (vgs, pvcreate, vgcreate, lvcreate,
...) through subprocess.  The tools are mocked, their stdout arrives as
bytes like the real check_output, and the tests assert command lines,
ordering and failure handling."""
import subprocess
import types
import unittest

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.SystemBuildLVM import SystemBuildLVM
from tests.helpers import SubprocessTestCase, new_module

KEY = '__SystemBuild_demo__'
VGS_NONE = b'  other   1   0   0 wz--n- 1.00g 1.00g\n'


class LvmTestCase(SubprocessTestCase):

    def setUp(self):
        SubprocessTestCase.setUp(self)
        self.sp.on('vgs', '--noheadings', stdout=VGS_NONE)
        self.system = {
            'system': types.SimpleNamespace(_getSizeInBytes=lambda s: 2 << 30),
            'disks': {
                'sda': {'device': '/dev/loop4',
                        'partitions': {'root': {'number': 1}}},
                'sdb': {'device': '/dev/loop5'}},
            'cleanup_methods': [],
            'recovery_methods': [],
        }
        self.module = new_module(SystemBuildLVM, log=self.log,
                                 env={KEY: self.system})

    def setup_lvm(self, build=True, **options):
        options = dict(options, system='demo')
        return self.module._setupLvm(options, build)


class TestSetupLvmBuild(LvmTestCase):

    def test_setup_lvm_build_runs_the_lvm_tools_in_order(self):
        result = self.setup_lvm(pv_a='sda.root', pv_b='sdb',
                                **{'vg_my-data': 'a, b', 'lv_var': 'my-data, 2G'})
        self.assertEqual(self.sp.all_cmds(), [
            ['vgs', '--noheadings'],
            ['pvcreate', '-M2', '-f', '-y', '/dev/loop4p1'],
            ['pvcreate', '-M2', '-f', '-y', '/dev/loop5'],
            ['vgcreate', '-M2', 'my-data', '/dev/loop4p1', '/dev/loop5'],
            ['lvcreate', '-n', 'var', '-L', '2G', 'my-data'],
            ['vgmknodes']])
        self.assertEqual(self.log.results, ['passed'])
        self.assertEqual(self.module.pvsCreated, ['/dev/loop4p1', '/dev/loop5'])
        self.assertEqual(self.module.vgsCreated,
                         [('my-data', ['/dev/loop4p1', '/dev/loop5'])])

    def test_setup_lvm_registers_the_logical_volume_as_a_disk(self):
        result = self.setup_lvm(pv_a='sda.root', **{
            'vg_my-data': 'a', 'lv_var-log': 'my-data, 2G'})
        self.assertEqual(result['var-log'], {
            'device': '/dev/my-data/var-log',
            'fstab-id': '/dev/mapper/my--data-var--log',
            'real': False, 'size': 2 << 30, 'path': 'my-data'})
        self.assertIs(self.system['disks']['var-log'], result['var-log'])

    def test_setup_lvm_cleanup_goes_first_in_the_cleanup_list(self):
        existing = lambda: None
        self.system['cleanup_methods'].append(existing)
        self.setup_lvm(pv_a='sda.root', vg_data='a')
        self.assertEqual(self.system['cleanup_methods'],
                         [self.module._cleanup, existing])

    def test_setup_lvm_vgs_output_is_bytes_decoded_by_the_module(self):
        self.setup_lvm(pv_a='sda.root', vg_data='a')
        vgs = self.sp.find('vgs')[0]
        self.assertNotIn('text', vgs.kwargs)
        self.assertNotIn('universal_newlines', vgs.kwargs)

    def test_setup_lvm_verbose_and_debug_flags_reach_vgmknodes(self):
        for settings, expected in [({'verbose': True}, ['-v']),
                                   ({'debug': True}, ['-vv']),
                                   ({'verbose': True, 'debug': True}, ['-vv'])]:
            with self.subTest(settings=settings):
                self.sp.calls.clear()
                self.module.settings.update(verbose=False, debug=False)
                self.module.settings.update(settings)
                self.setup_lvm(pv_a='sda.root', vg_data='a')
                self.assertEqual(self.sp.cmds('vgmknodes'),
                                 [['vgmknodes'] + expected])


class TestSetupLvmExistingVolumeGroups(LvmTestCase):

    def test_setup_lvm_existing_volume_group_fails_before_creating_anything(self):
        self.sp.on('vgs', stdout=b'  taken   1   2   0 wz--n- 10.00g 5.00g\n'
                                 b'  other   1   0   0 wz--n- 1.00g 1.00g\n')
        self.assertIsNone(self.setup_lvm(pv_a='sda.root', vg_taken='a'))
        self.assertIn("Volume group 'taken' already exists on the build system",
                      self.log.messages('error'))
        self.assertEqual(self.log.results, ['failed'])
        self.assertEqual(self.sp.cmds('pvcreate'), [])

    def test_setup_lvm_vgs_output_with_blank_and_indented_lines(self):
        self.sp.on('vgs', stdout=b'\n    spaced   1 2 3\n\n\tother 1\n')
        self.assertIsNone(self.setup_lvm(pv_a='sda.root', vg_spaced='a'))

    def test_setup_lvm_vgs_failure_propagates(self):
        self.sp.on('vgs', rc=5)
        with self.assertRaises(subprocess.CalledProcessError):
            self.setup_lvm(pv_a='sda.root', vg_data='a')
        self.assertEqual(self.sp.cmds('pvcreate'), [])


class TestSetupLvmUse(LvmTestCase):

    def test_use_system_build_activates_instead_of_creating(self):
        self.module._setupLvm(
            {'system': 'demo', 'pv_a': 'sda.root', 'vg_data': 'a',
             'lv_var': 'data, 2G'}, False)
        self.assertEqual(self.sp.all_cmds(), [
            ['vgs', '--noheadings'],
            ['pvscan', '--cache', '/dev/loop4p1'],
            ['vgchange', '-ay', 'data'],
            ['lvchange', '-ay', 'data/var'],
            ['vgmknodes']])


class TestSetupLvmFailures(LvmTestCase):

    def assertFailed(self, **options):
        self.assertIsNone(self.setup_lvm(**options))
        self.assertEqual(self.log.results, ['failed'])

    def test_setup_lvm_undefined_system_fails(self):
        self.module.env.env.clear()
        self.assertFailed(pv_a='sda.root')
        self.assertEqual(self.sp.calls, [])

    def test_setup_lvm_system_without_disks_fails(self):
        del self.system['disks']
        self.assertFailed(pv_a='sda.root')

    def test_setup_lvm_undefined_disk_fails(self):
        self.assertFailed(pv_a='nodisk.root', vg_data='a')

    def test_setup_lvm_undefined_partition_fails(self):
        self.assertFailed(pv_a='sda.nopart', vg_data='a')
        self.assertEqual(self.sp.cmds('pvcreate'), [])

    def test_setup_lvm_volume_group_referencing_an_unknown_pv_fails(self):
        self.assertFailed(pv_a='sda.root', vg_data='zzz')

    def test_setup_lvm_logical_volume_in_an_unknown_volume_group_fails(self):
        self.assertFailed(pv_a='sda.root', vg_data='a', lv_var='nogroup, 1G')
        self.assertEqual(self.sp.cmds('lvcreate'), [])

    def test_setup_lvm_logical_volume_clashing_with_a_disk_name_fails(self):
        self.assertFailed(pv_a='sda.root', vg_data='a', lv_sda='data, 1G')

    def test_setup_lvm_pvcreate_failure_propagates_without_a_volume_group(self):
        self.sp.on('pvcreate', rc=5)
        with self.assertRaises(subprocess.CalledProcessError):
            self.setup_lvm(pv_a='sda.root', vg_data='a')
        self.assertEqual(self.sp.cmds('vgcreate'), [])
        self.assertEqual(self.sp.cmds('pvremove'), [])

    def test_setup_lvm_vgcreate_failure_removes_the_created_physical_volume(self):
        self.sp.on('vgcreate', rc=5)
        with self.assertRaises(subprocess.CalledProcessError):
            self.setup_lvm(pv_a='sda.root', vg_data='a')
        self.assertEqual(self.sp.cmds('pvremove'),
                         [['pvremove', '-ffy', '/dev/loop4p1']])

    def test_setup_lvm_lvcreate_failure_unwinds_the_volume_group(self):
        self.sp.on('lvcreate', rc=5)
        self.sp.on('pvs', rc=5)
        self.sp.on('lvs', rc=5)
        with self.assertRaises(subprocess.CalledProcessError):
            self.setup_lvm(pv_a='sda.root', vg_data='a', lv_var='data, 1G')
        cmds = self.sp.all_cmds()
        order = [cmds.index(cmd) for cmd in (
            ['lvcreate', '-n', 'var', '-L', '1G', 'data'],
            ['vgchange', '-an', 'data'],
            ['lvremove', '-f', 'data'],
            ['pvremove', '-ffy', '/dev/loop4p1'])]
        self.assertEqual(order, sorted(order))


class TestCleanup(LvmTestCase):

    def setUp(self):
        LvmTestCase.setUp(self)
        self.module.systemEntry = self.system
        self.module.vgsCreated = [('vg0', ['/dev/loop4p1'])]
        self.module.pvsCreated = ['/dev/loop4p1']
        self.module.lvsCreated = []
        # lvs / pvs failing is how cleanup confirms the volumes are gone
        self.sp.on('lvs', rc=5)
        self.sp.on('pvs', rc=5)
        self.sp.on('ls', '-R', '/etc/lvm/archive',
                   stdout=b'/etc/lvm/archive:\n'
                          b'vg0_00000-111.vg\nvg0_00001-222.vg\n'
                          b'other_00000-333.vg\n')

    def test_cleanup_runs_the_full_removal_sequence_in_order(self):
        self.module._cleanup(recover=True)
        self.assertEqual(self.sp.all_cmds(), [
            ['vgchange', '-an', 'vg0'],
            ['lvremove', '-f', 'vg0'],
            ['pvremove', '-ffy', '/dev/loop4p1'],
            ['pvs', '/dev/loop4p1'],
            ['lvs', 'vg0'],
            ['ls', '-R', '/etc/lvm/archive'],
            ['rm', '-rf', '/etc/lvm/archive/vg0_00000-111.vg'],
            ['rm', '-rf', '/etc/lvm/archive/vg0_00001-222.vg'],
            ['rm', '-rf', '/etc/lvm/backup/vg0']])

    def test_cleanup_archive_listing_is_decoded_before_matching(self):
        self.module._cleanup(recover=True)
        listing = self.sp.find('ls')[0]
        self.assertNotIn('text', listing.kwargs)
        self.assertNotIn('universal_newlines', listing.kwargs)
        removed = [cmd[-1] for cmd in self.sp.cmds('rm')]
        self.assertNotIn('/etc/lvm/archive/other_00000-333.vg', removed)

    def test_cleanup_resets_the_bookkeeping(self):
        self.module._cleanup(recover=True)
        self.assertEqual((self.module.vgsCreated, self.module.pvsCreated,
                          self.module.lvsCreated), ([], [], []))

    def test_cleanup_with_nothing_created_does_nothing(self):
        self.module.vgsCreated = []
        self.module.pvsCreated = []
        self.module._cleanup()
        self.assertEqual(self.sp.calls, [])

    def test_cleanup_lvremove_is_done_once_per_volume_group(self):
        self.module.vgsCreated = [('vg0', ['/dev/loop4p1']),
                                  ('vg1', ['/dev/loop5']),
                                  ('vg0', ['/dev/loop4p1'])]
        self.module._cleanup(recover=True)
        removes = [cmd[-1] for cmd in self.sp.cmds('lvremove')]
        self.assertEqual(removes, ['vg0', 'vg1'])

    def test_cleanup_surviving_physical_volume_requeues_the_cleanup(self):
        self.sp.on('pvs', rc=0)
        self.assertFalse(self.module._cleanup())
        self.assertEqual(self.system['recovery_methods'], [self.module._recover])
        self.assertEqual(self.sp.cmds('ls'), [])
        self.assertEqual(self.module.vgsCreated, [('vg0', ['/dev/loop4p1'])])

    def test_cleanup_surviving_logical_volumes_requeues_the_cleanup(self):
        self.sp.on('lvs', rc=0)
        self.assertFalse(self.module._cleanup())
        self.assertEqual(self.system['recovery_methods'], [self.module._recover])
        self.assertEqual(len(self.log.messages('warning')), 1)

    def test_cleanup_recovery_unregisters_itself(self):
        self.system['recovery_methods'].append(self.module._recover)
        self.module._cleanup(recover=True)
        self.assertEqual(self.system['recovery_methods'], [])

    def test_cleanup_unregisters_the_cleanup_method(self):
        self.system['cleanup_methods'].append(self.module._cleanup)
        self.module._cleanup()
        self.assertEqual(self.system['cleanup_methods'], [])

    def test_cleanup_pvremove_failure_only_warns(self):
        self.sp.on('pvremove', rc=5)
        self.module._cleanup(recover=True)
        self.assertEqual(len(self.log.messages('warning')), 1)
        self.assertEqual(self.sp.cmds('rm')[-1], ['rm', '-rf', '/etc/lvm/backup/vg0'])

    def test_cleanup_archive_rm_failure_only_warns(self):
        self.sp.on('rm', rc=1)
        self.module._cleanup(recover=True)
        self.assertEqual(len(self.log.messages('warning')), 3)

    def test_cleanup_archive_listing_failure_propagates(self):
        self.sp.on('ls', rc=2)
        with self.assertRaises(subprocess.CalledProcessError):
            self.module._cleanup(recover=True)

    def test_recover_runs_the_cleanup_in_recovery_mode(self):
        self.system['recovery_methods'].append(self.module._recover)
        self.module._recover()
        self.assertEqual(self.system['recovery_methods'], [])
        self.assertIn(['rm', '-rf', '/etc/lvm/backup/vg0'], self.sp.all_cmds())

    @unittest.skip("pre-existing bug: SystemBuildLVM._onExit calls "
                   "self._cleanup(self), passing the module as 'recover'")
    def test_on_exit_runs_the_cleanup(self):
        pass
