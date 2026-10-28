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
from CsmakeCore.CsmakeAspect import CsmakeModule
import re

class SystemBuild(CsmakeModule):
    """Purpose: Set up a system (computer/os install) build.
       Library: csmake-system-build
       Phases: build, system_build, use_system_build 
                 - create the definition of the system
                   NOTE: When SystemBuild is used as a regular section,
                       SystemBuildEnd must be called before exiting.
       JoinPoints:
               start__build, start__system_build, start__use_system_build -
                     Will wrapper a section with the releant info for the given
                     system
                   NOTE: Multiple aspects on a section are not guaranteed
                         to execute in a given order
                   Also: It may be a little awkward to have the system
                         build occur as a cross-cutting concern
                         if that's the primary function of the build...
                         on the other hand, ensuring resorces are only
                         reserved for the exact part of the build
                         that is relevant can be done easily by using this
                         section as an aspect on the relevant
                         command or subcommand section
               end__build, end__system_build, end__use_system_build
                     Will end the wrappering for the system build and
                     free resources related to the system build.

       Options:
           system - A build internal name for the system being created
                    (this is *not* necessarily a host name - just an id so that
                     several systems can be built at the same time)
       Environment:
           __SystemBuild_<system>__ is created that will house all of the
               configuration information for the system.
               The entry is a dictionary:
                   system: pointer to the proper instance of this
                           module for the given system name
                   cleanup_methods: list of methods to call on cleanup
                           of the environment.
                           It is required that these methods be idempotent.
                           The methods will be executed in the
                           order added starting with the last
                   recovery_methods: list of methods to call on final csmake
                                     cleanup.
                           The methods will be executed in the order added
                           starting with the first.
    """

    REQUIRED_OPTIONS = ['system']

    def __init__(self, env, log):
        CsmakeModule.__init__(self, env, log)
        self.recovery_methods = []

    def _onExit(self):
        self._cleanupSystem()

    def _getEnvKey(self, system):
        return '__SystemBuild_%s__' % system

    def _getSizeInBytes(self, sizestr):
        matches = re.match(r"([0-9]*)([GMK]?)", sizestr)
        if matches is None:
            raise ValueError("size incorrectly specified: %s" % sizestr)
        groups = matches.groups()
        if len(groups) != 2 or len(groups[0]) ==0:
            raise ValueError("size incorrectly specified: %s" % sizestr)
        sizeUnit = groups[1]
        sizeValue = int(groups[0])
        if sizeUnit == 'G':
            endvalue = sizeValue *1024 *1024 *1024
        elif sizeUnit == 'M':
            endvalue = sizeValue *1024 *1024
        elif sizeUnit == 'K':
            endvalue = sizeValue *1024
        else:
            endvalue = sizeValue
        return endvalue

    def use_system_build(self, options):
        return self.build(options)
    def system_build(self, options):
        return self.build(options)
    def build(self, options):
        system = options['system']
        self.system = system
        key = self._getEnvKey(system)
        if key in self.env.env:
            self.log.error("Duplicate system: %s", system)
            self.log.failed()
            return None
        self.env.env[key] = {
            'system': self,
            'cleanup_methods': [],
            'recovery_methods' : [] }
        self._registerOnExitCallback('_onExit')
        self.log.passed()
        return self.env.env[key]

    def start__use_system_build(self, phase, options, step, stepoptions):
        return self.start__build(phase, options, step, stepoptions)
    def start__system_build(self, phase, options, step, stepoptions):
        return self.start__build(phase, options, step, stepoptions)
    def start__build(self, phase, options, step, stepoptions):
        return self.build(options)

    def end__use_system_build(self, phase, options, step, stepoptions):
        return self.end__build(phase, options, step, stepoptions)
    def end__system_build(self, phase, options, step, stepoptions):
        return self.end__build(phase, options, step, stepoptions)
    def end__build(self, phase, options, step, stepoptions):
        return self._cleanupSystem

    def _cleanupSystem(self):
        self._unregisterOnExitCallback('_onExit')
        key = self._getEnvKey(self.system)
        if key not in self.env.env:
            self.log.passed()
            return None
        #We want to do the methods in reverse but keep the original intact.
        methods = list(self.env.env[key]['cleanup_methods'])
        methods.reverse()
        for r in methods:
            r()
        if len(self.env.env[key]['recovery_methods']) != 0:
            self.recovery_methods.extend(self.env.env[key]['recovery_methods'])
            self._registerOnExitCallback('_onRecovery')
        else:
            del self.env.env[key]

    def _onRecovery(self):
        key = self._getEnvKey(self.system)
        for r in self.recovery_methods:
            r()
