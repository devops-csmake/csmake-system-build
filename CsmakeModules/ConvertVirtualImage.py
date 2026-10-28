# <copyright>
# (c) Copyright 2018 Cardinal Peak Technologies
# (c) Copyright 2017 Hewlett Packard Enterprise Development LP
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
from CsmakeCore.CsmakeModule import CsmakeModule
import subprocess
import os.path
import shlex

class ConvertVirtualImage(CsmakeModule):
    """Purpose: Convert a virtual disk image to a different format
       Library: csmake-system-build
       Phases:
           build, package_vm
       Options:
           extra - extra options to pass to the underlying tool
                   Default is nothing
           compress - If False, does not compress the image
                      Default is True
           tool - qemu-img or vbox-img
                  Default: for target format vmdk and no qcow is vbox-img,
                             everything else: qemu
       Maps:
           Expects a 1-1 mapping where files as disks are converted
           to the requested format.  The file types will inform
           the mapping.
           File Types:
               raw-image - Raw disk image
               vmdk-image - vmdk disk image (vmWare)
               vdi-image - vdi disk image (VirtualBox)
               qcow2-image - qcow2 disk image (KVM)
               vhdx-image - vhdx-image (Hyper V)
               vpc-image - vhd-image (Hyper V older format)
           (Eventually, it would be nice to be able to
            specify multiple parts 1-* and *-1)
       Requires:
           qemu-img
           vbox-img
    """

    def _checkAndCleanImage(self, toImage):
        if os.path.exists(toImage):
            os.remove(toImage)

    def package_vm(self, options):
        return self.build(options)

    def build(self, options):
        if 'tool' in options:
            toolOverride = options['tool'].strip()
        else:
            toolOverride = None

        for froms, tos in  self.mapping.iterspecs():
            if len(froms) > 1 or len(tos) > 1:
                self.log.error("This module can only map 1-1")
                self.log.failed()
                return None
            if 'used-size' in froms[0]:
                tos[0]['used-size'] = froms[0]['used-size']
            imageType = tos[0]['type'].replace('-image', '').upper()
            fromType = froms[0]['type'].replace('-image', '').upper()
            if toolOverride is None:
                if imageType == 'VMDK' and fromType != 'QCOW2':
                    tool = 'vbox-img'
                else:
                    tool = 'qemu-img'
            else:
                tool = toolOverride

            params = [tool]
            if tool.startswith('vbox'):
                self._checkAndCleanImage(tos[0]['location'])
                params.extend([
                    'convert', '--srcformat', fromType,
                               '--dstformat', imageType,
                               '--srcfilename', froms[0]['location'],
                               '--dstfilename', tos[0]['location'],
                               '--variant', "Stream" ] )
            else:
                params.extend([
                    'convert'])
                if 'compress' in options and \
                   options['compress'].strip() == 'False':
                    pass
                else:
                    params.append('-c')
                params.extend([
                     '-f', fromType.lower(),
                     froms[0]['location'],
                     '-O', imageType.lower(),
                     tos[0]['location'] ] )

            if 'extra' in options:
                extra = options['extra'].strip()
                params.extend(shlex.split(extra))

            self.log.debug("Command: %s", str(params))

            result = subprocess.call(
                    params,
                    stdout = self.log.out(),
                    stderr = self.log.err())
            if result != 0:
                self.log.error("Convert of the Virtual Image failed")
                self.log.failed()
                return None

        self.log.passed()
        return True
