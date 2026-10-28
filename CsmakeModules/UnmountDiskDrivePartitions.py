# <copyright>
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
from CsmakeModules.MountDiskDrivePartitions import MountDiskDrivePartitions
import os
import os.path

class UnmountDiskDrivePartitions(CsmakeModule):
    """Purpose: Unmount MountDiskDrivePartitions
       Library: csmake-system-build
       Options:
           tag - (OPTIONAL) Unmount the tagged mount
                     (Must match the 'tag' option in MountDiskDrivePartitions)
                     Default: <nothing>
       Phases:
           build
    """

    def build(self, options):
        taggedEnvKey = MountDiskDrivePartitions.ENVKEY
        if 'tag' in options:
            taggedEnvKey += options['tag']
        if taggedEnvKey not in self.env.env:
            self.log.error(
                "Attempting to unmount tag: '%s' - but it is not mounted",
                options['tag'] if 'tag' in options else '<nothing' )
            self.log.failed()
            return None
        mountdict = self.env.env[taggedEnvKey]
        mounterInstance = mountdict['instance']
        if mounterInstance._cleanUpMounts():
            self.log.passed()
        else:
            self.log.failed()
