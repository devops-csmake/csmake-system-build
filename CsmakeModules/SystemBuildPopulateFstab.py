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
from Csmake.CsmakeModule import CsmakeModule
import subprocess
import os.path
import os

class SystemBuildPopulateFstab(CsmakeModule):
    """Purpose: Set up the fstab on the given system
                Assumes that SystemBuildFileSystem was already completed
       Library: csmake-system-build
       Phases: build, system_build - create the file and definition
       Options:
           system - Name of the system to add the fstab to
       Environment:
           __SystemBuild_<system>__ is referenced - it is an error
              to not have the referenced system defined
    """
    REQUIRED_OPTIONS = ['system']

    def _getEnvKey(self, system):
        return '__SystemBuild_%s__' % system

    def system_build(self, options):
        return self.build(options)

    def build(self, options):
        system = options['system']
        self.system = system
        key = self._getEnvKey(system)
        if key not in self.env.env:
            self.log.error("System '%s' is not defined", system)
            self.log.failed()
            return None
        systemEntry = self.env.env[key]
        if 'filesystem' not in systemEntry:
            self.log.error("System '%s' does not have a filesystem", system)
            self.log.failed()
            return None
        fsEntry = systemEntry['filesystem']
        if 'mountInstance' not in systemEntry:
            self.log.error("System '%s' is not mounted, and must be to write the fstab", system)
            self.log.failed()
            return None
        mountLocation = systemEntry['mountInstance']._systemMountLocation()
        lines = []
        mountpts = list(fsEntry.keys())
        mountpts.sort()
        for mountptkey in mountpts:
            mountpt, device, fstype, fstabid = fsEntry[mountptkey]
            #TODO: Figure out better way to determine parms, dump, pass
            lines.append("%s\t%s\t%s\t%s\t%d\t%d\n" % (
                fstabid,
                mountpt,
                fstype,
                "noatime,errors=remount-ro",
                0,
                1 ) )
        swappts = []
        for disk in systemEntry['disks'].values():
            if 'swaps' in disk:
                swappts.extend(disk['swaps'])
        for swaplabel, swappart in swappts:
            lines.append("%s\tswap\tswap\tdefaults\t0\t0\n" % swappart['fstab-id'])
        templocation = os.path.join(
            self.env.env['RESULTS'],
            'temp_etc_fstab')
        with open(templocation, "w" ) as tempfstab:
            for line in lines:
                tempfstab.write(line)

        fstablocation = os.path.join(
            mountLocation,
            'etc/fstab' )

        subprocess.check_call(
            ['sudo', 'mv', templocation, fstablocation],
            stdout = self.log.out(),
            stderr = self.log.err() )

        subprocess.check_call(
            ['sudo', 'chown', '0:0', fstablocation],
            stdout = self.log.out(),
            stderr = self.log.err() )

        subprocess.check_call(
            ['sudo', 'chmod', '644', fstablocation],
            stdout = self.log.out(),
            stderr = self.log.err() )

        self.log.passed()
        return lines
