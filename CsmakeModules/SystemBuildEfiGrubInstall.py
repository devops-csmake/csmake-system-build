# <copyright>
# (c) Copyright 2018-2019 Cardinal Peak Technologies
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
from CsmakeModules.SystemBuildGrubInstall import SystemBuildGrubInstall
import os.path
import subprocess
import tempfile

class SystemBuildEfiGrubInstall(SystemBuildGrubInstall):
    """Purpose: Install grub for UEFI
                system must be mounted.
       Implements: SystemBuildGrubInstall
       Type: Module   Library: csmake-system-build
       Phases:
           build, system_build
       Options:
           system - The SystemBuild system to make bootable
           efi-directory - Mounted path of the efi partition
           efi-boot-name - (OPTIONAL) Name to use for boot loader name
                 DEFAULT: boot
       Notes:
           GPT partition table is assumed
    """

    REQUIRED_OPTIONS = ['system', 'efi-directory']

    GRUB_TARGET_OPTION = ['--target', 'x86_64-efi']
    #TODO: Make GRUB_OPTIONS dynamic from init, initialized from the static
    GRUB_OPTIONS = ['-v', '--no-floppy', '--recheck', '--no-nvram']

    def system_build(self, options):
        return self.build(options)

    def build(self, options):
        self.GRUB_OPTIONS.extend(['--efi-directory', options['efi-directory']])
        bootName = 'boot'
        if 'boot-name' in options:
            bootName = options['boot-name']
        self.GRUB_OPTIONS.extend(['--bootloader-id', bootName])
        result = SystemBuildGrubInstall.build(self, options)
        pathToEfi = os.path.join('/EFI', bootName, 'grubx64.efi')
        pathToStartup = os.path.join(
            self.systemPartition,
            options['efi-directory'].strip('/'),
            'startup.nsh')
        with tempfile.NamedTemporaryFile(delete=False) as startup:
            startup.write(pathToEfi.encode('utf-8'))
            filename = startup.name
        result = subprocess.call(
            ['sudo', 'mv', filename, pathToStartup],
            stdout=self.log.out(),
            stderr=self.log.err())
