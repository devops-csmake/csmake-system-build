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
import os
import os.path

class InjectDiskUsedToIndex(CsmakeModule):
    """Purpose: Add the current used size (as mounted)
                as an extra axis on in the file tracking.
       Library: csmake-system-build
       Phases:
           build
       Flags:
           mount - path to the mount point to capture
       Mappings:
           use a 1-1 mapping.  The rhs will contain an extra axis called
           'used-size'
           It *must* be a single 1-1 mapping that maps a single file to another
           single file - nothing else makes sense given this section
           maps the mountpoint to a raw disk image in the filetracking.
    """

    REQUIRED_OPTIONS=['mount']

    def build(self, options):
        if self.mapping is None:
            self.log.error("A mapping is required for this section - none was found")
            self.log.failed()
        if len(self.mapping) == 0:
            self.log.error("The mapping did not have anything to map")
            self.log.failed()
            return None
        if len(self.mapping) != 1:
            self.log.error("This section can currently only handle a single 1-1 mapping")
            self.log.failed()
            return None
        for froms, tos in self.mapping.iterspecs():
            if len(froms) != 1 or len(tos) != 1:
                self.log.error("The mapping must be 1-1 and exclusively only map a disk represented by the given mountpoint")
                self.log.failed()
                return None
        statresult = os.statvfs(options['mount'])
        if statresult is not None:
            #Populate the yielded files with extra information
            usedsize =  (statresult.f_frsize * statresult.f_blocks) \
                               - (statresult.f_bsize * statresult.f_bfree)

            tos[0]['used-size'] = usedsize
            self.log.passed()
        else:
            self.log.error("Could not stat file system: '%s'", options['mount'])
            self.log.failed()
        return True
