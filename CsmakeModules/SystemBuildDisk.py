# <copyright>
# (c) Copyright 2019 Autumn Samantha Jeremiah Patterson
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

class SystemBuildDisk(CsmakeModule):
    """Purpose: Set up a disk for a system build.
       Library: csmake-system-build
       Phases: build, system_build - create the file and definition
               clean, clean_build - delete the disk-file
               use_system_build - use the created file and definition
       Options:
           system - Name of the system to add the disk to
           disk-name - Name of the disk to add
           disk-file - Path to the disk file created by this section
           size - Size of the disk to create (the file will be sparse)
                   G, M, K all valid entries
       Note:
           It is assumed that these disks will be /dev/sda, /dev/sdb, etc.
           This probably won't matter unless you use a whole disk as
           a filesystem (unlikely).

       Environment:
           __SystemBuild_<system>__ is referenced - it is an error
              to not have the referenced system defined
              The entry added to the dictionary is:
                  disks:  A dictionary of disks
              The disk entry is a dictionary with the following entries:
                  path:  Path to the disk file (None if disk is real)
                  size:  Size of the disk in bytes
                  device: Path to the device special file for the disk
                  real: True if a real device is represented
                        (as opposed to a logical device)
                  fstab-id: The id or device path to use
                        if the id is not a device path the type is also listed
                        e.g., "LABEL=blah"
                  number: The presumed order of creation for the system
                          (This may be unreliable, but required for older
                           grub versions, e.g. 0.97)
    """
    REQUIRED_OPTIONS = ['system', 'disk-name', 'disk-file', 'size' ]

    def _getEnvKey(self, system):
        return '__SystemBuild_%s__' % system

    def _cleanup(self):
        self._cleanupUse()
        self._cleanupCreate()

    def _cleanupUse(self):
        key = self._getEnvKey(self.system)
        if key not in self.env.env:
            self.log.info("System '%s' is not defined", self.system)
            return
        systemEntry = self.env.env[key]
        if 'disks' not in systemEntry or \
            self.diskname not in systemEntry['disks']:
            self.log.info(
                "Disk '%s' is not defined in system '%s'",
                self.diskname,
                self.system )
            return
        diskEntry = systemEntry['disks'][self.diskname]
        device = diskEntry['device']
        diskPath = diskEntry['path']
        result = subprocess.call(
            ['sudo', 'losetup', '-d', device],
            stdout=self.log.out(),
            stderr=self.log.err())
        del systemEntry['disks'][self.diskname]
        if result != 0:
            self.log.warning("Deleting device '%s' failed", device)
        result = subprocess.call(
            ['sudo', 'ioctl', device, '19457'],
            stdout=self.log.out(),
            stderr=self.log.err())
        if result != 0:
            self.log.warning("Detaching lo device '%' failed", device)

    def _cleanupCreate(self):
        key = self._getEnvKey(self.system)
        if key not in self.env.env:
            self.log.info("System '%s' is not defined", self.system)
            return
        systemEntry = self.env.env[key]
        if 'disks' not in systemEntry or \
            self.diskname not in systemEntry['disks']:
            self.log.info(
                "Disk '%s' is not defined in system '%s'",
                self.diskname,
                self.system )
            return
        diskEntry = systemEntry['disks'][self.diskname]
        device = diskEntry['device']
        diskPath = diskEntry['path']
        result = subprocess.call(
            ['cp', '--sparse=always', diskPath, diskPath + '.save'],
            stdout=self.log.out(),
            stderr=self.log.err())
        if result != 0:
            self.log.warning("Copy of device '%s' failed", device)
        else:
            result = subprocess.call(
                ['mv', diskPath + '.save', diskPath],
                stdout=self.log.out(),
                stderr=self.log.err())
            if result != 0:
                self.log.warning("Move of save disk '%s' failed", device)

    def system_build(self, options):
        return self.build(options)

    def build(self, options):
        return self._setupDisk(options, True)

    def use_system_build(self, options):
        return self._setupDisk(options, False)

    def _setupDisk(self, options, build):
        system = options['system']
        self.system = system
        key = self._getEnvKey(system)
        if key not in self.env.env:
            self.log.error("System '%s' is not defined", system)
            self.log.failed()
            return None
        systemEntry = self.env.env[key]
        if 'disks' not in systemEntry:
            systemEntry['disks'] = {}
        diskname = options['disk-name']
        if diskname in systemEntry['disks']:
            self.log.error(
                "System: %s  Disk: %s  - Already defined",
                system,
                diskname)
            self.log.failed()
            return None
        diskpath = options['disk-file']
        disksize = systemEntry['system']._getSizeInBytes(options['size'])
        if build:
            if os.path.exists(diskpath):
                self.log.warning("A file exists at '%s' for the disk already, removing", diskpath)
                os.remove(diskpath)
            result = subprocess.call(
                ['truncate', '-s', options['size'], diskpath],
                stdout = self.log.out(),
                stderr = self.log.err() )
            if result != 0:
                self.log.error("Creating the disk file failed")
                self.log.failed()
                return None
        #Create the lo device.
        try:
            device = subprocess.check_output(
                ['sudo', 'losetup', '--show', '-f', diskpath] )
            device = device.decode('utf-8').strip()
        except:
            self.log.exception("Failed to create the device for the disk")
            self.log.failed()
            return None
        self.log.devdebug("Loopback device created: %s", device)
        number = len(systemEntry['disks'])
        designation = "/dev/sd%s" % chr(ord('a') + number)
        systemEntry['disks'][diskname] = {
            'path' : diskpath,
            'real' : True,
            'size' : disksize,
            'device' : device,
            'fstab-id' : designation,
            'number' : number }
        self.diskname = diskname
        if build:
            systemEntry['cleanup_methods'].append(self._cleanup)
        else:
            systemEntry['cleanup_methods'].append(self._cleanupUse)
        self.log.passed()
        return systemEntry['disks'][diskname]

    def clean_build(self, options):
        return self.clean(options)
    def clean(self, options):
        self.system = options['system']
        self.diskname = options['disk-name']
        self._cleanup()
        try:
            os.remove(options['disk-file'])
        except:
            self.log.exception("File could not be removed")
        self.log.passed()
        return None

