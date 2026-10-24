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
"""The EFI grub install writes startup.nsh through a NamedTemporaryFile,
which is a binary file in Python 3, then moves it into the system with sudo.
Real grub installation needs root, so the grub-install half of build() is
stubbed out and the fake 'mv' (run by the fake sudo) keeps the file."""
import os
from unittest import mock

from tests import csmake_alias
csmake_alias.install()

from CsmakeModules.SystemBuildEfiGrubInstall import SystemBuildEfiGrubInstall
from CsmakeModules.SystemBuildGrubInstall import SystemBuildGrubInstall
from tests.helpers import FakeBinTestCase, read_bytes


class TestEfiStartupScript(FakeBinTestCase):

    def test_startup_nsh_receives_the_efi_path_as_bytes(self):
        captured = os.path.join(self.tmp, 'captured-startup.nsh')
        # Take the temp file the module wrote, like the real mv would
        self.bin.add('mv', extra='/bin/mv "$1" "%s"' % captured)
        module = object.__new__(SystemBuildEfiGrubInstall)
        module.log = self.log
        module.systemPartition = '/build/mnt'

        with mock.patch.object(SystemBuildGrubInstall, 'build',
                               return_value=True), \
             mock.patch.object(SystemBuildEfiGrubInstall, 'GRUB_OPTIONS', []):
            module.build({'system': 'demo', 'efi-directory': '/boot/efi',
                          'boot-name': 'myos'})

        self.assertEqual(read_bytes(captured), b'/EFI/myos/grubx64.efi')
        moves = self.bin.calls('mv')
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0][2], '/build/mnt/boot/efi/startup.nsh')
