# <copyright>
# (c) Copyright 2019 Cardinal Peak Technologies
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
from CsmakeCore.CsmakeAspect import CsmakeAspect
import subprocess
import os.path
import glob
import functools

class SystemBuildMount(CsmakeAspect):
    """Purpose: Mount the Partitions of the given system
       NOTE: When used as a regular section (i.e., not an aspect)
             SystemBuildUnmount must be eventually specified.
       Library: csmake-system-build
       Phases:
           build, system_build, use_system_build - Mount the system filesystem
       JoinPoints:
           start__build, start__system_build - Mount the system filesystem
           end__build - Unmount the system filesystem
       Options:
           system - The SystemBuild system to mount
           location - Directory to mount the system on
           skip - (OPTIONAL) Directories to skip
       Environment:
           __SystemBuild_<system>__ is referenced - it is an error
              to not have the referenced system defined.
              'mountInstance' is the actual instance of the SystemBuildMount
                 instance that has mounted the disks - added by this instance.
              The 'filesystem' entry is referenced from the system entry.
              The filesystem's structure is
                 [ ( '<mountpoint>', '<device>', '<type>', '<fstabid>') ... ]
    """

    REQUIRED_OPTIONS = ['system', 'location']

    def _getEnvKey(self, system):
        return "__SystemBuild_%s__" % system

    def _onExit(self):
        self._cleanUpMounts(True)

    def _onRecovery(self, systemEntry, mountedDevices):
        self._cleanUpMounts(True, True, systemEntry, mountedDevices)

    def _systemMountLocation(self):
        return self.location

    def _cleanUpMounts(
        self,
        force=False,
        recovery=False,
        recoverySystemEntry=None,
        recoveryMountedDevices=None):

        mountedDevices = list(self.mountedDevices)
        if recoveryMountedDevices is not None:
            mountedDevices = recoveryMountedDevices

        systemEntry = self.systemEntry
        if recoverySystemEntry is not None:
            systemEntry = recoverySystemEntry

        #Switch to the instance that actually mounted the devices
        if 'count' not in systemEntry \
            or systemEntry['count'] <= 0:
            self.log.info("Clean up did not detect any mounts")
            return True
        if self is not systemEntry['mountInstance']:
            self = systemEntry['mountInstance']
        try:
            systemEntry['count'] -= 1
            if systemEntry['count'] > 0 and not force:
                self.log.info("System '%s' still has %d mounts - not unmounting", self.options['system'], mountdict['count'])
                return True
            systemEntry['count'] = 0
        except:
            self.log.exception("Proceeding - but, failed to get the mount count")
            self.log.warning("Attempting to unwind a partial mount")

        #Work backwards to clean out partial mounting
        mountedDevices.reverse()
        failures = False
        subprocess.call(
            ['sync'],
            stdout=self.log.out(),
            stderr=self.log.err() )
        for dev in mountedDevices:
            subprocess.call(
                ['sudo', 'fstrim', dev],
                stdout=self.log.out(),
                stderr=self.log.err())
            try:
                subprocess.check_call(
                    ['sudo', 'umount', dev],
                    stdout=self.log.out(),
                    stderr=self.log.err() )
            except:
                failures = True
                self.log.error("Couldn't eagerly umount - forcing lazy umount")
                subprocess.call(
                    ['sudo', 'umount', '-lf', dev],
                    stdout=self.log.out(),
                    stderr=self.log.err() )
                #With doing a lazy umount, we should be able to
                #skip the retry of the umounts - the processes
                #that would be holding on to the mounts should all have
                #disappeared by the time we get to recovery.

        if failures and not recovery:
            systemEntry['count'] += 1
            systemEntry['recovery_methods'].append(
                functools.partial(
                    self._onRecovery,
                    systemEntry,
                    list(self.mountedDevices) ) )
            self.log.warning("Couldn't umount, will try again at end")
            return True

        self.mountedDevices = []
        del systemEntry['mountInstance']

        #mountdev = self.partitionMapping[dev]
        #Resparsify the disk files, if possible
        for disk in self.systemEntry['disks'].values():
            subprocess.call(
                ['fallocate', '-d', disk['path']],
                stdout=self.log.out(),
                stderr=self.log.err() )

        #Clean up the mount directory:
        subprocess.call(
            [ 'rmdir', self.options['location'] ],
            stdout=self.log.out(),
            stderr=self.log.err() )

        try:
            self.systemEntry['cleanup_methods'].remove(self._onExit)
        except:
            self.log.info("The cleanup method for SystemBuildMount was not in the cleanup list")
        return True

    def _mountSystemPaths(self, mountpath):
        procmountpath = os.path.join(
            mountpath,
            'proc' )
        if not os.path.exists(procmountpath):
            result = subprocess.call(
                ['sudo', 'mkdir', procmountpath ],
                stdout = self.log.out(),
                stderr = self.log.err() )
            if result != 0:
                self.log.error("Create of procfs mount point failed")
                self.log.failed()
                return False
        result = subprocess.call(
            ['sudo', 'mount', '-t', 'proc', 'none', procmountpath ],
            stdout = self.log.out(),
            stderr = self.log.err() )
        if result != 0:
            self.log.error("Mount of procfs failed")
            self.log.failed()
            return False
        self.mountedDevices.append(procmountpath)

        devmountpath = os.path.join(
            mountpath,
            'dev' )
        if not os.path.exists(devmountpath):
            result = subprocess.call(
                ['sudo', 'mkdir', devmountpath ],
                stdout = self.log.out(),
                stderr = self.log.err() )
            if result != 0:
                self.log.error("Create of dev mount point failed")
                self.log.failed()
                return False
        result = subprocess.call(
            ['sudo', 'mount', '-t', 'devtmpfs', 'none', devmountpath ],
            stdout=self.log.out(),
            stderr=self.log.err() )
        if result != 0:
            self.log.error("Mount of dev failed")
            self.log.failed()
            return False
        self.mountedDevices.append(devmountpath)

        devshmmountpath = os.path.join(
            mountpath,
            'dev',
            'shm' )
        if not os.path.exists(devshmmountpath):
            result = subprocess.call(
                ['sudo', 'mkdir', devshmmountpath ],
                stdout = self.log.out(),
                stderr = self.log.err() )
            if result != 0:
                self.log.error("Create of dev/shm mount point failed")
                self.log.failed()
                return False
        result = subprocess.call(
            ['sudo', 'mount', '-t', 'tmpfs', '-o', 'rw,nosuid,nodev', 'tmpfs', devshmmountpath ],
            stdout=self.log.out(),
            stderr=self.log.err() )
        if result != 0:
            self.log.error("Mount of dev/shm failed")
            self.log.failed()
            return False
        subprocess.call(
            ['sudo', 'chmod', '777', devshmmountpath],
            stdout = self.log.out(),
            stderr = self.log.err())
        self.mountedDevices.append(devshmmountpath)

        ptsmountpath = os.path.join(
            mountpath,
            'dev',
            'pts' )
        if not os.path.exists(ptsmountpath):
            result = subprocess.call(
                ['sudo', 'mkdir', ptsmountpath ],
                stdout=self.log.out(),
                stderr=self.log.err() )
            if result != 0:
                self.log.error("Create of the pts mount point failed")
                self.log.failed()
                return False
        #result = subprocess.call(
        #    ['sudo', 'mount', '--bind', '/dev/pts', ptsmountpath],
        #    stdout=self.log.out(),
        #    stderr=self.log.err() )
        result = subprocess.call(
            ['sudo', 'mount',  '-t', 'devpts', '-o', 'rw,nosuid,noexec,relatime,gid=5,mode=620,ptmxmode=000', 'devpts', ptsmountpath ],
            stdout=self.log.out(),
            stderr=self.log.err() )
        if result != 0:
            self.log.error("Mount of dev/pts failed")
            self.log.failed()
            return False
        self.mountedDevices.append(ptsmountpath)

        runmountpath = os.path.join(
            mountpath,
            'run' )
        if not os.path.exists(runmountpath):
            result = subprocess.call(
                ['sudo', 'mkdir', runmountpath ],
                stdout=self.log.out(),
                stderr=self.log.err() )
            if result != 0:
                self.log.error("Create of the run mount point failed")
                self.log.failed()
                return False
        result = subprocess.call(
            ['sudo', 'mount', '-t', 'tmpfs', '-o', 'rw,nosuid,nodev,noexec,mode=755,size=10%', 'tmpfs', runmountpath ],
            stdout=self.log.out(),
            stderr=self.log.err() )
        if result != 0:
            self.log.error("Mount of /run failed")
            self.log.failed()
            return False
        self.mountedDevices.append(runmountpath)

        runshmmountpath = os.path.join(
            mountpath,
            'run',
            'shm' )
        if not os.path.exists(runshmmountpath):
            result = subprocess.call(
                ['sudo', 'mkdir', runshmmountpath ],
                stdout = self.log.out(),
                stderr = self.log.err() )
            if result != 0:
                self.log.error("Create of run/shm mount point failed")
                self.log.failed()
                return False
        result = subprocess.call(
            ['sudo', 'mount', '-t', 'tmpfs', '-o', 'rw,nosuid,nodev', 'tmpfs', runshmmountpath ],
            stdout=self.log.out(),
            stderr=self.log.err() )
        if result != 0:
            self.log.error("Mount of run/shm failed")
            self.log.failed()
            return False
        subprocess.call(
            ['sudo', 'chmod', '777', runshmmountpath],
            stdout = self.log.out(),
            stderr = self.log.err())
        self.mountedDevices.append(runshmmountpath)

        runlockmountpath = os.path.join(
            mountpath,
            'run',
            'lock' )
        if not os.path.exists(runlockmountpath):
            result = subprocess.call(
                ['sudo', 'mkdir', runlockmountpath ],
                stdout = self.log.out(),
                stderr = self.log.err() )
            if result != 0:
                self.log.error("Create of run/lock mount point failed")
                self.log.failed()
                return False
        result = subprocess.call(
            ['sudo', 'mount', '-t', 'tmpfs', '-o', 'rw,nosuid,nodev,noexec,mode=777', 'tmpfs', runlockmountpath ],
            stdout=self.log.out(),
            stderr=self.log.err() )
        if result != 0:
            self.log.error("Mount of run/lock failed")
            self.log.failed()
            return False
        self.mountedDevices.append(runlockmountpath)

        runusermountpath = os.path.join(
            mountpath,
            'run',
            'user' )
        if not os.path.exists(runusermountpath):
            result = subprocess.call(
                ['sudo', 'mkdir', runusermountpath ],
                stdout = self.log.out(),
                stderr = self.log.err() )
            if result != 0:
                self.log.error("Create of run/user mount point failed")
                self.log.failed()
                return False
        result = subprocess.call(
            ['sudo', 'mount', '-t', 'tmpfs', '-o', 'rw,nosuid,nodev,noexec,mode=777', 'tmpfs', runusermountpath ],
            stdout=self.log.out(),
            stderr=self.log.err() )
        if result != 0:
            self.log.error("Mount of run/user failed")
            self.log.failed()
            return False
        self.mountedDevices.append(runusermountpath)

        sysmountpath = os.path.join(
            mountpath,
            'sys' )
        if not os.path.exists(sysmountpath):
            result = subprocess.call(
                ['sudo', 'mkdir', sysmountpath],
                stdout=self.log.out(),
                stderr=self.log.err() )
            if result != 0:
                self.log.error("Create of the sys mount point failed")
                self.log.failed()
                return False
        result = subprocess.call(
            ['sudo', 'mount', '-t', 'sysfs', 'none', sysmountpath],
            stdout=self.log.out(),
            stderr=self.log.err() )
        if result != 0:
            self.log.error("Mount of sysfs failed")
            self.log.failed()
            return False
        self.mountedDevices.append(sysmountpath)
        return True

    def _initModule(self):
        self.taggedEnvKey = self._getEnvKey(self.options['system'])
        if self.taggedEnvKey not in self.env.env:
            self.log.error("System '%s' undefined", self.options['system'])
            self.log.failed()
            return None
        self.systemEntry = self.env.env[self.taggedEnvKey]
        if 'filesystem' not in self.systemEntry:
            self.log.error("System '%s' has no filesystem", self.options['system'])
            self.log.failed()
            return None
        self.fsEntry = self.systemEntry['filesystem']

        self.partitionMapping = {}
        self.mountMapping = {}
        self.mountedDevices = []

        self.skipmounts = []
        if 'skip' in self.options:
            skips = ','.join(self.options['skip'].split('\n')).split(',')
            self.skipmounts = [ x.strip() for x in skips if len(x.strip()) != 0 ]

        #This will make mounting reenterant
        if 'count' not in self.systemEntry:
            self.systemEntry['count'] = 0
        if self.systemEntry['count'] != 0:
            self.systemEntry['count'] += 1
            self.log.info("Mount called while already mounted - count now: %d", self.env.env[self.taggedEnvKey]['count'])
            self.log.passed()
            return False
        else:
            self.systemEntry['count'] += 1
            self.systemEntry['mountInstance'] = self
        return True

    def _mount(self):
        #Ensure mount directory exists.
        self.location = self.options['location']
        if not os.path.exists(self.location):
            subprocess.check_call(
                ['mkdir', '-p', self.location ],
                stdout=self.log.out(),
                stderr=self.log.err() )
        else:
            if not os.path.isdir(self.location):
                self.log.error("'location' path '%s' already exists and is not a directory", self.location)
                return False

        success = False
        try:
            mountpts = list(self.fsEntry.keys())
            #Sorting will ensure that the mountpoints are done
            #in the proper order.../ comes before /boot for example
            mountpts.sort()
            for mountptkey in mountpts:
                mountpt, device, fstype, fstabid = self.fsEntry[mountptkey]
                if mountpt in self.skipmounts:
                    self.log.debug("Skipping mount: %s", mountpt)
                    continue
                fullmntpath = os.path.join(
                    self.location,
                    mountpt[1:] )
                if not os.path.exists(fullmntpath):
                    subprocess.check_call(
                        ['sudo', 'mkdir', '-p', fullmntpath ],
                        stdout=self.log.out(),
                        stderr=self.log.err())
                subprocess.check_call(
                    ['sudo', 'mount', device, fullmntpath],
                    stdout=self.log.out(),
                    stderr=self.log.err())
                self.mountedDevices.append(fullmntpath)
            success = self._mountSystemPaths(self.location)
            if not success:
                raise SystemError("Could not bind mount system structure")
        except Exception as e:
            self.log.exception("Failed to mount system")
            raise
        finally:
            if not success:
                self._cleanUpMounts(True)
                return False

        self.systemEntry['cleanup_methods'].append(self._onExit)
        return True

    def use_system_build(self, options):
        return self.build(options)
    def system_build(self, options):
        return self.build(options)
    def build(self, options):
        self.options = options
        if not self._initModule():
            self.log.passed()
            return
        if self._mount():
            self.log.passed()
        else:
            self.log.failed()

    def start__use_system_build(self, phase, options, step, stepoptions):
        return self.start__build(phase, options, step, stepoptions)
    def start__system_build(self, phase, options, step, stepoptions):
        return self.start__build(phase, options, step, stepoptions)
    def start__build(self, phase, options, step, stepoptions):
        self.options = options
        if not self._initModule():
            self.log.passed()
            return
        if self._mount():
            self.log.passed()
        else:
            self.log.failed()

    def end__use_system_build(self, phase, options, step, stepoptions):
        return self.end__build(phase, options, step, stepoptions)
    def end__system_build(self, phase, options, step, stepoptions):
        return self.end__build(phase, options, step, stepoptions)
    def end__build(self, phase, options, step, stepoptions):
        self._cleanUpMounts()
        self.log.passed()
