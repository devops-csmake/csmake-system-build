# <copyright>
# (c) Copyright 2019 Autumn Samantha Jeremiah Patterson
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
from CsmakeModules.SystemBuild import SystemBuild
import os
import os.path

class SystemBuildEnd(CsmakeModule):
    """Purpose: End the SystemBuild process and clean up resources
          For use only when [SystemBuild@...] is a normal section
       Library: csmake-system-build
       Options:
           system - The system to end building
       Phases:
           build, system_build, use_system_build
    """
    REQUIRED_OPTIONS = ['system']

    def _getEnvKey(self, system):
        return '__SystemBuild_%s__' % system

    def use_system_build(self, options):
        self.build(options)
    def system_build(self, options):
        self.build(options)
    def build(self, options):
        key = self._getEnvKey(options['system'])
        if key not in self.env.env:
            self.log.warning("The system '%s' was not found", options['system'])
            self.log.passed()
            return
        systemEntry = self.env.env[key]
        systemInstance = systemEntry['system']
        systemInstance._cleanupSystem()
        self.log.passed()
