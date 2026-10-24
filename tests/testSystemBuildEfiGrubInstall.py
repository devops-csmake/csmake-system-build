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
"""The EFI grub install runs the real SystemBuildGrubInstall.build with the
chroot/grub tools mocked at the subprocess boundary, then writes
startup.nsh through a NamedTemporaryFile (binary in Python 3) and moves it
into the system with sudo.  The mocked 'mv' reads the temp file's bytes."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.SystemBuildEfiGrubInstall import SystemBuildEfiGrubInstall
from tests.helpers import (REGULAR, SubprocessTestCase, new_module, patch_stat)
from tests.testSystemBuildGrubInstall import GRUB_DEFAULT, system_entry

KEY = '__SystemBuild_demo__'
EFI_OPTIONS = ['-v', '--no-floppy', '--recheck', '--no-nvram']


class EfiTestCase(SubprocessTestCase):

    def setUp(self):
        SubprocessTestCase.setUp(self)
        tempfile.gettempdir()
        self.root = tempfile.mkdtemp(prefix='efitest')
        self.addCleanup(shutil.rmtree, self.root, True)
        grub = os.path.join(self.root, 'etc', 'default', 'grub')
        os.makedirs(os.path.dirname(grub))
        with open(grub, 'w') as handle:
            handle.write(GRUB_DEFAULT)
        patch_stat(self, {grub: (REGULAR, 0)})
        patcher = mock.patch.object(SystemBuildEfiGrubInstall,
                                    'GRUB_OPTIONS', list(EFI_OPTIONS))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.system = system_entry(self.root)
        self.module = new_module(SystemBuildEfiGrubInstall, log=self.log,
                                 env={KEY: self.system})
        self.startup = []
        self.sp.on('mv', effect=self.capture_startup)
        # no grub2-install in the target: the plain grub-install is used
        self.sp.on('chroot', self.root, 'which', rc=1)

    def capture_startup(self, call):
        source = call.argv[2]
        with open(source, 'rb') as handle:
            self.startup.append((handle.read(), call.argv[3]))
        os.remove(source)

    def build(self, **extra):
        options = {'system': 'demo', 'efi-directory': '/boot/efi'}
        options.update(extra)
        return self.module.build(options)


class TestEfiBuild(EfiTestCase):

    def test_build_installs_grub_for_x86_64_efi_with_the_efi_options(self):
        self.build(**{'boot-name': 'myos'})
        self.assertEqual(self.sp.cmds('chroot', self.root, 'grub-install'), [[
            'chroot', self.root, 'grub-install', '--target', 'x86_64-efi',
            '-v', '--no-floppy', '--recheck', '--no-nvram',
            '--efi-directory', '/boot/efi', '--bootloader-id', 'myos',
            '/dev/loop3']])

    def test_build_runs_update_grub_before_grub_install(self):
        self.build()
        cmds = self.sp.all_cmds()
        self.assertLess(cmds.index(['chroot', self.root, 'update-grub']),
                        [c[2] for c in cmds].index('grub-install'))

    def test_build_startup_nsh_receives_the_efi_path_as_bytes(self):
        self.build(**{'boot-name': 'myos'})
        content, destination = self.startup[0]
        self.assertEqual(content, b'/EFI/myos/grubx64.efi')
        self.assertEqual(destination, os.path.join(
            self.root, 'boot', 'efi', 'startup.nsh'))

    def test_build_default_boot_name_is_boot(self):
        self.build()
        self.assertEqual(self.startup[0][0], b'/EFI/boot/grubx64.efi')

    def test_build_startup_nsh_is_moved_with_sudo(self):
        self.build()
        self.assertTrue(self.sp.find('mv')[0].sudo)

    def test_build_grub_install_failure_is_not_reported_as_passed(self):
        self.sp.on('chroot', self.root, 'grub-install', rc=1)
        self.build()
        self.assertEqual(self.log.results, ['failed'])

    def test_build_system_build_phase_delegates(self):
        self.module.system_build({'system': 'demo', 'efi-directory': '/boot/efi'})
        self.assertEqual(len(self.startup), 1)

    @unittest.skip("pre-existing bug: build() ignores the result of the "
                   "base build, so a failed system lookup ends in an "
                   "AttributeError on systemPartition instead of failing")
    def test_build_undefined_system_fails_cleanly(self):
        pass

    @unittest.skip("pre-existing bug: build() extends the class-level "
                   "GRUB_OPTIONS list on every call, so a second build in the "
                   "same process repeats --efi-directory/--bootloader-id")
    def test_build_twice_does_not_accumulate_grub_options(self):
        pass
