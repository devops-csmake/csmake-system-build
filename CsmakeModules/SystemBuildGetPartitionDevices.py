#<copyright>
# (c) Copyright 2019 Autumn Samantha Jeremiah Patterson
# (c) Copyright 2018 Cardinal Peak Technologies
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
from Csmake.CsmakeAspect import CsmakeAspect

class SystemBuildGetPartitionDevices(CsmakeAspect):
    """Purpose: Get the devices associated with the requested mountpoints
       Library: csmake-system-build
       Notes: This must be used while a SystemBuildMount is in effect
       JoinPoints:
           start__build, start__system_build, start__use_system_build
                - Define devices in environment
           start - Define unknown into environment
           end - Undefine environment variables
       Options:
           system - The SystemBuild system to use
           env_<mountpoint> - The environment variable to set for the given
                              mountpoint
       Environment:
           __SystemBuild_<system>__ is referenced and will fail if not found
           'filesystem' entry is referenced from the system entry
           The values of env_<mountpoint> are used to define
             environment variables, if the specified environment variables
             are already in use, a warning will be issued.
           NOTE: When this section hits an "end" joinpoint, it removes
                 the definition from the environment.
                 Further attempts to access that environment variable
                 will cause the build to fail.
    """
    REQUIRED_OPTIONS = [ 'system' ]

    def _getEnvKey(self, system):
        return "__SystemBuild_%s__" % system

    def _getEnvironmentVariables(self):
        results = []
        for option, envvar in self.options.items():
            if option.startswith('env_'):
                results.append((option.lstrip('env_'), envvar))
        return results

    def start(self, phase, options, step, stepoptions):
        if phase == 'build' or phase == 'system_build':
            return self.start__build(phase, options, step, stepoptions)

        self.options = options
        envvars = self._getEnvironmentVariables()
        for _, env in envvars:
            if env in self.env.env:
                self.log.warning("Overwriting environment '%s'", env)
            self.env.env[env] = "<undefined>"
        self.log.passed()
        return None

    def end(self, phase, options, step, stepoptions):
        self.options = options
        envvars = self._getEnvironmentVariables()
        for _, env in envvars:
            if env in self.env.env:
                del self.env.env[env]
        self.log.passed()
        return None

    def end__build(self, phase, options, step, stepoptions):
        return self.end(phase, options, step, stepoptions)

    def end__system_build(self, phase, options, step, stepoptions):
        return self.end(phase, options, step, stepoptions)

    def end__use_system_build(self, phase, options, step, stepoptions):
        return self.end(phase, options, step, stepoptions)
        
    def start__build(self, phase, options, step, stepoptions):
        self.options = options
        envvars = self._getEnvironmentVariables()
        try:
            system = self.env.env[self._getEnvKey(self.options['system'])]
        except KeyError:
            self.log.error("System '%s' could not be found", self.options['system'])
            self.log.failed()
            return None
        for mpt, env in envvars:
            if 'filesystem' not in system:
                self.log.error("The filesystem for the SystemBuild is not yet defined")
                self.log.failed()
                return
            if mpt in system['filesystem']:
                system_mpt, device, _, _ = system['filesystem'][mpt]
                if env in self.env.env:
                    self.log.warning("Overwriting environment '%s'", env)
                self.env.env[env] = device
            else:
                self.log.warning("Mountpoint '%s' does not exist in system '%s'.", mpt, self.options['system'])
                self.env.env[env] = "## Device not found"
        self.log.passed()
        return None

    def start__system_build(self, phase, options, step, stepoptions):
        return self.start__build(phase, options, step, stepoptions)

    def start__use_system_build(self, phase, options, step, stepoptions):
        return self.start__build(phase, options, step, stepoptions)

