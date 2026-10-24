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
"""SystemBuildGrubInstall (BIOS grub2): locating the boot disk, editing
/etc/default/grub, update-grub and grub-install through chroot.  chmod,
chroot and the stat calls are mocked at their boundaries; the edited
default-grub file is real temp-dir file I/O because the file content is
what is under test."""
import os
import shutil
import stat
import subprocess
import tempfile
import types
from unittest import mock

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.SystemBuildGrubInstall import SystemBuildGrubInstall
from tests.helpers import (REGULAR, SAMPLE_FILESYSTEM, SubprocessTestCase,
                           new_module, patch_stat)

KEY = '__SystemBuild_demo__'
GRUB_DEFAULT = (
    '# If you change this file, run update-grub\n'
    'GRUB_TIMEOUT=5\n'
    'GRUB_CMDLINE_LINUX="quiet splash"\n'
    'GRUB_TERMINAL=console\n')


def system_entry(mount='/build/mnt'):
    return {
        'filesystem': dict(SAMPLE_FILESYSTEM),
        'filesystem-info': {'/': 'root-info', '/boot': 'boot-info',
                            '/boot/efi': 'efi-info', '/home': 'home-info'},
        'mountInstance': types.SimpleNamespace(
            _systemMountLocation=lambda: mount),
        'disks': {
            # an lvm-style disk first: not real, and must not match
            'var': {'device': '/dev/data/var', 'real': False},
            'sda': {'device': '/dev/loop3', 'real': True},
        },
    }


class GrubTestCase(SubprocessTestCase):
    MODULE = SystemBuildGrubInstall

    def setUp(self):
        SubprocessTestCase.setUp(self)
        self.system = system_entry()
        self.module = new_module(self.MODULE, log=self.log,
                                 env={'sys': self.system, KEY: self.system})


class TestSudoChangeFilePerms(GrubTestCase):

    def test_sudo_change_file_perms_returns_the_old_permission_digits(self):
        patch_stat(self, {'/etc/grub': (REGULAR, 0),
                          '/bin/x': (stat.S_IFREG | 0o4755, 0)})
        self.assertEqual(self.module._sudo_change_file_perms('/etc/grub', '0666'), '644')
        self.assertEqual(self.module._sudo_change_file_perms('/bin/x', '700'), '755')

    def test_sudo_change_file_perms_runs_chmod_through_sudo(self):
        patch_stat(self, {'/etc/grub': (REGULAR, 0)})
        self.module._sudo_change_file_perms('/etc/grub', '0666')
        self.assertEqual(self.sp.calls[0].argv, ['sudo', 'chmod', '0666', '/etc/grub'])

    def test_sudo_change_file_perms_chmod_failure_propagates(self):
        patch_stat(self, {'/etc/grub': (REGULAR, 0)})
        self.sp.on('chmod', rc=1)
        with self.assertRaises(subprocess.CalledProcessError):
            self.module._sudo_change_file_perms('/etc/grub', '0666')

    def test_sudo_change_file_perms_missing_file_raises_before_chmod(self):
        patch_stat(self, {})
        with self.assertRaises(FileNotFoundError):
            self.module._sudo_change_file_perms('/etc/grub', '0666')
        self.assertEqual(self.sp.calls, [])

    def test_sudo_change_file_perms_requires_a_str_mask(self):
        with self.assertRaises(AssertionError):
            self.module._sudo_change_file_perms('/etc/grub', 666)


