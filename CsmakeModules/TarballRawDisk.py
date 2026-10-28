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
import subprocess
import os

class TarballRawDisk(CsmakeModule):
    """Purpose: To package a raw disk into a tarball
       Library: csmake-system-build
       Maps: Map a raw disk directory 1-1 to a tarball
       Phases: package, clean
    """

    def package(self, options):
        currentuid = os.getuid()
        currentgid = os.getgid()
        for froms, tos in self.mapping.iterfiles():
            for source in froms:
                for dest in tos:

                    result = subprocess.call(
                        ['sudo', 'tar', '-czvf', dest, '-C', source, '.' ],
                        stdout=self.log.out(),
                        stderr=self.log.err())

                    if result != 0:
                        self.log.error("Tarball creation failed (%d)", result)
                        self.log.failed()
                        return False

                    subprocess.check_call(
                        ['sudo', 'chown',
                            '%d:%d' % (currentuid, currentgid),
                            dest ] )

        self.log.passed()
        return True

    def clean(self, options):
        self._cleaningFiles()
        for froms, tos in self.mapping.iterfiles():
            for source in froms:
                for dest in tos:
                    if os.path.exists(dest):
                        try:
                            result = os.remove(dest)
                        except:
                            self.log.exception("CLEAN: Could not remove archive")
        self.log.passed()
        return True

