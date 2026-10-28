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

class CopyRawImage(CsmakeModule):
    """Purpose: Copy a raw image directory into another directory
                (Useful for copying a raw image sitting on the filesystem
                   to a partition)
                It is best to do this step without a system-label
                   mounted partition.
       Library: csmake-system-build
       Phases:
           build
       Mappings:  Directories on the left will be placed to the right
                  An empty mapping will fail - it is assumed that
                  this section is required to do *something*
       Options:
           preserve: (OPTIONAL) comma separated list of attributes to
                  preserve.  Attributes can be mode, ownership, timestamps
                                               context, links, xattr, all
                  Default: all
    """

    def build(self, options):
        if len(self.mapping) == 0:
            self.log.error("Nothing specified to copy")
            self.log.failed()
            return None
        attributes = '-a'
        if 'preserve' in options:
            attributes = '-dR --preserve={}'.format(options['preserve'].strip().replace(' ',''))
        for froms, tos in self.mapping.iterfiles():
            for source in froms:
                for destination in tos:
                    #Ensure that /dev/shm is empty on the resulting build
                    devshmpath = os.path.join(
                        source,
                        "dev",
                        "shm" )
                    if os.path.exists(devshmpath):
                        self.log.info("Removing /dev/shm from the raw image")
                        result = subprocess.call(
                            ['sudo', 'rm', '-rf', devshmpath],
                            stdout=self.log.out(),
                            stderr=self.log.err())
                        if result != 0:
                            self.log.warning("Could not remove /dev/shm from the raw image")
                    #CONSIDER: Build avoidance
                    copyImage = True
                    if copyImage:
                        self.log.info("Copying %s to %s", source, destination)
                        result = subprocess.call(
                            'sudo cp -t %s %s %s/*' % (
                                destination,
                                attributes,
                                source ),
                            stdout=self.log.out(),
                            stderr=self.log.err(),
                            shell=True )
                        if result != 0:
                            self.log.error("Transfer of the image to the mounted filesystem failed")
                            self.log.failed()
                            return None
                    else:
                        self.log.info("Skipping build copy - build avoidance")

        self.log.passed()
        return True