class TestEditDefaultGrub(GrubTestCase):

    def setUp(self):
        GrubTestCase.setUp(self)
        # tempfile resolves its directory lazily with os.stat; do it first
        tempfile.gettempdir()
        self.root = tempfile.mkdtemp(prefix='grubtest')
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, 'etc', 'default'))
        self.path = os.path.join(self.root, 'etc', 'default', 'grub')
        self.write(GRUB_DEFAULT)
        self.stats = patch_stat(self, {self.path: (REGULAR, 0)})

    def write(self, text):
        with open(self.path, 'w') as handle:
            handle.write(text)

    def read(self):
        with open(self.path) as handle:
            return handle.read()

    def test_edit_default_grub_appends_serial_console_to_the_cmdline(self):
        self.module._edit_default_grub(self.root)
        self.assertEqual(self.read(), GRUB_DEFAULT.replace(
            'GRUB_CMDLINE_LINUX="quiet splash"',
            'GRUB_CMDLINE_LINUX="quiet splash console=tty0 console=ttyS0,38400n8"'))

    def test_edit_default_grub_empty_cmdline_gets_only_the_console(self):
        self.write('GRUB_CMDLINE_LINUX=""\n')
        self.module._edit_default_grub(self.root)
        self.assertEqual(self.read(),
                         'GRUB_CMDLINE_LINUX=" console=tty0 console=ttyS0,38400n8"\n')

    def test_edit_default_grub_without_the_key_leaves_content_unchanged(self):
        self.write('GRUB_TIMEOUT=5\n')
        self.module._edit_default_grub(self.root)
        self.assertEqual(self.read(), 'GRUB_TIMEOUT=5\n')

    def test_edit_default_grub_opens_permissions_then_restores_them(self):
        self.module._edit_default_grub(self.root)
        self.assertEqual(self.sp.all_cmds(), [['chmod', '0666', self.path],
                                              ['chmod', '644', self.path]])

    def test_edit_default_grub_chmod_failure_is_swallowed_and_file_untouched(self):
        self.sp.on('chmod', rc=1)
        self.module._edit_default_grub(self.root)
        self.assertEqual(self.read(), GRUB_DEFAULT)
        self.assertEqual(len(self.log.messages('exception')), 1)
        self.assertEqual(len(self.sp.cmds('chmod')), 1)   # nothing to restore

    def test_edit_default_grub_missing_file_is_swallowed(self):
        del self.stats[self.path]
        self.module._edit_default_grub(self.root)
        self.assertEqual(len(self.log.messages('exception')), 1)
        self.assertEqual(self.sp.calls, [])

    def test_edit_default_grub_restore_failure_fails_and_raises(self):
        self.sp.on('chmod', '644', rc=1)
        with self.assertRaises(subprocess.CalledProcessError):
            self.module._edit_default_grub(self.root)
        self.assertEqual(self.log.results, ['failed'])


class TestGetSystemBuildProperties(GrubTestCase):

    def test_properties_prefer_the_boot_filesystem_disk(self):
        self.assertTrue(self.module._getSystemBuildProperties('sys'))
        m = self.module
        self.assertEqual(m.systemDevice, '/dev/loop3')
        self.assertIs(m.systemDeviceObject, self.system['disks']['sda'])
        self.assertEqual(m.systemPathToSystemDevice, '/boot')
        self.assertEqual(m.systemFileSystemObject, SAMPLE_FILESYSTEM['/boot'])
        self.assertEqual(m.systemDeviceInfo, 'boot-info')
        self.assertEqual(m.rootTabId, 'LABEL=root')
        self.assertEqual(m.systemPartition, '/build/mnt')

    def test_properties_without_boot_use_the_root_filesystem(self):
        del self.system['filesystem']['/boot']
        self.assertTrue(self.module._getSystemBuildProperties('sys'))
        self.assertEqual(self.module.systemPathToSystemDevice, '/')
        self.assertEqual(self.module.systemDeviceInfo, 'root-info')

    def test_properties_undefined_system_fails(self):
        self.assertFalse(self.module._getSystemBuildProperties('missing'))
        self.assertEqual(self.log.results, ['failed'])

    def test_properties_system_without_filesystem_fails(self):
        del self.system['filesystem']
        self.assertFalse(self.module._getSystemBuildProperties('sys'))
        self.assertEqual(self.log.results, ['failed'])

    def test_properties_unmounted_system_fails(self):
        del self.system['mountInstance']
        self.assertFalse(self.module._getSystemBuildProperties('sys'))
        self.assertEqual(self.log.results, ['failed'])

    def test_properties_boot_on_a_logical_volume_fails(self):
        self.system['filesystem']['/boot'] = ('/boot', '/dev/data/var', 'ext2', 'x')
        self.assertFalse(self.module._getSystemBuildProperties('sys'))
        self.assertIn('/boot is not on a real disk (/dev/data/var) - this is not supported',
                      self.log.messages('error'))

    def test_properties_boot_without_any_matching_disk_fails(self):
        self.system['filesystem']['/boot'] = ('/boot', '/dev/other1', 'ext2', 'x')
        self.assertFalse(self.module._getSystemBuildProperties('sys'))
        self.assertEqual(self.log.results, ['failed'])

    def test_properties_missing_root_filesystem_fails(self):
        del self.system['filesystem']['/']
        self.assertFalse(self.module._getSystemBuildProperties('sys'))
        self.assertIn('There is no defined root filesystem', self.log.messages('error'))

    def test_properties_root_on_a_logical_volume_fails(self):
        del self.system['filesystem']['/boot']
        self.system['filesystem']['/'] = ('/', '/dev/data/var', 'ext4', 'x')
        self.assertFalse(self.module._getSystemBuildProperties('sys'))
        self.assertEqual(self.log.results, ['failed'])

    def test_properties_root_without_any_matching_disk_fails(self):
        del self.system['filesystem']['/boot']
        self.system['filesystem']['/'] = ('/', '/dev/other1', 'ext4', 'x')
        self.assertFalse(self.module._getSystemBuildProperties('sys'))
        self.assertEqual(self.log.results, ['failed'])


