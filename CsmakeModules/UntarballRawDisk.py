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

class UntarballRawDisk(CsmakeModule):
    """Purpose: To unpackage a raw disk into a tarball
       Library: csmake-system-build
       Maps: Map a raw disk tarball 1-1 to a directory
       Phases: build
               NOTE: clean is left to another step to ensure
                     results are not accidently deleted
                     (i.e., this step shouldn't "own" the result)
    """

    def build(self, options):
        for froms, tos in self.mapping.iterfiles():
            for source in froms:
                for dest in tos:
                    subprocess.check_call(
                        ['mkdir', '-p', dest],
                        stdout=self.log.out(),
                        stderr=self.log.err() )
                    result = subprocess.call(
                        ['sudo', 'tar', '--numeric-owner', '-xzpvf', source, '-C', dest],
                        stdout=self.log.out(),
                        stderr=self.log.err())

                    if result != 0:
                        self.log.error("Tarball untar failed (%d)", result)
                        self.log.failed()
                        return False

        self.log.passed()
        return True