class TestGrubCommands(GrubTestCase):

    def setUp(self):
        GrubTestCase.setUp(self)
        patcher = mock.patch.object(SystemBuildGrubInstall, 'GRUB_OPTIONS',
                                    ['-v', '--no-floppy'])
        patcher.start()
        self.addCleanup(patcher.stop)
        self.module.systemPartition = '/build/mnt'
        self.module.systemDevice = '/dev/loop3'
        self.module._edit_default_grub = mock.Mock()

    def test_generate_grub_config_edits_defaults_then_runs_update_grub(self):
        self.assertTrue(self.module._generateGrubConfig())
        self.module._edit_default_grub.assert_called_once_with('/build/mnt')
        self.assertEqual(self.sp.all_cmds(),
                         [['chroot', '/build/mnt', 'update-grub']])

    def test_generate_grub_config_update_grub_failure_fails(self):
        self.sp.on('chroot', '/build/mnt', 'update-grub', rc=1)
        self.assertFalse(self.module._generateGrubConfig())
        self.assertEqual(self.log.results, ['failed'])

    def test_call_grub_install_prefers_grub2_install_when_present(self):
        self.assertTrue(self.module._callGrubInstall())
        self.assertEqual(self.sp.all_cmds(), [
            ['chroot', '/build/mnt', 'which', 'grub2-install'],
            ['chroot', '/build/mnt', 'grub2-install', '--target', 'i386-pc',
             '-v', '--no-floppy', '/dev/loop3']])

    def test_call_grub_install_falls_back_to_grub_install(self):
        self.sp.on('chroot', '/build/mnt', 'which', rc=1)
        self.assertTrue(self.module._callGrubInstall())
        self.assertEqual(self.sp.all_cmds()[-1][2], 'grub-install')

    def test_call_grub_install_failure_fails(self):
        self.sp.on('chroot', '/build/mnt', 'grub2-install', rc=1)
        self.assertFalse(self.module._callGrubInstall())
        self.assertEqual(self.log.results, ['failed'])


class TestBuildOrchestration(GrubTestCase):
    """build() sequencing, with each step stubbed so only the flow is tested."""

    def setUp(self):
        GrubTestCase.setUp(self)
        self.order = []
        for name, result in (('_getSystemBuildProperties', True),
                             ('_prepareForGrubInstall', None),
                             ('_generateGrubConfig', True),
                             ('_callGrubInstall', True),
                             ('_cleanUpPostGrubInstall', None)):
            setattr(self.module, name, self.step(name, result))

    def step(self, name, result):
        def run(*args):
            self.order.append(name)
            return result
        return run

    def test_build_runs_the_steps_in_order_and_passes(self):
        self.assertTrue(self.module.build({'system': 'demo'}))
        self.assertEqual(self.order, [
            '_getSystemBuildProperties', '_prepareForGrubInstall',
            '_generateGrubConfig', '_callGrubInstall', '_cleanUpPostGrubInstall'])
        self.assertEqual(self.log.results, ['passed'])

    def test_build_property_failure_stops_immediately(self):
        self.module._getSystemBuildProperties = self.step('props', False)
        self.assertIsNone(self.module.build({'system': 'demo'}))
        self.assertEqual(self.order, ['props'])

    def test_build_config_failure_skips_install_but_still_cleans_up(self):
        self.module._generateGrubConfig = self.step('config', False)
        self.assertIsNone(self.module.build({'system': 'demo'}))
        self.assertEqual(self.order[-2:], ['config', '_cleanUpPostGrubInstall'])
        self.assertNotIn('_callGrubInstall', self.order)
        self.assertEqual(self.log.results, [])

    def test_build_install_failure_still_cleans_up(self):
        self.module._callGrubInstall = self.step('install', False)
        self.assertIsNone(self.module.build({'system': 'demo'}))
        self.assertEqual(self.order[-2:], ['install', '_cleanUpPostGrubInstall'])

    def test_build_cleans_up_when_a_step_raises(self):
        def explode():
            raise RuntimeError('boom')
        self.module._generateGrubConfig = explode
        with self.assertRaises(RuntimeError):
            self.module.build({'system': 'demo'})
        self.assertEqual(self.order[-1], '_cleanUpPostGrubInstall')

    def test_system_build_delegates_to_build(self):
        self.assertTrue(self.module.system_build({'system': 'demo'}))
